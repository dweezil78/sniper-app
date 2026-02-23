import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
from pathlib import Path

# ============================
# CONFIGURAZIONE PATH ASSOLUTI
# ============================
BASE_DIR = Path(__file__).resolve().parent
JSON_FILE = str(BASE_DIR / "arab_snapshot_multi.json")
NAZIONI_FILE = str(BASE_DIR / "nazioni_config.json")

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

def to_ymd(dt_or_str):
    return str(dt_or_str)[:10]

def daterange_ymd(start_ymd, end_ymd):
    start = datetime.fromisoformat(start_ymd).date()
    end = datetime.fromisoformat(end_ymd).date()
    out = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out

st.set_page_config(page_title="ARAB SNIPER - 3 DAYS PLANNER", layout="wide")

# ============================
# INITIALIZATION & PERSISTENCE
# ============================
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "available_countries" not in st.session_state: st.session_state["available_countries"] = []

def load_snapshot_file():
    if not os.path.exists(JSON_FILE): return {"version": 1, "days": {}}
    try:
        with open(JSON_FILE, "r") as f:
            js = json.load(f)
            return js if "days" in js else {"version": 1, "days": {}}
    except: return {"version": 1, "days": {}}

def save_snapshot_file(payload):
    try:
        with open(JSON_FILE, "w") as f: json.dump(payload, f)
    except: pass

def prune_snapshot_days(days_dict, keep_dates):
    return {d: v for d, v in days_dict.items() if d in keep_dates}

# Caricamento Snapshot
snap_payload = load_snapshot_file()
st.session_state["odds_memory"] = snap_payload.get("days", {})

# ============================
# API CORE
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
    return js

# ============================
# GESTIONE NAZIONI (PRO) - RIPRISTINATA
# ============================
def load_excluded_countries():
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                data = json.load(f)
                return list(data.get("excluded", []))
        except: return []
    return []

def save_excluded_countries(excluded_list):
    try:
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": excluded_list}, f)
    except: pass

if not st.session_state["available_countries"]:
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": now_rome().strftime("%Y-%m-%d"), "timezone": "Europe/Rome"})
            st.session_state["available_countries"] = sorted(list(set([f["league"]["country"] for f in data.get("response", [])])))
    except: pass

if "excluded_countries" not in st.session_state:
    st.session_state["excluded_countries"] = load_excluded_countries()

# ============================
# SIDEBAR UI
# ============================
st.sidebar.header("📅 Finestra Analisi")
today_ymd = now_rome().date().isoformat()
use_rolling = st.sidebar.toggle("🔁 Rolling automatico (3 giorni)", value=True)

if use_rolling:
    start_ymd = today_ymd
    end_ymd = (now_rome().date() + timedelta(days=2)).isoformat()
    st.sidebar.caption(f"Range: {start_ymd} / {end_ymd}")
else:
    dr = st.sidebar.date_input("Intervallo", value=(now_rome().date(), now_rome().date() + timedelta(days=2)))
    if isinstance(dr, (tuple, list)) and len(dr) == 2:
        start_ymd, end_ymd = dr[0].isoformat(), dr[1].isoformat()
    else: start_ymd = end_ymd = dr.isoformat() if not isinstance(dr, tuple) else dr[0].isoformat()

selected_dates = daterange_ymd(start_ymd, end_ymd)
selected_dates_set = set(selected_dates)

# Filtro Nazioni PRO (Cruciale per multi-giorno)
st.sidebar.markdown("---")
st.sidebar.subheader("🌍 Filtro Nazioni PRO")
with st.sidebar.expander("Gestisci Esclusioni", expanded=False):
    current_selected = [c for c in st.session_state["available_countries"] if c not in st.session_state["excluded_countries"]]
    to_exclude = st.selectbox("Escludi nazione:", ["-- seleziona --"] + current_selected)
    if to_exclude != "-- seleziona --":
        st.session_state["excluded_countries"].append(to_exclude)
        save_excluded_countries(st.session_state["excluded_countries"])
        st.rerun()
    
    st.markdown("---")
    to_include = st.selectbox("Ripristina nazione:", ["-- seleziona --"] + st.session_state["excluded_countries"])
    if to_include != "-- seleziona --":
        st.session_state["excluded_countries"].remove(to_include)
        save_excluded_countries(st.session_state["excluded_countries"])
        st.rerun()

st.session_state["only_gold_ui"] = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=False)

# ============================
# LOGICA STATISTICA (V16.00)
# ============================
team_stats_cache = {}

def get_comprehensive_stats(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 5, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}
        ht_h, conc_h, goals = 0, 0, []
        for f in fx:
            if ((f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0)) >= 1: ht_h += 1
            is_home = (f["teams"]["home"]["id"] == tid)
            conc_val = (f["goals"]["away"] if is_home else f["goals"]["home"]) or 0
            if conc_val > 0: conc_h += 1
            goals.append(int((f["goals"]["home"] if is_home else f["goals"]["away"]) or 0))
        res = {"ht_ratio": ht_h/5, "vulnerability": conc_h/5, "is_dry": (len(goals)>0 and goals[0]==0 and sum(1 for g in goals if g>=1)>=4)}
        team_stats_cache[tid] = res
        return res
    except: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    def pick_over(values, key):
        for x in values or []:
            if str(x.get("value") or "").lower().replace(" ", "").startswith(key):
                try: return float(x.get("odd") or 0)
                except: return 0.0
        return 0.0
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), str(b.get("name") or "").lower()
            if bid == 1:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5:
                try: data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x.get("value") == "Over 2.5"), 0))
                except: pass
            if "1st" in name or "first half" in name:
                if "over/under" in name or "total" in name:
                    if data["o05ht"] == 0: data["o05ht"] = pick_over(b.get("values", []), "over0.5")
                    if data["o15ht"] == 0: data["o15ht"] = pick_over(b.get("values", []), "over1.5")
            if (bid == 71 or ("both" in name and "1st" in name)):
                for x in b.get("values", []):
                    if str(x.get("value") or "").lower() in ["yes", "si", "oui"]:
                        data["gg_ht"] = float(x.get("odd") or 0)
    return data

# ============================
# RENDERING & CSS
# ============================
CUSTOM_CSS = """
    <style>
        .main { background-color: #f0f2f6; }
        table { width: 100%; border-collapse: collapse; font-size: 0.82rem; font-family: sans-serif; }
        th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
        td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
        .match-cell { text-align: left !important; min-width: 220px; font-weight: 700; color: inherit !important; }
        .date-cell { background-color: #e0e0e0; font-weight: 800; color: #000; text-align: left !important; }
    </style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ============================
# CORE ENGINE (Multi-day)
# ============================
def execute_full_scan(session, fixtures, snap_days, excluded_list):
    results, pb = [], st.progress(0)
    filtered = [f for f in fixtures if f["league"]["country"] not in excluded_list]
    if not filtered: return []
    for i, m in enumerate(filtered):
        pb.progress((i+1)/len(filtered))
        try:
            mk = extract_markets_pro(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            
            fid_s = str(m["fixture"]["id"])
            match_day = to_ymd(m["fixture"]["date"])
            s_h, s_a = get_comprehensive_stats(session, m["teams"]["home"]["id"]), get_comprehensive_stats(session, m["teams"]["away"]["id"])
            f_s = s_h if mk["q1"] < mk["q2"] else s_a

            # Snapshot check
            day_snap = (snap_days.get(match_day, {}) or {}).get("odds", {})
            det = []
            if s_h["ht_ratio"] >= 0.6 and s_a["ht_ratio"] >= 0.6: det.append("HT-OK")
            if 1.70 <= mk["o25"] < 2.00: det.append("O25-OK")
            if 1.30 <= mk["o05ht"] <= 1.55: det.append("O05-OK")
            
            if fid_s in day_snap:
                if (min(day_snap[fid_s]["q1"], day_snap[fid_s]["q2"]) - min(mk["q1"], mk["q2"])) >= 0.15: det.append("Drop")

            if (2.20 <= mk["o15ht"] <= 2.80) and (4.20 <= mk["gg_ht"] <= 5.50) and ("HT-OK" in det):
                det.append("GATE-11")
                if f_s["vulnerability"] >= 0.8: det.append("🎯 GG-PT")
            elif "HT-OK" in det and f_s["vulnerability"] >= 0.8: det.append("GG-PT-POT")

            if "O25-OK" in det and "O05-OK" in det and "HT-OK" in det:
                det.append("🔥 OVER-PRO")

            results.append({
                "Data": match_day, "Ora": m["fixture"]["date"][11:16],
                "Lega": f"{m['league']['name']} ({m['league']['country']})", 
                "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", 
                "O2.5": f"{mk['o25']:.2f}", "O0.5 PT": f"{mk['o05ht']:.2f}",
                "Info": f"[{'|'.join(det)}]", "Is_Gold": (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10)
            })
        except: continue
    return results

# ============================
# BOTTONI AZIONE
# ============================
col1, col2 = st.columns(2)

def handle_run(is_snap):
    with requests.Session() as s:
        try:
            all_fix = []
            for d in selected_dates:
                data = api_get(s, "fixtures", {"date": d, "timezone": "Europe/Rome"})
                day_fix = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and not any(t in f["league"]["name"].lower() for t in ["women","u19","u20","u21","u23","youth","friendly"])]
                all_fix.extend(day_fix)
            
            if is_snap:
                new_days = dict(st.session_state["odds_memory"])
                pb_s = st.progress(0)
                for i, m in enumerate(all_fix):
                    pb_s.progress((i+1)/len(all_fix))
                    mk_s = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if mk_s and mk_s["q1"] > 0:
                        d = to_ymd(m["fixture"]["date"])
                        if d not in new_days: new_days[d] = {"timestamp": now_rome().isoformat(), "odds": {}}
                        new_days[d]["odds"][str(m["fixture"]["id"])] = {"q1": mk_s["q1"], "q2": mk_s["q2"]}
                st.session_state["odds_memory"] = prune_snapshot_days(new_days, selected_dates_set)
                save_snapshot_file({"version": 1, "days": st.session_state["odds_memory"]})

            st.session_state["scan_results"] = execute_full_scan(s, all_fix, st.session_state["odds_memory"], st.session_state["excluded_countries"])
            st.rerun()
        except Exception as e: st.error(f"Errore: {e}")

if col1.button("📌 MULTI-DAY SNAPSHOT"): handle_run(True)
if col2.button("🚀 AVVIA RADAR 3 GIORNI"): handle_run(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    if st.session_state["only_gold_ui"]: df = df[df["Is_Gold"]]
    
    if not df.empty:
        df = df.sort_values(["Data", "Ora"])
        cols = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "O0.5 PT", "Info"]
        
        def apply_style(row):
            info = row['Info']
            if '🎯 GG-PT' in info: return ['background-color: #38003c; color: #00e5ff;' for _ in row]
            if '🔥 OVER-PRO' in info: return ['background-color: #003300; color: #00ff00;' for _ in row]
            if 'GG-PT-POT' in info: return ['background-color: #0c1a2b; color: #ffffff;' for _ in row]
            return ['' for _ in row]

        st_style = df[cols].style.apply(apply_style, axis=1)
        st.write(st_style.to_html(escape=False, index=False), unsafe_allow_html=True)
        st.download_button("💾 SCARICA AUDITOR 3-GG", df.to_csv(index=False).encode('utf-8'), "auditor_3days.csv")
        

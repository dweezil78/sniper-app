import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, date
import json
import os
from pathlib import Path

# ============================
# CONFIGURAZIONE PATH ASSOLUTI
# ============================
BASE_DIR = Path(__file__).resolve().parent
JSON_FILE = str(BASE_DIR / "arab_snapshot_multi.json") # File separato per non sporcare oggi
NAZIONI_FILE = str(BASE_DIR / "nazioni_config.json")

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

# --- HELPER DATE RANGE (Patch 2) ---
def to_ymd(dt_or_str):
    s = str(dt_or_str)
    return s[:10]

def daterange_ymd(start_ymd, end_ymd):
    try:
        start = datetime.fromisoformat(start_ymd).date()
        end = datetime.fromisoformat(end_ymd).date()
        out = []
        cur = start
        while cur <= end:
            out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out
    except: return [to_ymd(now_rome())]

def default_end_ymd(days_forward=2):
    return (now_rome().date() + timedelta(days=days_forward)).isoformat()

st.set_page_config(page_title="ARAB SNIPER - 3 DAYS PLANNER", layout="wide")

# ============================
# INITIALIZATION & PERSISTENCE (Patch 1 & 3)
# ============================
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "available_countries" not in st.session_state: st.session_state["available_countries"] = []

def load_snapshot_file():
    if not os.path.exists(JSON_FILE): return {"version": 1, "days": {}}
    try:
        with open(JSON_FILE, "r") as f:
            js = json.load(f)
            if isinstance(js, dict) and "days" in js: return js
            if isinstance(js, dict) and "date" in js and "odds" in js:
                return {"version": 1, "days": {js["date"]: {"timestamp": js.get("timestamp"), "odds": js.get("odds", {})}}}
    except: pass
    return {"version": 1, "days": {}}

def save_snapshot_file(payload):
    try:
        with open(JSON_FILE, "w") as f: json.dump(payload, f)
    except: pass

def prune_snapshot_days(days_dict, keep_dates):
    return {d: v for d, v in days_dict.items() if d in keep_dates}

# Recovery Multi-day
snap_payload = load_snapshot_file()
st.session_state["odds_memory"] = snap_payload.get("days", {})

try:
    all_ts = [datetime.fromisoformat(v["timestamp"]) for v in st.session_state["odds_memory"].values() if v.get("timestamp")]
    st.session_state["snap_time_obj"] = max(all_ts) if all_ts else None
except: st.session_state["snap_time_obj"] = None

# ============================
# API CORE & UTILS
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
    return js

# Caricamento Nazioni (Condiviso)
def load_excluded_countries():
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                data = json.load(f)
                return list(data.get("excluded", []))
        except: return []
    return []

if not st.session_state["available_countries"]:
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": now_rome().strftime("%Y-%m-%d"), "timezone": "Europe/Rome"})
            all_c = sorted(list(set([f["league"]["country"] for f in data.get("response", [])])))
            st.session_state["available_countries"] = all_c
    except: pass

excluded = load_excluded_countries()
selected_countries = [c for c in st.session_state["available_countries"] if c not in excluded]

# ============================
# LOGICA STATISTICA (INVARIATA V16)
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
    def is_first_half_market(n):
        n = str(n or "").lower()
        return (("1st" in n) or ("first" in n) or ("1h" in n)) and (("half" in n) or ("total" in n))
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
            if is_first_half_market(name):
                if data["o05ht"] == 0: data["o05ht"] = pick_over(b.get("values", []), "over0.5")
                if data["o15ht"] == 0: data["o15ht"] = pick_over(b.get("values", []), "over1.5")
            if (bid == 71 or ("both" in name and "1st" in name)) and data["gg_ht"] == 0:
                for x in b.get("values", []):
                    if str(x.get("value") or "").lower() in ["yes", "si", "si", "oui"]:
                        data["gg_ht"] = float(x.get("odd") or 0)
        if data["q1"] > 0 and data["o05ht"] > 0: break
    return data

# ============================
# CORE ENGINE (Patch 7: Multi-day Drop)
# ============================
def execute_full_scan(session, fixtures, snap_days, selected_countries):
    results, pb = [], st.progress(0)
    for i, m in enumerate(fixtures):
        pb.progress((i+1)/len(fixtures))
        try:
            mk = extract_markets_pro(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            
            fid_s = str(m["fixture"]["id"])
            s_h, s_a = get_comprehensive_stats(session, m["teams"]["home"]["id"]), get_comprehensive_stats(session, m["teams"]["away"]["id"])
            f_s, d_s = (s_h, s_a) if mk["q1"] < mk["q2"] else (s_a, s_h)

            # Drop Check Multi-day (Patch 7.2)
            match_day = to_ymd(m["fixture"]["date"])
            day_snap = (snap_days.get(match_day, {}) or {}).get("odds", {}) if isinstance(snap_days, dict) else {}
            
            det = []
            if s_h["ht_ratio"] >= 0.6 and s_a["ht_ratio"] >= 0.6: det.append("HT-OK")
            if 1.70 <= mk["o25"] < 2.00: det.append("O25-OK")
            if 1.30 <= mk["o05ht"] <= 1.55: det.append("O05-OK")
            
            if fid_s in day_snap:
                old_f = min(day_snap[fid_s]["q1"], day_snap[fid_s]["q2"])
                cur_f = min(mk["q1"], mk["q2"])
                if (old_f - cur_f) >= 0.15: det.append("Drop")

            results.append({
                "Data": match_day, "Ora": m["fixture"]["date"][11:16],
                "Lega": f"{m['league']['name']} ({m['league']['country']})", 
                "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", 
                "O2.5": f"{mk['o25']:.2f}", "O0.5 PT": f"{mk['o05ht']:.2f}",
                "Info": f"[{'|'.join(det)}]", "Fixture_ID": fid_s
            })
        except: continue
    return results

# ============================
# UI & RUNTIME (Patch 4, 5, 6, 8)
# ============================
st.sidebar.header("📅 Finestra Analisi (Patch 4)")
today_ymd = now_rome().date().isoformat()
use_rolling = st.sidebar.toggle("🔁 Rolling automatico (3 giorni)", value=True)

if use_rolling:
    start_ymd, end_ymd = today_ymd, default_end_ymd(2)
    st.sidebar.caption(f"Finestra: {start_ymd} → {end_ymd}")
else:
    dr = st.sidebar.date_input("Intervallo", value=(now_rome().date(), now_rome().date() + timedelta(days=2)))
    if isinstance(dr, (tuple, list)) and len(dr) == 2:
        start_ymd, end_ymd = dr[0].isoformat(), dr[1].isoformat()
    else: start_ymd = end_ymd = dr.isoformat() if not isinstance(dr, tuple) else dr[0].isoformat()

selected_dates = daterange_ymd(start_ymd, end_ymd)
selected_dates_set = set(selected_dates)

if use_rolling:
    st.session_state["odds_memory"] = prune_snapshot_days(st.session_state["odds_memory"], selected_dates_set)
    save_snapshot_file({"version": 1, "days": st.session_state["odds_memory"]})

# Sidebar Status (Patch 8)
if st.session_state["odds_memory"]:
    days_loaded = sorted(st.session_state["odds_memory"].keys())
    st.sidebar.success(f"✅ Snapshot giorni: {len(days_loaded)}")
    st.sidebar.caption(" | ".join(days_loaded[:6]) + (" ..." if len(days_loaded) > 6 else ""))
    if st.session_state["snap_time_obj"]:
        st.sidebar.caption(f"Ultimo snap: {st.session_state['snap_time_obj'].strftime('%d/%m %H:%M')}")
else: st.sidebar.warning("⚠️ Nessun Snapshot Caricato")

col_b1, col_b2 = st.columns(2)

def handle_run(is_snap):
    with requests.Session() as s:
        try:
            # Recupero Multi-giorno (Patch 5)
            all_fixtures = []
            for d in selected_dates:
                data = api_get(s, "fixtures", {"date": d, "timezone": "Europe/Rome"})
                day_fix = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and not any(t in f["league"]["name"].lower() for t in ["women","u19","u20","u21","u23","youth","friendly"])]
                all_fixtures.extend(day_fix)
            
            fixtures = all_fixtures

            # Snapshot Multi-day (Patch 6)
            if is_snap:
                new_days = dict(st.session_state["odds_memory"])
                pb_snap = st.progress(0)
                for i, m in enumerate(fixtures):
                    pb_snap.progress((i+1)/len(fixtures))
                    try:
                        mk_s = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                        if not mk_s or mk_s["q1"] <= 0: continue
                        fid, day = str(m["fixture"]["id"]), to_ymd(m["fixture"]["date"])
                        if day not in new_days: new_days[day] = {"timestamp": now_rome().isoformat(), "odds": {}}
                        new_days[day]["timestamp"] = now_rome().isoformat()
                        new_days[day]["odds"][fid] = {"q1": mk_s["q1"], "q2": mk_s["q2"]}
                    except: continue
                new_days = prune_snapshot_days(new_days, selected_dates_set)
                st.session_state["odds_memory"] = new_days
                st.session_state["snap_time_obj"] = now_rome()
                save_snapshot_file({"version": 1, "days": st.session_state["odds_memory"]})

            st.session_state["scan_results"] = execute_full_scan(s, fixtures, st.session_state["odds_memory"], selected_countries)
            st.rerun()
        except Exception as e: st.error(f"Errore: {e}")

if col_b1.button("📌 MULTI-DAY SNAPSHOT"): handle_run(True)
if col_b2.button("🚀 AVVIA RADAR 3 GIORNI"): handle_run(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    st.table(df) # Render semplice per il planner

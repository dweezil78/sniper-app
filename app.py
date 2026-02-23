import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import json
import os
from pathlib import Path

# ============================
# CONFIGURAZIONE PATH ASSOLUTI
# ============================
BASE_DIR = Path(__file__).resolve().parent
JSON_FILE = str(BASE_DIR / "arab_snapshot.json")
NAZIONI_FILE = str(BASE_DIR / "nazioni_config.json")
LOG_CSV = str(BASE_DIR / "sniper_history_log.csv")

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V16.00 - PURE AUDITOR", layout="wide")

# --- INITIALIZATION ---
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "available_countries" not in st.session_state: st.session_state["available_countries"] = []

# Recovery Snapshot
if not st.session_state["odds_memory"] and os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, "r") as f:
            saved = json.load(f)
            if saved.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = saved.get("odds", {})
                st.session_state["snap_time_obj"] = datetime.fromisoformat(saved["timestamp"])
    except: pass

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

if not st.session_state["available_countries"]:
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": now_rome().strftime("%Y-%m-%d"), "timezone": "Europe/Rome"})
            all_c = sorted(list(set([f["league"]["country"] for f in data.get("response", [])])))
            st.session_state["available_countries"] = all_c
    except: pass

# ============================
# GESTIONE NAZIONI (PRO)
# ============================
def load_excluded_countries():
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict): return list(data.get("excluded", []))
        except: return []
    return []

def save_excluded_countries(excluded_list):
    try:
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": excluded_list}, f)
    except: pass

if "excluded_countries" not in st.session_state:
    st.session_state["excluded_countries"] = load_excluded_countries()

st.session_state["excluded_countries"] = [c for c in st.session_state["excluded_countries"] if c in st.session_state["available_countries"]]
st.session_state["selected_countries"] = [c for c in st.session_state["available_countries"] if c not in st.session_state["excluded_countries"]]

# ============================
# LOGICA STATISTICA E PARSING
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
        if ("2nd" in n) or ("second" in n): return False
        return (("1st" in n) or ("first" in n) or ("1h" in n)) and (("half" in n) or ("total" in n))
    def pick_over(values, key):
        for x in values or []:
            v_val = str(x.get("value") or "").lower().replace(" ", "")
            if v_val.startswith(key):
                try: return float(x.get("odd") or 0)
                except: return 0.0
        return 0.0
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), str(b.get("name") or "").lower()
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5 and data["o25"] == 0:
                try: data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x.get("value") == "Over 2.5"), 0))
                except: data["o25"] = 0.0
            if is_first_half_market(name):
                if data["o05ht"] == 0: data["o05ht"] = pick_over(b.get("values", []), "over0.5")
                if data["o15ht"] == 0: data["o15ht"] = pick_over(b.get("values", []), "over1.5")
            is_btts, is_1h = ("both" in name) or ("btts" in name) or ("gg" in name), ("1st" in name) or ("first" in name) or ("1h" in name) or ("half" in name)
            if (bid == 71 or (is_btts and is_1h)) and data["gg_ht"] == 0:
                for x in b.get("values", []):
                    if str(x.get("value") or "").strip().lower() in ["yes", "si", "oui"]:
                        try: data["gg_ht"] = float(x.get("odd") or 0)
                        except: data["gg_ht"] = 0.0
        if data["q1"] > 0 and data["o05ht"] > 0 and data["o15ht"] > 0 and data["gg_ht"] > 0: break
    return data

# ============================
# CORE ENGINE: PURE AUDITOR (V16.00)
# ============================
def execute_full_scan(session, fixtures, snap_mem, selected_countries):
    results, pb = [], st.progress(0)
    filtered = [f for f in fixtures if f["league"]["country"] in selected_countries]
    if not filtered: return []
    for i, m in enumerate(filtered):
        pb.progress((i+1)/len(filtered))
        try:
            mk = extract_markets_pro(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            fid_s = str(m["fixture"]["id"])
            s_h, s_a = get_comprehensive_stats(session, m["teams"]["home"]["id"]), get_comprehensive_stats(session, m["teams"]["away"]["id"])
            f_s, d_s = (s_h, s_a) if mk["q1"] < mk["q2"] else (s_a, s_h)

            # --- ANALISI PURA (TAG DI STATO) ---
            ht_ok = (s_h["ht_ratio"] >= 0.6 and s_a["ht_ratio"] >= 0.6)
            is_11ht_gate = (2.20 <= mk["o15ht"] <= 2.80) and (4.20 <= mk["gg_ht"] <= 5.50) and ht_ok
            is_o25_ok = (1.70 <= mk["o25"] < 2.00)
            is_o25_val = (1.70 <= mk["o25"] <= 2.25)
            is_o05_ok = (1.30 <= mk["o05ht"] <= 1.55)
            is_dry = f_s["is_dry"]
            
            det = []
            if ht_ok: det.append("HT-OK")
            if is_o25_ok: det.append("O25-OK")
            elif is_o25_val: det.append("O25-VAL")
            if is_o05_ok: det.append("O05-OK")
            if is_11ht_gate: det.append("GATE-11")
            
            # --- ASSEGNAZIONE STRATEGIE (SENZA RATING) ---
            score_gg, score_over = 0, 0
            
            if is_11ht_gate and f_s["vulnerability"] >= 0.8 and d_s["ht_ratio"] >= 0.6:
                det.append("🎯 GG-PT")
                score_gg = 1 # Flag per audit
            elif ht_ok and f_s["vulnerability"] >= 0.8:
                det.append("GG-PT-POT")

            if is_o25_ok and is_o05_ok and ht_ok:
                det.append("🔥 OVER-PRO")
                score_over = 1 # Flag per audit
                if (1.75 <= mk["o25"] < 2.00) and (mk["o05ht"] < 1.40): det.append("OVER-PRO+")
            
            if is_dry: det.append("DRY 💧")
            
            # Drop check (Context)
            if fid_s in snap_mem:
                if (min(snap_mem[fid_s]["q1"], snap_mem[fid_s]["q2"]) - min(mk["q1"], mk["q2"])) >= 0.15: det.append("Drop")

            # Marcaggio Top 5 Gate (usiamo HT Ratio media come criterio di ordinamento temporaneo)
            is_pool_ball = is_11ht_gate
            sort_val = (s_h["ht_ratio"] + s_a["ht_ratio"]) / 2

            results.append({
                "Ora": m["fixture"]["date"][11:16], "Lega": f"{m['league']['name']} ({m['league']['country']})", 
                "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5 Finale": f"{mk['o25']:.2f}", "O0.5 PT": f"{mk['o05ht']:.2f}",
                "O1.5 PT": f"{mk['o15ht']:.2f}", "GG PT": f"{mk['gg_ht']:.2f}", "Info": f"[{'|'.join(det)}]", 
                "Is_Gold": (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10), "Fixture_ID": fid_s,
                "Is_Pool": is_pool_ball, "SortVal": sort_val, "ScoreGG": score_gg, "ScoreOV": score_over
            })
        except: continue
    
    # ⚽ PALLONI: Top 5 del Gate per HT Ratio media
    pool = [r for r in results if r["Is_Pool"]]
    top_ids = set([x["Fixture_ID"] for x in sorted(pool, key=lambda z: z["SortVal"], reverse=True)[:5]])
    for r in results:
        if r["Fixture_ID"] in top_ids: r["Info"] = r["Info"][:-1] + "|⚽]"
    return results

# ============================
# UI E RENDERING
# ============================
st.sidebar.header("👑 Configurazione Auditor")
with st.sidebar.expander("🌍 Gestione Nazioni (PRO)", expanded=False):
    to_exclude = st.selectbox("Sposta in Escluse:", ["-- seleziona --"] + st.session_state["selected_countries"])
    if to_exclude != "-- seleziona --":
        if to_exclude not in st.session_state["excluded_countries"]:
            st.session_state["excluded_countries"].append(to_exclude)
            save_excluded_countries(st.session_state["excluded_countries"])
            st.rerun()
    st.markdown("---")
    to_include = st.selectbox("Sposta in Incluse:", ["-- seleziona --"] + st.session_state["excluded_countries"])
    if to_include != "-- seleziona --":
        st.session_state["excluded_countries"].remove(to_include)
        save_excluded_countries(st.session_state["excluded_countries"])
        st.rerun()

if st.session_state["odds_memory"]:
    st.sidebar.success(f"✅ Snapshot: {st.session_state['snap_time_obj'].strftime('%H:%M')}")
else: st.sidebar.warning("⚠️ Nessun Snapshot Caricato")

st.session_state["only_gold_ui"] = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=False)

CUSTOM_CSS = """
    <style>
        .main { background-color: #f0f2f6; }
        table { width: 100%; border-collapse: collapse; font-size: 0.82rem; font-family: sans-serif; }
        th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
        td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
        .match-cell { text-align: left !important; min-width: 220px; font-weight: 700; color: #333; }
    </style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

col_b1, col_b2 = st.columns(2)
def handle_run(is_snap):
    with requests.Session() as s:
        try:
            data = api_get(s, "fixtures", {"date": now_rome().strftime("%Y-%m-%d"), "timezone": "Europe/Rome"})
            fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and not any(t in f["league"]["name"].lower() for t in ["women","u19","u20","u21","u23","youth","friendly"])]
            if is_snap:
                new_snap = {}
                pb_snap = st.progress(0)
                for i, m in enumerate(fixtures):
                    pb_snap.progress((i+1)/len(fixtures))
                    try:
                        mk_s = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                        if mk_s and mk_s["q1"] > 0: new_snap[str(m["fixture"]["id"])] = {"q1": mk_s["q1"], "q2": mk_s["q2"]}
                    except: continue
                st.session_state["odds_memory"], st.session_state["snap_time_obj"] = new_snap, now_rome()
                with open(JSON_FILE, "w") as f: json.dump({"date": now_rome().strftime("%Y-%m-%d"), "timestamp": now_rome().isoformat(), "odds": new_snap}, f)
            st.session_state["scan_results"] = execute_full_scan(s, fixtures, st.session_state["odds_memory"], st.session_state["selected_countries"])
            st.rerun()
        except Exception as e: st.error(f"Errore: {e}")

if col_b1.button("📌 SNAPSHOT + SCAN"): handle_run(True)
if col_b2.button("🚀 AVVIA SCAN TOTALE"): handle_run(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    if st.session_state["only_gold_ui"]: df = df[df["Is_Gold"]]
    if not df.empty:
        cols = ["Ora", "Lega", "Match", "1X2", "O2.5 Finale", "O0.5 PT", "O1.5 PT", "GG PT", "Info"]
        def apply_row_style(row):
            info = df.loc[row.name, 'Info']
            # GERARCHIA COLORI
            if '🎯 GG-PT' in info: return ['background-color: #38003c; color: #00e5ff;' for _ in row] # VIOLA (1T)
            if 'OVER-PRO' in info: return ['background-color: #003300; color: #00ff00;' for _ in row] # VERDE (FT)
            if 'GG-PT-POT' in info or 'O25-VAL' in info: return ['background-color: #0c1a2b; color: #ffffff;' for _ in row] # BLU (Potenziale)
            return ['' for _ in row]
        st_style = df[cols].style.apply(apply_row_style, axis=1)
        st.write(st_style.to_html(escape=False, index=False), unsafe_allow_html=True)
        st.markdown("---")
        c1, c2 = st.columns(2)
        c1.download_button("💾 AUDITOR COMPLETO (CSV)", df.to_csv(index=False).encode('utf-8'), f"auditor_full_{now_rome().strftime('%Y%m%d')}.csv")
        h_dl = f"<html><head>{CUSTOM_CSS}</head><body>{st_style.to_html(escape=False, index=False)}</body></html>"
        c2.download_button("🌐 REPORT HTML", h_dl.encode('utf-8'), f"report_full.html")

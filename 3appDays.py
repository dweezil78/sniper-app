import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE PATH E BLACKLIST
# ============================
BASE_DIR = Path(__file__).resolve().parent
NAZIONI_FILE = str(BASE_DIR / "nazioni_config.json")

# Lista nazioni escluse di default (Aggiornata V18.20)
DEFAULT_EXCLUDED = [
    "Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda", 
    "Macedonia", "Nigeria", "Ivory-Coast", "Oman", "El-Salvador", 
    "Ethiopia", "Cameroon", "Jordan", "Algeria", "South-Africa",
    "Tanzania", "Montenegro", "UAE", "Guatemala", "Costa-Rica"
]

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

def get_snapshot_path(horizon):
    return str(BASE_DIR / f"arab_snapshot_{horizon}d.json")

def get_results_path(horizon):
    return str(BASE_DIR / f"last_results_{horizon}d.json")

st.set_page_config(page_title="ARAB SNIPER V18.20 - MASTER INTEGRITY", layout="wide")

# ============================
# API CORE
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params, retries=2):
    for i in range(retries + 1):
        try:
            r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
            if r.status_code == 429 and i < retries:
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            js = r.json()
            if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
            return js
        except Exception as e:
            if i == retries: raise e
            time.sleep(1)

# ============================
# INITIALIZATION & PERSISTENZA
# ============================
team_stats_cache = {} 

st.sidebar.header("👑 Arab Sniper Console")
st.sidebar.markdown("---")
HORIZON = st.sidebar.selectbox("Orizzonte Scan:", options=[1, 2, 3], index=0)

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "available_countries" not in st.session_state: st.session_state["available_countries"] = []
if "current_horizon" not in st.session_state: st.session_state["current_horizon"] = HORIZON

if st.session_state["current_horizon"] != HORIZON:
    st.session_state["odds_memory"] = {}
    st.session_state["scan_results"] = None
    st.session_state["current_horizon"] = HORIZON
    st.session_state["available_countries"] = []
    team_stats_cache.clear()

def load_excluded():
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                return list(json.load(f).get("excluded", DEFAULT_EXCLUDED))
        except: return DEFAULT_EXCLUDED
    return DEFAULT_EXCLUDED

if "excluded" not in st.session_state:
    st.session_state["excluded"] = load_excluded()

target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(HORIZON)]

# FIX 2: Popolamento available_countries
if not st.session_state["available_countries"]:
    try:
        with requests.Session() as s_fix:
            all_c = set()
            for d_fix in target_dates:
                data_fix = api_get(s_fix, "fixtures", {"date": d_fix, "timezone": "Europe/Rome"})
                for f_fix in data_fix.get("response", []):
                    all_c.add(f_fix["league"]["country"])
            st.session_state["available_countries"] = sorted(list(all_c))
    except:
        st.session_state["available_countries"] = []

# FIX 3: Recupero Risultati coerente con target_dates[0]
RES_FILE = get_results_path(HORIZON)
if st.session_state["scan_results"] is None and os.path.exists(RES_FILE):
    try:
        with open(RES_FILE, "r") as f:
            saved_res = json.load(f)
            if saved_res.get("base_date") == target_dates[0]:
                st.session_state["scan_results"] = saved_res.get("results", [])
    except: pass

SNAP_FILE = get_snapshot_path(HORIZON)
snapshot_info = None
if os.path.exists(SNAP_FILE):
    try:
        with open(SNAP_FILE, "r") as f:
            saved = json.load(f)
            snapshot_info = saved.get("timestamp", "N/D")
            if not st.session_state["odds_memory"]:
                if saved.get("base_date") == target_dates[0]:
                    st.session_state["odds_memory"] = saved.get("odds", {})
    except: pass

if snapshot_info:
    st.sidebar.success(f"📦 Snapshot {HORIZON}d: {snapshot_info}")
else:
    st.sidebar.warning(f"⚠️ Nessun Snapshot {HORIZON}d")

if st.sidebar.button(f"🧹 Reset Snapshot ({HORIZON}d)"):
    try: os.remove(get_snapshot_path(HORIZON))
    except: pass
    st.session_state["odds_memory"] = {}
    st.rerun()

# ============================
# LOGICA STATISTICHE (8 MATCH)
# ============================
def get_stats(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return {"ht_ratio": 0.0, "vulnerability": 0.0, "o25_ratio": 0.0, "gg_ratio": 0.0}
        ht, conc, o25, gg = 0, 0, 0, 0
        actual = len(fx)
        for f in fx:
            if ((f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0)) >= 1: ht += 1
            is_home = (f["teams"]["home"]["id"] == tid)
            if ((f["goals"]["away"] if is_home else f["goals"]["home"]) or 0) > 0: conc += 1
            if ((f["goals"]["home"] or 0) + (f["goals"]["away"] or 0)) >= 3: o25 += 1
            if (f["goals"]["home"] or 0) > 0 and (f["goals"]["away"] or 0) > 0: gg += 1
        res = {"ht_ratio": ht/actual, "vulnerability": conc/actual, "o25_ratio": o25/actual, "gg_ratio": gg/actual}
        team_stats_cache[tid] = res
        return res
    except: return {"ht_ratio": 0.0, "vulnerability": 0.0, "o25_ratio": 0.0, "gg_ratio": 0.0}

def extract_markets(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    
    def pick_o(values, key):
        for x in values or []:
            v = str(x.get("value") or "").lower().replace(" ", "").replace(",", ".")
            if v.startswith(key):
                try: return float(x.get("odd") or 0)
                except: return 0.0
        return 0.0

    for ibm, bm in enumerate(resp[0].get("bookmakers", [])):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), str(b.get("name") or "").lower()
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5 and data["o25"] == 0:
                for x in b.get("values", []) or []:
                    val = str(x.get("value") or "").lower().replace(" ", "").replace(",", ".")
                    if val.startswith("over2.5"):
                        try: data["o25"] = float(x.get("odd") or 0); break
                        except: pass
            is_btts_ht = (("both" in name or "btts" in name or "gg" in name) and ("1st" in name or "first" in name or "1h" in name or "half" in name))
            if (bid == 71 or is_btts_ht) and data["gg_ht"] == 0:
                for x in b.get("values", []):
                    if str(x.get("value") or "").strip().lower() in ["yes","si","oui"]:
                        try: data["gg_ht"] = float(x.get("odd") or 0); break
                        except: pass
            if ("1st" in name or "first half" in name) and ("over/under" in name or "total" in name):
                if data["o05ht"] == 0: data["o05ht"] = pick_o(b.get("values", []), "over0.5")
                if data["o15ht"] == 0: data["o15ht"] = pick_o(b.get("values", []), "over1.5")
        
        # FIX 4: Logica di break robusta per GGHT
        have_core = (data["q1"] > 0 and data["qx"] > 0 and data["q2"] > 0)
        have_over = (data["o25"] > 0 and data["o05ht"] > 0)
        have_gate = (data["o15ht"] > 0 and data["gg_ht"] > 0)
        if have_core and have_over and have_gate: break
        if ibm >= 4 and have_core and have_over: break 
    return data

# ============================
# CORE ENGINE: PRO LOGIC
# ============================
def execute_scan(session, fixtures, snap_mem, excluded, min_rating_val):
    results, pb = [], st.progress(0)
    filtered = [f for f in fixtures if f["league"]["country"] not in excluded]
    if not filtered: pb.progress(1.0); return []

    for i, m in enumerate(filtered):
        pb.progress((i+1)/len(filtered))
        try:
            mk = extract_markets(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            
            fid_s = str(m["fixture"]["id"])
            match_date = m["fixture"]["date"][:10]
            s_h, s_a = get_stats(session, m["teams"]["home"]["id"]), get_stats(session, m["teams"]["away"]["id"])
            fav_side = "q1" if mk["q1"] < mk["q2"] else "q2"
            f_s, d_s = (s_h, s_a) if fav_side == "q1" else (s_a, s_h)

            HT_OK = 1 if (s_h["ht_ratio"] >= 0.625 and s_a["ht_ratio"] >= 0.625) else 0
            O25_OK = 1 if (1.70 <= mk["o25"] < 2.00) else 0
            GATE_11 = 1 if ((2.20 <= mk["o15ht"] <= 2.80) and (4.20 <= mk["gg_ht"] <= 5.50) and HT_OK) else 0
            HAS_DROP = 1 if (fid_s in snap_mem and (snap_mem[fid_s].get("fav_odd", 0) - mk[snap_mem[fid_s].get("fav_side", "q1")]) >= 0.15) else 0

            SIG_GG_PT = 1 if (GATE_11 and f_s["vulnerability"] >= 0.625) else 0
            avg_vul = (s_h["vulnerability"] + s_a["vulnerability"]) / 2
            SIG_O25_BOOST = 1 if (HT_OK and (1.70 <= mk["o25"] <= 2.10) and (1.18 <= mk["o05ht"] <= 1.40) and (avg_vul >= 0.625 or f_s["vulnerability"] >= 0.75)) else 0
            SIG_OVER_PRO = 1 if (O25_OK and (1.30 <= mk["o05ht"] <= 1.55) and HT_OK) else 0

            FISH_O = 1 if (1.40 <= min(mk["q1"], mk["q2"]) <= 1.80 and f_s["o25_ratio"] >= 0.625) else 0
            FISH_GG = 1 if (2.20 <= mk["q1"] <= 3.80 and 2.20 <= mk["q2"] <= 3.80 and s_h["gg_ratio"] >= 0.625 and s_a["gg_ratio"] >= 0.625) else 0

            det = []
            if HT_OK: det.append("HT-OK")
            if O25_OK: det.append("O25-OK")
            if GATE_11: det.append("GATE-11")
            if HAS_DROP: det.append("Drop")
            if SIG_GG_PT: det.append("🎯 GG-PT")
            if SIG_O25_BOOST: det.append("💣 O25-BOOST")
            if SIG_OVER_PRO: det.append("🔥 OVER-PRO")
            if FISH_O: det.append("🐟O")
            if FISH_GG: det.append("🐟GG")

            b_seg = max((25 if SIG_GG_PT else 0), (30 if SIG_O25_BOOST else (20 if SIG_OVER_PRO else 0)))
            b_drop = (30 if HAS_DROP else 0)
            b_fish = (10 if (FISH_O or FISH_GG) else 0)
            rating = min(100, 45 + b_seg + b_drop + b_fish)

            if rating >= min_rating_val:
                results.append({
                    "Data": match_date, "Ora": m["fixture"]["date"][11:16], "Lega": f"{m['league']['name']} ({m['league']['country']})", "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}", "O1.5HT": f"{mk['o15ht']:.2f}", "GGPT": f"{mk['gg_ht']:.2f}",
                    "Info": f"[{'|'.join(det)}]", "Rating": rating, "Gold": "✅" if (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10) else "❌",
                    "Is_Gold_Bool": (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10), "O25_OK": O25_OK
                })
        except: continue
    return results

# ============================
# UI E RENDERING
# ============================
st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Configurazione Audit")
only_fav_gold = st.sidebar.toggle("🎯 SOLO SWEET SPOT FAV", value=False)
only_o25_gold = st.sidebar.toggle("⚽ SOLO SWEET SPOT O2.5", value=False)
min_rating_ui = st.sidebar.slider("Rating Minimo", 0, 85, 20)

# FIX 1: available_countries expander
with st.sidebar.expander("🌍 Filtro Nazioni", expanded=False):
    sel = [c for c in st.session_state["available_countries"] if c not in st.session_state["excluded"]]
    to_ex = st.selectbox("Escludi:", ["-- seleziona --"] + sel)
    if to_ex != "-- seleziona --":
        st.session_state["excluded"].append(to_ex)
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": st.session_state["excluded"]}, f)
        st.rerun()
    to_in = st.selectbox("Ripristina:", ["-- seleziona --"] + st.session_state["excluded"])
    if to_in != "-- seleziona --":
        st.session_state["excluded"].remove(to_in)
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": st.session_state["excluded"]}, f)
        st.rerun()

CUSTOM_CSS = """
<style>
    .stTableContainer { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    th { background-color: #1a1c23; color: #00e5ff; padding: 8px; white-space: nowrap; }
    td { padding: 5px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

def run_scan(is_snap):
    with requests.Session() as s:
        try:
            all_fixs = []
            for d in target_dates:
                data = api_get(s, "fixtures", {"date": d, "timezone": "Europe/Rome"})
                all_fixs.extend([f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and not any(t in f["league"]["name"].lower() for t in ["women","u19","u20","u21","u23","youth","friendly"])])
            
            if is_snap:
                existing_snap = {}
                if os.path.exists(get_snapshot_path(HORIZON)):
                    try:
                        with open(get_snapshot_path(HORIZON), "r") as f:
                            saved = json.load(f)
                            if saved.get("base_date") == target_dates[0]: existing_snap = saved.get("odds", {})
                    except: pass
                new_snap = dict(existing_snap)
                pb_s = st.progress(0)
                total_s = len(all_fixs)
                if total_s > 0:
                    for i, m in enumerate(all_fixs):
                        pb_s.progress((i+1)/total_s)
                        fid = str(m["fixture"]["id"])
                        if fid in new_snap: continue
                        mk = extract_markets(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                        if mk and mk["q1"] > 0:
                            fs = "q1" if mk["q1"] < mk["q2"] else "q2"
                            new_snap[fid] = {"fav_side": fs, "fav_odd": mk[fs], "q1": mk["q1"], "q2": mk["q2"]}
                else: pb_s.progress(1.0)
                st.session_state["odds_memory"] = new_snap
                ts = now_rome().strftime("%d/%m/%Y %H:%M")
                with open(get_snapshot_path(HORIZON), "w") as f:
                    json.dump({"base_date": target_dates[0], "horizon": HORIZON, "dates": target_dates, "odds": new_snap, "timestamp": ts}, f)
            
            res = execute_scan(s, all_fixs, st.session_state["odds_memory"], st.session_state["excluded"], min_rating_ui)
            st.session_state["scan_results"] = res
            with open(get_results_path(HORIZON), "w") as f:
                json.dump({"base_date": target_dates[0], "results": res}, f)
            st.rerun()
        except Exception as e: st.error(str(e))

col1, col2 = st.columns(2)
if col1.button("📌 SNAPSHOT + SCAN"): run_scan(True)
if col2.button("🚀 SCAN TOTALE"): run_scan(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    if not df.empty:
        if only_fav_gold: df = df[df["Is_Gold_Bool"]]
        if only_o25_gold: df = df[df["O25_OK"] == 1]
    
    if df.empty: st.warning("Nessun match trovato.")
    else:
        def style_row(row):
            if '🎯 GG-PT' in row['Info']: return ['background-color: #38003c; color: #00e5ff;' for _ in row]
            if '💣 O25-BOOST' in row['Info']: return ['background-color: #003300; color: #00ff00;' for _ in row] 
            return ['' for _ in row]
        DISPLAY_COLS = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "O1.5HT", "GGPT", "Info", "Rating", "Gold"]
        st_style = df[DISPLAY_COLS].sort_values(["Data", "Ora"]).style.apply(style_row, axis=1)
        st.write(st_style.to_html(escape=False, index=False), unsafe_allow_html=True)
        with st.expander("📖 GUIDA"):
            st.markdown("* **💣 O25-BOOST:** Over 2.5 Top. * **🎯 GG-PT:** Gol Entrambe 1T. * **🐟O:** Dominio. * **🐟GG:** Scambio.")

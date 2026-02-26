import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE V19.60 - SECURITY & PRECISION
# ============================
BASE_DIR = Path(__file__).resolve().parent
NAZIONI_FILE = str(BASE_DIR / "nazioni_config.json")

DEFAULT_EXCLUDED = [
    "Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda", 
    "Macedonia", "Nigeria", "Ivory-Coast", "Oman", "El-Salvador", 
    "Ethiopia", "Cameroon", "Jordan", "Algeria", "South-Africa",
    "Tanzania", "Montenegro", "UAE", "Guatemala", "Costa-Rica"
]

LEAGUE_KEYWORDS_BLACKLIST = [
    "regionalliga", "carioca", "paulista", "pernambucano", "gaucho", 
    "mineiro", "youth", "friendly", "u19", "u20", "u21", "u23", "women"
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

st.set_page_config(page_title="ARAB SNIPER V19.60 - SECURITY & PRECISION", layout="wide")

# ============================
# API CORE & SECURITY CHECK (Fix Critico #1)
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("⚠️ Manca API_SPORTS_KEY nei Secrets di Streamlit Cloud. Controlla la configurazione.")
    st.stop()

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
# INITIALIZATION & SLIDING WINDOW
# ============================
if "excluded" not in st.session_state:
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                st.session_state["excluded"] = list(json.load(f).get("excluded", DEFAULT_EXCLUDED))
        except: st.session_state["excluded"] = DEFAULT_EXCLUDED
    else:
        st.session_state["excluded"] = DEFAULT_EXCLUDED

if "available_countries" not in st.session_state: st.session_state["available_countries"] = []
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None

st.sidebar.header("👑 Arab Sniper Console")
st.sidebar.markdown("---")
HORIZON = st.sidebar.selectbox("Orizzonte Scan:", options=[1, 2, 3], index=0)

if "current_horizon" not in st.session_state or st.session_state["current_horizon"] != HORIZON:
    st.session_state["odds_memory"] = {}
    st.session_state["scan_results"] = None
    st.session_state["current_horizon"] = HORIZON

target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(HORIZON)]

def load_sliding_data():
    res_path = get_results_path(HORIZON)
    if os.path.exists(res_path):
        try:
            with open(res_path, "r") as f:
                data = json.load(f)
                if data.get("base_date") == target_dates[0]:
                    st.session_state["scan_results"] = data.get("results", [])
        except: pass

    snap_path = get_snapshot_path(HORIZON)
    if os.path.exists(snap_path):
        try:
            with open(snap_path, "r") as f:
                data = json.load(f)
                if data.get("base_date") == target_dates[0]:
                    st.session_state["odds_memory"] = data.get("odds", {})
                    return data.get("timestamp", "N/D")
        except: pass
    return None

snap_info = load_sliding_data()
if snap_info:
    st.sidebar.success(f"📦 Dati caricati: {target_dates[0]}\nSnapshot: {snap_info}")

if not st.session_state["available_countries"]:
    try:
        with requests.Session() as s_init:
            all_c = set()
            d_init = target_dates[0]
            data_init = api_get(s_init, "fixtures", {"date": d_init, "timezone": "Europe/Rome"})
            for f_init in data_init.get("response", []): all_c.add(f_init["league"]["country"])
            st.session_state["available_countries"] = sorted(list(all_c))
    except: pass

# ============================
# LOGICA IBRIDA STATS
# ============================
team_stats_cache = {}

def get_stats(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return {"ht5":0.0, "vul5":0.0, "o25_8":0.0, "gg8":0.0}
        
        fx5 = fx[:5]
        ht5 = sum(1 for f in fx5 if ((f["score"]["halftime"]["home"] or 0) + (f["score"]["halftime"]["away"] or 0)) >= 1) / len(fx5)
        
        def is_conc(f, team_id):
            is_h = (f["teams"]["home"]["id"] == team_id)
            return 1 if ((f["goals"]["away"] if is_h else f["goals"]["home"]) or 0) > 0 else 0
        vul5 = sum(1 for f in fx5 if is_conc(f, tid)) / len(fx5)
        
        act8 = len(fx)
        o25_8 = sum(1 for f in fx if ((f["goals"]["home"] or 0) + (f["goals"]["away"] or 0)) >= 3) / act8
        gg8 = sum(1 for f in fx if (f["goals"]["home"] or 0) > 0 and (f["goals"]["away"] or 0) > 0) / act8
        
        res = {"ht5": ht5, "vul5": vul5, "o25_8": o25_8, "gg8": gg8}
        team_stats_cache[tid] = res
        return res
    except: return {"ht5":0.0, "vul5":0.0, "o25_8":0.0, "gg8":0.0}

def extract_markets(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    def clean(s): return str(s or "").lower().replace(" ", "").replace("(", "").replace(")", "").replace("-", "").replace(",", ".")

    for ibm, bm in enumerate(resp[0].get("bookmakers", [])):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), clean(b.get("name"))
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3:
                    for vo in v:
                        vn = clean(vo.get("value"))
                        if "home" in vn: data["q1"] = float(vo["odd"])
                        elif "draw" in vn: data["qx"] = float(vo["odd"])
                        elif "away" in vn: data["q2"] = float(vo["odd"])
                    if data["q1"] == 0: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            
            if bid == 5 and data["o25"] == 0:
                for x in b.get("values", []):
                    if "over2.5" in clean(x.get("value")): data["o25"] = float(x.get("odd") or 0); break
            
            is_btts = any(k in name for k in ["btts", "both", "gg"])
            # Fix Critico #2: "first" rimosso per evitare mercati non-HT
            is_1h = any(k in name for k in ["1st", "1h", "firsthalf", "half"])
            
            if (bid == 71 or (is_btts and is_1h)) and data["gg_ht"] == 0:
                for x in b.get("values", []):
                    vn = clean(x.get("value"))
                    if any(vn.startswith(k) for k in ["yes", "si", "oui"]): data["gg_ht"] = float(x.get("odd") or 0); break
            
            if is_1h and any(k in name for k in ["overunder", "total"]):
                for x in b.get("values", []):
                    vn = clean(x.get("value"))
                    if "over0.5" in vn and data["o05ht"] == 0: data["o05ht"] = float(x.get("odd") or 0)
                    if "over1.5" in vn and data["o15ht"] == 0: data["o15ht"] = float(x.get("odd") or 0)
        
        if data["q1"]>0 and data["o25"]>0 and data["o05ht"]>0: break
        if ibm >= 5: break 
    return data

# ============================
# CORE ENGINE
# ============================
def execute_scan(session, fixtures, snap_mem, excluded, min_rating_val):
    results, pb = [], st.progress(0)
    filtered = [f for f in fixtures if f["league"]["country"] not in excluded and not any(k in f["league"]["name"].lower() for k in LEAGUE_KEYWORDS_BLACKLIST)]
    
    for i, m in enumerate(filtered):
        pb.progress((i+1)/len(filtered))
        try:
            mk = extract_markets(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            fid_s = str(m["fixture"]["id"])
            s_h, s_a = get_stats(session, m["teams"]["home"]["id"]), get_stats(session, m["teams"]["away"]["id"])
            
            HT_OK = 1 if ((s_h["ht5"] + s_a["ht5"]) / 2 >= 0.6) else 0
            
            HAS_DROP = 0
            if fid_s in snap_mem:
                sq1, sq2 = float(snap_mem[fid_s].get("q1", 0)), float(snap_mem[fid_s].get("q2", 0))
                if max(sq1 - mk["q1"], sq2 - mk["q2"]) >= 0.15: HAS_DROP = 1

            O25_OK = 1 if (1.70 <= mk["o25"] < 2.00) else 0
            gate_o15, gate_gg = (2.20 <= mk["o15ht"] <= 2.80), (4.20 <= mk["gg_ht"] <= 5.50)
            GATE_11 = 1 if (HT_OK and (gate_o15 or gate_gg)) else 0
            fav_side = "q1" if mk["q1"] < mk["q2"] else "q2"
            f_stats = s_h if fav_side == "q1" else s_a
            
            SIG_GG_PT = 1 if (GATE_11 and f_stats["vul5"] >= 0.6) else 0
            avg_vul = (s_h["vul5"] + s_a["vul5"]) / 2
            SIG_O25_BOOST = 1 if (HT_OK and (1.70 <= mk["o25"] <= 2.10) and (1.18 <= mk["o05ht"] <= 1.40) and (avg_vul >= 0.6 or f_stats["vul5"] >= 0.8)) else 0
            SIG_OVER_PRO = 1 if (O25_OK and (1.30 <= mk["o05ht"] <= 1.55) and HT_OK) else 0

            FISH_O = 1 if (1.40 <= min(mk["q1"], mk["q2"]) <= 1.80 and f_stats["o25_8"] >= 0.75) else 0
            FISH_GG = 1 if (2.20 <= mk["q1"] <= 3.80 and 2.20 <= mk["q2"] <= 3.80 and s_h["gg8"] >= 0.75 and s_a["gg8"] >= 0.75) else 0

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

            rating = min(100, 40 + max((25 if SIG_GG_PT else 0), (30 if SIG_O25_BOOST else (20 if SIG_OVER_PRO else 0))) + (30 if HAS_DROP else 0) + (15 if (FISH_O or FISH_GG) else 0))

            if rating >= min_rating_val:
                results.append({
                    "Fixture_ID": m["fixture"]["id"], "Data": m["fixture"]["date"][:10], "Ora": m["fixture"]["date"][11:16], 
                    "Lega": f"{m['league']['name']} ({m['league']['country']})", "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}", "O1.5HT": f"{mk['o15ht']:.2f}", 
                    "Quota GG1T": f"{mk['gg_ht']:.2f}", 
                    "Info": f"[{'|'.join(det)}]", "Rating": rating, "Gold": "✅" if (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10) else "❌",
                    "Is_Gold_Bool": (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10), "O25_OK": O25_OK
                })
        except: continue
    return results

# ============================
# UI E RENDERING
# ============================
st.sidebar.subheader("🛡️ Audit Config")
only_fav_gold = st.sidebar.toggle("🎯 SOLO SWEET SPOT FAV")
only_o25_gold = st.sidebar.toggle("⚽ SOLO SWEET SPOT O2.5")
min_rating_ui = st.sidebar.slider("Rating Minimo", 0, 85, 30) # Default 30 come richiesto

with st.sidebar.expander("🌍 Filtro Nazioni", expanded=False):
    sel_countries = [c for c in st.session_state["available_countries"] if c not in st.session_state["excluded"]]
    to_ex = st.selectbox("Escludi:", ["-- seleziona --"] + sel_countries)
    if to_ex != "-- seleziona --":
        st.session_state["excluded"].append(to_ex)
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": st.session_state["excluded"]}, f)
        st.rerun()
    to_in = st.selectbox("Ripristina:", ["-- seleziona --"] + st.session_state["excluded"])
    if to_in != "-- seleziona --":
        st.session_state["excluded"].remove(to_in)
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": st.session_state["excluded"]}, f)
        st.rerun()

CUSTOM_CSS = """<style>.stTableContainer { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 0.82rem; } th { background-color: #1a1c23; color: #00e5ff; padding: 8px; white-space: nowrap; } td { padding: 5px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }</style>"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

def run_scan(is_snap):
    with requests.Session() as s:
        try:
            all_fixs = []
            for d in target_dates:
                data = api_get(s, "fixtures", {"date": d, "timezone": "Europe/Rome"})
                all_fixs.extend([f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS"])
            
            if is_snap:
                new_snap = {}
                pb_s = st.progress(0)
                for i, m in enumerate(all_fixs):
                    pb_s.progress((i+1)/len(all_fixs))
                    mk = extract_markets(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if mk and mk["q1"] > 0: new_snap[str(m["fixture"]["id"])] = {"q1": mk["q1"], "q2": mk["q2"]}
                st.session_state["odds_memory"] = new_snap
                with open(get_snapshot_path(HORIZON), "w") as f: 
                    json.dump({"base_date": target_dates[0], "odds": new_snap, "timestamp": now_rome().strftime("%d/%m/%Y %H:%M")}, f)
            
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
    def style_row(row):
        if '🎯 GG-PT' in row['Info']: return ['background-color: #38003c; color: #00e5ff;' for _ in row]
        if '💣 O25-BOOST' in row['Info']: return ['background-color: #003300; color: #00ff00;' for _ in row] 
        if ('🐟O' in row['Info'] or '🐟GG' in row['Info']) and row['Rating'] >= 55: return ['background-color: #004d4d; color: #00ffff;' for _ in row]
        return ['' for _ in row]
    
    DISPLAY_COLS = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "O1.5HT", "Quota GG1T", "Info", "Rating", "Gold"]
    st_style = df[DISPLAY_COLS].sort_values(["Data", "Ora"]).style.apply(style_row, axis=1)
    st.write(st_style.to_html(escape=False, index=False), unsafe_allow_html=True)
    
    st.markdown("---")
    c1, c2 = st.columns(2)
    c1.download_button("💾 CSV Audit", df.to_csv(index=False).encode('utf-8'), f"audit_{target_dates[0]}.csv")
    c2.download_button("🌐 HTML Report", f"<html><head>{CUSTOM_CSS}</head><body>{st_style.to_html(escape=False, index=False)}</body></html>".encode('utf-8'), f"report_{target_dates[0]}.html")

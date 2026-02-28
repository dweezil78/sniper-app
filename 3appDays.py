import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE V20.50 - ROLLING DATABASE
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

# Usiamo un percorso unico per il Database per favorire lo sliding automatico
def get_db_path():
    return str(BASE_DIR / "arab_sniper_database.json")

def get_snap_db_path():
    return str(BASE_DIR / "arab_snapshot_database.json")

st.set_page_config(page_title="ARAB SNIPER V20.50 - ROLLING DB", layout="wide")

# ============================
# API CORE & SECURITY
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("❌ API_SPORTS_KEY mancante!")
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
# INITIALIZATION & ROLLING LOGIC
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
if "scan_results" not in st.session_state: st.session_state["scan_results"] = []

target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

def load_and_slide_db():
    """Carica il database e rimuove i match dei giorni passati (Sliding Window)"""
    db_path = get_db_path()
    snap_path = get_snap_db_path()
    today_str = target_dates[0]

    if os.path.exists(db_path):
        try:
            with open(db_path, "r") as f:
                data = json.load(f)
                all_results = data.get("results", [])
                # SLIDING: Teniamo solo i match da oggi in poi
                valid_results = [r for r in all_results if r["Data"] >= today_str]
                st.session_state["scan_results"] = valid_results
        except: pass

    if os.path.exists(snap_path):
        try:
            with open(snap_path, "r") as f:
                data = json.load(f)
                st.session_state["odds_memory"] = data.get("odds", {})
                return data.get("timestamp", "N/D")
        except: pass
    return None

last_snap_ts = load_and_slide_db()

st.sidebar.header("👑 Arab Sniper Console")
st.sidebar.markdown(f"📅 **Oggi:** {target_dates[0]}")
HORIZON = st.sidebar.selectbox("Orizzonte Scan (Giorno):", options=[1, 2, 3], index=0)

if last_snap_ts:
    st.sidebar.success(f"📦 DB Sincronizzato ({last_snap_ts})")

# Popolamento nazioni (invariato)
if not st.session_state["available_countries"]:
    try:
        with requests.Session() as s_init:
            all_c = set()
            data_init = api_get(s_init, "fixtures", {"date": target_dates[0], "timezone": "Europe/Rome"})
            for f_init in data_init.get("response", []): all_c.add(f_init["league"]["country"])
            st.session_state["available_countries"] = sorted(list(all_c))
    except: pass

# ============================
# LOGICA STATISTICHE & MERCATI
# ============================
team_stats_cache = {}

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
            is_h = (f["teams"]["home"]["id"] == tid)
            if ((f["goals"]["away"] if is_h else f["goals"]["home"]) or 0) > 0: conc += 1
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
    def clean(s): return str(s or "").lower().replace(" ", "").replace("(", "").replace(")", "").replace("-", "").replace(",", ".")

    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name_raw = b.get("id"), str(b.get("name") or "").lower()
            name_clean = clean(name_raw)
            if bid == 1 and data["q1"] == 0:
                for vo in b.get("values", []):
                    vn = clean(vo.get("value"))
                    if "home" in vn: data["q1"] = float(vo["odd"])
                    elif "draw" in vn: data["qx"] = float(vo["odd"])
                    elif "away" in vn: data["q2"] = float(vo["odd"])
            if bid == 5 and data["o25"] == 0:
                for x in b.get("values", []):
                    if clean(x.get("value")) == "over2.5": data["o25"] = float(x.get("odd") or 0); break
            
            is_1h = (("1st" in name_raw) or ("firsthalf" in name_clean) or (("first" in name_raw) and ("half" in name_raw))) and not (("2nd" in name_raw) or ("second" in name_raw))
            
            if (bid == 71 or (("gg" in name_clean or "both" in name_clean) and is_1h)) and data["gg_ht"] == 0:
                for x in b.get("values", []):
                    if clean(x.get("value")) in ["yes", "si", "oui"]: data["gg_ht"] = float(x.get("odd") or 0); break
            if is_1h and any(k in name_raw for k in ["over/under", "total"]):
                for x in b.get("values", []):
                    vn, odd_val = clean(x.get("value")), float(x.get("odd") or 0)
                    if vn == "over0.5" and data["o05ht"] == 0 and odd_val < 1.75: data["o05ht"] = odd_val
                    if vn == "over1.5" and data["o15ht"] == 0: data["o15ht"] = odd_val
        if data["q1"]>0 and data["o05ht"]>0: break
    return data

# ============================
# CORE SCAN ENGINE
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
            
            HT_OK = 1 if (s_h["ht_ratio"] >= 0.625 and s_a["ht_ratio"] >= 0.625) else 0
            
            HAS_DROP = 0
            if fid_s in snap_mem:
                sq1, sq2 = float(snap_mem[fid_s].get("q1", 0)), float(snap_mem[fid_s].get("q2", 0))
                if max(sq1 - mk["q1"], sq2 - mk["q2"]) >= 0.15: HAS_DROP = 1

            O25_OK = 1 if (1.70 <= mk["o25"] < 2.00) else 0
            gate_o15, gate_gg = (2.20 <= mk["o15ht"] <= 2.80), (4.20 <= mk["gg_ht"] <= 5.50)
            GATE_11 = 1 if (HT_OK and (gate_o15 or gate_gg)) else 0
            fav_side = "q1" if mk["q1"] < mk["q2"] else "q2"
            f_stats = s_h if fav_side == "q1" else s_a
            
            SIG_GG_PT = 1 if (GATE_11 and f_stats["vulnerability"] >= 0.6) else 0
            avg_vul = (s_h["vulnerability"] + s_a["vulnerability"]) / 2
            
            SIG_O25_BOOST = 1 if (HT_OK and (1.60 <= mk["o25"] <= 2.15) and (1.20 <= mk["o05ht"] <= 1.55) and (avg_vul >= 0.6 or f_stats["vulnerability"] >= 0.75)) else 0
            SIG_OVER_PRO = 1 if (O25_OK and (1.20 <= mk["o05ht"] <= 1.55) and HT_OK) else 0

            FISH_O = 1 if (1.40 <= min(mk["q1"], mk["q2"]) <= 1.80 and f_stats["o25_ratio"] >= 0.625) else 0
            FISH_GG = 1 if (2.20 <= mk["q1"] <= 3.80 and 2.20 <= mk["q2"] <= 3.80 and s_h["gg_ratio"] >= 0.625 and s_a["gg_ratio"] >= 0.625) else 0

            det = []
            if HT_OK: det.append("HT-OK")
            if SIG_GG_PT: det.append("🎯 GG-PT")
            if SIG_O25_BOOST: det.append("💣 O25-BOOST")
            if SIG_OVER_PRO: det.append("🔥 OVER-PRO")
            if FISH_O: det.append("🐟O")
            if FISH_GG: det.append("🐟GG")
            if HAS_DROP: det.append("Drop")

            rating = min(100, 45 + max((25 if SIG_GG_PT else 0), (30 if SIG_O25_BOOST else (20 if SIG_OVER_PRO else 0))) + (30 if HAS_DROP else 0) + (10 if (FISH_O or FISH_GG) else 0))

            if rating >= min_rating_val:
                results.append({
                    "Fixture_ID": m["fixture"]["id"], "Data": m["fixture"]["date"][:10], "Ora": m["fixture"]["date"][11:16], 
                    "Lega": f"{m['league']['name']} ({m['league']['country']})", "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}", "O1.5HT": f"{mk['o15ht']:.2f}", 
                    "Quota GG1T": f"{mk['gg_ht']:.2f}", "Info": f"[{'|'.join(det)}]", "Rating": rating, "Gold": "✅" if (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10) else "❌",
                    "Is_Gold_Bool": (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10), "O25_OK": O25_OK
                })
        except: continue
    return results

# ============================
# UI SIDEBAR (Tua Struttura Originale)
# ============================
st.sidebar.subheader("🛡️ Audit Config")
only_fav_gold = st.sidebar.toggle("🎯 SOLO SWEET SPOT FAV", value=False)
only_o25_gold = st.sidebar.toggle("⚽ SOLO SWEET SPOT O2.5", value=False)
min_rating_ui = st.sidebar.slider("Rating Minimo", 0, 85, 30)

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

# ============================
# RENDERING & INCREMENTAL SCAN
# ============================
CUSTOM_CSS = """<style>.stTableContainer { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 0.82rem; } th { background-color: #1a1c23; color: #00e5ff; padding: 8px; white-space: nowrap; } td { padding: 5px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }</style>"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

def run_scan(is_snap):
    with requests.Session() as s:
        try:
            target_date = target_dates[HORIZON - 1]
            st.info(f"Avvio scan incrementale per il giorno: {target_date}")
            
            data = api_get(s, "fixtures", {"date": target_date, "timezone": "Europe/Rome"})
            day_fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS"]
            
            if is_snap:
                current_snap = st.session_state["odds_memory"]
                pb_s = st.progress(0)
                for i, m in enumerate(day_fixtures):
                    pb_s.progress((i+1)/len(day_fixtures))
                    mk = extract_markets(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if mk and mk["q1"] > 0: current_snap[str(m["fixture"]["id"])] = {"q1": mk["q1"], "q2": mk["q2"]}
                
                st.session_state["odds_memory"] = current_snap
                with open(get_snap_db_path(), "w") as f_s: 
                    json.dump({"odds": current_snap, "timestamp": now_rome().strftime("%d/%m/%Y %H:%M")}, f_s)
            
            new_results = execute_scan(s, day_fixtures, st.session_state["odds_memory"], st.session_state["excluded"], min_rating_ui)
            
            # UNIONE NEL DATABASE UNICO
            existing = st.session_state["scan_results"]
            existing_ids = [r["Fixture_ID"] for r in existing]
            filtered_new = [r for r in new_results if r["Fixture_ID"] not in existing_ids]
            all_res = existing + filtered_new
            
            st.session_state["scan_results"] = all_res
            with open(get_db_path(), "w") as f_db: 
                json.dump({"results": all_res}, f_db)
            
            st.success(f"Giorno {target_date} sincronizzato nel database!"); time.sleep(1); st.rerun()
        except Exception as e:
            st.error(str(e))

col1, col2 = st.columns(2)
if col1.button("📌 SNAPSHOT + SCAN (MIRATO)"): run_scan(True)
if col2.button("🚀 SCAN VELOCE (NO SNAP)"): run_scan(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    # Mostriamo solo i match del giorno selezionato in sidebar
    df_view = df[df["Data"] == target_dates[HORIZON-1]]
    
    if not df_view.empty:
        if only_fav_gold: df_view = df_view[df_view["Is_Gold_Bool"]]
        if only_o25_gold: df_view = df_view[df_view["O25_OK"] == 1]
        
        def style_row(row):
            if '🎯 GG-PT' in row['Info']: return ['background-color: #38003c; color: #00e5ff;' for _ in row]
            if '💣 O25-BOOST' in row['Info']: return ['background-color: #003300; color: #00ff00;' for _ in row] 
            if ('🐟O' in row['Info'] or '🐟GG' in row['Info']) and row['Rating'] >= 55: return ['background-color: #004d4d; color: #00ffff;' for _ in row]
            return ['' for _ in row]
        
        DISPLAY_COLS = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "O1.5HT", "Quota GG1T", "Info", "Rating", "Gold"]
        st_style = df_view[DISPLAY_COLS].sort_values(["Ora"]).style.apply(style_row, axis=1)
        st.write(st_style.to_html(escape=False, index=False), unsafe_allow_html=True)
        
        st.markdown("---")
        # Il download esporta SEMPRE tutto il database (3 giorni) per l'Auditor
        st.download_button("💾 Esporta D

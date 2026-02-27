import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE V20.10 - AUTO-SLIDE FIX
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

st.set_page_config(page_title="ARAB SNIPER V20.10 - AUTO-SLIDE", layout="wide")

# ============================
# API CORE
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
# INITIALIZATION & AUTO-SLIDING LOGIC
# ============================
if "excluded" not in st.session_state:
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                st.session_state["excluded"] = list(json.load(f).get("excluded", DEFAULT_EXCLUDED))
        except: st.session_state["excluded"] = DEFAULT_EXCLUDED
    else: st.session_state["excluded"] = DEFAULT_EXCLUDED

if "available_countries" not in st.session_state: st.session_state["available_countries"] = []
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None

st.sidebar.header("👑 Arab Sniper Console")
HORIZON = st.sidebar.selectbox("Giorno da Scansionare:", options=[1, 2, 3], index=0)

target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

def load_sliding_data():
    """Tenta di caricare i dati. Se la data è cambiata, prova a recuperare dal file 3d."""
    res_path = get_results_path(3) # Usiamo sempre il file globale da 3 giorni come database
    snap_path = get_snapshot_path(3)
    
    if os.path.exists(res_path):
        try:
            with open(res_path, "r") as f:
                data = json.load(f)
                saved_date = data.get("base_date")
                results = data.get("results", [])
                
                # Se la data salvata è diversa da oggi, filtriamo i match vecchi
                # ma teniamo quelli che scadono oggi o nei prossimi giorni
                today_str = target_dates[0]
                filtered_res = [r for r in results if r["Data"] >= today_str]
                st.session_state["scan_results"] = filtered_res
                
                # Se abbiamo dovuto pulire il file perché la data è cambiata, aggiorniamo il file
                if saved_date != today_str:
                    with open(res_path, "w") as fw:
                        json.dump({"base_date": today_str, "results": filtered_res}, fw)
        except: pass

    if os.path.exists(snap_path):
        try:
            with open(snap_path, "r") as f:
                data = json.load(f)
                st.session_state["odds_memory"] = data.get("odds", {})
                return data.get("timestamp", "N/D")
        except: pass
    return None

snap_info = load_sliding_data()
if snap_info:
    st.sidebar.success(f"📦 Database Sincronizzato\nData Base: {target_dates[0]}")

# ============================
# MOTORE DI ANALISI (ESTRAZIONE E STATS)
# ============================
def get_stats(session, tid):
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
        return {"ht_ratio": ht/actual, "vulnerability": conc/actual, "o25_ratio": o25/actual, "gg_ratio": gg/actual}
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
# SCAN & UI
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
            HAS_DROP = 1 if (fid_s in snap_mem and max(float(snap_mem[fid_s].get("q1", 0)) - mk["q1"], float(snap_mem[fid_s].get("q2", 0)) - mk["q2"]) >= 0.15) else 0
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

def run_scan(is_snap):
    with requests.Session() as s:
        try:
            specific_date = target_dates[HORIZON - 1]
            data = api_get(s, "fixtures", {"date": specific_date, "timezone": "Europe/Rome"})
            day_fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS"]
            
            if is_snap:
                current_snap = st.session_state["odds_memory"]
                pb_s = st.progress(0)
                for i, m in enumerate(day_fixtures):
                    pb_s.progress((i+1)/len(day_fixtures))
                    mk = extract_markets(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if mk and mk["q1"] > 0: current_snap[str(m["fixture"]["id"])] = {"q1": mk["q1"], "q2": mk["q2"]}
                st.session_state["odds_memory"] = current_snap
                with open(get_snapshot_path(3), "w") as f: 
                    json.dump({"base_date": target_dates[0], "odds": current_snap, "timestamp": now_rome().strftime("%d/%m/%Y %H:%M")}, f)
            
            new_results = execute_scan(s, day_fixtures, st.session_state["odds_memory"], st.session_state["excluded"], min_rating_ui)
            
            # Unione e salvataggio unico nel file "3d"
            existing = st.session_state["scan_results"] or []
            existing_ids = [r["Fixture_ID"] for r in existing]
            filtered_new = [r for r in new_results if r["Fixture_ID"] not in existing_ids]
            all_res = existing + filtered_new
            
            st.session_state["scan_results"] = all_res
            with open(get_results_path(3), "w") as f: 
                json.dump({"base_date": target_dates[0], "results": all_res}, f)
            st.success(f"Giorno {specific_date} salvato nel database!"); time.sleep(1); st.rerun()
        except Exception as e: st.error(str(e))

col1, col2 = st.columns(2)
if col1.button("📌 SNAPSHOT + SCAN (MIRATO)"): run_scan(True)
if col2.button("🚀 SCAN VELOCE (NO SNAPSHOT)"): run_scan(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    # Filtro visuale per mostrare solo i match del giorno selezionato (ma in memoria ci sono tutti!)
    df_view = df[df["Data"] == target_dates[HORIZON-1]]
    
    if not df_view.empty:
        def style_row(row):
            if '🎯 GG-PT' in row['Info']: return ['background-color: #38003c; color: #00e5ff;' for _ in row]
            if '💣 O25-BOOST' in row['Info']: return ['background-color: #003300; color: #00ff00;' for _ in row] 
            if ('🐟O' in row['Info'] or '🐟GG' in row['Info']) and row['Rating'] >= 55: return ['background-color: #004d4d; color: #00ffff;' for _ in row]
            return ['' for _ in row]
        
        DISPLAY_COLS = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "O1.5HT", "Quota GG1T", "Info", "Rating", "Gold"]
        st_style = df_view[DISPLAY_COLS].sort_values(["Ora"]).style.apply(style_row, axis=1)
        st.write(st_style.to_html(escape=False, index=False), unsafe_allow_html=True)
        st.download_button("💾 Esporta Database Completo (3gg)", df.to_csv(index=False).encode('utf-8'), f"audit_full_{target_dates[0]}.csv")

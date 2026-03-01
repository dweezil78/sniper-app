import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ==========================================
# CONFIGURAZIONE ARAB SNIPER V22.04.2
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "arab_sniper_database.json")
SNAP_FILE = str(BASE_DIR / "arab_snapshot_database.json")
CONFIG_FILE = str(BASE_DIR / "nazioni_config.json")

DEFAULT_EXCLUDED = [
    "Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda",
    "Macedonia", "Nigeria", "Ivory-Coast", "Oman", "El-Salvador",
    "Ethiopia", "Cameroon", "Jordan", "Algeria", "South-Africa",
    "Tanzania", "Montenegro", "UAE", "Guatemala", "Costa-Rica"
]

LEAGUE_BLACKLIST = ["u19", "u20", "youth", "women", "friendly", "carioca", "paulista", "mineiro"]

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V22.04.2", layout="wide")

# --- Inizializzazione Session State ---
if "config" not in st.session_state:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            st.session_state.config = json.load(f)
    else:
        st.session_state.config = {"excluded": DEFAULT_EXCLUDED}

if "team_stats_cache" not in st.session_state:
    st.session_state.team_stats_cache = {}
if "available_countries" not in st.session_state:
    st.session_state.available_countries = []
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "odds_memory" not in st.session_state:
    st.session_state.odds_memory = {}

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(st.session_state.config, f)

def load_db():
    today = now_rome().strftime("%Y-%m-%d")
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f).get("results", [])
                st.session_state.scan_results = [r for r in data if r.get("Data", "") >= today]
        except: pass
    if os.path.exists(SNAP_FILE):
        try:
            with open(SNAP_FILE, "r") as f:
                snap_data = json.load(f)
                st.session_state.odds_memory = snap_data.get("odds", {})
                return snap_data.get("timestamp", "N/D")
        except: pass
    return None

last_snap_ts = load_db()

# ==========================================
# API & STATS ENGINE
# ==========================================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params, retries=3):
    for i in range(retries):
        try:
            r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=20)
            if r.status_code == 200: return r.json()
            if r.status_code == 429: time.sleep(2)
            time.sleep(1)
        except: time.sleep(1)
    return None

def get_team_performance(session, tid):
    if str(tid) in st.session_state.team_stats_cache:
        return st.session_state.team_stats_cache[str(tid)]
    
    res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
    fx = res.get("response", []) if res else []
    if len(fx) < 1: return None
    
    act = len(fx)
    tht, gf, gs = 0, 0, 0
    for f in fx:
        ht = f.get("score", {}).get("halftime", {})
        tht += (ht.get("home") or 0) + (ht.get("away") or 0)
        is_home = f["teams"]["home"]["id"] == tid
        gf += (f["goals"]["home"] or 0) if is_home else (f["goals"]["away"] or 0)
        gs += (f["goals"]["away"] or 0) if is_home else (f["goals"]["home"] or 0)

    stats = {
        "avg_ht": tht / act,
        "avg_total": (gf + gs) / act,
        "avg_gf": gf / act,
        "avg_gs": gs / act
    }
    st.session_state.team_stats_cache[str(tid)] = stats
    return stats

def extract_markets(session, fid):
    res = api_get(session, "odds", {"fixture": fid})
    if not res or not res.get("response") or len(res["response"]) == 0: return None
    mk = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "gght": 0.0}
    for bm in res["response"][0].get("bookmakers", []):
        for b in bm.get("bets", []):
            n = (b.get("name") or "").lower()
            if b.get("id") == 1:
                for v in b.get("values", []):
                    vl = (v.get("value") or "").lower()
                    if vl == "home": mk["q1"] = float(v["odd"])
                    elif vl == "draw": mk["qx"] = float(v["odd"])
                    elif vl == "away": mk["q2"] = float(v["odd"])
            elif b.get("id") == 5:
                for v in b.get("values", []):
                    if (v.get("value") or "").lower() == "over 2.5": mk["o25"] = float(v["odd"])
            elif any(k in n for k in ["1st half", "first half", "1h"]):
                if "total" in n:
                    for v in b.get("values", []):
                        if (v.get("value") or "").lower() == "over 0.5": mk["o05ht"] = float(v["odd"])
                if any(k in n for k in ["btts", "gg", "both"]):
                    for v in b.get("values", []):
                        if (v.get("value") or "").lower() in ["yes", "si"]: mk["gght"] = float(v["odd"])
        if mk["q1"] > 0 and mk["o25"] > 0: break
    return mk

# ==========================================
# SCAN ENGINE (LOGICA SEGNALI)
# ==========================================
def run_full_scan(snap=False):
    target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    with requests.Session() as s:
        target_date = target_dates[HORIZON - 1]
        res = api_get(s, "fixtures", {"date": target_date, "timezone": "Europe/Rome"})
        if not res: return
        day_fx = [f for f in res.get("response", []) if f["fixture"]["status"]["short"] == "NS"]
        
        # Aggiorna Nazioni Sidebar
        st.session_state.available_countries = sorted(list(set(st.session_state.available_countries) | {fx["league"]["country"] for fx in day_fx}))
        
        if snap:
            csnap = {}
            for f in day_fx:
                m = extract_markets(s, f["fixture"]["id"])
                if m: csnap[str(f["fixture"]["id"])] = {"q1": m["q1"], "q2": m["q2"]}
            st.session_state.odds_memory = csnap
            with open(SNAP_FILE, "w") as f: json.dump({"odds": csnap, "timestamp": now_rome().strftime("%H:%M")}, f)

        final_list = []
        pb = st.progress(0)
        for i, f in enumerate(day_fx):
            pb.progress((i + 1) / len(day_fx))
            cnt = f["league"]["country"]
            if cnt in st.session_state.config["excluded"]: continue
            if any(k in f["league"]["name"].lower() for k in LEAGUE_BLACKLIST): continue

            mk = extract_markets(s, f["fixture"]["id"])
            if not mk: continue
            s_h = get_team_performance(s, f["teams"]["home"]["id"])
            s_a = get_team_performance(s, f["teams"]["away"]["id"])
            if not s_h or not s_a: continue

            # --- APPLICAZIONE LOGICA ESPERIENZA ---
            q1, q2, q_o25, q_ht = mk["q1"], mk["q2"], mk["o25"], mk["o05ht"]
            avg_h, avg_a = s_h["avg_total"], s_a["avg_total"]
            tags = ["HT-OK"]
            
            # 1. PESCE (OVER & GOAL)
            has_pesce = False
            if (min(q1, q2) < 1.75) and (avg_h >= 1.0 and avg_a >= 1.0):
                tags.append("🐟 PESCE-OVER"); has_pesce = True
            if (2.00 <= q1 <= 3.50) and (2.00 <= q2 <= 3.50) and (avg_h >= 1.0 and avg_a >= 1.0):
                tags.append("🐟 PESCE-GOAL"); has_pesce = True

            # 2. OVER & OVER BOOST
            has_over_any = False
            if (avg_h >= 2.0) and (avg_a >= 2.0):
                if q_o25 > 1.80 and q_ht > 1.30:
                    tags.append("⚽ OVER"); has_over_any = True
                elif q_o25 <= 1.80 and q_ht <= 1.30:
                    tags.append("🚀 OVER-BOOST"); has_over_any = True

            # 3. GGPT
            has_ggpt = False
            if (avg_h >= 1.2) and (avg_a >= 1.2):
                tags.append("🎯 GGPT"); has_ggpt = True

            # 4. PALLONE DORATO (L'Incrocio Perfetto)
            if has_pesce and has_over_any and has_ggpt:
                tags.insert(0, "⚽⭐ PALLONE DORATO")
                rtg = 100
            else:
                rtg = int(45 + (s_h["avg_ht"] + s_a["avg_ht"]) * 10 + (15 if "🚀 OVER-BOOST" in tags else 0))

            final_list.append({
                "Data": f["fixture"]["date"][:10], "Ora": f["fixture"]["date"][11:16],
                "Lega": f"{f['league']['name']} ({cnt})", "Match": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                "1": f"{q1:.2f}", "X": f"{mk['qx']:.2f}", "2": f"{q2:.2f}", "O2.5": f"{q_o25:.2f}", 
                "O0.5HT": f"{q_ht:.2f}", "GGHT": f"{mk['gght']:.2f}",
                "HT_Avg": f"{s_h['avg_ht']:.1f}|{s_a['avg_ht']:.1f}", "Rating": rtg, "Info": "|".join(tags),
                "Fixture_ID": f["fixture"]["id"]
            })
        
        st.session_state.scan_results = sorted(final_list, key=lambda x: (x["Data"], x["Ora"]))
        with open(DB_FILE, "w") as f: json.dump({"results": st.session_state.scan_results}, f)
        st.rerun()

# ==========================================
# UI & VISUALIZZAZIONE
# ==========================================
st.sidebar.header("👑 Arab Sniper V22.04.2")
HORIZON = st.sidebar.selectbox("Orizzonte:", options=[1, 2, 3], index=0)
target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

# Gestione Nazioni Sidebar
all_discovered = sorted(list(set(st.session_state.get("available_countries", []))))
if all_discovered:
    new_ex = st.sidebar.multiselect("Nazioni Escluse:", options=all_discovered, default=[c for c in st.session_state.config.get("excluded", []) if c in all_discovered])
    if st.sidebar.button("💾 SALVA CONFIG"):
        st.session_state.config["excluded"] = new_ex
        save_config(); st.rerun()

c1, c2 = st.columns(2)
if c1.button("📌 SNAP + SCAN"): run_full_scan(snap=True)
if c2.button("🚀 SCAN VELOCE"): run_full_scan(snap=False)

if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    view = df[df["Data"] == target_dates[HORIZON - 1]]
    
    def style_row(row):
        info = str(row.get("Info", ""))
        if "PALLONE DORATO" in info: return ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
        if "OVER-BOOST" in info: return ['background-color: #FF0000; color: white; font-weight: bold'] * len(row)
        if "GGPT" in info: return ['background-color: #0000FF; color: white; font-weight: bold'] * len(row)
        return ['color: #cccccc'] * len(row)

    if not view.empty:
        st.write(view.style.apply(style_row, axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("Nessun match trovato per questa data.")
else:
    st.info("Esegui uno scan per iniziare.")
    # ==========================================
# ESPORTAZIONE DATI (FINE CODICE)
# ==========================================
if not view.empty:
    st.markdown("---")
    c1, c2 = st.columns(2)

    # 1. Download CSV
    csv_data = view.to_csv(index=False).encode("utf-8")
    c1.download_button(
        label="💾 SCARICA CSV",
        data=csv_data,
        file_name=f"arab_sniper_{target_dates[HORIZON-1]}.csv",
        mime="text/csv"
    )

    # 2. Report HTML (mantiene i colori dei segnali)
    html_report = (
        "<html><head><meta charset='utf-8'><style>"
        "table { font-family: Arial; border-collapse: collapse; width: 100%; }"
        "th { background-color: #333; color: white; padding: 8px; }"
        "td { padding: 8px; border: 1px solid #ddd; text-align: center; }"
        "</style></head><body>"
        f"<h2>Arab Sniper Report - {target_dates[HORIZON-1]}</h2>"
        f"{view.style.apply(style_row, axis=1).to_html(index=False)}"
        "</body></html>"
    )
    
    c2.download_button(
        label="🌐 SCARICA REPORT HTML",
        data=html_report.encode("utf-8"),
        file_name=f"report_arab_{target_dates[HORIZON-1]}.html",
        mime="text/html"
    )

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ==========================================
# CONFIGURAZIONE ARAB SNIPER V22.04.3
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "arab_sniper_database.json")
SNAP_FILE = str(BASE_DIR / "arab_snapshot_database.json")
CONFIG_FILE = str(BASE_DIR / "nazioni_config.json")

DEFAULT_EXCLUDED = ["Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda", "Nigeria", "Oman", "Algeria", "UAE"]
LEAGUE_BLACKLIST = ["u19", "u20", "youth", "women", "friendly", "carioca", "paulista", "mineiro"]

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V22.04.3", layout="wide")

# --- Inizializzazione Session State ---
if "config" not in st.session_state:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f: st.session_state.config = json.load(f)
    else: st.session_state.config = {"excluded": DEFAULT_EXCLUDED}

if "team_stats_cache" not in st.session_state: st.session_state.team_stats_cache = {}
if "available_countries" not in st.session_state: st.session_state.available_countries = []
if "scan_results" not in st.session_state: st.session_state.scan_results = []
if "odds_memory" not in st.session_state: st.session_state.odds_memory = {}

def save_config():
    with open(CONFIG_FILE, "w") as f: json.dump(st.session_state.config, f)

def load_db():
    today = now_rome().strftime("%Y-%m-%d")
    ts = None
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
                ts = snap_data.get("timestamp", "N/D")
        except: pass
    return ts

last_snap_ts = load_db()

# ==========================================
# SIDEBAR (STATO & FILTRI)
# ==========================================
st.sidebar.header("👑 Arab Sniper V22.04.3")

if last_snap_ts:
    st.sidebar.success(f"✅ SNAPSHOT ATTIVO: {last_snap_ts}")
else:
    st.sidebar.warning("⚠️ SNAPSHOT ASSENTE")

HORIZON = st.sidebar.selectbox("Orizzonte Temporale:", options=[1, 2, 3], index=0, help="1=Oggi, 2=Domani, 3=Dopodomani")
target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

all_discovered = sorted(list(set(st.session_state.get("available_countries", []))))
if all_discovered:
    new_ex = st.sidebar.multiselect("Nazioni Escluse (Memoria):", options=all_discovered, default=[c for c in st.session_state.config.get("excluded", []) if c in all_discovered])
    if st.sidebar.button("💾 SALVA CONFIG NAZIONI"):
        st.session_state.config["excluded"] = new_ex
        save_config()
        st.sidebar.info("Configurazione salvata su file.")

# ==========================================
# ENGINE & LOGICA
# ==========================================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    try:
        r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=20)
        return r.json() if r.status_code == 200 else None
    except: return None

def get_team_performance(session, tid):
    if str(tid) in st.session_state.team_stats_cache: return st.session_state.team_stats_cache[str(tid)]
    res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
    fx = res.get("response", []) if res else []
    if not fx: return None
    act = len(fx)
    tht, gf, gs = 0, 0, 0
    for f in fx:
        ht = f.get("score", {}).get("halftime", {})
        tht += (ht.get("home") or 0) + (ht.get("away") or 0)
        is_home = f["teams"]["home"]["id"] == tid
        gf += (f["goals"]["home"] or 0) if is_home else (f["goals"]["away"] or 0)
        gs += (f["goals"]["away"] or 0) if is_home else (f["goals"]["home"] or 0)
    stats = {"avg_ht": tht/act, "avg_total": (gf+gs)/act, "avg_gf": gf/act, "avg_gs": gs/act}
    st.session_state.team_stats_cache[str(tid)] = stats
    return stats

def extract_markets(session, fid):
    res = api_get(session, "odds", {"fixture": fid})
    if not res or not res.get("response"): return None
    mk = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "gght":0.0}
    for bm in res["response"][0].get("bookmakers", []):
        for b in bm.get("bets", []):
            n = b.get("name", "").lower()
            if b.get("id") == 1:
                for v in b.get("values", []):
                    vl = v["value"].lower()
                    if vl == "home": mk["q1"] = float(v["odd"])
                    elif vl == "away": mk["q2"] = float(v["odd"])
                    elif vl == "draw": mk["qx"] = float(v["odd"])
            elif b.get("id") == 5:
                for v in b.get("values", []):
                    if "over 2.5" in v["value"].lower(): mk["o25"] = float(v["odd"])
            elif "1st half" in n or "first half" in n:
                if "total" in n:
                    for v in b.get("values", []):
                        if "over 0.5" in v["value"].lower(): mk["o05ht"] = float(v["odd"])
                if any(k in n for k in ["btts", "gg", "both"]):
                    for v in b.get("values", []):
                        if v["value"].lower() in ["yes", "si"]: mk["gght"] = float(v["odd"])
        if mk["q1"] > 0: break
    return mk

def run_full_scan(snap=False):
    with requests.Session() as s:
        target_date = target_dates[HORIZON - 1]
        res = api_get(s, "fixtures", {"date": target_date, "timezone": "Europe/Rome"})
        if not res: return
        day_fx = [f for f in res.get("response", []) if f["fixture"]["status"]["short"] == "NS"]
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
            pb.progress((i+1)/len(day_fx))
            cnt = f["league"]["country"]
            if cnt in st.session_state.config["excluded"]: continue
            mk = extract_markets(s, f["fixture"]["id"])
            if not mk: continue
            s_h, s_a = get_team_performance(s, f["teams"]["home"]["id"]), get_team_performance(s, f["teams"]["away"]["id"])
            if not s_h or not s_a: continue

            # LOGICA SEGNALI
            tags = ["HT-OK"]
            h_pesce, h_over, h_ggpt = False, False, False
            if (min(mk["q1"], mk["q2"]) < 1.75) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0):
                tags.append("🐟 PESCE-OVER"); h_pesce = True
            if (2.0 <= mk["q1"] <= 3.5) and (2.0 <= mk["q2"] <= 3.5) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0):
                tags.append("🐟 PESCE-GOAL"); h_pesce = True
            
            if (s_h["avg_total"] >= 2.0 and s_a["avg_total"] >= 2.0):
                if mk["o25"] > 1.80 and mk["o05ht"] > 1.30: tags.append("⚽ OVER"); h_over = True
                elif mk["o25"] <= 1.80 and mk["o05ht"] <= 1.30: tags.append("🚀 OVER-BOOST"); h_over = True
            
            if (s_h["avg_total"] >= 1.2 and s_a["avg_total"] >= 1.2):
                tags.append("🎯 GGPT"); h_ggpt = True
            
            if h_pesce and h_over and h_ggpt: tags.insert(0, "⚽⭐ PALLONE DORATO")
            
            final_list.append({
                "Data": f["fixture"]["date"][:10], "Ora": f["fixture"]["date"][11:16],
                "Lega": f"{f['league']['name']} ({cnt})", "Match": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                "1": mk["q1"], "X": mk["qx"], "2": mk["q2"], "O2.5": mk["o25"], "O0.5HT": mk["o05ht"], "GGHT": mk["gght"],
                "HT_Avg": f"{s_h['avg_ht']:.1f}|{s_a['avg_ht']:.1f}", "Info": "|".join(tags), "Fixture_ID": f["fixture"]["id"]
            })
        st.session_state.scan_results = final_list
        st.rerun()

# ==========================================
# MAIN UI
# ==========================================
c1, c2 = st.columns(2)
if c1.button("📌 SNAP + SCAN"): run_full_scan(snap=True)
if c2.button("🚀 SCAN VELOCE"): run_full_scan(snap=False)

if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    view = df[df["Data"] == target_dates[HORIZON - 1]]
    
    if not view.empty:
        def style_row(row):
            info = str(row.get("Info", ""))
            if "PALLONE DORATO" in info: return ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
            if "OVER-BOOST" in info: return ['background-color: #FF0000; color: white; font-weight: bold'] * len(row)
            if "GGPT" in info: return ['background-color: #0000FF; color: white; font-weight: bold'] * len(row)
            return ['color: #cccccc'] * len(row)

        st.write(view.style.apply(style_row, axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)
        
        st.markdown("---")
        d1, d2 = st.columns(2)
        d1.download_button("💾 SCARICA CSV", view.to_csv(index=False).encode("utf-8"), f"sniper_{target_dates[HORIZON-1]}.csv", "text/csv")
        html_rep = f"<html><body style='background:#000;color:#fff;'>{view.style.apply(style_row, axis=1).to_html(index=False)}</body></html>"
        d2.download_button("🌐 SCARICA HTML", html_rep.encode("utf-8"), f"report_{target_dates[HORIZON-1]}.html", "text/html")
    else:
        st.info("Nessun match per la data selezionata. Cambia l'orizzonte o fai uno scan.")
else:
    st.info("Pronto. Esegui uno scan.")

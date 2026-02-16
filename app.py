import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import json
import os
from pathlib import Path
import base64
from typing import Any, Dict, List, Tuple, Optional

# ============================
# CONFIGURAZIONE PATH
# ============================
BASE_DIR = Path(__file__).resolve().parent
JSON_FILE = str(BASE_DIR / "arab_snapshot.json")
LOG_CSV  = str(BASE_DIR / "sniper_history_log.csv")

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V15.35 - GOLD MASTER", layout="wide")

# ============================
# SESSION STATE & PRELOAD
# ============================
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results_raw" not in st.session_state: st.session_state["scan_results_raw"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

def load_local_snapshot():
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r") as f:
            data = json.load(f)
            if data.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = data.get("odds", {})
                st.session_state["found_countries"] = sorted({v.get("country") for v in data.get("odds", {}).values() if v.get("country")})
                return data.get("timestamp")
    return None

snap_timestamp = load_local_snapshot()

def apply_custom_css():
    st.markdown("""
        <style>
            .match-cell { text-align: left !important; font-weight: 700; }
            .advice-tag { display: block; font-size: 0.75rem; color: #00e5ff; font-weight: 800; }
            .diag-box { padding: 10px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #00e5ff; background: #1a1c23; color: #00e5ff; }
            .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API ENGINES (Estratti per brevità ma integrati)
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=20)
    return r.json()

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            if b["id"] == 1: 
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if b["id"] == 5:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            if "0.5" in str(b.get("name")) and "1st" in str(b.get("name")):
                data["o05ht"] = float(next((x["odd"] for x in b.get("values", []) if "Over" in x["value"]), 0))
        if data["q1"] > 0 and data["o25"] > 0: break
    return data

# ============================
# UI SIDEBAR
# ============================
st.sidebar.header("👑 Configurazione GOLD")

# Stato Snapshot
if snap_timestamp:
    st.sidebar.success(f"📸 Snapshot ATTIVO\nSalvato alle: {snap_timestamp[11:16]}")
else:
    st.sidebar.warning("⚠️ Nessun Snapshot per oggi")

min_rating = st.sidebar.slider("Rating Minimo", 50, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
only_gold_ui = st.sidebar.toggle("🎯 MOSTRA SOLO SWEET SPOT", value=False)
st.sidebar.markdown("---")
blocked_user = st.sidebar.multiselect("🚫 Blocca Paesi", st.session_state["found_countries"])
forced_user = st.sidebar.multiselect("✅ Forza Paesi", st.session_state["found_countries"])

# ============================
# LOGICA RATING & STATS (V15.35)
# ============================
def calculate_rating(fid, mk, snap_data, max_q_gold):
    q_fav = min(mk['q1'], mk['q2'])
    is_gold = 1.40 <= q_fav <= max_q_gold
    into_trap = False
    
    # Verifica Trap/Asterisco
    if q_fav < 1.40:
        old_q = min(snap_data.get(str(fid), {}).get("q1", 0), snap_data.get(str(fid), {}).get("q2", 0))
        if old_q >= 1.40 and (old_q - q_fav) >= 0.10: into_trap = True
        else: return None

    sc, det = 40, ["Val"]
    if is_gold: sc += 10
    if 1.70 <= mk['o25'] <= 2.15: sc += 15
    # Aggiungi qui logica Drop/Inv...
    return {"rating": min(100, sc), "det": det, "is_gold": is_gold, "into_trap": into_trap}

# ============================
# AZIONI PRINCIPALI
# ============================
oggi = now_rome().strftime("%Y-%m-%d")

col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    if st.button("📌 SALVA/AGGIORNA SNAPSHOT"):
        with requests.Session() as s:
            raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
            valid = [m for m in raw if m['fixture']['status']['short'] == 'NS']
            new_snap = {}
            pb = st.progress(0)
            for i, m in enumerate(valid):
                pb.progress((i+1)/len(valid))
                mo = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                mk = extract_markets_pro(mo)
                if mk: 
                    mk["country"] = m["league"]["country"]
                    new_snap[str(m["fixture"]["id"])] = mk
            
            ts = now_rome().isoformat()
            with open(JSON_FILE, "w") as f: 
                json.dump({"date": oggi, "timestamp": ts, "odds": new_snap}, f)
            st.rerun()

with col_btn2:
    if st.button("🚀 SCANSIONE MATCH"):
        with requests.Session() as s:
            raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
            # Nazione aggiunta nel nome lega
            results = []
            for m in raw:
                if m['fixture']['status']['short'] != 'NS': continue
                country = m["league"]["country"]
                if country in blocked_user and country not in forced_user: continue
                
                mo = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                mk = extract_markets_pro(mo)
                if not mk: continue
                
                analysis = calculate_rating(m["fixture"]["id"], mk, st.session_state["odds_memory"], max_q_gold)
                if analysis and analysis["rating"] >= 50:
                    results.append({
                        "Ora": m["fixture"]["date"][11:16],
                        "Lega": f"{m['league']['name']} ({country})",
                        "Nazione": country,
                        "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                        "1X2": f"{mk['q1']}|{mk['qx']}|{mk['q2']}",
                        "O2.5": mk['o25'],
                        "O0.5HT": mk['o05ht'],
                        "Rating": analysis["rating"],
                        "Is_Gold": analysis["is_gold"],
                        "Info": f"[{'|'.join(analysis['det'])}]",
                        "Fixture_ID": m["fixture"]["id"]
                    })
            st.session_state["scan_results_raw"] = results

# ============================
# VISUALIZZAZIONE DINAMICA
# ============================
if st.session_state["scan_results_raw"]:
    full_data = pd.DataFrame(st.session_state["scan_results_raw"])
    
    # Filtro istantaneo senza ricaricare API
    if only_gold_ui:
        display_df = full_data[full_data["Is_Gold"] == True].copy()
    else:
        display_df = full_data.copy()

    if not display_df.empty:
        # Formattazione per la tabella
        display_df["Match_Disp"] = display_df.apply(lambda r: 
            f"<div class='match-cell'>{'👑 ' if r['Is_Gold'] else ''}{r['Match']}"
            f"<span class='advice-tag'>{'🔥 TARGET: 0.5 HT' if r['Is_Gold'] else ''}</span></div>", axis=1)
        
        st.write(display_df[["Ora", "Lega", "Match_Disp", "1X2", "O2.5", "Rating"]].to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("Nessun match Sweet Spot trovato tra i risultati attuali.")

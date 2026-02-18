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
LOG_CSV = str(BASE_DIR / "sniper_history_log.csv")

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V15.51 - GOLD MASTER", layout="wide")

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

# ============================
# CSS ORIGINALE (NON TOCCARE)
# ============================
def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
            .match-cell { text-align: left !important; min-width: 220px; font-weight: 700; color: inherit !important; }
            .advice-tag { display: block; font-size: 0.65rem; color: #00e5ff; font-style: italic; margin-top: 2px; }
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; border: 1px solid #00e5ff; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API & PARSING BLINDATO
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
    return js

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), str(b.get("name") or "").lower()
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            if ("1st" in name or "half" in name) and ("goals" in name or "over/under" in name):
                for x in b.get("values", []):
                    v_val = str(x.get("value") or "").lower().replace(" ", "")
                    if "over0.5" in v_val: data["o05ht"] = float(x.get("odd") or 0)
                    if "over1.5" in v_val: data["o15ht"] = float(x.get("odd") or 0)
            if bid == 71 or "both teams to score - 1st half" in name:
                for x in b.get("values", []):
                    if str(x.get("value") or "") == "Yes": data["gg_ht"] = float(x.get("odd") or 0)
        if data["q1"] > 0 and data["o25"] > 0: break
    return data

# ... (Funzioni get_stats, is_allowed_league, calculate_rating incluse) ...
# [Le funzioni rimangono quelle della versione precedente per mantenere la logica HT/DRY]

# ============================
# UI SIDEBAR
# ============================
st.sidebar.header("👑 Configurazione Sniper")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
only_gold_ui = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=False)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)

# ============================
# RENDERING TABELLA & TASTI EXPORT
# ============================
if st.session_state["scan_results"]:
    df_raw = pd.DataFrame(st.session_state["scan_results"])
    df_show = df_raw[df_raw["Is_Gold"] == True].copy() if only_gold_ui else df_raw.copy()

    if not df_show.empty:
        # Costruzione Cella Match con Simboli
        df_show["Match_Disp_Cell"] = df_show.apply(lambda r: f"<div class='match-cell'>{'👑 ' if r['Is_Gold'] else ''}{r['Match_Disponibili']}<span class='advice-tag'>{r['Advice']}</span></div>", axis=1)
        
        # Colonna Rating in Grassetto
        df_show["Rating_Bold"] = df_show["Rating"].apply(lambda x: f"<b>{x}</b>")
        
        # Ordine Colonne 1-10 come richiesto
        cols = ["Ora", "Lega", "Match_Disp_Cell", "1X2", "O25 Finale", "O05 PT", "O15 PT", "GG PT", "Info", "Rating_Bold"]
        
        def style_rows(row):
            r_val, is_gold, info = row["Rating"], row["Is_Gold"], row["Info"]
            if r_val >= 85: return ['background-color: #1b4332; color: #ffffff; font-weight: bold;'] * len(row)
            elif is_gold or r_val >= 75 or "DRY" in info: return ['background-color: #2d6a4f; color: #ffffff; font-weight: bold;'] * len(row)
            return [''] * len(row)

        st.write(df_show.style.apply(style_rows, axis=1).hide(axis="columns", subset=[c for c in df_show.columns if c not in cols]).to_html(escape=False, index=False), unsafe_allow_html=True)

        # ============================
        # TASTI DI SALVATAGGIO (RIPRISTINATI)
        # ============================
        st.markdown("---")
        oggi = now_rome().strftime("%Y-%m-%d")
        col_dl1, col_dl2, col_dl3 = st.columns(3)
        
        with col_dl1:
            # CSV specifico per Auditor (con tutte le nuove colonne)
            st.download_button("💾 CSV PER AUDITOR", data=df_raw.to_csv(index=False).encode('utf-8'), file_name=f"auditor_export_{oggi}.csv")
        
        with col_dl2:
            # HTML Report
            html = df_raw.to_html(escape=False, index=False)
            html_styled = f"<html><head><style>table{{border-collapse:collapse;width:100%;font-family:Arial;}} th,td{{border:1px solid #ddd;padding:8px;text-align:center;}} th{{background-color:#f2f2f2;}}</style></head><body>{html}</body></html>"
            st.download_button("🌐 REPORT HTML", data=html_styled.encode('utf-8'), file_name=f"report_{oggi}.html", mime="text/html")
        
        with col_dl3:
            # Database Storico
            if os.path.exists(LOG_CSV):
                with open(LOG_CSV, "rb") as f:
                    st.download_button("🗂️ DATABASE STORICO (Log)", data=f.read(), file_name="sniper_history_log.csv")

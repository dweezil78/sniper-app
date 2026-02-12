import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import json
import os
from typing import Any, Dict, List, Tuple, Optional

# ============================
# CONFIGURAZIONE & SESSIONE
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

JSON_FILE = "arab_snapshot.json"
st.set_page_config(page_title="ARAB SNIPER V15.4", layout="wide")

# Punto 1: Persistenza Ibrida corretta
if "odds_memory" not in st.session_state:
    st.session_state["odds_memory"] = {}
if "snap_date_mem" not in st.session_state:
    st.session_state["snap_date_mem"] = None

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; color: #000000 !important; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; color: #000000 !important; font-weight: 600; white-space: nowrap; }
            .match-cell { text-align: left !important; min-width: 180px; font-weight: 700; color: inherit !important; }
            .lega-cell { max-width: 120px; overflow: hidden; text-overflow: ellipsis; font-size: 0.75rem; color: inherit !important; text-align: left !important; }
            .drop-inline { color: #d68910; font-size: 0.72rem; font-weight: 800; margin-left: 5px; }
            .details-inline { font-size: 0.7rem; color: inherit !important; font-weight: 800; margin-left: 5px; opacity: 0.9; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API HELPERS
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=25)
    r.raise_for_status() 
    return r.json()

def is_allowed_league(league_name, league_country):
    name = league_name.lower()
    banned = ["women", "u19", "u20", "u21", "u23", "primavera"]
    if any(x in name for x in banned): return False
    if league_country in ["Algeria","Egypt","Morocco","Saudi Arabia","UAE","India"]: return False
    return True

# ============================
# PERSISTENZA (Fix Punto 1)
# ============================
def save_snapshot(data_dict, date_str):
    st.session_state["odds_memory"] = data_dict
    st.session_state["snap_date_mem"] = date_str
    with open(JSON_FILE, "w") as f:
        json.dump({"date": date_str, "odds": data_dict}, f)

def load_snapshot():
    # Carica da sessione se esiste
    if st.session_state["odds_memory"] and st.session_state["snap_date_mem"]:
        return st.session_state["snap_date_mem"], st.session_state["odds_memory"]
    # Altrimenti da file
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r") as f:
            data = json.load(f)
            st.session_state["odds_memory"] = data.get("odds", {})
            st.session_state["snap_date_mem"] = data.get("date")
            return st.session_state["snap_date_mem"], st.session_state["odds_memory"]
    return None, {}

# ============================
# LOGICA RATING (Fix Punto 3 & 4)
# ============================
def calculate_rating(fid, q1, q2, o25, snap_data, max_quota_fav):
    sc = 40
    det = []
    drop_msg = ""
    fid_s = str(fid)
    
    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_q1, old_q2 = old.get("q1", 0), old.get("q2", 0)
        
        if old_q1 > 0 and old_q2 > 0:
            gap_old = abs(old_q1 - old_q2)
            fav_at_snap = "1" if old_q1 < old_q2 else "2"
            old_fav_p = old_q1 if fav_at_snap == "1" else old_q2
            cur_fav_p = q1 if fav_at_snap == "1" else q2
            
            # Punto 4: Drop reale + Controllo Quota Max
            delta = old_fav_p - cur_fav_p
            if delta >= 0.15 and cur_fav_p <= max_quota_fav:
                sc += 40; det.append("Drop"); drop_msg = f"<span class='drop-inline'>📉 Δ{round(delta,2)}</span>"
            
            # Punto 3: Inversione Robusta (Margine 0.10 sia prima che dopo)
            gap_now = abs(q1 - q2)
            if gap_old >= 0.10 and gap_now >= 0.10:
                if fav_at_snap == "1" and q2 < q1:
                    sc += 20; det.append("Inv"); drop_msg = "<span class='drop-inline'>🔄 INV 1→2</span>"
                elif fav_at_snap == "2" and q1 < q2:
                    sc += 20; det.append("Inv"); drop_msg = "<span class='drop-inline'>🔄 INV 2→1</span>"

    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 0 < o25 < 1.55: sc = 0
    return min(100, sc), det, drop_msg

# ============================
# UI E CORE EXECUTION
# ============================
st.sidebar.header("Settings")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_fav = st.sidebar.slider("Quota Max Favorito", 1.50, 3.00, 1.85)

oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
snap_date, snap_odds = load_snapshot()

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("📌 SALVA SNAPSHOT"):
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            all_fx = data.get("response", []) or []
            new_snap = {}
            pb = st.progress(0)
            
            # Filtro Punto 2: Filtriamo subito le leghe e lo status NS
            valid_fx = [m for m in all_fx if m['fixture']['status']['short'] == 'NS' and is_allowed_league(m['league']['name'], m['league']['country'])]
            
            for i, m in enumerate(valid_fx):
                pb.progress((i+1)/len(valid_fx))
                try:
                    r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                    resp = r_o.get("response", [])
                    if resp:
                        bets = resp[0].get("bookmakers", [{}])[0].get("bets", [])
                        q1 = q2 = o25 = 0.0
                        for b in bets:
                            if b["id"] == 1:
                                vals = b.get("values", [])
                                if len(vals) >= 3: q1, q2 = float(vals[0]["odd"]), float(vals[2]["odd"])
                            if b["id"] == 5:
                                o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
                        if q1 > 0: new_snap[m["fixture"]["id"]] = {"q1": q1, "q2": q2, "o25": o25}
                except: continue
            save_snapshot(new_snap, oggi)
            st.success(f"Snapshot OK: {len(new_snap)} match salvati.")

with c2:
    st.write(f"Snapshot del: **{snap_date}**" if snap_date == oggi else f"⚠️ Snapshot obsoleto o mancante ({snap_date})")

# Punto 5: Cache locale per HT rate durante la scansione
ht_cache = {}

if st.button("🚀 AVVIA SCANSIONE"):
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"])]
        
        results = []
        pb = st.progress(0)
        for i, m in enumerate(fixtures):
            pb.progress((i+1)/len(fixtures))
            try:
                r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                q1 = qx = q2 = o25 = 0.0
                resp = r_o.get("response", [])
                if resp:
                    bets = resp[0].get("bookmakers", [{}])[0].get("bets", [])
                    for b in bets:
                        if b["id"] == 1:
                            vals = b.get("values", [])
                            if len(vals) >= 3: q1, qx, q2 = float(vals[0]["odd"]), float(vals[1]["odd"]), float(vals[2]["odd"])
                        if b["id"] == 5:
                            o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
                
                if q1 <= 0: continue
                
                # Calcolo Rating iniziale
                rating, det_list, drop_label = calculate_rating(m["fixture"]["id"], q1, q2, o25, snap_odds, max_q_fav)
                
                # Punto 5: HT con Cache Locale
                if rating >= (min_rating - 20):
                    def get_cached_ht(tid):
                        if tid in ht_cache: return ht_cache[tid]
                        rx = api_get(s, "fixtures", {"team": tid, "last": 5, "status": "FT"})
                        fx = rx.get("response", [])
                        rate = sum([1 for f in fx if (f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0) >= 1]) / len(fx) if fx else 0.0
                        ht_cache[tid] = rate
                        return rate
                    
                    if (get_cached_ht(m["teams"]["home"]["id"]) >= 0.6 and get_cached_ht(m["teams"]["away"]["id"]) >= 0.6):
                        rating += 20; det_list.append("HT")
                
                if rating >= min_rating:
                    results.append({
                        "Ora": m["fixture"]["date"][11:16],
                        "Lega": f"<div class='lega-cell'>{m['league']['name']}</div>",
                        "Match": f"<div class='match-cell'>{m['teams']['home']['name']} - {m['teams']['away']['name']} {drop_label}</div>",
                        "1X2": f"{q1:.2f}|{qx:.2f}|{q2:.2f}",
                        "O2.5": f"{o25:.2f}",
                        "Rating": f"<b>{rating}</b>",
                        "Info": f"<span class='details-inline'>[{'|'.join(det_list)}]</span>",
                        "R_VAL": rating
                    })
            except: continue

        if results:
            df = pd.DataFrame(results).sort_values("Ora")
            def style_rows(row):
                if row['R_VAL'] >= 85: return ['background-color: #1b4332; color: #ffffff !important;'] * len(row)
                if row['R_VAL'] >= 70: return ['background-color: #2d6a4f; color: #ffffff !important;'] * len(row)
                return [''] * len(row)
            st.write(df.style.apply(style_rows, axis=1).hide(subset=["R_VAL"], axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)

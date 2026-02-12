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
st.set_page_config(page_title="ARAB SNIPER V15.3", layout="wide")

if "odds_memory" not in st.session_state:
    st.session_state["odds_memory"] = {}

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; color: #000000 !important; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; color: #000000 !important; font-weight: 600; }
            .match-cell { text-align: left !important; min-width: 180px; font-weight: 700; }
            .drop-inline { color: #d68910; font-size: 0.72rem; font-weight: 800; margin-left: 5px; }
            .details-inline { font-size: 0.7rem; color: inherit !important; font-weight: 800; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API HELPERS (Con raise_for_status)
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session: requests.Session, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=25)
    r.raise_for_status() # Punto 6: Controllo errori
    return r.json()

def is_allowed_league(league_name, league_country):
    name = league_name.lower()
    banned = ["women", "u19", "u20", "u21", "u23", "primavera"]
    if any(x in name for x in banned): return False
    if league_country in ["Algeria","Egypt","Morocco","Saudi Arabia","UAE","India"]: return False
    return True

# ============================
# PERSISTENZA (Punto 1 & 2)
# ============================
def save_snapshot(data_dict):
    st.session_state["odds_memory"] = data_dict
    oggi_str = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
    with open(JSON_FILE, "w") as f:
        json.dump({"date": oggi_str, "odds": data_dict}, f)

def load_snapshot():
    # Prova prima dalla sessione, poi dal file
    if st.session_state["odds_memory"]:
        return datetime.now().strftime("%Y-%m-%d"), st.session_state["odds_memory"]
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r") as f:
            data = json.load(f)
            st.session_state["odds_memory"] = data.get("odds", {})
            return data.get("date"), data.get("odds", {})
    return None, {}

# ============================
# LOGICA RATING (Punto 3 & 4)
# ============================
def calculate_rating(fid, q1, q2, o25, snap_data):
    sc = 40
    det = []
    drop_msg = ""
    fid_s = str(fid)
    
    if fid_s in snap_data:
        old = snap_data[fid_s]
        # Identifico chi era favorito allo SNAPSHOT
        old_q1, old_q2 = old.get("q1", 0), old.get("q2", 0)
        if old_q1 > 0 and old_q2 > 0:
            fav_at_snap = "1" if old_q1 < old_q2 else "2"
            old_fav_price = old_q1 if fav_at_snap == "1" else old_q2
            cur_fav_price = q1 if fav_at_snap == "1" else q2
            
            # Calcolo Drop sullo stesso lato
            delta = old_fav_price - cur_fav_price
            if delta >= 0.15:
                sc += 40; det.append("Drop"); drop_msg = f"<span class='drop-inline'>📉 Δ{round(delta,2)}</span>"
            
            # Inversione con soglia minima (Punto 3)
            # Serve che il nuovo favorito sia tale con almeno 0.10 di margine
            gap_old = abs(old_q1 - old_q2)
            if fav_at_snap == "1" and q2 < (q1 - 0.10):
                sc += 20; det.append("Inv"); drop_msg = "<span class='drop-inline'>🔄 INV 1→2</span>"
            elif fav_at_snap == "2" and q1 < (q2 - 0.10):
                sc += 20; det.append("Inv"); drop_msg = "<span class='drop-inline'>🔄 INV 2→1</span>"

    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 0 < o25 < 1.55: sc = 0
    return min(100, sc), det, drop_msg

# ============================
# UI E CORE
# ============================
st.sidebar.header("Settings")
min_rating = st.sidebar.slider("Rating Min", 0, 85, 60)
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
            for i, m in enumerate(all_fx):
                pb.progress((i+1)/len(all_fx))
                try:
                    # Chiamata odds (Punto 5: facciamo solo questa in snapshot)
                    r_odds = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                    resp = r_odds.get("response", [])
                    if resp:
                        bets = resp[0].get("bookmakers", [{}])[0].get("bets", [])
                        q1 = qx = q2 = o25 = 0.0
                        for b in bets:
                            if b["id"] == 1:
                                vals = b.get("values", [])
                                if len(vals) >= 3: q1, q2 = float(vals[0]["odd"]), float(vals[2]["odd"])
                            if b["id"] == 5:
                                o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
                        if q1 > 0: new_snap[m["fixture"]["id"]] = {"q1": q1, "q2": q2, "o25": o25}
                except: continue
            save_snapshot(new_snap)
            st.success("Snapshot OK")

with c2:
    st.write(f"Snapshot: {snap_date}" if snap_date == oggi else "⚠️ No Snapshot")

if st.button("🚀 AVVIA SCANSIONE"):
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"])]
        
        results = []
        pb = st.progress(0)
        for i, m in enumerate(fixtures):
            pb.progress((i+1)/len(fixtures))
            try:
                # 1. Chiamata Odds
                r_odds = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                q1, qx, q2, o25 = 0.0, 0.0, 0.0, 0.0
                resp = r_odds.get("response", [])
                if resp:
                    bets = resp[0].get("bookmakers", [{}])[0].get("bets", [])
                    for b in bets:
                        if b["id"] == 1:
                            vals = b.get("values", [])
                            if len(vals) >= 3: q1, qx, q2 = float(vals[0]["odd"]), float(vals[1]["odd"]), float(vals[2]["odd"])
                        if b["id"] == 5:
                            o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
                
                if q1 <= 0: continue
                
                # 2. Calcolo Rating (Punto 5: facciamo HT rate solo se match potenzialmente buono)
                rating, det_list, drop_label = calculate_rating(m["fixture"]["id"], q1, q2, o25, snap_odds)
                
                # 3. HT Rate post-filtro (Punto 5: Risparmio API)
                if rating >= (min_rating - 20): # Se è vicino alla soglia, controlliamo HT
                    h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
                    # Funzione HT integrata qui per brevità
                    def quick_ht(tid):
                        r = api_get(s, "fixtures", {"team": tid, "last": 5, "status": "FT"})
                        fx = r.get("response", [])
                        if not fx: return 0.0
                        return sum([1 for f in fx if (f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0) >= 1]) / len(fx)
                    
                    if (quick_ht(h_id) >= 0.6 and quick_ht(a_id) >= 0.6):
                        rating += 20
                        det_list.append("HT")
                
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

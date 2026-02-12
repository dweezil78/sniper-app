import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import json
import os
from typing import Any, Dict, List, Tuple, Optional

# ============================
# CONFIG E PERSISTENZA
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

JSON_FILE = "arab_snapshot.json"
st.set_page_config(page_title="ARAB SNIPER V15.2", layout="wide")

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; color: #000000 !important; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; color: #000000 !important; font-weight: 600; white-space: nowrap; }
            
            /* Larghezza ridotta per le squadre */
            .match-cell { text-align: left !important; min-width: 180px; font-weight: 700; color: inherit !important; }
            .lega-cell { max-width: 120px; overflow: hidden; text-overflow: ellipsis; font-size: 0.75rem; color: inherit !important; text-align: left !important; }
            
            .drop-inline { color: #d68910; font-size: 0.72rem; font-weight: 800; margin-left: 5px; }
            
            /* Fix colore scritte su righe colorate */
            .details-inline { font-size: 0.7rem; color: inherit !important; font-weight: 800; margin-left: 5px; opacity: 0.9; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# FUNZIONI API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=25)
    return r.json()

def is_allowed_league(league_name, league_country):
    name = league_name.lower()
    banned = ["women", "u19", "u20", "u21", "u23", "primavera"]
    if any(x in name for x in banned): return False
    if league_country in ["Algeria","Egypt","Morocco","Saudi Arabia","UAE","India"]: return False
    return True

# ============================
# ENGINE PERSISTENZA
# ============================
def save_json_snapshot(data_dict):
    oggi_str = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
    with open(JSON_FILE, "w") as f:
        json.dump({"date": oggi_str, "odds": data_dict}, f)

def load_json_snapshot():
    if not os.path.exists(JSON_FILE): return None, {}
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
    return data.get("date"), data.get("odds", {})

@st.cache_data(ttl=900)
def fetch_odds(fixture_id):
    try:
        r = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": fixture_id}, timeout=20).json()
        resp = r.get("response", [])
        if not resp: return 0.0, 0.0, 0.0, 0.0
        bets = resp[0].get("bookmakers", [{}])[0].get("bets", [])
        q1 = qx = q2 = o25 = 0.0
        for b in bets:
            if b["id"] == 1:
                vals = b.get("values", [])
                if len(vals) >= 3: q1, qx, q2 = float(vals[0]["odd"]), float(vals[1]["odd"]), float(vals[2]["odd"])
            if b["id"] == 5:
                o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
        return q1, qx, q2, o25
    except: return 0.0, 0.0, 0.0, 0.0

@st.cache_data(ttl=3600)
def get_ht_rate(team_id):
    try:
        r = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": team_id, "last": 5, "status": "FT"}).json()
        fx = r.get("response", [])
        if not fx: return 0.0
        ht_goals = sum([1 for f in fx if (f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0) >= 1])
        return ht_goals / len(fx)
    except: return 0.0

# ============================
# LOGICA RATING
# ============================
def calculate_rating(fid, q1, q2, o25, h_ht, a_ht, snap_data):
    sc = 40
    det = []
    drop_msg = ""
    fid_s = str(fid)
    if fid_s in snap_data:
        old = snap_data[fid_s]
        is_h = q1 < q2
        old_fav, cur_fav = (old.get("q1"), q1) if is_h else (old.get("q2"), q2)
        if old_fav and cur_fav:
            delta = old_fav - cur_fav
            if delta >= 0.15: 
                sc += 40; det.append("Drop"); drop_msg = f"<span class='drop-inline'>📉 Δ{round(delta,2)}</span>"
            if (old.get("q1",0) < old.get("q2",0) and q2 < q1) or (old.get("q2",0) < old.get("q1",0) and q1 < q2):
                sc += 20; det.append("Inv"); drop_msg = "<span class='drop-inline'>🔄 INV</span>"
    if h_ht >= 0.6 and a_ht >= 0.6: sc += 20; det.append("HT")
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 0 < o25 < 1.55: sc = 0
    return min(100, sc), det, drop_msg

# ============================
# UI E SCANSIONE
# ============================
st.sidebar.header("Settings")
min_rating = st.sidebar.slider("Rating Min", 0, 85, 60)
oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
snap_date, snap_odds = load_json_snapshot()

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("📌 SALVA SNAPSHOT"):
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        all_fx = data.get("response", []) or []
        new_snap = {}
        pb = st.progress(0)
        for i, m in enumerate(all_fx):
            q1, qx, q2, o25 = fetch_odds(m["fixture"]["id"])
            if q1 > 0: new_snap[m["fixture"]["id"]] = {"q1": q1, "q2": q2, "o25": o25}
            pb.progress((i+1)/len(all_fx))
        save_json_snapshot(new_snap)
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
        q1, qx, q2, o25 = fetch_odds(m["fixture"]["id"])
        if q1 <= 0: continue
        rating, det_list, drop_label = calculate_rating(m["fixture"]["id"], q1, q2, o25, get_ht_rate(m["teams"]["home"]["id"]), get_ht_rate(m["teams"]["away"]["id"]), snap_odds)
        
        if rating >= min_rating:
            det_str = "|".join(det_list)
            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Lega": f"<div class='lega-cell'>{m['league']['name']}</div>",
                "Match": f"<div class='match-cell'>{m['teams']['home']['name']} - {m['teams']['away']['name']} {drop_label}</div>",
                "1X2": f"{q1:.2f}|{qx:.2f}|{q2:.2f}",
                "O2.5": f"{o25:.2f}",
                "Rating": f"<b>{rating}</b>",
                "Info": f"<span class='details-inline'>[{det_str}]</span>",
                "R_VAL": rating
            })

    if results:
        # ORDINAMENTO PER ORA (ASCENDENTE)
        df = pd.DataFrame(results).sort_values("Ora", ascending=True)
        
        def style_rows(row):
            if row['R_VAL'] >= 85: return ['background-color: #1b4332; color: #ffffff !important;'] * len(row)
            if row['R_VAL'] >= 70: return ['background-color: #2d6a4f; color: #ffffff !important;'] * len(row)
            return [''] * len(row)
        
        st.write(df.style.apply(style_rows, axis=1).hide(subset=["R_VAL"], axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)

import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import base64
import json
import os
from typing import Any, Dict, List, Tuple, Optional

# ============================
# TIMEZONE & FILE PATH
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

JSON_FILE = "arab_snapshot.json"

# ============================
# 1) CONFIG PAGINA E STILI V15.1
# ============================
st.set_page_config(page_title="ARAB SNIPER V15.1", layout="wide")
st.title("🎯 ARAB SNIPER V15.1 - Persistent Edition")
st.caption("Rating basato su Memory Snapshot (Drop Reale), HT Goal Rate e Mercati 1X2.")

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; color: #000000 !important; margin-bottom: 20px; font-family: 'Segoe UI', sans-serif; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 15px; text-align: center; border: 1px solid #444; }
            td { padding: 12px; border: 1px solid #ccc; vertical-align: middle; text-align: center; color: #000000 !important; font-weight: 600; }
            .rating-badge { padding: 10px; border-radius: 8px; font-weight: 900; font-size: 1.2em; display: inline-block; min-width: 54px; }
            .match-cell { text-align: left !important; min-width: 320px; }
            .drop-tag { color: #d68910; font-size: 0.85em; font-weight: 900; margin-top: 4px; display: block; }
            .details-list { font-size: 0.75em; margin-top: 8px; line-height: 1.3; text-align: left; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# 2) CONFIG API & FUNZIONI CORE
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session: requests.Session, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

BANNED_COUNTRIES = set(["Algeria","Angola","Egypt","Morocco","Nigeria","South Africa","Tunisia","Saudi Arabia","Qatar","UAE","India"])

def is_allowed_league(league_name: str, league_country: str) -> bool:
    name = league_name.lower()
    for t in ["women", "u19", "u20", "u21", "u23", "primavera"]:
        if t in name: return False
    if league_country in BANNED_COUNTRIES: return False
    return True

# ============================
# 3) PERSISTENZA JSON (LA MEMORIA)
# ============================
def save_json_snapshot(data_dict: Dict[int, Dict]):
    oggi_str = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
    payload = {"date": oggi_str, "odds": data_dict}
    with open(JSON_FILE, "w") as f:
        json.dump(payload, f)

def load_json_snapshot() -> Tuple[Optional[str], Dict[str, Dict]]:
    if not os.path.exists(JSON_FILE):
        return None, {}
    with open(JSON_FILE, "r") as f:
        data = json.load(f)
    return data.get("date"), data.get("odds", {})

# ============================
# 4) ENGINE ODDS & STATS
# ============================
@st.cache_data(ttl=900)
def fetch_odds(fixture_id: int):
    try:
        url = f"https://{HOST}/odds"
        r = requests.get(url, headers=HEADERS, params={"fixture": fixture_id}, timeout=20).json()
        resp = r.get("response", [])
        if not resp: return 0.0, 0.0, 0.0, 0.0
        bookmaker = resp[0].get("bookmakers", [{}])[0]
        bets = bookmaker.get("bets", [])
        
        q1 = qx = q2 = o25 = 0.0
        for b in bets:
            if b["id"] == 1: # 1X2
                vals = b.get("values", [])
                if len(vals) >= 3:
                    q1, qx, q2 = float(vals[0]["odd"]), float(vals[1]["odd"]), float(vals[2]["odd"])
            if b["id"] == 5: # Over 2.5
                o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
        return q1, qx, q2, o25
    except:
        return 0.0, 0.0, 0.0, 0.0

@st.cache_data(ttl=3600)
def get_ht_rate(team_id: int):
    try:
        url = f"https://{HOST}/fixtures"
        r = requests.get(url, headers=HEADERS, params={"team": team_id, "last": 5, "status": "FT"}, timeout=20).json()
        fx = r.get("response", [])
        if not fx: return 0.0
        ht_goals = sum([1 for f in fx if (f.get("score", {}).get("halftime", {}).get("home") or 0) + (f.get("score", {}).get("halftime", {}).get("away") or 0) >= 1])
        return ht_goals / len(fx)
    except:
        return 0.0

# ============================
# 5) LOGICA RATING V15.1
# ============================
def calculate_rating(fid, q1, q2, o25, h_ht, a_ht, snap_data):
    sc = 40
    det = []
    drop_msg = "STABILE"
    
    fid_s = str(fid)
    if fid_s in snap_data:
        old = snap_data[fid_s]
        is_h = q1 < q2
        old_fav = old.get("q1") if is_h else old.get("q2")
        cur_fav = q1 if is_h else q2
        
        if old_fav and cur_fav:
            delta = old_fav - cur_fav
            if delta >= 0.15:
                sc += 40; det.append(f"DROP REALE 🔥 (+40)")
                drop_msg = f"📉 DROP Δ {round(delta,2)}"
            
            if (old.get("q1", 0) < old.get("q2", 0) and q2 < q1) or (old.get("q2", 0) < old.get("q1", 0) and q1 < q2):
                sc += 20; det.append("INVERSIONE ↔️ (+20)")
                drop_msg = "🔄 INVERSIONE"

    if h_ht >= 0.6 and a_ht >= 0.6:
        sc += 20; det.append("HT STAT OK (+20)")
    
    if 1.70 <= o25 <= 2.15:
        sc += 20; det.append("QUOTA VALUE (+20)")
        
    if 0 < o25 < 1.55: sc = 0 
    
    return min(100, sc), det, drop_msg

# ============================
# 6) UI & ESECUZIONE
# ============================
st.sidebar.header("⚙️ Settings V15.1")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)

oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
snap_date, snap_odds = load_json_snapshot()

col1, col2 = st.columns([1, 2])
with col1:
    if st.button("📌 SALVA SNAPSHOT QUOTE"):
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        all_fx = data.get("response", []) or []
        new_snap = {}
        pb_snap = st.progress(0)
        for i, m in enumerate(all_fx):
            fid = m["fixture"]["id"]
            q1, qx, q2, o25 = fetch_odds(fid)
            if q1 > 0: new_snap[fid] = {"q1": q1, "q2": q2, "o25": o25}
            pb_snap.progress((i+1)/len(all_fx))
        save_json_snapshot(new_snap)
        st.success(f"Snapshot salvato! ({len(new_snap)} match)")

with col2:
    status_snap = f"✅ Snapshot presente: {snap_date}" if snap_date == oggi else "❌ Nessun snapshot di oggi"
    st.write(status_snap)

if st.button("🚀 AVVIA SCANSIONE V15.1"):
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
    fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"])]
    
    results = []
    progress_bar = st.progress(0)
    for i, m in enumerate(fixtures):
        progress_bar.progress((i+1)/len(fixtures))
        fid = m["fixture"]["id"]
        q1, qx, q2, o25 = fetch_odds(fid)
        if q1 <= 0: continue
        
        h_ht = get_ht_rate(m["teams"]["home"]["id"])
        a_ht = get_ht_rate(m["teams"]["away"]["id"])
        
        rating, det, drop_label = calculate_rating(fid, q1, q2, o25, h_ht, a_ht, snap_odds)
        
        if rating >= min_rating:
            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Match": f"<div class='match-cell'>{m['teams']['home']['name']} - {m['teams']['away']['name']}<br><span class='drop-tag'>{drop_label}</span></div>",
                "1X2": f"{q1} | {qx} | {q2}",
                "O2.5": o25,
                "Rating": rating,
                "Dettagli": "".join([f"<div>• {d}</div>" for d in det]),
                "R_VAL": rating
            })

    if results:
        df = pd.DataFrame(results).sort_values("R_VAL", ascending=False)
        def style_rows(row):
            rm = row['R_VAL']
            if rm >= 85: return ['background-color: #1b4332; color: #ffffff !important; font-weight: bold;'] * len(row)
            if rm >= 70: return ['background-color: #2d6a4f; color: #ffffff !important;'] * len(row)
            return ['color: #000000 !important;'] * len(row)

        styler = df.style.apply(style_rows, axis=1).hide(subset=["R_VAL"], axis=1)
        st.write(styler.to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("Nessun match con rating sufficiente trovato.")
        

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
st.set_page_config(page_title="ARAB SNIPER V15.7", layout="wide")

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
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; font-family: monospace; font-size: 0.85rem; line-height: 1.4; border: 1px solid #00e5ff; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API HELPERS & ROBUST PARSING (Punto 3)
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=25)
    r.raise_for_status() 
    return r.json()

def extract_bets_robust(resp_json):
    """Scorre i bookmaker finché non trova uno che contiene sia Esito Finale (1) che Over 2.5 (5)"""
    resp = resp_json.get("response", [])
    if not resp: return []
    for bm in resp[0].get("bookmakers", []):
        bets = bm.get("bets", [])
        ids = [b.get("id") for b in bets]
        if 1 in ids and 5 in ids: # Punto 3: Verifica mercati essenziali
            return bets
    return []

def is_allowed_league(league_name, league_country):
    name = league_name.lower()
    banned = ["women", "u19", "u20", "u21", "u23", "primavera"]
    if any(x in name for x in banned): return False
    if league_country in ["Algeria","Egypt","Morocco","Saudi Arabia","UAE","India"]: return False
    return True

# ============================
# PERSISTENZA 
# ============================
def save_snapshot(data_dict, date_str):
    st.session_state["odds_memory"] = data_dict
    st.session_state["snap_date_mem"] = date_str
    with open(JSON_FILE, "w") as f:
        json.dump({"date": date_str, "odds": data_dict}, f)

def load_snapshot():
    if st.session_state["odds_memory"] and st.session_state["snap_date_mem"]:
        return st.session_state["snap_date_mem"], st.session_state["odds_memory"]
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r") as f:
                data = json.load(f)
                st.session_state["odds_memory"] = data.get("odds", {})
                st.session_state["snap_date_mem"] = data.get("date")
                return st.session_state["snap_date_mem"], st.session_state["odds_memory"]
        except: return None, {}
    return None, {}

# ============================
# LOGICA RATING (Punto 4: Inversione Leggibile)
# ============================
def calculate_rating(fid, q1, qx, q2, o25, snap_data, max_q_fav, trap_fav, inv_margin):
    sc = 40
    det = []
    msgs = []
    fid_s = str(fid)
    
    if q1 > 0 and q2 > 0:
        fav_now_price = min(q1, q2)
        if fav_now_price <= trap_fav:
            return 0, [], "🚫 TRAP FAV", "trap_fav"
    
    if 0 < o25 < 1.55:
        return 0, [], "🚫 TRAP O25", "trap_o25"

    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_q1, old_q2 = old.get("q1", 0), old.get("q2", 0)
        
        if old_q1 > 0 and old_q2 > 0:
            gap_old = abs(old_q1 - old_q2)
            fav_at_snap = "1" if old_q1 < old_q2 else "2"
            old_fav_p = old_q1 if fav_at_snap == "1" else old_q2
            cur_fav_p = q1 if fav_at_snap == "1" else q2
            
            # DROP
            delta = old_fav_p - cur_fav_p
            if delta >= 0.15 and cur_fav_p <= max_q_fav:
                sc += 40; det.append("Drop")
                msgs.append(f"📉 Δ{round(delta,2)}")
            
            # INVERSIONE (Punto 4: Pulizia Casi)
            gap_now = abs(q1 - q2)
            if gap_old >= 0.10 and gap_now >= inv_margin:
                inv_detected = False
                if fav_at_snap == "1" and q2 <= (q1 - inv_margin):
                    inv_detected = True
                elif fav_at_snap == "2" and q1 <= (q2 - inv_margin):
                    inv_detected = True
                
                if inv_detected:
                    sc += 20; det.append("Inv")
                    msgs.append("🔄 INV")

    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    
    drop_msg = f"<span class='drop-inline'>{' + '.join(msgs)}</span>" if msgs else ""
    return min(100, sc), det, drop_msg, "ok"

# ============================
# UI E CORE EXECUTION
# ============================
st.sidebar.header("⚙️ Sniper Settings")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_fav = st.sidebar.slider("Quota Max Favorito", 1.50, 3.00, 1.85)
trap_fav = st.sidebar.slider("Trap favorito <=", 1.25, 1.70, 1.45, 0.01)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)

oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
snap_date, snap_odds = load_snapshot()

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("📌 SALVA SNAPSHOT"):
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            all_fx = data.get("response", []) or []
            new_snap = {}
            valid_fx = [m for m in all_fx if m['fixture']['status']['short'] == 'NS' and is_allowed_league(m['league']['name'], m['league']['country'])]
            pb = st.progress(0)
            for i, m in enumerate(valid_fx):
                pb.progress((i+1)/len(valid_fx))
                try:
                    r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                    bets = extract_bets_robust(r_o)
                    if bets:
                        q1 = qx = q2 = o25 = 0.0
                        for b in bets:
                            if b["id"] == 1:
                                v = b.get("values", [])
                                if len(v) >= 3: q1, qx, q2 = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
                            if b["id"] == 5:
                                o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
                        if q1 > 0: new_snap[m["fixture"]["id"]] = {"q1": q1, "qx": qx, "q2": q2, "o25": o25}
                except: continue
            save_snapshot(new_snap, oggi)
            st.success(f"Snapshot OK: {len(new_snap)} match.")

with c2:
    st.write(f"Snapshot: **{snap_date}**" if snap_date == oggi else f"⚠️ Snapshot obsoleto ({snap_date})")

ht_cache = {}

if st.button("🚀 AVVIA SCANSIONE"):
    # Punto 1, 2, 5: Diagnostica Integrale
    diag = {"analyzed": 0, "total": 0, "trap_fav": 0, "trap_o25": 0, "no_odds": 0, "below_min": 0, "errors": 0}
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"])]
        results = []
        pb = st.progress(0)
        
        for i, m in enumerate(fixtures):
            diag["analyzed"] += 1
            pb.progress((i+1)/len(fixtures))
            try:
                r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                bets = extract_bets_robust(r_o)
                q1 = qx = q2 = o25 = 0.0
                if bets:
                    for b in bets:
                        if b["id"] == 1:
                            v = b.get("values", [])
                            if len(v) >= 3: q1, qx, q2 = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
                        if b["id"] == 5:
                            o25 = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
                
                if q1 <= 0: 
                    diag["no_odds"] += 1
                    continue
                
                rating, det_list, drop_label, status = calculate_rating(m["fixture"]["id"], q1, qx, q2, o25, snap_odds, max_q_fav, trap_fav, inv_margin)
                
                if status != "ok":
                    diag[status] += 1
                    continue

                # Calcolo HT Rate (con cache)
                if rating >= (min_rating - 20) and rating > 0:
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
                    diag["total"] += 1
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
                else:
                    diag["below_min"] += 1
            except Exception as e:
                diag["errors"] += 1
                continue

        # BOX DIAGNOSTICA DEFINITIVO
        st.markdown(f"""
        <div class='diag-box'>
            📡 <b>SCAN REPORT:</b> Analizzati: {diag['analyzed']} | ✅ Mostrati: {diag['total']} | 📉 Sotto Soglia Rating: {diag['below_min']}<br>
            🚫 <b>FILTRATI:</b> Trap Fav: {diag['trap_fav']} | Trap O25: {diag['trap_o25']} | ⚠️ No Odds: {diag['no_odds']} | ❌ Errori API: {diag['errors']}
        </div>
        """, unsafe_allow_html=True)

        if results:
            df = pd.DataFrame(results).sort_values("Ora")
            def style_rows(row):
                if row['R_VAL'] >= 85: return ['background-color: #1b4332; color: #ffffff !important;'] * len(row)
                if row['R_VAL'] >= 70: return ['background-color: #2d6a4f; color: #ffffff !important;'] * len(row)
                return [''] * len(row)
            st.write(df.style.apply(style_rows, axis=1).hide(subset=["R_VAL"], axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)

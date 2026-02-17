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

st.set_page_config(page_title="ARAB SNIPER V15.43 - GOLD MASTER", layout="wide")

# ============================
# SESSION STATE & PRELOAD
# ============================
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

if os.path.exists(JSON_FILE) and not st.session_state["odds_memory"]:
    try:
        with open(JSON_FILE, "r") as f:
            _d = json.load(f)
            if _d.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = _d.get("odds", {})
                ts = _d.get("timestamp")
                if ts: st.session_state["snap_time_obj"] = datetime.fromisoformat(ts)
                st.session_state["found_countries"] = sorted({v.get("country") for v in _d.get("odds", {}).values() if v.get("country")})
    except: pass

# ============================
# API & STATS ENGINES
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
    return js

ht_cache, dry_cache = {}, {}
def get_stats(session, tid, mode="ht"):
    cache = ht_cache if mode=="ht" else dry_cache
    if tid in cache: return cache[tid]
    try:
        # Per HT guardiamo le ultime 5, per DRY solo l'ultima
        limit = 5 if mode == "ht" else 1
        rx = api_get(session, "fixtures", {"team": tid, "last": limit, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return 0.0
        if mode == "ht":
            res = sum([1 for f in fx if (f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0) >= 1]) / len(fx)
        else:
            goals = fx[0]["goals"]["home"] if fx[0]["teams"]["home"]["id"] == tid else fx[0]["goals"]["away"]
            res = 1.0 if (int(goals or 0) == 0) else 0.0
        cache[tid] = res
        return res
    except: return 0.0

# [extract_markets_pro e calculate_rating rimangono identici per coerenza]
def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), (b.get("name") or "").lower()
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            if data["o05ht"] == 0 and ("1st" in name or "half" in name) and ("goals" in name or "over/under" in name):
                for x in b.get("values", []):
                    v_val = (x.get("value") or "").lower().replace(" ", "")
                    if "over0.5" in v_val or v_val == "over0.5":
                        data["o05ht"] = float(x.get("odd") or 0); break
        if data["q1"] > 0 and data["o25"] > 0: break
    return data

def calculate_rating(fid, q1, qx, q2, o25, o05ht, snap_data, max_q_gold, inv_margin):
    sc, det = 40, []
    is_gold = (1.40 <= min(q1, q2) <= max_q_gold) if q1 > 0 and q2 > 0 else False
    fid_s = str(fid)
    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_fav = min(old.get("q1", 0), old.get("q2", 0))
        cur_fav = min(q1, q2)
        if (old_fav - cur_fav) >= 0.15: sc += 40; det.append("Drop")
        if abs(q1-q2) >= inv_margin:
            # Semplificazione per brevità inversione
            fav_snap = "1" if old.get("q1",0) < old.get("q2",0) else "2"
            if (fav_snap == "1" and q2 < q1) or (fav_snap == "2" and q1 < q2):
                sc += 25; det.append("Inv")
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    return min(100, sc), det, is_gold

# ============================
# UI & EXECUTION
# ============================
st.sidebar.header("👑 Configurazione")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
only_gold_ui = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=False)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)

if st.button("🚀 AVVIA SCANSIONE MATCH"):
    if not st.session_state["odds_memory"]: st.error("Fai prima lo Snapshot."); st.stop()
    with requests.Session() as s:
        try:
            oggi = now_rome().strftime("%Y-%m-%d")
            all_raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
            fixtures = [f for f in all_raw if f["fixture"]["status"]["short"] == "NS"]
            
            results, pb = [], st.progress(0)
            for i, m in enumerate(fixtures):
                pb.progress((i+1)/len(fixtures))
                try:
                    mk = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if not mk or mk["q1"] <= 0: continue
                    
                    rating, det, is_gold = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], st.session_state["odds_memory"], max_q_gold, inv_margin)
                    
                    # --- RIPRISTINO LOGICA HT & DRY ---
                    h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
                    if get_stats(s, h_id, "ht") >= 0.6 and get_stats(s, a_id, "ht") >= 0.6:
                        rating += 20; det.append("HT")
                        # Dry Rebound sulla favorita
                        fav_id = h_id if mk["q1"] < mk["q2"] else a_id
                        if get_stats(s, fav_id, "dry") >= 1.0:
                            rating = min(100, rating + 15); det.append("DRY")
                    
                    if rating >= min_rating:
                        results.append({
                            "Ora": m["fixture"]["date"][11:16],
                            "Lega": f"{m['league']['name']} ({m['league']['country']})",
                            "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                            "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                            "O2.5": f"{mk['o25']:.2f}",
                            "Rating": rating,
                            "Info": f"[{'|'.join(det)}]",
                            "Is_Gold": is_gold,
                            "Advice": "🔥 TARGET: 0.5 HT" if is_gold else ""
                        })
                except: continue
            st.session_state["scan_results"] = results
        except Exception as e: st.error(f"Errore: {e}")

# ============================
# RENDERING
# ============================
if st.session_state["scan_results"]:
    df_raw = pd.DataFrame(st.session_state["scan_results"])
    df_show = df_raw[df_raw["Is_Gold"] == True].copy() if only_gold_ui else df_raw.copy()
    
    def style_rows(row):
        r_val, is_gold, info = row["Rating"], row["Is_Gold"], row["Info"]
        if r_val >= 85: return ['background-color: #1b4332; color: #ffffff; font-weight: bold;'] * len(row)
        elif is_gold or r_val >= 75 or "DRY" in info: return ['background-color: #2d6a4f; color: #ffffff; font-weight: bold;'] * len(row)
        return [''] * len(row)

    if not df_show.empty:
        df_show["Match_Disp"] = df_show.apply(lambda r: f"{'👑 ' if r['Is_Gold'] else ''}{r['Match']}<br><small style='color:#00e5ff'>{r['Advice']}</small>", axis=1)
        styled = df_show.style.apply(style_rows, axis=1)
        cols = ["Ora", "Lega", "Match_Disp", "1X2", "O2.5", "Rating", "Info"]
        st.write(styled.hide(axis="columns", subset=[c for c in df_show.columns if c not in cols]).to_html(escape=False, index=False), unsafe_allow_html=True)
        

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

# ============================
# TIMEZONE & SESSION STATE
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V15.42 - IRONCLAD MASTER", layout="wide")

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

# ============================
# PRELOAD SNAPSHOT & STATUS
# ============================
snap_status_msg = "⚠️ Nessun Snapshot salvato per oggi"
snap_status_type = "warning"

if os.path.exists(JSON_FILE) and not st.session_state["odds_memory"]:
    try:
        with open(JSON_FILE, "r") as f:
            _d = json.load(f)
            if _d.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = _d.get("odds", {})
                ts = _d.get("timestamp")
                if ts: st.session_state["snap_time_obj"] = datetime.fromisoformat(ts)
                st.session_state["found_countries"] = sorted(
                    {v.get("country") for v in st.session_state["odds_memory"].values() if v.get("country")}
                )
    except Exception: pass

if st.session_state["snap_time_obj"]:
    snap_status_msg = f"✅ Snapshot ATTIVO (Ore {st.session_state['snap_time_obj'].strftime('%H:%M')})"
    snap_status_type = "success"

# ============================
# CSS & STILE
# ============================
def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
            .match-cell { text-align: left !important; min-width: 180px; font-weight: 700; color: inherit !important; }
            .advice-tag { display: block; font-size: 0.65rem; color: #00e5ff; font-style: italic; margin-top: 2px; }
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; border: 1px solid #00e5ff; }
        </style>
    """, unsafe_allow_html=True)

# ============================
# MOTORE DI RATING
# ============================
def calculate_rating(fid, q1, qx, q2, o25, o05ht, snap_data, max_q_gold, trap_limit, inv_margin):
    sc, det = 40, []
    is_gold, into_trap = False, False
    current_fav = min(q1, q2) if q1 > 0 and q2 > 0 else 0
    if trap_limit <= current_fav <= max_q_gold: is_gold = True
    
    fid_s = str(fid)
    if 0 < current_fav < trap_limit:
        if fid_s in snap_data:
            old_q = min(snap_data[fid_s].get("q1", 0), snap_data[fid_s].get("q2", 0))
            if old_q >= trap_limit and (old_q - current_fav) >= 0.10: into_trap = True
            else: return 0, [], "trap_fav", False, False
        else: return 0, [], "trap_fav", False, False
        
    if 0 < o25 < 1.55: return 0, [], "trap_o25", False, False
    
    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_q1, old_q2 = old.get("q1", 0), old.get("q2", 0)
        if old_q1 > 0 and old_q2 > 0:
            fav_snap = "1" if old_q1 < old_q2 else "2"
            old_fav, cur_fav = (old_q1, q1) if fav_snap == "1" else (old_q2, q2)
            if (old_fav - cur_fav) >= 0.15 and cur_fav <= max_q_gold:
                sc += 40; det.append("Drop")
            if abs(q1-q2) >= inv_margin:
                if (fav_snap == "1" and q2 <= q1-inv_margin) or (fav_snap == "2" and q1 <= q2-inv_margin):
                    sc += 25; det.append("Inv")
                    
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    return min(100, sc), det, "ok", is_gold, into_trap

# ============================
# API & PARSING
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"):
        raise RuntimeError(f"API Errors: {js['errors']}")
    return js

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid = b.get("id")
            name = (b.get("name") or "").lower()
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

def is_allowed_league(league_name, league_country, blocked_user, forced_user):
    name = (league_name or "").lower()
    banned = ["women", "femminile", "u19", "u20", "u21", "u23", "primavera", "youth", "reserve", "friendly"]
    if any(t in name for t in banned): return False
    country = (league_country or "").strip()
    if country in forced_user: return True
    if country in blocked_user: return False
    AREAS = {"Italy", "Spain", "France", "Germany", "England", "Portugal", "Netherlands", "Belgium", "Switzerland", "Austria", "Greece", "Turkey", "Scotland", "Denmark", "Norway", "Sweden", "Poland", "Czech Republic", "Slovakia", "Hungary", "Romania", "Croatia", "Serbia", "Brazil", "Argentina", "Uruguay", "Colombia", "Chile", "USA", "Mexico", "Canada", "Japan", "South Korea", "Australia"}
    return country in AREAS

# ============================
# UI SIDEBAR
# ============================
apply_custom_css()
st.sidebar.header("👑 Configurazione")
if snap_status_type == "success": st.sidebar.success(snap_status_msg)
else: st.sidebar.warning(snap_status_msg)

min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
only_gold_ui = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=False)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)

st.sidebar.markdown("---")
blocked_user = st.sidebar.multiselect("🚫 Blocca Paesi", st.session_state.get("found_countries", []), key="blocked_user")
forced_user = st.sidebar.multiselect("✅ Forza Paesi", st.session_state.get("found_countries", []), key="forced_user")

# ============================
# AZIONI SNAPSHOT & SCAN
# ============================
oggi = now_rome().strftime("%Y-%m-%d")

if st.button("📌 SALVA/AGGIORNA SNAPSHOT"):
    with requests.Session() as s:
        try:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            valid_fx = [m for m in (data.get("response", []) or []) if m['fixture']['status']['short'] == 'NS']
            if not valid_fx: st.warning("Nessun match NS."); st.stop()
            new_snap, pb = {}, st.progress(0)
            for i, m in enumerate(valid_fx):
                pb.progress((i+1)/len(valid_fx))
                mk = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                if mk and mk["q1"] > 0:
                    mk["country"] = m["league"]["country"]
                    new_snap[m["fixture"]["id"]] = mk
            snap_time = now_rome()
            st.session_state["odds_memory"], st.session_state["snap_time_obj"] = new_snap, snap_time
            st.session_state["found_countries"] = sorted({v.get("country") for v in new_snap.values() if v.get("country")})
            with open(JSON_FILE, "w") as f: 
                json.dump({"date": oggi, "timestamp": snap_time.isoformat(), "odds": new_snap}, f)
            st.rerun()
        except Exception as e: st.error(f"Errore: {e}")

if st.button("🚀 AVVIA SCANSIONE MATCH"):
    if not st.session_state["odds_memory"]: st.error("Fai prima lo Snapshot."); st.stop()
    with requests.Session() as s:
        try:
            all_raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
            fixtures = [f for f in all_raw if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"], blocked_user, forced_user)]
            
            if not fixtures:
                st.warning("Nessun match trovato con i filtri attuali."); st.stop()
            
            results, pb = [], st.progress(0)
            for i, m in enumerate(fixtures):
                pb.progress((i+1)/len(fixtures))
                try:
                    mk = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if not mk or mk["q1"] <= 0: continue
                    res = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], st.session_state["odds_memory"], max_q_gold, 1.40, inv_margin)
                    rating, det, status, is_gold, into_trap = res
                    if status != "ok" or rating < min_rating: continue
                    
                    results.append({
                        "Ora": m["fixture"]["date"][11:16], 
                        "Lega": f"{m['league']['name']} ({m['league']['country']})", 
                        "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}{' *' if into_trap else ''}", 
                        "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", 
                        "O2.5": f"{mk['o25']:.2f}", "Rating": rating, 
                        "Info": f"[{'|'.join(det)}]", 
                        "Advice": "🔥 TARGET: 0.5 HT" if is_gold else "",
                        "Is_Gold": is_gold, "Fixture_ID": m["fixture"]["id"]
                    })
                except: continue
            
            st.session_state["scan_results"] = results
            if results:
                new_df = pd.DataFrame(results)
                new_df["Log_Date"] = now_rome().strftime("%Y-%m-%d %H:%M")
                new_df["Fixture_ID"] = new_df["Fixture_ID"].astype(str)
                if os.path.exists(LOG_CSV):
                    old = pd.read_csv(LOG_CSV, dtype={"Fixture_ID": str})
                    pd.concat([old, new_df], ignore_index=True).drop_duplicates(subset=["Fixture_ID"]).to_csv(LOG_CSV, index=False)
                else: new_df.to_csv(LOG_CSV, index=False)
        except Exception as e: st.error(f"Errore: {e}")

# ============================
# RENDERING (FIX KEYERROR)
# ============================
if st.session_state["scan_results"]:
    res = st.session_state["scan_results"]
    st.markdown(f"<div class='diag-box'>📡 ANALIZZATI: {len(res)} match validi</div>", unsafe_allow_html=True)
    
    df_raw = pd.DataFrame(res).sort_values("Ora")
    df_show = df_raw[df_raw["Is_Gold"] == True].copy() if only_gold_ui else df_raw.copy()

    def style_rows(row):
        r_val, is_gold = row["Rating"], row["Is_Gold"]
        if r_val >= 85: return ['background-color: #1b4332; color: #ffffff; font-weight: bold;'] * len(row)
        elif is_gold or r_val >= 75: return ['background-color: #2d6a4f; color: #ffffff; font-weight: bold;'] * len(row)
        return [''] * len(row)

    if not df_show.empty:
        # Applichiamo lo stile includendo Is_Gold, poi lo nascondiamo nel rendering
        styled_df = df_show.style.apply(style_rows, axis=1)
        cols_to_show = ["Ora", "Lega", "Match", "1X2", "O2.5", "Rating", "Info"]
        
        st.write(
            styled_df.format(precision=2)
            .hide(axis="columns", subset=[c for c in df_show.columns if c not in cols_to_show])
            .to_html(escape=False, index=False), 
            unsafe_allow_html=True
        )
        

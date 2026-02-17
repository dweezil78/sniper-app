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

st.set_page_config(page_title="ARAB SNIPER V15.40 - IRONCLAD", layout="wide")

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

# ============================
# PRELOAD SNAPSHOT (BUG 1 FIX)
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
# API & PARSING (REGRESSIONE 1 & 2 FIX)
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status() # REGRESSIONE 1: Ripristinata protezione errori
    return r.json()

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            name = (b.get("name") or "").lower()
            # 1X2
            if b["id"] == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            # OVER 2.5
            if b["id"] == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            # REGRESSIONE 2: Parsing Robusto Over 0.5 HT
            if data["o05ht"] == 0 and ("1st" in name or "first" in name or "half" in name) and ("goals" in name or "over/under" in name):
                for x in b.get("values", []):
                    v_val = (x.get("value") or "").lower().replace(" ", "")
                    if "over0.5" in v_val or v_val == "over0.5":
                        data["o05ht"] = float(x.get("odd") or 0)
                        break
        if data["q1"] > 0 and data["o25"] > 0: break
    return data

# ============================
# FILTRI LEGA (REGRESSIONE 3 FIX)
# ============================
def is_allowed_league(league_name, league_country, blocked_user, forced_user):
    name = (league_name or "").lower()
    banned = ["women", "femminile", "u19", "u20", "u21", "u23", "primavera", "youth", "reserve", "friendly"]
    if any(t in name for t in banned): return False
    country = (league_country or "").strip()
    if country in forced_user: return True
    if country in blocked_user: return False
    # Filtro aree geografiche standard
    AREAS = {"Italy", "Spain", "France", "Germany", "England", "Portugal", "Netherlands", "Belgium", "Switzerland", "Austria", "Greece", "Turkey", "Scotland", "Denmark", "Norway", "Sweden", "Poland", "Czech Republic", "Slovakia", "Hungary", "Romania", "Croatia", "Serbia", "Brazil", "Argentina", "Uruguay", "Colombia", "Chile", "USA", "United States", "Mexico", "Canada", "Japan", "South Korea", "Korea Republic", "Australia", "New Zealand"}
    return country in AREAS

# [Funzioni calculate_rating e apply_custom_css rimangono le stesse della V15.39]

# ============================
# UI SIDEBAR
# ============================
st.sidebar.header("👑 Configurazione & Legenda")
if snap_status_type == "success": st.sidebar.success(snap_status_msg)
else: st.sidebar.warning(snap_status_msg)

min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
only_gold_ui = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=False)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01) # Slider attivo

st.sidebar.markdown("---")
blocked_user = st.sidebar.multiselect("🚫 Blocca Paesi", st.session_state.get("found_countries", []), key="blocked_user")
forced_user = st.sidebar.multiselect("✅ Forza Paesi", st.session_state.get("found_countries", []), key="forced_user")

# ============================
# LOGICA SNAPSHOT & SCANSIONE
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
            st.session_state["odds_memory"] = new_snap
            st.session_state["snap_time_obj"] = snap_time
            st.session_state["found_countries"] = sorted({v.get("country") for v in new_snap.values() if v.get("country")})
            
            with open(JSON_FILE, "w") as f: 
                json.dump({"date": oggi, "timestamp": snap_time.isoformat(), "odds": new_snap}, f)
            st.rerun()
        except Exception as e: st.error(f"Errore Snapshot: {e}")

if st.button("🚀 AVVIA SCANSIONE MATCH"):
    if not st.session_state["odds_memory"]:
        st.error("❌ Errore: Snapshot non trovato. Salva lo snapshot prima di scansionare.")
        st.stop()
        
    with requests.Session() as s:
        try:
            all_raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
            # REGRESSIONE 3: Ripristinato filtro Lega/Paese
            fixtures = [
                f for f in all_raw 
                if f["fixture"]["status"]["short"] == "NS" 
                and is_allowed_league(f["league"]["name"], f["league"]["country"], blocked_user, forced_user)
            ]
            
            results, pb = [], st.progress(0)
            for i, m in enumerate(fixtures):
                pb.progress((i+1)/len(fixtures))
                try:
                    mk = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if not mk or mk["q1"] <= 0: continue
                    # FIX 6: Utilizzo dello slider inv_margin
                    res = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], st.session_state["odds_memory"], max_q_gold, 1.40, inv_margin)
                    rating, det, _, _, status, is_gold, into_trap = res
                    if status != "ok": continue
                    
                    if rating >= min_rating:
                        results.append({
                            "Ora": m["fixture"]["date"][11:16], 
                            "Lega": f"{m['league']['name']} ({m['league']['country']})", 
                            "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}{' *' if into_trap else ''}", 
                            "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", 
                            "O2.5": f"{mk['o25']:.2f}", 
                            "Rating": rating, 
                            "Info": f"[{'|'.join(det)}]", 
                            "Is_Gold": is_gold,
                            "Fixture_ID": m["fixture"]["id"]
                        })
                except: continue
            st.session_state["scan_results"] = results
        except Exception as e: st.error(f"Errore Scansione: {e}")

# ============================
# RENDERING (BUG 4 FIX)
# ============================
if st.session_state["scan_results"]:
    df_d = pd.DataFrame(st.session_state["scan_results"])
    df_show = df_d[df_d["Is_Gold"] == True].copy() if only_gold_ui else df_d.copy()

    def style_rows(row):
        r_val = row["Rating"]
        info_val = row["Info"]
        is_gold = row["Is_Gold"]
        if r_val >= 85: return ['background-color: #1b4332; color: #ffffff; font-weight: bold;'] * len(row)
        elif is_gold or r_val >= 75 or (r_val >= 65 and "DRY" in info_val):
            return ['background-color: #2d6a4f; color: #ffffff; font-weight: bold;'] * len(row)
        return [''] * len(row)

    if not df_show.empty:
        # Mostra tabella pulita
        to_show = df_show[["Ora", "Lega", "Match", "1X2", "O2.5", "Rating", "Info"]]
        st.write(to_show.style.apply(style_rows, axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)
        

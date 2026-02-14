import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import json
import os
from typing import Any, Dict, List, Tuple, Optional

# ============================
# CONFIGURAZIONE & TIMEZONE
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

JSON_FILE = "arab_snapshot.json"
LOG_CSV = "sniper_history_log.csv"

st.set_page_config(page_title="ARAB SNIPER V15.20", layout="wide")

# Setup Session State
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_date_mem" not in st.session_state: st.session_state["snap_date_mem"] = None
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

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
            .details-inline { font-size: 0.7rem; font-weight: 800; opacity: 0.9; margin-left: 5px; color: #333 !important; }
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; font-family: monospace; font-size: 0.85rem; border: 1px solid #00e5ff; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API HELPERS & ROBUST PARSING
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=25)
    r.raise_for_status() 
    return r.json()

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        bets = bm.get("bets", [])
        for b in bets:
            b_name = b.get("name", "").lower()
            if b["id"] == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if b["id"] == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            # Miglioria B: Parsing HT ultra-tollerante
            if data["o05ht"] == 0 and ("1st" in b_name or "half" in b_name) and ("goals" in b_name or "over/under" in b_name):
                for val in b.get("values", []):
                    v_label = val.get("value", "").lower().replace(" ","")
                    if ("over" in v_label and "0.5" in v_label) or ("o0.5" in v_label):
                        data["o05ht"] = float(val["odd"]); break
        if data["q1"] > 0 and data["o25"] > 0 and data["o05ht"] > 0: break
    return data

# ============================
# LOGICA CORE
# ============================
def is_allowed_league(league_name, league_country, blocked_user, forced_user):
    name = (league_name or "").lower()
    banned = ["women", "femminile", "u19", "u20", "u21", "u23", "primavera", "youth", "reserve", "friendly"]
    if any(t in name for t in banned): return False
    country = (league_country or "").strip()
    if country in forced_user: return True
    if country in blocked_user: return False
    AREAS = {"Italy", "Spain", "France", "Germany", "England", "Portugal", "Netherlands", "Belgium", "Switzerland", "Austria", "Greece", "Turkey", "Scotland", "Denmark", "Norway", "Sweden", "Poland", "Czech Republic", "Slovakia", "Hungary", "Romania", "Croatia", "Serbia", "Brazil", "Argentina", "Uruguay", "Colombia", "Chile", "USA", "United States", "Mexico", "Canada", "Japan", "South Korea", "Korea Republic", "Australia", "New Zealand"}
    return country in AREAS

def calculate_rating(fid, q1, qx, q2, o25, o05ht, snap_data, max_q_fav, trap_fav, inv_margin):
    sc, det, msgs_h, msgs_t = 40, [], [], []
    fid_s = str(fid)
    if q1 > 0 and q2 > 0:
        if min(q1, q2) <= trap_fav and o25 <= 1.65: return 0, [], "", "", "trap_fav"
    if 0 < o25 < 1.55: return 0, [], "", "", "trap_o25"
    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_q1, old_q2 = old.get("q1", 0), old.get("q2", 0)
        if old_q1 > 0 and old_q2 > 0:
            fav_snap = "1" if old_q1 < old_q2 else "2"
            old_fav, cur_fav = (old_q1, q1) if fav_snap == "1" else (old_q2, q2)
            delta = old_fav - cur_fav
            if delta >= 0.15 and cur_fav <= max_q_fav:
                sc += 40; det.append("Drop"); msgs_h.append(f"📉 Δ{round(delta,2)}"); msgs_t.append(f"Drop Δ{round(delta,2)}")
            if abs(old_q1-old_q2) >= 0.10 and abs(q1-q2) >= inv_margin:
                if (fav_snap == "1" and q2 <= q1-inv_margin) or (fav_snap == "2" and q1 <= q2-inv_margin):
                    b_inv = 25 if qx < 3.20 else 20
                    sc += b_inv; det.append("Inv"); msgs_h.append("🔄 INV"); msgs_t.append("INV")
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    h_msg = f"<span class='drop-inline'>{' + '.join(msgs_h)}</span>" if msgs_h else ""
    t_msg = " + ".join(msgs_t) if msgs_t else "STABILE"
    return min(100, sc), det, h_msg, t_msg, "ok"

# ============================
# PERSISTENZA & UI SIDEBAR
# ============================
oggi = now_rome().strftime("%Y-%m-%d")

# Caricamento Paesi (Fix 2: Fallback su Fixtures se JSON incompleto)
if not st.session_state["found_countries"]:
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r") as f:
            _d = json.load(f)
            st.session_state["found_countries"] = sorted(list(set(v.get("country") for v in _d.get("odds", {}).values() if v.get("country"))))
    
    # Se ancora vuoto (JSON vecchio o assente), facciamo chiamata fixtures leggera
    if not st.session_state["found_countries"]:
        try:
            with requests.Session() as s:
                raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
                st.session_state["found_countries"] = sorted(list(set(f["league"]["country"] for f in raw)))
        except: pass

st.sidebar.header("⚙️ Sniper Settings")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_fav = st.sidebar.slider("Quota Max Favorito", 1.50, 3.00, 1.85)
trap_fav = st.sidebar.slider("Trap favorito <=", 1.25, 1.70, 1.45, 0.01)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)
st.sidebar.markdown("---")
st.sidebar.subheader("🌍 Filtro Campionati")
blocked_user = st.sidebar.multiselect("🚫 Blocca Paesi", st.session_state["found_countries"], key="blocked_user")
forced_user = st.sidebar.multiselect("✅ Forza Paesi", st.session_state["found_countries"], key="forced_user")

# ============================
# CORE EXECUTION
# ============================
if os.path.exists(JSON_FILE) and not st.session_state["odds_memory"]:
    with open(JSON_FILE, "r") as f:
        _d = json.load(f)
        st.session_state["odds_memory"], st.session_state["snap_date_mem"] = _d.get("odds", {}), _d.get("date")
        st.session_state["snap_time_obj"] = datetime.fromisoformat(_d.get("timestamp")) if _d.get("timestamp") else None

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("📌 SALVA SNAPSHOT"):
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            all_raw = data.get("response", []) or []
            valid_fx = [m for m in all_raw if m['fixture']['status']['short'] == 'NS']
            
            if not valid_fx:
                st.warning("Nessun match NS trovato oggi.")
            else:
                new_snap, pb = {}, st.progress(0)
                for i, m in enumerate(valid_fx):
                    pb.progress((i+1)/len(valid_fx))
                    try:
                        r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                        mk = extract_markets_pro(r_o)
                        if mk and mk["q1"] > 0 and min(mk["q1"], mk["q2"]) <= 5.0:
                            mk["country"] = m["league"]["country"]
                            new_snap[m["fixture"]["id"]] = mk
                    except: continue
                
                snap_time = now_rome()
                st.session_state["odds_memory"], st.session_state["snap_date_mem"] = new_snap, oggi
                st.session_state["snap_time_obj"] = snap_time
                with open(JSON_FILE, "w") as f: 
                    json.dump({"date": oggi, "timestamp": snap_time.isoformat(), "odds": new_snap}, f)
                st.rerun()

with c2:
    if st.session_state['snap_date_mem'] == oggi and st.session_state["snap_time_obj"]:
        diff = now_rome() - st.session_state["snap_time_obj"]
        st.write(f"Snapshot delle: **{st.session_state['snap_time_obj'].strftime('%H:%M')}** ({int(diff.total_seconds()//60)} min fa)")
        # Miglioria C: Warning se snapshot obsoleto o di ieri
        if st.session_state['snap_date_mem'] != oggi: st.warning("⚠️ Lo snapshot in memoria non è di oggi!")
    else: st.write(f"⚠️ Snapshot assente.")

if st.button("🚀 AVVIA SCANSIONE"):
    if st.session_state["snap_time_obj"]:
        age_min = (now_rome() - st.session_state["snap_time_obj"]).total_seconds() / 60
        if age_min < 15: st.warning(f"⚠️ Snapshot molto recente ({int(age_min)} min). Attendere movimenti di quota.")
    
    diag = {"analyzed": 0, "total": 0, "trap_fav": 0, "trap_o25": 0, "no_odds": 0, "below_min": 0, "errors": 0}
    with requests.Session() as s:
        all_raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
        fixtures = [f for f in all_raw if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"], blocked_user, forced_user)]
        
        if not fixtures:
            st.warning("Nessun match trovato per i filtri selezionati.")
        else:
            results, pb = [], st.progress(0)
            for i, m in enumerate(fixtures):
                diag["analyzed"] += 1
                pb.progress((i+1)/len(fixtures))
                try:
                    r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                    mk = extract_markets_pro(r_o)
                    if not mk or mk["q1"] <= 0: diag["no_odds"] += 1; continue
                    
                    rating, det, d_html, d_text, status = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], st.session_state["odds_memory"], max_q_fav, trap_fav, inv_margin)
                    
                    # Fix 1: Incremento robusto diagnostica
                    if status != "ok":
                        diag[status] = diag.get(status, 0) + 1
                        continue
                    
                    if rating >= min_rating:
                        diag["total"] += 1
                        results.append({"Ora": m["fixture"]["date"][11:16], "Lega": m['league']['name'], "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}", "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}" if mk['o05ht'] > 0 else "N/D", "Rating": rating, "Info": f"[{'|'.join(det)}]", "Drop_Inv": d_html, "Drop_Inv_Text": d_text, "Fixture_ID": m["fixture"]["id"]})
                    else: diag["below_min"] += 1
                except: diag["errors"] += 1
            st.session_state["scan_results"] = {"data": results, "diag": diag, "date": oggi}

# RENDERING PERSISTENTE
if st.session_state["scan_results"]:
    res = st.session_state["scan_results"]
    st.markdown(f"<div class='diag-box'>📡 ANALIZZATI: {res['diag']['analyzed']} | ✅ MOSTRATI: {res['diag']['total']} | 🚫 TRAPS: {res['diag'].get('trap_fav',0) + res['diag'].get('trap_o25',0)} | ❌ ERRORS: {res['diag']['errors']}</div>", unsafe_allow_html=True)
    if res["data"]:
        df_d = pd.DataFrame(res["data"]).sort_values("Ora")
        df_s = df_d.copy()
        df_s["Lega"] = df_s["Lega"].apply(lambda x: f"<div class='lega-cell'>{x}</div>")
        df_s["Match"] = df_s.apply(lambda r: f"<div class='match-cell'>{r['Match']} {r['Drop_Inv']}</div>", axis=1)
        df_s["Info"] = df_s["Info"].apply(lambda x: f"<span class='details-inline'>{x}</span>")
        df_s["Rating_D"] = df_s["Rating"].apply(lambda x: f"<b>{x}</b>")
        html_out = df_s[["Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "Rating_D", "Info"]].to_html(escape=False, index=False)
        st.write(html_out, unsafe_allow_html=True)

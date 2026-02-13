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
LOG_CSV = "sniper_history_log.csv"

st.set_page_config(page_title="ARAB SNIPER V15.12", layout="wide")

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
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; font-family: monospace; font-size: 0.85rem; border: 1px solid #00e5ff; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API HELPERS & ROBUST HT PARSING (Fix Punto 2 & 3)
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
            # 1X2
            if b["id"] == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3:
                    data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            # Over 2.5 FT
            if b["id"] == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            # Over 0.5 HT - Fix Punto 3: Parsing più robusto
            if data["o05ht"] == 0:
                if b["id"] == 13 or ("half" in b_name and "goals" in b_name):
                    for val in b.get("values", []):
                        v_label = val.get("value", "").lower()
                        if "over 0.5" in v_label:
                            data["o05ht"] = float(val["odd"])
                            break
        
        # Fix Punto 2: Non uscire finché non abbiamo anche HT (se disponibile)
        if data["q1"] > 0 and data["o25"] > 0 and data["o05ht"] > 0:
            break
            
    return data

def is_allowed_league(league_name, league_country):
    name = league_name.lower()
    banned = ["women", "u19", "u20", "u21", "u23", "primavera", "youth", "reserve"]
    if any(x in name for x in banned): return False
    if league_country in ["Algeria","Egypt","Morocco","Saudi Arabia","UAE","India"]: return False
    return True

# ============================
# PERSISTENZA & LOG (Fix Punto 1 & A)
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
    # Fix Punto 1: Se leggiamo da file, aggiorniamo la sessione
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r") as f:
                data = json.load(f)
                st.session_state["odds_memory"] = data.get("odds", {})
                st.session_state["snap_date_mem"] = data.get("date")
                return st.session_state["snap_date_mem"], st.session_state["odds_memory"]
        except: return None, {}
    return None, {}

def log_to_csv(results_list):
    if not results_list: return
    clean_list = []
    for r in results_list:
        clean_r = r.copy()
        clean_r["Drop_Inv"] = r.get("Drop_Inv_Text", "STABILE")
        # Fix Punto A: Uso di pop per evitare errori se la chiave manca
        clean_r.pop("Drop_Inv_Text", None)
        clean_list.append(clean_r)
    
    new_df = pd.DataFrame(clean_list)
    new_df['Log_Date'] = datetime.now(ROME_TZ).strftime("%Y-%m-%d %H:%M")
    if os.path.exists(LOG_CSV):
        pd.concat([pd.read_csv(LOG_CSV), new_df], ignore_index=True).drop_duplicates(subset=['Ora', 'Match']).to_csv(LOG_CSV, index=False)
    else:
        new_df.to_csv(LOG_CSV, index=False)

# ============================
# LOGICA RATING
# ============================
def calculate_rating(fid, q1, qx, q2, o25, o05ht, snap_data, max_q_fav, trap_fav, inv_margin):
    sc = 40
    det = []
    msgs_html = []
    msgs_text = []
    fid_s = str(fid)
    
    if q1 > 0 and q2 > 0:
        fav = min(q1, q2)
        if fav <= trap_fav and o25 <= 1.65:
            return 0, [], "", "", "trap_fav"
    
    if 0 < o25 < 1.55: return 0, [], "", "", "trap_o25"

    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_q1, old_q2 = old.get("q1", 0), old.get("q2", 0)
        
        if old_q1 > 0 and old_q2 > 0:
            fav_at_snap = "1" if old_q1 < old_q2 else "2"
            old_fav_p, cur_fav_p = (old_q1, q1) if fav_at_snap == "1" else (old_q2, q2)
            
            delta = old_fav_p - cur_fav_p
            if delta >= 0.15 and cur_fav_p <= max_q_fav:
                sc += 40; det.append("Drop")
                msgs_html.append(f"📉 Δ{round(delta,2)}")
                msgs_text.append(f"Drop Δ{round(delta,2)}")
            
            gap_now = abs(q1 - q2)
            if abs(old_q1-old_q2) >= 0.10 and gap_now >= inv_margin:
                if (fav_at_snap == "1" and q2 <= q1 - inv_margin) or (fav_at_snap == "2" and q1 <= q2 - inv_margin):
                    bonus_inv = 20
                    if qx < 3.20: bonus_inv += 5 
                    sc += bonus_inv; det.append("Inv")
                    msgs_html.append("🔄 INV")
                    msgs_text.append("INV")

    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    
    html_msg = f"<span class='drop-inline'>{' + '.join(msgs_html)}</span>" if msgs_html else ""
    text_msg = " + ".join(msgs_text) if msgs_text else "STABILE"
    
    return min(100, sc), det, html_msg, text_msg, "ok"

# ============================
# STATS CACHE
# ============================
ht_cache = {}
dry_cache = {}

def get_stats(session, tid, mode="ht"):
    cache = ht_cache if mode=="ht" else dry_cache
    if tid in cache: return cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 5 if mode=="ht" else 1, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return 0.0
        if mode == "ht":
            res = sum([1 for f in fx if (f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0) >= 1]) / len(fx)
        else:
            is_h = fx[0]["teams"]["home"]["id"] == tid
            res = (int(fx[0]["goals"]["home"] if is_h else fx[0]["goals"]["away"] or 0) == 0)
        cache[tid] = res
        return res
    except: return 0.0

# ============================
# CORE UI
# ============================
st.sidebar.header("⚙️ Sniper Settings")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_fav = st.sidebar.slider("Quota Max Favorito", 1.50, 3.00, 1.85)
trap_fav = st.sidebar.slider("Trap favorito <=", 1.25, 1.70, 1.45, 0.01)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)
st.sidebar.subheader("🔥 Bonus Strategici")
use_sb_bonus = st.sidebar.toggle("Bonus Sblocco HT (Ultima a secco)", value=True)

oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
snap_date, snap_odds = load_snapshot()

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("📌 SALVA SNAPSHOT"):
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            valid_fx = [m for m in data.get("response", []) if m['fixture']['status']['short'] == 'NS' and is_allowed_league(m['league']['name'], m['league']['country'])]
            new_snap = {}
            pb = st.progress(0)
            for i, m in enumerate(valid_fx):
                pb.progress((i+1)/len(valid_fx))
                try:
                    r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                    m_data = extract_markets_pro(r_o)
                    if m_data and m_data["q1"] > 0: new_snap[m["fixture"]["id"]] = m_data
                except: continue
            save_snapshot(new_snap, oggi)
            st.success(f"Snapshot OK: {len(new_snap)} match.")

if st.button("🚀 AVVIA SCANSIONE"):
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
                mk = extract_markets_pro(r_o)
                if not mk or mk["q1"] <= 0:
                    diag["no_odds"] += 1
                    continue
                
                rating, det_list, drop_html, drop_text, status = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], snap_odds, max_q_fav, trap_fav, inv_margin)
                
                if status != "ok":
                    diag[status] += 1
                    continue

                if rating >= (min_rating - 10) and rating > 0:
                    h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
                    if get_stats(s, h_id, "ht") >= 0.6 and get_stats(s, a_id, "ht") >= 0.6:
                        rating += 20; det_list.append("HT")
                    if use_sb_bonus and (get_stats(s, h_id, "dry") or get_stats(s, a_id, "dry")):
                        rating = min(100, rating + 10); det_list.append("DRY")
                
                if rating >= min_rating:
                    diag["total"] += 1
                    results.append({
                        "Ora": m["fixture"]["date"][11:16],
                        "Lega": m['league']['name'],
                        "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                        "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                        "O2.5": f"{mk['o25']:.2f}",
                        "O0.5HT": f"{mk['o05ht']:.2f}",
                        "Rating": rating,
                        "Info": f"[{'|'.join(det_list)}]",
                        "Drop_Inv": drop_html,
                        "Drop_Inv_Text": drop_text,
                        "Fixture_ID": m["fixture"]["id"]
                    })
                else: diag["below_min"] += 1
            except: diag["errors"] += 1

        st.markdown(f"<div class='diag-box'>📡 ANALIZZATI: {diag['analyzed']} | ✅ MOSTRATI: {diag['total']} | 📉 BELOW: {diag['below_min']} | 🚫 TRAPS: {diag['trap_fav'] + diag['trap_o25']} | ❌ ERRORS: {diag['errors']}</div>", unsafe_allow_html=True)

        if results:
            df_display = pd.DataFrame(results).sort_values("Ora")
            log_to_csv(results)
            
            # Fix Punto B: Ripristino styling condizionale
            df_styled = df_display.copy()
            df_styled["Lega"] = df_styled["Lega"].apply(lambda x: f"<div class='lega-cell'>{x}</div>")
            df_styled["Match"] = df_styled.apply(lambda r: f"<div class='match-cell'>{r['Match']} {r['Drop_Inv']}</div>", axis=1)
            df_styled["Info"] = df_styled["Info"].apply(lambda x: f"<span class='details-inline'>{x}</span>")
            df_styled["Rating_D"] = df_styled["Rating"].apply(lambda x: f"<b>{x}</b>")
            
            to_show = df_styled[["Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "Rating_D", "Info"]]
            
            def style_rows(row):
                # Recuperiamo il rating originale tramite l'indice della riga
                idx = row.name
                r_val = df_display.loc[idx, "Rating"]
                if r_val >= 85: return ['background-color: #1b4332; color: #ffffff !important;'] * len(row)
                if r_val >= 70: return ['background-color: #2d6a4f; color: #ffffff !important;'] * len(row)
                return [''] * len(row)

            html_output = to_show.style.apply(style_rows, axis=1).to_html(escape=False, index=False)
            st.write(html_output, unsafe_allow_html=True)
            st.download_button("📥 DOWNLOAD REPORT", data=html_output, file_name=f"Sniper_{oggi}.html", mime="text/html")

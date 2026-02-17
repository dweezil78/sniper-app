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

st.set_page_config(page_title="ARAB SNIPER V15.46 - GOLD MASTER", layout="wide")

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_date_mem" not in st.session_state: st.session_state["snap_date_mem"] = None
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

# ============================
# PRELOAD SNAPSHOT (Fix Selezione Paesi & Stato)
# ============================
snap_status_msg = "⚠️ Nessun Snapshot salvato per oggi"
snap_status_type = "warning"

if os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, "r") as f:
            _d = json.load(f)
            if _d.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = _d.get("odds", {})
                st.session_state["snap_date_mem"] = _d.get("date")
                ts = _d.get("timestamp")
                st.session_state["snap_time_obj"] = datetime.fromisoformat(ts) if ts else None
                st.session_state["found_countries"] = sorted(
                    {v.get("country") for v in st.session_state["odds_memory"].values() if v.get("country")}
                )
                snap_status_msg = f"✅ Snapshot ATTIVO (Ore {ts[11:16]})"
                snap_status_type = "success"
    except Exception: pass

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
            .match-cell { text-align: left !important; min-width: 180px; font-weight: 700; color: inherit !important; }
            .drop-inline { color: #ffcc00; font-size: 0.72rem; font-weight: 800; margin-left: 5px; }
            .advice-tag { display: block; font-size: 0.65rem; color: #00e5ff; font-style: italic; margin-top: 2px; }
            .details-inline { font-size: 0.7rem; font-weight: 800; opacity: 0.9; margin-left: 5px; color: inherit !important; }
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; font-family: monospace; font-size: 0.85rem; border: 1px solid #00e5ff; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API HELPERS & PARSING
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
            if data["o05ht"] == 0 and ("1st" in b_name or "half" in b_name) and ("goals" in b_name or "over/under" in b_name):
                for val in b.get("values", []):
                    v_label = val.get("value", "").lower().replace(" ","")
                    if ("over" in v_label and "0.5" in v_label) or ("o0.5" in v_label):
                        data["o05ht"] = float(val["odd"]); break
        if data["q1"] > 0 and data["o25"] > 0:
            break
    return data

# ============================
# LOGICA FILTRI & RATING
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

def calculate_rating(fid, q1, qx, q2, o25, o05ht, snap_data, max_q_gold, trap_limit, inv_margin):
    sc, det, msgs_h, msgs_t = 40, [], [], []
    is_gold, into_trap = False, False
    current_fav = min(q1, q2) if q1 > 0 and q2 > 0 else 0
    if trap_limit <= current_fav <= max_q_gold: is_gold = True
    fid_s = str(fid)
    if 0 < current_fav < trap_limit:
        if fid_s in snap_data:
            old_q = min(snap_data[fid_s].get("q1", 0), snap_data[fid_s].get("q2", 0))
            if old_q >= trap_limit and (old_q - current_fav) >= 0.10: into_trap = True
            else: return 0, [], "", "", "trap_fav", False, False
        else: return 0, [], "", "", "trap_fav", False, False
    if 0 < o25 < 1.55: return 0, [], "", "", "trap_o25", False, False
    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_q1, old_q2 = old.get("q1", 0), old.get("q2", 0)
        if old_q1 > 0 and old_q2 > 0:
            fav_snap = "1" if old_q1 < old_q2 else "2"
            old_fav, cur_fav = (old_q1, q1) if fav_snap == "1" else (old_q2, q2)
            delta = old_fav - cur_fav
            if delta >= 0.15 and cur_fav <= max_q_gold:
                sc += 40; det.append("Drop"); msgs_h.append(f"📉 Δ{round(delta,2)}"); msgs_t.append(f"Drop Δ{round(delta,2)}")
            if abs(old_q1-old_q2) >= 0.10 and abs(q1-q2) >= inv_margin:
                if (fav_snap == "1" and q2 <= q1-inv_margin) or (fav_snap == "2" and q1 <= q2-inv_margin):
                    b_inv = 25 if qx < 3.20 else 20
                    sc += b_inv; det.append("Inv"); msgs_h.append("🔄 INV"); msgs_t.append("INV")
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    h_msg = f"<span class='drop-inline'>{' + '.join(msgs_h)}</span>" if msgs_h else ""
    t_msg = " + ".join(msgs_t) if msgs_t else "STABILE"
    return min(100, sc), det, h_msg, t_msg, "ok", is_gold, into_trap

ht_cache, dry_cache = {}, {}
def get_stats(session, tid, mode="ht"):
    cache = ht_cache if mode=="ht" else dry_cache
    if tid in cache: return cache[tid]
    try:
        # Per HT guardiamo le ultime 5, per DRY guardiamo SOLO L'ULTIMA
        limit = 5 if mode == "ht" else 1
        rx = api_get(session, "fixtures", {"team": tid, "last": limit, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return 0.0
        if mode == "ht": 
            res = sum([1 for f in fx if (f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0) >= 1]) / len(fx)
        else:
            # Verifica se la squadra non ha segnato (0 gol) nell'ultimo match
            goals = fx[0]["goals"]["home"] if fx[0]["teams"]["home"]["id"] == tid else fx[0]["goals"]["away"]
            res = 1.0 if (int(goals or 0) == 0) else 0.0
        cache[tid] = res
        return res
    except: return 0.0

def log_to_csv(results_list):
    if not results_list: return
    clean_list = []
    for r in results_list:
        clean_r = r.copy()
        clean_r["Drop_Inv"] = r.get("Drop_Inv_Text", "STABILE")
        clean_r.pop("Drop_Inv_Text", None)
        clean_list.append(clean_r)
    new_df = pd.DataFrame(clean_list)
    new_df['Log_Date'] = now_rome().strftime("%Y-%m-%d %H:%M")
    new_df["Fixture_ID"] = new_df["Fixture_ID"].astype(str)
    if os.path.exists(LOG_CSV):
        old_df = pd.read_csv(LOG_CSV, dtype={"Fixture_ID": str})
        pd.concat([old_df, new_df], ignore_index=True).drop_duplicates(subset=['Fixture_ID']).to_csv(LOG_CSV, index=False)
    else: new_df.to_csv(LOG_CSV, index=False)

# ============================
# UI SIDEBAR
# ============================
st.sidebar.header("👑 Gold Settings")

if snap_status_type == "success": st.sidebar.success(snap_status_msg)
else: st.sidebar.warning(snap_status_msg)

min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
only_gold_ui = st.sidebar.toggle("🎯 SOLO SWEET SPOT (Visuale Live)", value=False)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)
st.sidebar.markdown("---")
blocked_user = st.sidebar.multiselect("🚫 Blocca Paesi", st.session_state.get("found_countries", []), key="blocked_user")
forced_user = st.sidebar.multiselect("✅ Forza Paesi", st.session_state.get("found_countries", []), key="forced_user")
use_sb_bonus = st.sidebar.toggle("Bonus Sblocco HT (DRY)", value=True)

# ============================
# CORE EXECUTION
# ============================
oggi = now_rome().strftime("%Y-%m-%d")

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("📌 SALVA/AGGIORNA SNAPSHOT"):
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            all_raw = data.get("response", []) or []
            valid_fx = [m for m in all_raw if m['fixture']['status']['short'] == 'NS']
            if not valid_fx: st.warning("Nessun match NS trovato."); st.stop()
            new_snap, pb = {}, st.progress(0)
            status_text_snap = st.empty()
            for i, m in enumerate(valid_fx):
                pb.progress((i+1)/len(valid_fx))
                status_text_snap.text(f"Snapshotting {i+1}/{len(valid_fx)}...")
                try:
                    r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                    mk = extract_markets_pro(r_o)
                    if mk and mk["q1"] > 0:
                        mk["country"] = m["league"]["country"]
                        new_snap[m["fixture"]["id"]] = mk
                except: continue
            st.session_state["found_countries"] = sorted({v.get("country") for v in new_snap.values() if v.get("country")})
            snap_time = now_rome()
            st.session_state["odds_memory"], st.session_state["snap_date_mem"] = new_snap, oggi
            st.session_state["snap_time_obj"] = snap_time
            with open(JSON_FILE, "w") as f: json.dump({"date": oggi, "timestamp": snap_time.isoformat(), "odds": new_snap}, f)
            st.rerun()

if st.button("🚀 AVVIA SCANSIONE MATCH"):
    diag = {"analyzed": 0, "total": 0, "trap_fav": 0, "errors": 0}
    with requests.Session() as s:
        all_raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
        fixtures = [f for f in all_raw if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"], blocked_user, forced_user)]
        results, pb = [], st.progress(0)
        status_text_scan = st.empty()
        for i, m in enumerate(fixtures):
            diag["analyzed"] += 1
            pb.progress((i+1)/len(fixtures))
            status_text_scan.text(f"Scansione {i+1}/{len(fixtures)}: {m['teams']['home']['name']}...")
            try:
                r_o = api_get(s, "odds", {"fixture": m["fixture"]["id"]})
                mk = extract_markets_pro(r_o)
                if not mk or mk["q1"] <= 0: continue
                res = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], st.session_state["odds_memory"], max_q_gold, 1.40, inv_margin)
                rating, det, d_html, d_text, status, is_gold, into_trap = res
                if status != "ok": diag[status] = diag.get(status, 0) + 1; continue
                
                # --- LOGICA REBOUND DRY 💧💧 ---
                if rating >= (min_rating - 15) and rating > 0:
                    h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
                    # 1. Verifica HT (Trend Statistico > 60%)
                    if get_stats(s, h_id, "ht") >= 0.6 and get_stats(s, a_id, "ht") >= 0.6:
                        rating += 20; det.append("HT")
                        
                        # 2. Solo se HT attivo, controlliamo la FAVORITA per il DRY
                        if use_sb_bonus:
                            fav_id = h_id if mk["q1"] < mk["q2"] else a_id
                            if get_stats(s, fav_id, "dry") >= 1.0:
                                rating = min(100, rating + 15); det.append("DRY 💧💧")
                
                if rating >= min_rating:
                    diag["total"] += 1
                    advice = ""
                    if is_gold:
                        advice = "🔥 TARGET: 0.5 HT (DRY REBOUND)" if "DRY" in det else "🔥 TARGET: 0.5 HT / 2.5 FT"
                    m_name = f"{m['teams']['home']['name']} - {m['teams']['away']['name']}{' *' if into_trap else ''}"
                    results.append({"Ora": m["fixture"]["date"][11:16], "Lega": f"{m['league']['name']} ({m['league']['country']})", "Match": m_name, "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}" if mk.get("o05ht", 0) > 0 else "N/D", "Rating": rating, "Info": f"[{'|'.join(det)}]", "Advice": advice, "Is_Gold": is_gold, "Drop_Inv": d_html, "Drop_Inv_Text": d_text, "Fixture_ID": m["fixture"]["id"]})
            except: diag["errors"] += 1
        st.session_state["scan_results"] = {"data": results, "diag": diag, "date": oggi}
        log_to_csv(results)

# ============================
# RENDERING & EXPORT
# ============================
if st.session_state["scan_results"]:
    res = st.session_state["scan_results"]
    st.markdown(f"<div class='diag-box'>📡 ANALIZZATI: {res['diag']['analyzed']} | ✅ MOSTRATI: {res['diag']['total']}</div>", unsafe_allow_html=True)
    if res["data"]:
        df_d = pd.DataFrame(res["data"]).sort_values("Ora")
        df_display = df_d[df_d["Is_Gold"] == True].copy() if only_gold_ui else df_d.copy()

        if not df_display.empty:
            df_s = df_display.copy()
            df_s["Match"] = df_s.apply(lambda r: f"<div class='match-cell'>{'👑 ' if r['Is_Gold'] else ''}{r['Match']} {r['Drop_Inv']}<span class='advice-tag'>{r['Advice']}</span></div>", axis=1)
            df_s["Info"] = df_s["Info"].apply(lambda x: f"<span class='details-inline'>{x}</span>")
            df_s["Rating"] = df_s["Rating"].apply(lambda x: f"<b>{x}</b>")
            to_show = df_s[["Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "Rating", "Info"]]
            
            def style_rows(row):
                idx = row.name
                r_val = df_display.loc[idx, "Rating"]
                info_val = df_display.loc[idx, "Info"]
                is_gold = df_display.loc[idx, "Is_Gold"]
                if r_val >= 85: return ['background-color: #1b4332; color: #ffffff !important; font-weight: bold;'] * len(row)
                elif is_gold or r_val >= 75 or (r_val >= 65 and "DRY" in info_val): return ['background-color: #2d6a4f; color: #ffffff !important; font-weight: bold;'] * len(row)
                return [''] * len(row)

            st.write(to_show.style.apply(style_rows, axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)
        

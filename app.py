import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import json
import os
from pathlib import Path
import base64

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

st.set_page_config(page_title="ARAB SNIPER V15.59 - GOLD MASTER", layout="wide")

# Session States
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []
if "only_gold_ui" not in st.session_state: st.session_state["only_gold_ui"] = False

# ============================
# CARICAMENTO SNAPSHOT ESISTENTE
# ============================
if not st.session_state["odds_memory"] and os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, "r") as f:
            js = json.load(f)
            if js.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = js.get("odds", {})
                st.session_state["snap_time_obj"] = datetime.fromisoformat(js["timestamp"])
    except: pass

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
            .match-cell { text-align: left !important; min-width: 220px; font-weight: 700; color: inherit !important; }
            .advice-tag { display: block; font-size: 0.65rem; color: #00e5ff; font-style: italic; margin-top: 2px; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API CORE
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
    return js

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), str(b.get("name") or "").lower()
            if bid == 1:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            if ("1st" in name or "1h" in name) and ("goals" in name or "over/under" in name):
                for x in b.get("values", []):
                    v_val = str(x.get("value") or "").lower().replace(" ", "")
                    if "over0.5" in v_val: data["o05ht"] = float(x.get("odd") or 0)
                    if "over1.5" in v_val: data["o15ht"] = float(x.get("odd") or 0)
            if bid == 71 or (("both" in name or "btts" in name) and ("1st" in name or "1h" in name)):
                for x in b.get("values", []):
                    if str(x.get("value") or "").lower() in ["yes", "si"]: data["gg_ht"] = float(x.get("odd") or 0)
    return data

# ============================
# LOGICA STATISTICA 
# ============================
team_stats_cache = {}
def get_comprehensive_stats(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 5, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}
        ht_hits, conceded_hits, goals_scored = 0, 0, []
        for f in fx:
            if ((f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0)) >= 1: ht_hits += 1
            is_home = (f["teams"]["home"]["id"] == tid)
            if (f["goals"]["away"] if is_home else f["goals"]["home"] or 0) > 0: conceded_hits += 1
            goals_scored.append(int((f["goals"]["home"] if is_home else f["goals"]["away"]) or 0))
        res = {"ht_ratio": ht_hits/5, "vulnerability": conceded_hits/5, "is_dry": (goals_scored[0]==0 and sum(1 for g in goals_scored if g>=1)>=4)}
        team_stats_cache[tid] = res
        return res
    except: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}

def is_allowed_league(league_name, league_country):
    name = str(league_name).lower()
    banned = ["women", "femminile", "u19", "u20", "u21", "u23", "primavera", "youth", "reserve", "friendly"]
    return not any(t in name for t in banned)

def calculate_rating(fid, q1, qx, q2, o25, o05ht, snap_data, max_q_gold, inv_margin):
    sc, det = 40, []
    is_gold = (1.40 <= min(q1, q2) <= max_q_gold) if q1 > 0 and q2 > 0 else False
    if str(fid) in snap_data:
        old = snap_data[str(fid)]
        old_fav, cur_fav = min(old.get("q1", 0), old.get("q2", 0)), min(q1, q2)
        if (old_fav - cur_fav) >= 0.15: sc += 40; det.append("Drop")
        if abs(q1-q2) >= inv_margin:
            fav_snap = "1" if old.get("q1",0) < old.get("q2",0) else "2"
            if (fav_snap == "1" and q2 < q1) or (fav_snap == "2" and q1 < q2): sc += 25; det.append("Inv")
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    return min(100, sc), det, is_gold

# ============================
# CORE ENGINE
# ============================
def execute_full_scan(session, fixtures, snap_mem, min_rating, max_q_gold, inv_margin):
    results, pb = [], st.progress(0)
    for i, m in enumerate(fixtures):
        pb.progress((i+1)/len(fixtures))
        try:
            mk = extract_markets_pro(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            rating, det, is_gold = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], snap_mem, max_q_gold, inv_margin)
            
            s_h, s_a = get_comprehensive_stats(session, m["teams"]["home"]["id"]), get_comprehensive_stats(session, m["teams"]["away"]["id"])
            q_fav = min(mk["q1"], mk["q2"])
            f_s = s_h if mk["q1"] < mk["q2"] else s_a
            d_s = s_a if mk["q1"] < mk["q2"] else s_h
            
            advice = "🔥 TARGET: 0.5 HT / 2.5 FT" if is_gold else ""
            if s_h["ht_ratio"] >= 0.6 and s_a["ht_ratio"] >= 0.6:
                rating += 20; det.append("HT")
                if f_s["vulnerability"] >= 0.8 and d_s["ht_ratio"] >= 0.6:
                    if 1.70 <= q_fav <= 2.20:
                        rating = min(100, rating + 25); det.append("🎯 GG-PT"); advice = "💎 DIAMOND: GG PT / O1.5 HT"
                    else: det.append("GG-PT-POT"); advice = "🔥 TARGET: GG PT"
            if f_s["is_dry"]: rating = min(100, rating + 15); det.append("DRY 💧")

            if rating >= min_rating:
                results.append({
                    "Ora": m["fixture"]["date"][11:16], "Lega": f"{m['league']['name']} ({m['league']['country']})",
                    "Country": m['league']['country'],
                    "Match_Disp_Raw": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                    "O2.5 Finale": f"{mk['o25']:.2f}", "O0.5 PT": f"{mk['o05ht']:.2f}",
                    "O1.5 PT": f"{mk['o15ht']:.2f}", "GG PT": f"{mk['gg_ht']:.2f}",
                    "Info": f"[{'|'.join(det)}]", "Rating": rating, "Is_Gold": is_gold, "Advice": advice, "Fixture_ID": str(m["fixture"]["id"])
                })
        except: continue
    return results

# ============================
# SIDEBAR UI (CON FILTRI E STATO)
# ============================
st.sidebar.header("👑 Configurazione Sniper")

# Indicatore Snapshot
if st.session_state["odds_memory"]:
    st.sidebar.success(f"✅ Snapshot Attivo: {st.session_state['snap_time_obj'].strftime('%H:%M')}")
else:
    st.sidebar.warning("⚠️ Nessun Snapshot Caricato")

min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
st.session_state["only_gold_ui"] = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=st.session_state["only_gold_ui"])
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)

# Filtro Campionati (Multi-select)
selected_countries = st.sidebar.multiselect("🌍 Filtra per Nazione", 
                                            options=sorted(list(set(st.session_state["found_countries"]))), 
                                            default=st.session_state["found_countries"])

oggi = now_rome().strftime("%Y-%m-%d")
col_b1, col_b2 = st.columns(2)

# ============================
# LOGICA BOTTONI
# ============================
if col_b1.button("📌 SNAPSHOT + SCAN"):
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"])]
        res = execute_full_scan(s, fixtures, {}, min_rating, max_q_gold, inv_margin)
        new_snap = {r["Fixture_ID"]: {"q1": float(r["1X2"].split("|")[0]), "q2": float(r["1X2"].split("|")[2])} for r in res}
        st.session_state["odds_memory"], st.session_state["snap_time_obj"] = new_snap, now_rome()
        st.session_state["scan_results"] = res
        st.session_state["found_countries"] = list(set([r["Country"] for r in res]))
        with open(JSON_FILE, "w") as f: json.dump({"date": oggi, "timestamp": now_rome().isoformat(), "odds": new_snap}, f)
        st.rerun()

if col_b2.button("🚀 AVVIA SOLO SCANNER"):
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"])]
        res = execute_full_scan(s, fixtures, st.session_state["odds_memory"], min_rating, max_q_gold, inv_margin)
        st.session_state["scan_results"] = res
        st.session_state["found_countries"] = list(set([r["Country"] for r in res]))
        st.rerun()

# ============================
# RENDERING TABELLA
# ============================
if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    # Applicazione Filtri (Sweet Spot + Nazione)
    if st.session_state["only_gold_ui"]: df = df[df["Is_Gold"]]
    if selected_countries: df = df[df["Country"].isin(selected_countries)]
    
    if not df.empty:
        df["Match Disponibili"] = df.apply(lambda r: f"<div class='match-cell'>{'💎 ' if 'DIAMOND' in r['Advice'] else '👑 ' if r['Is_Gold'] else ''}{r['Match_Disp_Raw']}<span class='advice-tag'>{r['Advice']}</span></div>", axis=1)
        df["Rating_Bold"] = df["Rating"].apply(lambda x: f"<b>{x}</b>")
        st.write(df[["Ora", "Lega", "Match Disponibili", "1X2", "O2.5 Finale", "O0.5 PT", "O1.5 PT", "GG PT", "Info", "Rating_Bold"]].style.apply(lambda row: ['background-color: #38003c; color: #00e5ff;' if 'GG-PT' in df.loc[row.name, 'Info'] else '' for _ in row], axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)
        
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.download_button("💾 CSV AUDITOR", df.to_csv(index=False).encode('utf-8'), "auditor.csv")
        c2.download_button("🌐 REPORT HTML", df.to_html().encode('utf-8'), "report.html")
        if os.path.exists(LOG_CSV): c3.download_button("🗂️ LOG STORICO", open(LOG_CSV,"rb").read(), "history.csv")

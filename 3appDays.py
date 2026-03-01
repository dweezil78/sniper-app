import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE V22.01 - ELITE SNIPER (ESTETICA RIPRISTINATA)
# ============================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "arab_sniper_database.json")
SNAP_FILE = str(BASE_DIR / "arab_snapshot_database.json")
CONFIG_FILE = str(BASE_DIR / "nazioni_config.json")

DEFAULT_EXCLUDED = [
    "Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda",
    "Macedonia", "Nigeria", "Ivory-Coast", "Oman", "El-Salvador",
    "Ethiopia", "Cameroon", "Jordan", "Algeria", "South-Africa",
    "Tanzania", "Montenegro", "UAE", "Guatemala", "Costa-Rica"
]

LEAGUE_BLACKLIST = ["u19", "u20", "youth", "women", "friendly", "carioca", "paulista", "mineiro"]

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception: ROME_TZ = None

def now_rome(): return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V22.01", layout="wide")

# ===== TARGET DATES (sempre disponibili per le funzioni) =====
target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

# ============================
# FASE 1: GESTIONE PERSISTENZA & SIDEBAR
# ============================
if "config" not in st.session_state:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f: st.session_state.config = json.load(f)
    else:
        st.session_state.config = {"excluded": DEFAULT_EXCLUDED}

if "available_countries" not in st.session_state: st.session_state.available_countries = []
if "odds_memory" not in st.session_state: st.session_state.odds_memory = {}
if "scan_results" not in st.session_state: st.session_state.scan_results = []

def save_config():
    with open(CONFIG_FILE, "w") as f: json.dump(st.session_state.config, f)

def load_db():
    today = now_rome().strftime("%Y-%m-%d")
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f).get("results", [])
                st.session_state.scan_results = [r for r in data if r["Data"] >= today]
        except: pass
    if os.path.exists(SNAP_FILE):
        try:
            with open(SNAP_FILE, "r") as f:
                snap_data = json.load(f)
                st.session_state.odds_memory = snap_data.get("odds", {})
                return snap_data.get("timestamp", "N/D")
        except: pass
    return None

last_snap_ts = load_db()

# ============================
# API CORE (PATCHED)
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params, retries=3):
    for i in range(retries):
        try:
            r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(2)
                continue
            return r.json()
        except:
            if i == retries - 1: return None
            time.sleep(1)
    return None

# ============================
# ANALISI STATISTICA
# ============================
team_stats_cache = {}

def get_team_performance(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
    fx = res.get("response", []) if res else []
    if len(fx) < 3: return None
    actual = len(fx)
    total_goals_ht, total_conceded_ft, o25_count, gg_count = 0, 0, 0, 0
    for f in fx:
        ht = f.get("score", {}).get("halftime", {})
        total_goals_ht += (ht.get("home") or 0) + (ht.get("away") or 0)
        goals_h, goals_a = f.get("goals", {}).get("home") or 0, f.get("goals", {}).get("away") or 0
        if (goals_h + goals_a) >= 3: o25_count += 1
        if goals_h > 0 and goals_a > 0: gg_count += 1
        is_h = f["teams"]["home"]["id"] == tid
        total_conceded_ft += goals_a if is_h else goals_h
    avg_ht = total_goals_ht / actual
    stats = {
        "avg_ht": avg_ht, "avg_vul": total_conceded_ft / actual,
        "o25_perc": o25_count / actual, "gg_perc": gg_count / actual, "is_elite": avg_ht >= 1.2
    }
    team_stats_cache[tid] = stats
    return stats

# ============================
# ESTRAZIONE MERCATI (PATCHED & MULTI-BOOK)
# ============================
def extract_elite_markets(session, fid):
    res = api_get(session, "odds", {"fixture": fid})
    if not res or not res.get("response"): return None
    mk = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "gght":0.0}
    
    # Ricerca aggressiva su più bookmaker
    for bm in res["response"][0].get("bookmakers", []):
        for b in bm.get("bets", []):
            name = b["name"].lower()
            if b["id"] == 1 and mk["q1"] == 0:
                for v in b["values"]:
                    if v["value"].lower() == "home": mk["q1"] = float(v["odd"])
                    if v["value"].lower() == "draw": mk["qx"] = float(v["odd"])
                    if v["value"].lower() == "away": mk["q2"] = float(v["odd"])
            if b["id"] == 5 and mk["o25"] == 0:
                for v in b["values"]:
                    if v["value"].lower() == "over 2.5": mk["o25"] = float(v["odd"])
            # Fallback O2.5 se ID 5 fallisce
            if "total" in name and "goals" in name and mk["o25"] == 0:
                for v in b["values"]:
                    if v["value"].lower() == "over 2.5": mk["o25"] = float(v["odd"])
            
            is_1h = "1st half" in name or "1st" in name or "first half" in name
            if is_1h:
                if "total" in name:
                    for v in b["values"]:
                        if v["value"].lower() == "over 0.5": mk["o05ht"] = float(v["odd"])
                if any(k in name for k in ["both", "gg", "btts", "goal/no goal"]):
                    # Logica anti-noise per BTTS 1H
                    if not any(noise in name for noise in ["exact", "correct", "first team", "last team"]):
                        for v in b["values"]:
                            if v["value"].lower() in ["yes", "si", "oui"]: mk["gght"] = float(v["odd"])
        if mk["q1"] > 0 and mk["o25"] > 0 and mk["o05ht"] > 0: break
    if (1.01 <= mk["q1"] <= 1.10) or (1.01 <= mk["q2"] <= 1.10) or (1.01 <= mk["o25"] <= 1.30): return "SKIP"
    return mk

# ============================
# CORE ENGINE
# ============================
def execute_elite_scan(session, fixtures, snap_mem, min_rating_ui):
    final_list, pb = [], st.progress(0)
    for i, f in enumerate(fixtures):
        pb.progress((i+1)/len(fixtures))
        country = f["league"]["country"]
        if country in st.session_state.config["excluded"]: continue
        if any(k in f["league"]["name"].lower() for k in LEAGUE_BLACKLIST): continue
        mk = extract_elite_markets(session, f["fixture"]["id"])
        if not mk or mk == "SKIP": continue
        s_h, s_a = get_team_performance(session, f["teams"]["home"]["id"]), get_team_performance(session, f["teams"]["away"]["id"])
        if not s_h or not s_a: continue
        if not ((s_h["avg_ht"] >= 0.7 and s_a["avg_ht"] >= 0.7) or (s_h["is_elite"] or s_a["is_elite"])): continue

        fav_odd = mk["q1"] if mk["q1"] < mk["q2"] else mk["q2"]
        f_stats = s_h if mk["q1"] < mk["q2"] else s_a
        gold_zone, o25_zone = (1.40 <= fav_odd <= 1.90), (1.50 <= mk["o25"] <= 2.20)
        fid_s, drop_val = str(f["fixture"]["id"]), 0.0
        if fid_s in snap_mem:
            old_q = float(snap_mem[fid_s].get("q1" if mk["q1"]<mk["q2"] else "q2", 0))
            drop_val = old_q - fav_odd

        tags = ["HT-OK"]
        if o25_zone: tags.append("O25-SS")
        if drop_val >= 0.15: tags.append(f"Drop {drop_val:.2f}")
        is_boost = (o25_zone and f_stats["avg_ht"] >= 0.8 and f_stats["avg_vul"] >= 1.0)
        if is_boost: tags.append("💣 O25-BOOST")
        is_gg_pt = (mk["gght"] >= 3.0 and s_h["avg_ht"] >= 0.7 and s_a["avg_ht"] >= 0.7)
        if is_gg_pt: tags.append("🎯 GG-PT")
        is_super_red = is_boost and (f_stats["o25_perc"] >= 0.70)
        
        rating = min(100, int(45 + (s_h["avg_ht"]+s_a["avg_ht"])*10 + (20 if is_boost else 0) + (15 if drop_val>=0.20 else 0)))
        if rating >= min_rating_ui:
            final_list.append({
                "Fixture_ID": f["fixture"]["id"], "Data": f["fixture"]["date"][:10], "Ora": f["fixture"]["date"][11:16],
                "Lega": f"{f['league']['name']} ({country})", "Match": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                "1X2": f"{mk['q1']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "HT_Avg": f"{s_h['avg_ht']:.1f}|{s_a['avg_ht']:.1f}",
                "Info": f"[{'|'.join(tags)}]", "Rating": rating, "Gold": "✅" if gold_zone else "❌",
                "Is_Super_Red": is_super_red, "Is_GGPT": is_gg_pt, "Is_Boost": is_boost, "Is_Gold": gold_zone, "Is_O25SS": o25_zone
            })
    return final_list

# ============================
# UI SIDEBAR
# ============================
st.sidebar.header("👑 Arab Sniper V22.01")
if last_snap_ts: st.sidebar.success(f"✅ SNAPSHOT: {last_snap_ts}")
else: st.sidebar.warning("⚠️ SNAPSHOT ASSENTE")

HORIZON = st.sidebar.selectbox("Orizzonte:", options=[1, 2, 3], index=0)
only_gold = st.sidebar.toggle("🎯 SOLO GOLD ZONE (1.40-1.90)")
only_o25 = st.sidebar.toggle("⚽ SOLO O25 SS (1.50-2.20)")
min_rating = st.sidebar.slider("Rating Minimo", 30, 95, 45)

with st.sidebar.expander("🌍 Gestione Nazioni"):
    to_ex = st.selectbox("Escludi Nazione:", ["--"] + sorted([c for c in st.session_state.available_countries if c not in st.session_state.config["excluded"]]))
    if to_ex != "--":
        st.session_state.config["excluded"].append(to_ex)
        save_config(); st.rerun()
    to_in = st.selectbox("Ripristina Nazione:", ["--"] + sorted(st.session_state.config["excluded"]))
    if to_in != "--":
        st.session_state.config["excluded"].remove(to_in)
        save_config(); st.rerun()

# ============================
# BOTTONI SCAN
# ============================
def run_full_scan(snap=False):
    with requests.Session() as s:
        target_date = target_dates[HORIZON-1]
        res = api_get(s, "fixtures", {"date": target_date, "timezone": "Europe/Rome"})
        if not res: return
        day_fx = [f for f in res.get("response", []) if f["fixture"]["status"]["short"] == "NS"]
        if snap:
            current_snap, pb_snap = {}, st.progress(0)
            for j, f in enumerate(day_fx):
                pb_snap.progress((j+1)/len(day_fx))
                m = extract_elite_markets(s, f["fixture"]["id"])
                if m and m != "SKIP": current_snap[str(f["fixture"]["id"])] = {"q1": m["q1"], "q2": m["q2"]}
            with open(SNAP_FILE, "w") as f: json.dump({"odds": current_snap, "timestamp": now_rome().strftime("%H:%M")}, f)
            st.session_state.odds_memory = current_snap
        new_res = execute_elite_scan(s, day_fx, st.session_state.odds_memory, min_rating)
        existing_ids = [r["Fixture_ID"] for r in st.session_state.scan_results]
        st.session_state.scan_results += [r for r in new_res if r["Fixture_ID"] not in existing_ids]
        with open(DB_FILE, "w") as f: json.dump({"results": st.session_state.scan_results}, f)
        st.rerun()

c1, c2 = st.columns(2)
if c1.button("📌 SNAP + SCAN"): run_full_scan(snap=True)
if c2.button("🚀 SCAN VELOCE"): run_full_scan(snap=False)

# ============================
# TABELLA E COLORI (RIPRISTINO ESTETICA)
# ============================
if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    view = df[df["Data"] == target_dates[HORIZON-1]]
    if not view.empty:
        if only_gold: view = view[view["Is_Gold"]]
        if only_o25: view = view[view["Is_O25SS"]]

        # Colonne da mostrare (Logica estetica 3appDays (8))
        cols_to_show = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "HT_Avg", "Info", "Rating", "Gold"]

        def color_logic(row):
            # Usiamo i flag nascosti per decidere i colori
            if row["Is_Super_Red"]: return ['background-color: #8b0000; color: white'] * len(row)
            if row["Is_GGPT"]: return ['background-color: #38003c; color: #00e5ff'] * len(row)
            if row["Is_Boost"]: return ['background-color: #003300; color: #00ff00'] * len(row)
            return ['color: #cccccc'] * len(row)

        # Applichiamo lo stile all'intero frame prima di visualizzarlo
        styled = view.sort_values("Rating", ascending=False).style.apply(color_logic, axis=1)
        
        # CSS per layout lineare e bloccato (da 3appDays (8))
        st.markdown("""
            <style>
                table { font-size: 13px; font-weight: 600; width: 100%; border-collapse: collapse; }
                th { background-color: #1a1c23; color: #00e5ff; padding: 10px; text-align: center; }
                td { padding: 8px; border: 1px solid #333; text-align: center; white-space: nowrap; }
                .stDownloadButton { margin-top: 10px; }
            </style>
        """, unsafe_allow_html=True)
        
        # Rendering HTML pulito con colonne selezionate
        st.write(styled.to_html(escape=False, index=False, columns=cols_to_show), unsafe_allow_html=True)
        
        st.markdown("---")
        c1, c2 = st.columns(2)
        c1.download_button("💾 CSV AUDITOR", df.to_csv(index=False).encode('utf-8'), "audit.csv")
        html_rep = f"<html><body style='background:#0e1117'>{styled.to_html(index=False, columns=cols_to_show)}</body></html>"
        c2.download_button("🌐 HTML REPORT", html_rep.encode('utf-8'), "report.html")

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ==========================================
# CONFIGURAZIONE ARAB SNIPER V22.04.10 - UI REFINED
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "arab_sniper_database.json")
SNAP_FILE = str(BASE_DIR / "arab_snapshot_database.json")
CONFIG_FILE = str(BASE_DIR / "nazioni_config.json")

DEFAULT_EXCLUDED = ["Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda", "Nigeria", "Oman", "Algeria", "UAE"]
LEAGUE_BLACKLIST = ["u19", "u20", "youth", "women", "friendly", "carioca", "paulista", "mineiro"]

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V22.04.10", layout="wide")

# --- Inizializzazione Session State ---
if "config" not in st.session_state:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f: st.session_state.config = json.load(f)
    else: st.session_state.config = {"excluded": DEFAULT_EXCLUDED}

if "team_stats_cache" not in st.session_state: st.session_state.team_stats_cache = {}
if "available_countries" not in st.session_state: st.session_state.available_countries = []
if "scan_results" not in st.session_state: st.session_state.scan_results = []
if "odds_memory" not in st.session_state: st.session_state.odds_memory = {}

def save_config():
    with open(CONFIG_FILE, "w") as f: json.dump(st.session_state.config, f)

def load_db():
    """Carica i risultati salvati e rimuove quelli vecchi (scalata data)"""
    today = now_rome().strftime("%Y-%m-%d")
    ts = None
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f).get("results", [])
                st.session_state.scan_results = [r for r in data if r.get("Data", "") >= today]
        except: pass
    if os.path.exists(SNAP_FILE):
        try:
            with open(SNAP_FILE, "r") as f:
                snap_data = json.load(f)
                st.session_state.odds_memory = snap_data.get("odds", {})
                ts = snap_data.get("timestamp", "N/D")
        except: pass
    return ts

last_snap_ts = load_db()

# ==========================================
# API CORE & ROBUST PARSING
# ==========================================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    try:
        r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=20)
        return r.json() if r.status_code == 200 else None
    except: return None

def _is_junk_market(name_lower: str) -> bool:
    junk = ["corner", "card", "booking", "yellow", "red", "offside", "throw", "foul", "shot", "goal kick"]
    return any(j in name_lower for j in junk)

def _is_team_total(name_lower: str) -> bool:
    if "team total" in name_lower: return True
    if "total" in name_lower and ("home" in name_lower or "away" in name_lower): return True
    return False

def extract_elite_markets(session, fid):
    res = api_get(session, "odds", {"fixture": fid})
    if not res or not res.get("response"): return None
    mk = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "gght": 0.0}
    for bm in res["response"][0].get("bookmakers", []):
        for b in bm.get("bets", []):
            n = (b.get("name") or "").lower()
            if not n: continue
            if b.get("id") == 1 and mk["q1"] == 0:
                for v in b.get("values", []):
                    vl = (v.get("value") or "").lower()
                    if vl == "home": mk["q1"] = float(v["odd"])
                    elif vl == "draw": mk["qx"] = float(v["odd"])
                    elif vl == "away": mk["q2"] = float(v["odd"])
            if b.get("id") == 5 and mk["o25"] == 0:
                if _is_junk_market(n): continue
                for v in b.get("values", []):
                    if (v.get("value") or "").lower() == "over 2.5": mk["o25"] = float(v["odd"])
            is_1h = any(k in n for k in ["1st half", "first half", "1h", "1st", "half time", "halftime"])
            if not is_1h or _is_junk_market(n): continue
            if mk["o05ht"] == 0 and any(k in n for k in ["total", "over/under", "ou"]):
                if _is_team_total(n): continue
                for v in b.get("values", []):
                    if (v.get("value") or "").lower() == "over 0.5": mk["o05ht"] = float(v["odd"])
            if mk["gght"] == 0 and any(k in n for k in ["both teams to score", "btts", "gg", "both"]):
                if any(x in n for x in ["exact", "correct"]): continue
                for v in b.get("values", []):
                    if (v.get("value") or "").lower() in ["yes", "si"]: mk["gght"] = float(v["odd"])
        if mk["q1"] > 0 and mk["o25"] > 0 and (mk["o05ht"] > 0 or mk["gght"] > 0): break
    if (1.01 <= mk["q1"] <= 1.10) or (1.01 <= mk["q2"] <= 1.10) or (1.01 <= mk["o25"] <= 1.30): return "SKIP"
    return mk

def get_team_performance(session, tid):
    if str(tid) in st.session_state.team_stats_cache: return st.session_state.team_stats_cache[str(tid)]
    res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
    fx = res.get("response", []) if res else []
    if not fx: return None
    act = len(fx)
    tht, gf, gs = 0, 0, 0
    for f in fx:
        ht = f.get("score", {}).get("halftime", {})
        tht += (ht.get("home") or 0) + (ht.get("away") or 0)
        is_home = f["teams"]["home"]["id"] == tid
        gf += (f["goals"]["home"] or 0) if is_home else (f["goals"]["away"] or 0)
        gs += (f["goals"]["away"] or 0) if is_home else (f["goals"]["home"] or 0)
    stats = {"avg_ht": tht/act, "avg_total": (gf+gs)/act}
    st.session_state.team_stats_cache[str(tid)] = stats
    return stats

def run_full_scan(snap=False):
    target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    with st.spinner("🚀 Arab Sniper: Analisi mercati e Gold Zone..."):
        with requests.Session() as s:
            target_date = target_dates[HORIZON - 1]
            res = api_get(s, "fixtures", {"date": target_date, "timezone": "Europe/Rome"})
            if not res: return
            day_fx = [f for f in res.get("response", []) if f["fixture"]["status"]["short"] == "NS"]
            st.session_state.available_countries = sorted(list(set(st.session_state.available_countries) | {fx["league"]["country"] for fx in day_fx}))
            
            if snap:
                csnap = {}
                for f in day_fx:
                    m = extract_elite_markets(s, f["fixture"]["id"])
                    if m and m != "SKIP": csnap[str(f["fixture"]["id"])] = {"q1": m["q1"], "q2": m["q2"]}
                st.session_state.odds_memory = csnap
                with open(SNAP_FILE, "w") as f: json.dump({"odds": csnap, "timestamp": now_rome().strftime("%H:%M")}, f)

            final_list = []
            pb = st.progress(0)
            for i, f in enumerate(day_fx):
                pb.progress((i+1)/len(day_fx))
                cnt = f["league"]["country"]
                if cnt in st.session_state.config["excluded"]: continue
                mk = extract_elite_markets(s, f["fixture"]["id"])
                if not mk or mk == "SKIP": continue
                s_h, s_a = get_team_performance(s, f["teams"]["home"]["id"]), get_team_performance(s, f["teams"]["away"]["id"])
                if not s_h or not s_a: continue

                fav = min(mk["q1"], mk["q2"])
                is_gold = (1.40 <= fav <= 1.90)
                tags = ["HT-OK"]
                h_p, h_o, h_g = False, False, False
                if (fav < 1.75) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0): tags.append("🐟O"); h_p = True
                if (2.0 <= mk["q1"] <= 3.5) and (2.0 <= mk["q2"] <= 3.5) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0): tags.append("🐟G"); h_p = True
                if (s_h["avg_total"] >= 2.0 and s_a["avg_total"] >= 2.0):
                    if mk["o25"] > 1.80 and mk["o05ht"] > 1.30: tags.append("⚽"); h_o = True
                    elif mk["o25"] <= 1.80 and mk["o05ht"] <= 1.30: tags.append("🚀"); h_o = True
                if (s_h["avg_total"] >= 1.2 and s_a["avg_total"] >= 1.2): tags.append("🎯PT"); h_g = True
                if h_p and h_o and h_g: tags.insert(0, "⚽⭐")

                final_list.append({
                    "Ora": f["fixture"]["date"][11:16],
                    "Lega": f"{f['league']['name']} ({cnt})",
                    "Match": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                    "O2.5": f"{mk['o25']:.2f}", "O0.5H": f"{mk['o05ht']:.2f}", "GGH": f"{mk['gght']:.2f}",
                    "HT": f"{s_h['avg_ht']:.1f}|{s_a['avg_ht']:.1f}",
                    "Info": " ".join(tags), "Gold": "✅" if is_gold else "❌", "Data": f["fixture"]["date"][:10],
                    "Fixture_ID": f["fixture"]["id"]
                })
            
            eids = [r["Fixture_ID"] for r in st.session_state.scan_results]
            st.session_state.scan_results += [r for r in final_list if r["Fixture_ID"] not in eids]
            with open(DB_FILE, "w") as f: json.dump({"results": st.session_state.scan_results}, f)
            st.rerun()

# ==========================================
# UI SIDEBAR
# ==========================================
st.sidebar.header("👑 Arab Sniper V22.04.10")
HORIZON = st.sidebar.selectbox("Orizzonte Temporale:", options=[1, 2, 3], index=0)
target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

all_discovered = sorted(list(set(st.session_state.get("available_countries", []))))
if st.session_state.scan_results:
    historical_cnt = {r["Lega"].split('(')[-1].replace(')', '') for r in st.session_state.scan_results}
    all_discovered = sorted(list(set(all_discovered) | historical_cnt))

if all_discovered:
    new_ex = st.sidebar.multiselect("Escludi Nazioni:", options=all_discovered, default=[c for c in st.session_state.config.get("excluded", []) if c in all_discovered])
    if st.sidebar.button("💾 SALVA CONFIG"):
        st.session_state.config["excluded"] = new_ex
        save_config(); st.rerun()

if last_snap_ts: st.sidebar.success(f"✅ SNAPSHOT: {last_snap_ts}")
else: st.sidebar.warning("⚠️ SNAPSHOT ASSENTE")

# ==========================================
# MAIN UI & TABLE (FIXED HEADER & SCROLL)
# ==========================================
c1, c2 = st.columns(2)
if c1.button("📌 SNAP + SCAN"): run_full_scan(snap=True)
if c2.button("🚀 SCAN VELOCE"): run_full_scan(snap=False)

if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    view = df[df["Data"] == target_dates[HORIZON - 1]].drop(columns=["Data", "Fixture_ID"])
    
    if not view.empty:
        st.markdown("""
            <style>
                .main-container { width: 100%; max-height: 800px; overflow: auto; border: 1px solid #444; border-radius: 8px; background-color: #0e1117; }
                .mobile-table { width: 100%; min-width: 1000px; border-collapse: separate; border-spacing: 0; font-family: sans-serif; font-size: 11px; }
                .mobile-table th { 
                    position: sticky; top: 0; 
                    background: #1a1c23; color: #00e5ff; 
                    z-index: 10; padding: 12px 5px; 
                    border-bottom: 2px solid #333; border-right: 1px solid #333; 
                }
                .mobile-table td { padding: 8px 5px; border-bottom: 1px solid #333; border-right: 1px solid #333; text-align: center; white-space: nowrap; }
                .row-dorato { background-color: #FFD700 !important; color: black !important; font-weight: bold; }
                .row-boost { background-color: #FF0000 !important; color: white !important; font-weight: bold; }
                .row-ggpt { background-color: #0000FF !important; color: white !important; font-weight: bold; }
                .row-std { background-color: white !important; color: black !important; }
            </style>
        """, unsafe_allow_html=True)

        def get_row_class(info):
            if "⚽⭐" in info: return "row-dorato"
            if "🚀" in info: return "row-boost"
            if "🎯PT" in info: return "row-ggpt"
            return "row-std"

        html = '<div class="main-container"><table class="mobile-table"><thead><tr>'
        html += ''.join(f'<th>{c}</th>' for c in view.columns) + '</tr></thead><tbody>'
        for _, row in view.iterrows():
            cls = get_row_class(row["Info"])
            html += f'<tr class="{cls}">' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>'
        html += '</tbody></table></div>'
        
        st.markdown(html, unsafe_allow_html=True)
        st.markdown("---")
        d1, d2 = st.columns(2)
        d1.download_button("💾 CSV", view.to_csv(index=False).encode("utf-8"), f"arab_{target_dates[HORIZON-1]}.csv")
        d2.download_button("🌐 HTML", html.encode("utf-8"), f"arab_{target_dates[HORIZON-1]}.html")
else:
    st.info("Esegui uno scan.")

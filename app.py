import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ==========================================
# CONFIGURAZIONE ARAB SNIPER V22.04.18 - ROBUSTNESS & AUDIT FIX
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

st.set_page_config(page_title="ARAB SNIPER V22.04.18", layout="wide")

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

API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    try:
        r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=20)
        return r.json() if r.status_code == 200 else None
    except: return None

# ==========================================
# UTILITY DI PARSING ROBUSTO
# ==========================================
def _contains_ht(text):
    t = str(text or "").lower()
    return any(k in t for k in ["1st half", "first half", "1h", "ht", "half time", "halftime", "1° tempo"])

def _contains_btts(text):
    t = str(text or "").lower()
    return any(k in t for k in ["both teams", "btts", "gg", "to score", "gol/gol", "entrambe segnano"])

def _is_yes(text):
    t = str(text or "").strip().lower()
    return t in ["yes", "si", "sì", "y", "1"]

def safe_float(val):
    try:
        if val is None: return 0.0
        return float(str(val).replace(",", "."))
    except:
        return 0.0

def extract_elite_markets(session, fid):
    # PROBLEMA 2 FIX: fid forzato a int
    res = api_get(session, "odds", {"fixture": int(fid)})
    if not res or not res.get("response"): return None
    
    mk = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "gght": 0.0}
    
    for bm in res["response"][0].get("bookmakers", []):
        for b in bm.get("bets", []):
            name = str(b.get("name", "")).lower()
            bid = b.get("id")
            
            # 1X2 FT - MIGLIORAMENTO B: Prendi la quota migliore
            if bid == 1:
                for v in b.get("values", []):
                    vl = str(v.get("value", "")).lower()
                    odd = safe_float(v.get("odd"))
                    if "home" in vl: mk["q1"] = max(mk["q1"], odd)
                    elif "draw" in vl: mk["qx"] = max(mk["qx"], odd)
                    elif "away" in vl: mk["q2"] = max(mk["q2"], odd)
            
            # OVER 2.5 FT
            if bid == 5:
                if any(j in name for j in ["corner", "card", "booking"]): continue
                for v in b.get("values", []):
                    txt = str(v.get("value", "")).lower().replace(",", ".")
                    if "over" in txt and "2.5" in txt:
                        mk["o25"] = max(mk["o25"], safe_float(v.get("odd")))
            
            # OVER 0.5 HT - MIGLIORAMENTO A: Match numerico robusto
            if _contains_ht(name) and any(k in name for k in ["total", "over/under", "ou", "goals"]):
                if "team" in name: continue
                for v in b.get("values", []):
                    txt = str(v.get("value", "")).lower().replace(",", ".")
                    if "over" in txt and "0.5" in txt:
                        mk["o05ht"] = max(mk["o05ht"], safe_float(v.get("odd")))

            # GGH / BTTS 1H (Parsing Universale)
            if _contains_btts(name):
                if any(x in name for x in ["exact", "correct", "score"]): continue
                is_name_ht = _contains_ht(name)
                for v in b.get("values", []):
                    val_txt = str(v.get("value", "")).lower()
                    if _is_yes(val_txt) and (is_name_ht or _contains_ht(val_txt) or bid in [40, 71]):
                        mk["gght"] = max(mk["gght"], safe_float(v.get("odd")))
                        break
                    
        if all(v > 0 for v in mk.values()): break
            
    if (1.01 <= mk["q1"] <= 1.10) or (1.01 <= mk["q2"] <= 1.10) or (1.01 <= mk["o25"] <= 1.30):
        return "SKIP"
    return mk

# ==========================================
# ENGINE STATS & SCAN
# ==========================================
def get_team_performance(session, tid):
    if str(tid) in st.session_state.team_stats_cache: return st.session_state.team_stats_cache[str(tid)]
    res = api_get(session, "fixtures", {"team": int(tid), "last": 8, "status": "FT"})
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
    with st.spinner("🚀 Arab Sniper: Analisi Robustezza V18..."):
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
                
                fid = int(f["fixture"]["id"])
                mk = extract_elite_markets(s, fid)
                if not mk or mk == "SKIP" or mk["q1"] == 0: continue
                
                s_h, s_a = get_team_performance(s, f["teams"]["home"]["id"]), get_team_performance(s, f["teams"]["away"]["id"])
                if not s_h or not s_a: continue

                fav = min(mk["q1"], mk["q2"])
                is_gold_zone = (1.40 <= fav <= 1.90)
                tags = ["HT-OK"]
                
                if str(fid) in st.session_state.odds_memory:
                    old_data = st.session_state.odds_memory[str(fid)]
                    old_q = old_data["q1"] if mk["q1"] < mk["q2"] else old_data["q2"]
                    if old_q > fav:
                        diff = old_q - fav
                        if diff >= 0.05: tags.append(f"📉-{diff:.2f}")

                # LOGICA SEGNALI
                h_p = (fav < 1.75) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0)
                if h_p: tags.append("🐟O")
                
                h_g_pesce = (2.0 <= mk["q1"] <= 3.5) and (2.0 <= mk["q2"] <= 3.5) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0)
                if h_g_pesce: tags.append("🐟G")
                
                h_o = (s_h["avg_total"] >= 2.0 and s_a["avg_total"] >= 2.0)
                if h_o:
                    if mk["o25"] > 1.80 and mk["o05ht"] > 1.30: tags.append("⚽")
                    elif mk["o25"] <= 1.80 and mk["o05ht"] <= 1.30: tags.append("🚀")
                
                h_pt_gg = (s_h["avg_total"] >= 1.5 and s_a["avg_total"] >= 1.5)
                if h_pt_gg: tags.append("🎯PT")
                
                if (h_p or h_g_pesce) and h_o and h_pt_gg and s_h["avg_ht"] >= 0.8 and s_a["avg_ht"] >= 0.8:
                    tags.insert(0, "⚽⭐")

                # PROBLEMA 3 FIX: Salvataggio GGH_RAW per Audit
                display_gght = f"{mk['gght']:.2f}" if (s_h["avg_ht"] >= 0.9 and s_a["avg_ht"] >= 0.9) else "0.00"

                final_list.append({
                    "Ora": f["fixture"]["date"][11:16],
                    "Lega": f"{f['league']['name']} ({cnt})",
                    "Match": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                    "Gold": "✅" if is_gold_zone else "❌",
                    "1X2": f"{mk['q1']:.1f}|{mk['qx']:.1f}|{mk['q2']:.1f}",
                    "O2.5": f"{mk['o25']:.2f}", 
                    "O0.5H": f"{mk['o05ht']:.2f}", 
                    "GGH": display_gght,
                    "GGH_RAW": f"{mk['gght']:.2f}", # Per l'Auditor
                    "HT": f"{s_h['avg_ht']:.1f}|{s_a['avg_ht']:.1f}",
                    "Info": " ".join(tags), "Data": f["fixture"]["date"][:10],
                    "Fixture_ID": fid
                })
            
            current_db = {str(r["Fixture_ID"]): r for r in st.session_state.scan_results}
            for r in final_list:
                current_db[str(r["Fixture_ID"])] = r
            
            st.session_state.scan_results = list(current_db.values())
            with open(DB_FILE, "w") as f: json.dump({"results": st.session_state.scan_results}, f)
            st.rerun()

# --- UI ---
st.sidebar.header("👑 Arab Sniper V22.04.18")
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

c1, c2 = st.columns(2)
if c1.button("📌 SNAP + SCAN"): run_full_scan(snap=True)
if c2.button("🚀 SCAN VELOCE"): run_full_scan(snap=False)

if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    view_raw = df[df["Data"] == target_dates[HORIZON - 1]]
    
    # Rimuoviamo colonne tecniche per la visualizzazione pulita
    view = view_raw.drop(columns=["Data", "Fixture_ID", "GGH_RAW"]) if not view_raw.empty else view_raw
    
    if not view.empty:
        st.markdown("""
            <style>
                .main-container { width: 100%; max-height: 800px; overflow: auto; border: 1px solid #444; border-radius: 8px; background-color: #0e1117; }
                .mobile-table { width: 100%; min-width: 1000px; border-collapse: separate; border-spacing: 0; font-family: sans-serif; font-size: 11px; }
                .mobile-table th { position: sticky; top: 0; background: #1a1c23; color: #00e5ff; z-index: 10; padding: 12px 5px; border-bottom: 2px solid #333; border-right: 1px solid #333; }
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
        # Il CSV scaricato conterrà la colonna GGH_RAW per l'Auditor
        d1.download_button("💾 CSV (FULL DATA)", df.to_csv(index=False).encode("utf-8"), f"arab_full_{target_dates[HORIZON-1]}.csv")
        d2.download_button("🌐 HTML", html.encode("utf-8"), f"arab_view_{target_dates[HORIZON-1]}.html")
else:
    st.info("Esegui uno scan.")

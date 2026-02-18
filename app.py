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

st.set_page_config(page_title="ARAB SNIPER V15.60 - SNIPER 1-1 PT", layout="wide")

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "only_gold_ui" not in st.session_state: st.session_state["only_gold_ui"] = False

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
            .match-cell { text-align: left !important; min-width: 220px; font-weight: 700; color: inherit !important; }
            .advice-tag { display: block; font-size: 0.65rem; color: #00e5ff; font-style: italic; margin-top: 2px; }
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; border: 1px solid #00e5ff; }
            .target-11 { background-color: #ff4b4b !important; color: white !important; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API HELPERS
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
    return js

# ============================
# ANALISI STATS PT AVANZATA
# ============================
pt_adv_cache = {}

def get_pt_advanced_stats(session, tid):
    if tid in pt_adv_cache: return pt_adv_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 5, "status": "FT"})
        fx = rx.get("response", [])
        if len(fx) < 5: return None
        
        stats = {
            "scored_pt": 0, "conceded_pt": 0, "total_goals_pt": 0,
            "scored_pt_count": 0, "conceded_pt_count": 0,
            "history_pt": [], "always_closed": True
        }
        
        for f in fx:
            is_home = (f["teams"]["home"]["id"] == tid)
            h_g = int(f["score"]["halftime"]["home"] or 0)
            a_g = int(f["score"]["halftime"]["away"] or 0)
            
            s_pt = h_g if is_home else a_g
            c_pt = a_g if is_home else h_g
            
            stats["scored_pt"] += s_pt
            stats["conceded_pt"] += c_pt
            stats["total_goals_pt"] += (h_g + a_g)
            if s_pt > 0: stats["scored_pt_count"] += 1
            if c_pt > 0: stats["conceded_pt_count"] += 1
            
            stats["history_pt"].append(h_g + a_g)
            # Verifica "PT sempre chiuso" (0-0 o 1-0)
            if not ((h_g == 0 and a_g == 0) or (h_g + a_g == 1)):
                stats["always_closed"] = False
                
        # Scarta se 3+ consecutivi a 0
        stats["streak_0"] = "000" in "".join([str(x) for x in stats["history_pt"]])
        pt_adv_cache[tid] = stats
        return stats
    except: return None

# ============================
# PARSING & RATING
# ============================
def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), str(b.get("name") or "").lower()
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            is_fh = any(x in name for x in ["1st", "first", "1h", "half"])
            if is_fh and ("goals" in name or "over/under" in name):
                for x in b.get("values", []):
                    v_val = str(x.get("value") or "").lower().replace(" ", "")
                    if "over0.5" in v_val and data["o05ht"] == 0: data["o05ht"] = float(x.get("odd") or 0)
                    if "over1.5" in v_val and data["o15ht"] == 0: data["o15ht"] = float(x.get("odd") or 0)
            if bid == 71 or (("both" in name or "btts" in name) and is_fh):
                for x in b.get("values", []):
                    if str(x.get("value") or "").lower() in ["yes", "si", "oui"]:
                        if data["gg_ht"] == 0: data["gg_ht"] = float(x.get("odd") or 0)
        if data["q1"] > 0 and data["gg_ht"] > 0 and data["o15ht"] > 0: break
    return data

def check_11_pt_filters(mk, s_h, s_a, ht_q_tag):
    """Implementa la COMBO OPERATIVA FINALE 1-1 PT"""
    if not ht_q_tag: return False
    
    q_min = min(mk["q1"], mk["q2"])
    q_max = max(mk["q1"], mk["q2"])
    
    # Filtri Quote
    if not (q_min >= 1.45 and q_max <= 6.50): return False
    if not (1.45 <= mk["q1"] <= 2.90 or 1.45 <= mk["q2"] <= 2.90): return False # Bilanciamento
    if mk["o25"] < 1.55: return False
    
    # Instabilità Difensiva (Scarta se CS PT >= 60% o 0 gol subiti)
    if (s_h["conceded_pt_count"] <= 2) or (s_a["conceded_pt_count"] <= 2): return False
    
    # Reciprocità Offensiva
    h_segna_pct = s_h["scored_pt_count"] / 5
    a_segna_pct = s_a["scored_pt_count"] / 5
    if not ((h_segna_pct >= 0.6 and a_segna_pct >= 0.4) or (a_segna_pct >= 0.6 and h_segna_pct >= 0.4)): return False
    
    # Avvio Attivo (Media Combinata)
    avg_comb = (s_h["total_goals_pt"] + s_a["total_goals_pt"]) / 10
    if avg_comb < 0.9: return False
    
    # No Estremi
    if s_h["streak_0"] or s_a["streak_0"]: return False
    if s_h["always_closed"] or s_a["always_closed"]: return False
    
    return True

# ============================
# CORE SCANNER
# ============================
def execute_full_scan(session, fixtures, snap_mem, min_rating, max_q_gold):
    results, pb = [], st.progress(0)
    status_txt = st.empty()
    for i, m in enumerate(fixtures):
        pb.progress((i+1)/len(fixtures))
        status_txt.text(f"Scanning {i+1}/{len(fixtures)}...")
        try:
            mk = extract_markets_pro(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            
            # Stats Avanzate
            s_h = get_pt_advanced_stats(session, m["teams"]["home"]["id"])
            s_a = get_pt_advanced_stats(session, m["teams"]["away"]["id"])
            if not s_h or not s_a: continue
            
            # Rating Base
            ht_q_tag = (1.30 <= mk["o05ht"] <= 1.50)
            is_11_target = check_11_pt_filters(mk, s_h, s_a, ht_q_tag)
            
            rating = 40
            det = []
            if ht_q_tag: det.append("HT-Q")
            if is_11_target: rating += 30; det.append("SNIPER 1-1")
            
            if rating >= min_rating:
                results.append({
                    "Ora": m["fixture"]["date"][11:16],
                    "Lega": f"{m['league']['name']} ({m['league']['country']})",
                    "Match_Raw": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                    "O2.5 Finale": f"{mk['o25']:.2f}",
                    "O0.5 PT": f"{mk['o05ht']:.2f}",
                    "O1.5 PT": f"{mk['o15ht']:.2f}",
                    "GG PT": f"{mk['gg_ht']:.2f}",
                    "Info": f"[{'|'.join(det)}]",
                    "Rating": rating, "Is_Gold": (1.45 <= min(mk["q1"], mk["q2"]) <= max_q_gold),
                    "Is_11": is_11_target, "Advice": "🎯 TARGET 1-1 PT" if is_11_target else ""
                })
        except: continue
    return results

# ============================
# UI & RENDERING
# ============================
st.sidebar.header("👑 Configurazione 1-1 PT")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 40)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
st.session_state["only_gold_ui"] = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=st.session_state["only_gold_ui"])

if st.button("🚀 AVVIA SCANNER 1-1 PT"):
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": now_rome().strftime("%Y-%m-%d"), "timezone": "Europe/Rome"})
        st.session_state["scan_results"] = execute_full_scan(s, data.get("response", []), {}, min_rating, max_q_gold)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    df = df[df["Is_Gold"]] if st.session_state["only_gold_ui"] else df
    
    if not df.empty:
        df["Match Disponibili"] = df.apply(lambda r: f"<div class='match-cell'>{'👑 ' if r['Is_Gold'] else ''}{r['Match_Raw']}<span class='advice-tag'>{r['Advice']}</span></div>", axis=1)
        
        cols = ["Ora", "Lega", "Match Disponibili", "1X2", "O2.5 Finale", "O0.5 PT", "O1.5 PT", "GG PT", "Info", "Rating"]
        
        def highlight_target(row):
            styles = [''] * len(row)
            if row["Is_11"]:
                # Coloriamo rosso O1.5 PT (indice 6) e GG PT (indice 7)
                styles[6] = 'background-color: #ff4b4b; color: white;'
                styles[7] = 'background-color: #ff4b4b; color: white;'
            return styles

        st.write(df[cols].style.apply(highlight_target, axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)

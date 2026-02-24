import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import json
import os
from pathlib import Path

# ============================
# CONFIGURAZIONE PATH
# ============================
BASE_DIR = Path(__file__).resolve().parent
JSON_FILE = str(BASE_DIR / "arab_snapshot.json")
NAZIONI_FILE = str(BASE_DIR / "nazioni_config.json")

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V16.50 - STABILITY", layout="wide")

# ============================
# API CORE (Spostata in alto per evitare NameError)
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
# INITIALIZATION & RECOVERY (Fix #1: NameError risolto)
# ============================
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "available_countries" not in st.session_state: st.session_state["available_countries"] = []

def load_excluded():
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                return list(json.load(f).get("excluded", []))
        except: return []
    return []

if "excluded" not in st.session_state:
    st.session_state["excluded"] = load_excluded()

# Recupero paesi del giorno (Ora api_get è definita)
if not st.session_state["available_countries"]:
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": now_rome().strftime("%Y-%m-%d"), "timezone": "Europe/Rome"})
            st.session_state["available_countries"] = sorted(list(set(f["league"]["country"] for f in data.get("response", []))))
    except: pass

# Recovery Snapshot
if not st.session_state["odds_memory"] and os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, "r") as f:
            saved = json.load(f)
            if saved.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = saved.get("odds", {})
    except: pass

# ============================
# LOGICA MERCATI & STATS
# ============================
team_stats_cache = {}

def get_stats(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 5, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}
        ht_h, conc_h, goals = 0, 0, []
        for f in fx:
            if ((f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0)) >= 1: ht_h += 1
            is_home = (f["teams"]["home"]["id"] == tid)
            conc_val = (f["goals"]["away"] if is_home else f["goals"]["home"]) or 0
            if conc_val > 0: conc_h += 1
            goals.append(int((f["goals"]["home"] if is_home else f["goals"]["away"]) or 0))
        res = {"ht_ratio": ht_h/5, "vulnerability": conc_h/5, "is_dry": (len(goals)>0 and goals[0]==0 and sum(1 for g in goals if g>=1)>=4)}
        team_stats_cache[tid] = res
        return res
    except: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}

def extract_markets(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    
    def pick_o(values, key):
        for x in values or []:
            v = str(x.get("value") or "").lower().replace(" ", "").replace(",", ".")
            if v.startswith(key):
                try: return float(x.get("odd") or 0)
                except: return 0.0
        return 0.0

    # FIX #3: Compromesso di scansione (max 4 bookmaker per trovare il Gate)
    for ibm, bm in enumerate(resp[0].get("bookmakers", [])):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), str(b.get("name") or "").lower()
            
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            
            if bid == 5 and data["o25"] == 0:
                for x in b.get("values", []) or []:
                    val = str(x.get("value") or "").lower().replace(" ", "").replace(",", ".")
                    if val.startswith("over2.5"):
                        try: data["o25"] = float(x.get("odd") or 0); break
                        except: pass
            
            if bid == 71 and data["gg_ht"] == 0:
                for x in b.get("values", []):
                    if str(x.get("value") or "").strip().lower() in ["yes","si","oui"]:
                        try: data["gg_ht"] = float(x.get("odd") or 0); break
                        except: pass
            
            if ("1st" in name or "first half" in name):
                if ("over/under" in name or "total" in name):
                    if data["o05ht"] == 0: data["o05ht"] = pick_o(b.get("values", []), "over0.5")
                    if data["o15ht"] == 0: data["o15ht"] = pick_o(b.get("values", []), "over1.5")
                # FIX #4: Fallback GGHT robusto
                if data["gg_ht"] == 0 and ("both" in name or "gg" in name):
                    for x in b.get("values", []):
                        if str(x.get("value") or "").strip().lower() in ["yes","si","oui"]:
                            try: data["gg_ht"] = float(x.get("odd") or 0); break
                            except: pass

        have_core = (data["q1"] > 0 and data["qx"] > 0 and data["q2"] > 0)
        have_over_pack = (data["o25"] > 0 and data["o05ht"] > 0)
        have_gate = (data["o15ht"] > 0 and data["gg_ht"] > 0)

        if have_core and have_over_pack and have_gate: break
        if have_core and have_over_pack and ibm >= 3: break # Max 4 bookies
            
    return data

# ============================
# CORE ENGINE: ANALYTICAL (V16.50)
# ============================
def execute_scan(session, fixtures, snap_mem, excluded, min_rating_val):
    results, pb = [], st.progress(0)
    filtered = [f for f in fixtures if f["league"]["country"] not in excluded]
    if not filtered:
        pb.progress(1.0); return []

    for i, m in enumerate(filtered):
        pb.progress((i+1)/len(filtered))
        try:
            mk = extract_markets(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            
            fid_s = str(m["fixture"]["id"])
            s_h, s_a = get_stats(session, m["teams"]["home"]["id"]), get_stats(session, m["teams"]["away"]["id"])
            fav_side = "q1" if mk["q1"] < mk["q2"] else "q2"
            f_s, d_s = (s_h, s_a) if fav_side == "q1" else (s_a, s_h)

            HT_OK = 1 if (s_h["ht_ratio"] >= 0.6 and s_a["ht_ratio"] >= 0.6) else 0
            O25_OK = 1 if (1.70 <= mk["o25"] < 2.00) else 0
            O05_OK = 1 if (1.30 <= mk["o05ht"] <= 1.55) else 0
            GATE_11 = 1 if ((2.20 <= mk["o15ht"] <= 2.80) and (4.20 <= mk["gg_ht"] <= 5.50) and HT_OK) else 0
            
            HAS_DROP = 0
            if fid_s in snap_mem:
                sd = snap_mem[fid_s]
                if (sd.get("fav_odd", 0) - mk[sd.get("fav_side", "q1")]) >= 0.15: HAS_DROP = 1

            SIG_GG_PT = 1 if (GATE_11 and f_s["vulnerability"] >= 0.8 and d_s["ht_ratio"] >= 0.6) else 0
            avg_vul = (s_h["vulnerability"] + s_a["vulnerability"]) / 2
            SIG_O25_BOOST = 1 if (HT_OK and (1.70 <= mk["o25"] <= 2.10) and (1.18 <= mk["o05ht"] <= 1.40) and (avg_vul >= 0.6 or f_s["vulnerability"] >= 0.8)) else 0
            SIG_OVER_PRO = 1 if (O25_OK and O05_OK and HT_OK and not f_s["is_dry"]) else 0

            det = []
            if HT_OK: det.append("HT-OK")
            if O25_OK: det.append("O25-OK")
            if GATE_11: det.append("GATE-11")
            if HAS_DROP: det.append("Drop")
            if SIG_GG_PT: det.append("🎯 GG-PT")
            if SIG_O25_BOOST: det.append("💣 O25-BOOST")
            if SIG_OVER_PRO: det.append("🔥 OVER-PRO")

            rating = min(100, 45 + max((25 if SIG_GG_PT else 0), (30 if SIG_O25_BOOST else (20 if SIG_OVER_PRO else 0))) + (30 if HAS_DROP else 0))

            if rating >= min_rating_val:
                results.append({
                    "Ora": m["fixture"]["date"][11:16], "Lega": f"{m['league']['name']} ({m['league']['country']})", 
                    "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}",
                    "Info": f"[{'|'.join(det)}]", "Rating": rating, "Fixture_ID": fid_s, "Is_Gold": (1.40 <= min(mk["q1"], mk["q2"]) <= 2.10),
                    "HTR_H": s_h["ht_ratio"], "HTR_A": s_a["ht_ratio"], "VUL_H": s_h["vulnerability"], "VUL_A": s_a["vulnerability"], "AVG_VUL": avg_vul,
                    "HT_OK": HT_OK, "O25_OK": O25_OK, "GATE_11": GATE_11, "HAS_DROP": HAS_DROP, "SIG_O25_BOOST": SIG_O25_BOOST
                })
        except: continue
    return results

# ============================
# UI E RENDERING (Fix #2: Expander Nazioni ripristinato)
# ============================
st.sidebar.header("👑 Configurazione Auditor")
with st.sidebar.expander("🌍 Filtro Nazioni PRO", expanded=False):
    sel = [c for c in st.session_state["available_countries"] if c not in st.session_state["excluded"]]
    to_ex = st.selectbox("Escludi:", ["-- seleziona --"] + sel)
    if to_ex != "-- seleziona --":
        st.session_state["excluded"].append(to_ex)
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": st.session_state["excluded"]}, f)
        st.rerun()
    st.markdown("---")
    to_in = st.selectbox("Ripristina:", ["-- seleziona --"] + st.session_state["excluded"])
    if to_in != "-- seleziona --":
        st.session_state["excluded"].remove(to_in)
        with open(NAZIONI_FILE, "w") as f: json.dump({"excluded": st.session_state["excluded"]}, f)
        st.rerun()

min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 20)
st.session_state["only_gold"] = st.sidebar.toggle("🎯 SOLO SWEET SPOT FAV", value=False)
st.session_state["only_o25_gold"] = st.sidebar.toggle("⚽ SOLO SWEET SPOT O2.5", value=False)

st.markdown("<style>table { width: 100%; border-collapse: collapse; font-size: 0.82rem; } th { background-color: #1a1c23; color: #00e5ff; padding: 8px; } td { padding: 5px; border: 1px solid #ccc; text-align: center; font-weight: 600; }</style>", unsafe_allow_html=True)

col1, col2 = st.columns(2)
def run_scan(is_snap):
    with requests.Session() as s:
        try:
            data = api_get(s, "fixtures", {"date": now_rome().strftime("%Y-%m-%d"), "timezone": "Europe/Rome"})
            fixs = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and not any(t in f["league"]["name"].lower() for t in ["women","u19","u20","u21","u23","youth","friendly"])]
            if is_snap:
                new_snap = {}
                for m in fixs:
                    mk = extract_markets(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if mk and mk["q1"] > 0:
                        fs = "q1" if mk["q1"] < mk["q2"] else "q2"
                        new_snap[str(m["fixture"]["id"])] = {"fav_side": fs, "fav_odd": mk[fs]}
                st.session_state["odds_memory"] = new_snap
                with open(JSON_FILE, "w") as f: json.dump({"date": now_rome().strftime("%Y-%m-%d"), "odds": new_snap}, f)
            st.session_state["scan_results"] = execute_scan(s, fixs, st.session_state["odds_memory"], st.session_state["excluded"], min_rating)
            st.rerun()
        except Exception as e: st.error(str(e))

if col1.button("📌 SNAPSHOT + SCAN"): run_scan(True)
if col2.button("🚀 SCAN TOTALE"): run_scan(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    if st.session_state["only_gold"]: df = df[df["Is_Gold"]]
    if st.session_state["only_o25_gold"]: df = df[df["O25_OK"] == 1]
    
    def style_row(row):
        if '🎯 GG-PT' in row['Info']: return ['background-color: #38003c; color: #00e5ff;' for _ in row]
        if '💣 O25-BOOST' in row['Info']: return ['background-color: #003300; color: #00ff00;' for _ in row] 
        return ['' for _ in row]

    st.write(df[["Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "Info", "Rating"]].style.apply(style_row, axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)
    st.download_button("💾 DOWNLOAD AUDITOR (CSV)", df.to_csv(index=False).encode('utf-8'), "auditor_final.csv")

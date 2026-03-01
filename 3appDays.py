import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE V21.30 - CLEAN & FEEDBACK (HT-OK FILTER)
# ============================
BASE_DIR = Path(__file__).resolve().parent
NAZIONI_FILE = str(BASE_DIR / "nazioni_config.json")

DEFAULT_EXCLUDED = [
    "Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda",
    "Macedonia", "Nigeria", "Ivory-Coast", "Oman", "El-Salvador",
    "Ethiopia", "Cameroon", "Jordan", "Algeria", "South-Africa",
    "Tanzania", "Montenegro", "UAE", "Guatemala", "Costa-Rica"
]

LEAGUE_KEYWORDS_BLACKLIST = [
    "regionalliga", "carioca", "paulista", "pernambucano", "gaucho",
    "mineiro", "youth", "friendly", "u19", "u20", "u21", "u23", "women"
]

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

def get_db_path(): return str(BASE_DIR / "arab_sniper_database.json")
def get_snap_db_path(): return str(BASE_DIR / "arab_snapshot_database.json")

st.set_page_config(page_title="ARAB SNIPER V21.30 - CLEAN & FEEDBACK", layout="wide")

# ============================
# API CORE
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("❌ API_SPORTS_KEY mancante!")
    st.stop()

HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params, retries=2):
    for i in range(retries + 1):
        try:
            r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
            if r.status_code == 429 and i < retries:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status()
            js = r.json()
            if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
            return js
        except Exception as e:
            if i == retries: raise e
            time.sleep(1)

# ============================
# INITIALIZATION & DB ROLLING
# ============================
if "excluded" not in st.session_state:
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                st.session_state["excluded"] = list(json.load(f).get("excluded", DEFAULT_EXCLUDED))
        except: st.session_state["excluded"] = DEFAULT_EXCLUDED
    else: st.session_state["excluded"] = DEFAULT_EXCLUDED

if "available_countries" not in st.session_state: st.session_state["available_countries"] = []
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = []

target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

def load_and_slide_db():
    db_path, snap_path = get_db_path(), get_snap_db_path()
    today_str = target_dates[0]
    ts_found = None
    if os.path.exists(db_path):
        try:
            with open(db_path, "r") as f:
                data = json.load(f)
                st.session_state["scan_results"] = [r for r in data.get("results", []) if r["Data"] >= today_str]
        except: pass
    if os.path.exists(snap_path):
        try:
            with open(snap_path, "r") as f:
                data = json.load(f)
                st.session_state["odds_memory"] = data.get("odds", {})
                ts_found = data.get("timestamp", "N/D")
        except: pass
    return ts_found

last_snap_ts = load_and_slide_db()

# ============================
# STATS ENGINE (HUNGER/ELITE)
# ============================
team_stats_cache = {}

def get_stats(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return {"ht_std": False, "is_elite": False, "vul_5": 0.0, "o25_8": 0.0, "gght_stat_ok": False}
        actual = len(fx)
        ht_c, o25_c, gg_c, vul_5, gght_hist = 0, 0, 0, 0, 0
        for idx, f in enumerate(fx):
            score_ht = f.get("score",{}).get("halftime",{})
            gh, ga = score_ht.get("home") or 0, score_ht.get("away") or 0
            if (gh + ga) >= 1: ht_c += 1
            if gh > 0 and ga > 0: gght_hist += 1
            is_h = (f["teams"]["home"]["id"] == tid)
            if ((f["goals"]["home"] or 0) + (f["goals"]["away"] or 0)) >= 3: o25_c += 1
            if idx < 5 and ((f["goals"]["away"] if is_h else f["goals"]["home"]) or 0) > 0: vul_5 += 1
        
        ht_std = (actual >= 8 and ht_c >= 5) or (actual == 7 and ht_c >= 4) or (actual == 6 and ht_c >= 4) or (actual == 5 and ht_c >= 3)
        is_elite = (actual >= 8 and ht_c >= 6) or (actual >= 6 and ht_c >= 5)
        gght_stat_ok = (actual >= 8 and gght_hist >= 3) or (actual >= 5 and gght_hist >= 2)
        res = {"ht_std": ht_std, "is_elite": is_elite, "vul_5": vul_5/min(actual, 5), "o25_8": o25_c/actual, "gght_stat_ok": gght_stat_ok}
        team_stats_cache[tid] = res
        return res
    except: return {"ht_std": False, "is_elite": False, "vul_5": 0.0, "o25_8": 0.0, "gght_stat_ok": False}

# ============================
# ESTRAZIONE MERCATI
# ============================
def extract_markets(session, fixture_id):
    try:
        resp_json = api_get(session, "odds", {"fixture": fixture_id})
        resp = resp_json.get("response", [])
        if not resp: return None
        data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
        def clean(s): return str(s or "").lower().replace(" ", "").replace("(", "").replace(")", "").replace("-", "").replace(",", ".")
        for bm in resp[0].get("bookmakers", []):
            for b in bm.get("bets", []):
                bid, name_raw = b.get("id"), str(b.get("name") or "").lower()
                name_clean = clean(name_raw)
                if bid == 1 and data["q1"] == 0:
                    for vo in b.get("values", []):
                        vn = clean(vo.get("value"))
                        if "home" in vn: data["q1"] = float(vo["odd"])
                        elif "draw" in vn: data["qx"] = float(vo["odd"])
                        elif "away" in vn: data["q2"] = float(vo["odd"])
                if bid == 5 and data["o25"] == 0:
                    for x in b.get("values", []):
                        if clean(x.get("value")) == "over2.5": data["o25"] = float(x.get("odd") or 0); break
                is_1h = (("1st" in name_raw) or ("firsthalf" in name_clean) or ("first" in name_raw and "half" in name_raw)) and not ("2nd" in name_raw or "second" in name_raw)
                if is_1h:
                    is_btts = any(k in name_clean for k in ["gg", "both", "btts"]) or ("goal" in name_clean and "no" not in name_clean)
                    is_noise = any(k in name_clean for k in ["first", "last", "exact", "total", "multi"])
                    if (bid == 71 or (is_btts and not is_noise)) and data["gg_ht"] == 0:
                        for x in b.get("values", []):
                            if clean(x.get("value")) in ["yes", "si", "oui"]:
                                val = float(x.get("odd") or 0)
                                if 3.00 <= val <= 7.50: data["gg_ht"] = val; break
                    if any(k in name_raw for k in ["over/under", "total"]):
                        for x in b.get("values", []):
                            vn, odd_val = clean(x.get("value")), float(x.get("odd") or 0)
                            if vn == "over0.5" and data["o05ht"] == 0 and odd_val < 1.75: data["o05ht"] = odd_val
                            if vn == "over1.5" and data["o15ht"] == 0: data["o15ht"] = odd_val
            if data["q1"]>0 and data["o05ht"]>0 and data["gg_ht"]>0: break
        return data
    except: return None

# ============================
# CORE ENGINE (CLEAN TABLE LOGIC)
# ============================
def execute_scan(session, fixtures, snap_mem, excluded, min_rating_val):
    results, pb = [], st.progress(0)
    filtered = [f for f in fixtures if f["league"]["country"] not in excluded and not any(k in f["league"]["name"].lower() for k in LEAGUE_KEYWORDS_BLACKLIST)]
    for i, m in enumerate(filtered):
        pb.progress((i+1)/len(filtered))
        try:
            mk = extract_markets(session, m["fixture"]["id"])
            if not mk or mk["q1"] <= 0: continue
            fid_s, s_h, s_a = str(m["fixture"]["id"]), get_stats(session, m["teams"]["home"]["id"]), get_stats(session, m["teams"]["away"]["id"])
            
            # --- SBARRAMENTO HT-OK ---
            HT_OK = 1 if ((s_h["ht_std"] and s_a["ht_std"]) or (s_h["is_elite"] or s_a["is_elite"])) else 0
            
            # PULIZIA: Se non supera HT-OK, scarta il match (Profit Protection)
            if not HT_OK: continue

            HAS_DROP = 1 if (fid_s in snap_mem and max(float(snap_mem[fid_s].get("q1", 0)) - mk["q1"], float(snap_mem[fid_s].get("q2", 0)) - mk["q2"]) >= 0.15) else 0
            fav_side = "q1" if mk["q1"] < mk["q2"] else "q2"
            f_stats = s_h if fav_side == "q1" else s_a
            
            SIG_GG_PT = 1 if (HT_OK and (2.00 <= mk["o15ht"] <= 2.80 or 3.50 <= mk["gg_ht"] <= 6.50) and f_stats["vul_5"] >= 0.60 and s_h["gght_stat_ok"] and s_a["gght_stat_ok"]) else 0
            is_boost = (HT_OK and (1.60 <= mk["o25"] <= 2.15) and (1.20 <= mk["o05ht"] <= 1.55) and (f_stats["vul_5"] >= 0.60 or (s_h["vul_5"]+s_a["vul_5"])/2 >= 0.60) and f_stats["o25_8"] >= 0.625)
            boost_tag = ("💣 O25-BOOST+" if (1.40 <= mk[fav_side] <= 1.75) else "💣 O25-BOOST") if is_boost else ""
            
            is_gold_bool = (1.40 <= mk[fav_side] <= 2.10)
            o25_ok_bool = (1.70 <= mk["o25"] <= 2.10)
            FISH_O = 1 if (1.40 <= mk[fav_side] <= 1.80 and f_stats["o25_8"] >= 0.75) else 0
            is_super_red = 1 if (boost_tag == "💣 O25-BOOST+" and FISH_O) else 0

            det = ["HT-OK"]
            if SIG_GG_PT: det.append("🎯 GG-PT")
            if boost_tag: det.append(boost_tag)
            if o25_ok_bool: det.append("O25-SS")
            if FISH_O: det.append("🐟O")
            if HAS_DROP: det.append("Drop")

            rating = min(100, 45 + (30 if is_boost else 0) + (10 if boost_tag == "💣 O25-BOOST+" else 0) + (25 if SIG_GG_PT else 0) + (20 if HAS_DROP else 0))
            if rating >= min_rating_val:
                results.append({
                    "Fixture_ID": m["fixture"]["id"], "Data": m["fixture"]["date"][:10], "Ora": m["fixture"]["date"][11:16], 
                    "Lega": f"{m['league']['name']} ({m['league']['country']})", "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}", "O1.5HT": f"{mk['o15ht']:.2f}", 
                    "Quota GG1T": f"{mk['gg_ht']:.2f}", "Info": f"[{'|'.join(det)}]", "Rating": rating, "Gold": "✅" if is_gold_bool else "❌",
                    "Is_Gold_Bool": is_gold_bool, "O25_OK": o25_ok_bool, "Is_Super_Red": is_super_red
                })
        except: continue
    return results

# ============================
# UI SIDEBAR (WITH FEEDBACK)
# ============================
st.sidebar.header("👑 Arab Sniper Console")

# --- FEEDBACK SNAPSHOT ---
if last_snap_ts:
    st.sidebar.success(f"✅ Snapshot Presente\n({last_snap_ts})")
else:
    st.sidebar.warning("⚠️ Snapshot Assente\n(Esegui SNAP+SCAN)")

HORIZON = st.sidebar.selectbox("Giorno:", options=[1, 2, 3], index=0)
only_fav_gold, only_o25_gold = st.sidebar.toggle("🎯 SOLO SWEET SPOT FAV"), st.sidebar.toggle("⚽ SOLO SWEET SPOT O2.5")
min_rating_ui = st.sidebar.slider("Rating Min", 0, 85, 30)

with st.sidebar.expander("🌍 Filtro Nazioni"):
    if not st.session_state["available_countries"]:
        try:
            with requests.Session() as s:
                d = api_get(s, "fixtures", {"date": target_dates[0], "timezone": "Europe/Rome"})
                st.session_state["available_countries"] = sorted(list(set(f["league"]["country"] for f in d.get("response", []))))
        except: pass
    to_ex = st.selectbox("Escludi:", ["--"] + [c for c in st.session_state["available_countries"] if c not in st.session_state["excluded"]])
    if to_ex != "--": st.session_state["excluded"].append(to_ex); json.dump({"excluded": st.session_state["excluded"]}, open(NAZIONI_FILE, "w")); st.rerun()

# ============================
# RUN SCAN LOGIC
# ============================
def run_scan(is_snap):
    with requests.Session() as s:
        target_date = target_dates[HORIZON - 1]
        data = api_get(s, "fixtures", {"date": target_date, "timezone": "Europe/Rome"})
        day_fx = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS"]
        if is_snap:
            pb_s = st.progress(0)
            for idx, m in enumerate(day_fx):
                pb_s.progress((idx+1)/len(day_fx)); mk = extract_markets(s, m["fixture"]["id"])
                if mk and mk["q1"] > 0: st.session_state["odds_memory"][str(m["fixture"]["id"])] = {"q1": mk["q1"], "q2": mk["q2"]}
            json.dump({"odds": st.session_state["odds_memory"], "timestamp": now_rome().strftime("%d/%m/%Y %H:%M")}, open(get_snap_db_path(), "w"))
        
        new_res = execute_scan(s, day_fx, st.session_state["odds_memory"], st.session_state["excluded"], min_rating_ui)
        ex_ids = [r["Fixture_ID"] for r in st.session_state["scan_results"]]
        st.session_state["scan_results"] += [r for r in new_res if r["Fixture_ID"] not in ex_ids]
        json.dump({"results": st.session_state["scan_results"]}, open(get_db_path(), "w")); st.rerun()

col1, col2 = st.columns(2)
if col1.button("📌 SNAPSHOT + SCAN"): run_scan(True)
if col2.button("🚀 SCAN VELOCE"): run_scan(False)

# ============================
# RENDERING
# ============================
if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    df_view = df[df["Data"] == target_dates[HORIZON-1]]
    if not df_view.empty:
        if only_fav_gold: df_view = df_view[df_view["Is_Gold_Bool"]]
        if only_o25_gold: df_view = df_view[df_view["O25_OK"]]
        
        def style_row(row):
            if row.get('Is_Super_Red'): return ['background-color: #8b0000; color: #ffffff;' for _ in row]
            if '🎯 GG-PT' in row['Info']: return ['background-color: #38003c; color: #00e5ff;' for _ in row]
            if '💣 O25-BOOST' in row['Info']: return ['background-color: #003300; color: #00ff00;' for _ in row] 
            return ['' for _ in row]
        
        CUSTOM_CSS = """<style>.stTableContainer { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 0.82rem; } th { background-color: #1a1c23; color: #00e5ff; padding: 8px; white-space: nowrap; } td { padding: 5px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }</style>"""
        st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
        DISPLAY_COLS = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "O1.5HT", "Quota GG1T", "Info", "Rating", "Gold"]
        st_table = df_view[DISPLAY_COLS].sort_values(["Ora"]).style.apply(style_row, axis=1)
        st.write(st_table.to_html(escape=False, index=False), unsafe_allow_html=True)
        
        st.markdown("---")
        c1, c2 = st.columns(2)
        c1.download_button("💾 CSV AUDITOR", df.to_csv(index=False).encode('utf-8'), f"audit_full_{target_dates[0]}.csv")
        html_report = f"<html><head>{CUSTOM_CSS}</head><body>{st_table.to_html(escape=False, index=False)}</body></html>"
        c2.download_button("🌐 HTML REPORT", html_report.encode('utf-8'), f"report_{target_dates[HORIZON-1]}.html")

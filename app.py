import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import re
from pathlib import Path

# ==========================================
# CONFIG
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "arab_sniper_database.json")
SNAP_FILE = str(BASE_DIR / "arab_snapshot_database.json")
CONFIG_FILE = str(BASE_DIR / "nazioni_config.json")

DEFAULT_EXCLUDED = ["Thailand", "Indonesia", "India", "Kenya", "Morocco", "Rwanda", "Nigeria", "Oman", "Algeria", "UAE"]

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V22.04.8", layout="wide")

# ==========================================
# SESSION INIT
# ==========================================
if "config" not in st.session_state:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            st.session_state.config = json.load(f)
    else:
        st.session_state.config = {"excluded": DEFAULT_EXCLUDED}

if "scan_results" not in st.session_state:
    st.session_state.scan_results = []

if "team_stats_cache" not in st.session_state:
    st.session_state.team_stats_cache = {}

# ==========================================
# API
# ==========================================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    try:
        r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=20)
        return r.json() if r.status_code == 200 else None
    except:
        return None

# ==========================================
# TEAM STATS
# ==========================================
def get_team_performance(session, tid):
    if str(tid) in st.session_state.team_stats_cache:
        return st.session_state.team_stats_cache[str(tid)]

    res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
    fx = res.get("response", []) if res else []
    if not fx:
        return None

    act = len(fx)
    tht, gf, gs = 0, 0, 0

    for f in fx:
        ht = f.get("score", {}).get("halftime", {})
        tht += (ht.get("home") or 0) + (ht.get("away") or 0)

        is_home = f["teams"]["home"]["id"] == tid
        gf += (f["goals"]["home"] or 0) if is_home else (f["goals"]["away"] or 0)
        gs += (f["goals"]["away"] or 0) if is_home else (f["goals"]["home"] or 0)

    stats = {"avg_ht": tht / act, "avg_total": (gf + gs) / act}
    st.session_state.team_stats_cache[str(tid)] = stats
    return stats

# ==========================================
# ROBUST MARKET EXTRACTION + TOP ODDS
# ==========================================
def _norm(s):
    return (s or "").strip().lower()

def _to_float_odd(x):
    try:
        return float(str(x).replace(",", "."))
    except:
        return None

def _is_over_value(val_norm, line):
    if "over" not in val_norm:
        return False
    m = re.search(r"(\d+(?:[.,]\d+)?)", val_norm)
    if not m:
        return False
    return m.group(1).replace(",", ".") == line

def _is_btts_yes(val_norm):
    return val_norm in {"yes", "si", "sì", "y"}

# PATCH: prende la quota più alta
def _maybe_set(mk, key, odd_val):
    if odd_val and odd_val > 0:
        current = float(mk.get(key, 0) or 0)
        if odd_val > current:
            mk[key] = odd_val

def extract_markets(session, fid):
    res = api_get(session, "odds", {"fixture": fid})
    if not res or not res.get("response"):
        return None

    mk = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "gght": 0.0}

    bookmakers = res["response"][0].get("bookmakers", [])

    for bm in bookmakers:
        bets = bm.get("bets", [])
        for b in bets:
            b_id = b.get("id")
            b_name = _norm(b.get("name"))

            for v in b.get("values", []):
                vv = _norm(v.get("value"))
                odd = _to_float_odd(v.get("odd"))

                # 1X2
                if b_id == 1 or "match winner" in b_name:
                    if vv in {"home", "1"}:
                        _maybe_set(mk, "q1", odd)
                    elif vv in {"draw", "x"}:
                        _maybe_set(mk, "qx", odd)
                    elif vv in {"away", "2"}:
                        _maybe_set(mk, "q2", odd)

                # Over 2.5 FT
                if b_id == 5 or ("over/under" in b_name and "half" not in b_name):
                    if _is_over_value(vv, "2.5"):
                        _maybe_set(mk, "o25", odd)

                # Over 0.5 HT
                if (b_id == 13 or "1st half" in b_name or "first half" in b_name):
                    if _is_over_value(vv, "0.5"):
                        _maybe_set(mk, "o05ht", odd)

                # BTTS 1H
                if "both teams to score" in b_name and ("1st half" in b_name or "first half" in b_name):
                    if _is_btts_yes(vv):
                        _maybe_set(mk, "gght", odd)

    return mk

# ==========================================
# SCAN
# ==========================================
def run_scan():
    with st.spinner("🚀 Scan in corso..."):
        with requests.Session() as s:
            today = now_rome().strftime("%Y-%m-%d")
            res = api_get(s, "fixtures", {"date": today, "timezone": "Europe/Rome"})
            if not res:
                return

            final = []

            for f in res.get("response", []):
                if f["fixture"]["status"]["short"] != "NS":
                    continue

                country = f["league"]["country"]
                if country in st.session_state.config["excluded"]:
                    continue

                mk = extract_markets(s, f["fixture"]["id"])
                if not mk:
                    continue

                s_h = get_team_performance(s, f["teams"]["home"]["id"])
                s_a = get_team_performance(s, f["teams"]["away"]["id"])
                if not s_h or not s_a:
                    continue

                tags = []

                if (s_h["avg_total"] >= 2 and s_a["avg_total"] >= 2 and
                    mk["o25"] > 1.8 and mk["o05ht"] > 1.3):
                    tags.append("⚽")

                final.append({
                    "Ora": f["fixture"]["date"][11:16],
                    "Match": f"{f['teams']['home']['name']} - {f['teams']['away']['name']}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                    "O2.5": mk["o25"],
                    "O0.5H": mk["o05ht"],
                    "GGH": mk["gght"],
                    "Info": " ".join(tags)
                })

            st.session_state.scan_results = final

# ==========================================
# UI
# ==========================================
if st.button("🚀 SCAN"):
    run_scan()

if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    st.dataframe(df, use_container_width=True)
else:
    st.info("Pronto per lo scan.")

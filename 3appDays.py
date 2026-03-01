import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE V21.25 - FULL SNIPER + HTML REPORT
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

st.set_page_config(page_title="ARAB SNIPER V21.25", layout="wide")

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
            r = session.get(
                f"https://v3.football.api-sports.io/{path}",
                headers=HEADERS,
                params=params,
                timeout=25
            )
            if r.status_code == 429 and i < retries:
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status()
            js = r.json()
            if js.get("errors"):
                raise RuntimeError(f"API Errors: {js['errors']}")
            return js
        except Exception as e:
            if i == retries:
                raise e
            time.sleep(1)

# ============================
# INITIALIZATION & DB ROLLING
# ============================
if "excluded" not in st.session_state:
    if os.path.exists(NAZIONI_FILE):
        try:
            with open(NAZIONI_FILE, "r") as f:
                st.session_state["excluded"] = list(json.load(f).get("excluded", DEFAULT_EXCLUDED))
        except:
            st.session_state["excluded"] = DEFAULT_EXCLUDED
    else:
        st.session_state["excluded"] = DEFAULT_EXCLUDED

if "available_countries" not in st.session_state: st.session_state["available_countries"] = []
if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "scan_results" not in st.session_state: st.session_state["scan_results"] = []

target_dates = [(now_rome().date() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

def load_and_slide_db():
    db_path, snap_path = get_db_path(), get_snap_db_path()
    today_str = target_dates[0]
    if os.path.exists(db_path):
        try:
            with open(db_path, "r") as f:
                data = json.load(f)
                st.session_state["scan_results"] = [r for r in data.get("results", []) if r["Data"] >= today_str]
        except:
            pass
    if os.path.exists(snap_path):
        try:
            with open(snap_path, "r") as f:
                data = json.load(f)
                st.session_state["odds_memory"] = data.get("odds", {})
                return data.get("timestamp", "N/D")
        except:
            pass
    return None

last_snap_ts = load_and_slide_db()

# ============================
# STATS ENGINE (HUNGER/ELITE/GGHT)
# ============================
team_stats_cache = {}

def get_stats(session, tid):
    if tid in team_stats_cache:
        return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
        fx = rx.get("response", [])
        if not fx:
            return {
                "ht_std": False, "is_elite": False, "vul_5": 0.0,
                "o25_8": 0.0, "gg_8": 0.0, "gght_stat_ok": False
            }
        actual = len(fx)
        ht_c, o25_c, gg_c, vul_5, gght_hist = 0, 0, 0, 0, 0

        for idx, f in enumerate(fx):
            score_ht = f.get("score", {}).get("halftime", {})
            gh, ga = score_ht.get("home") or 0, score_ht.get("away") or 0
            if (gh + ga) >= 1:
                ht_c += 1
            if gh > 0 and ga > 0:
                gght_hist += 1

            is_h = (f["teams"]["home"]["id"] == tid)
            if ((f["goals"]["home"] or 0) + (f["goals"]["away"] or 0)) >= 3:
                o25_c += 1
            if (f["goals"]["home"] or 0) > 0 and (f["goals"]["away"] or 0) > 0:
                gg_c += 1
            if idx < 5 and ((f["goals"]["away"] if is_h else f["goals"]["home"]) or 0) > 0:
                vul_5 += 1

        ht_std = (actual >= 8 and ht_c >= 5) or (actual == 7 and ht_c >= 4) or (actual == 6 and ht_c >= 4) or (actual == 5 and ht_c >= 3)
        is_elite = (actual >= 8 and ht_c >= 6) or (actual >= 6 and ht_c >= 5)
        gght_stat_ok = (actual >= 8 and gght_hist >= 3) or (actual >= 5 and gght_hist >= 2)

        res = {
            "ht_std": ht_std,
            "is_elite": is_elite,
            "vul_5": vul_5 / min(actual, 5),
            "o25_8": o25_c / actual,
            "gght_stat_ok": gght_stat_ok
        }
        team_stats_cache[tid] = res
        return res
    except:
        return {
            "ht_std": False, "is_elite": False, "vul_5": 0.0,
            "o25_8": 0.0, "gght_stat_ok": False
        }

# ============================
# ESTRAZIONE MERCATI (ANTI-NOISE) - FIXED
# ============================
def extract_markets(session, fixture_id):
    """
    Estrae quote chiave da API-Sports Odds.
    Fix principale: evitare "uscite anticipate" che lasciano a 0 mercati fondamentali (O2.5, O1.5HT, GG1T).
    Strategia:
      - scandisce più bookmakers (max 6) e si ferma solo quando ha: 1X2 + O2.5 + O0.5HT e (O1.5HT o GG1T)
      - O2.5: prende sia da bet id=5 (Over/Under FT) che da mercati FT con nome "over/under/total"
      - GG1T: riconosce BTTS 1st half in modo più stretto, evitando rumore su mercati "first goal", "exact", ecc.
    """
    try:
        resp_json = api_get(session, "odds", {"fixture": fixture_id})
        resp = resp_json.get("response", [])
        if not resp:
            return None

        data = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "o15ht": 0.0, "gg_ht": 0.0}

        def clean(s: str) -> str:
            return str(s or "").lower().replace(" ", "").replace("(", "").replace(")", "").replace("-", "").replace(",", ".").replace("_", "")

        def ffloat(x):
            try:
                return float(x)
            except Exception:
                return 0.0

        def pick_over(values, key: str) -> float:
            # key esempio: "over0.5", "over1.5", "over2.5"
            for x in values or []:
                vn = clean(x.get("value"))
                if vn == key:
                    return ffloat(x.get("odd") or 0)
            return 0.0

        bookmakers = resp[0].get("bookmakers", []) or []
        for ibm, bm in enumerate(bookmakers):
            bets = bm.get("bets", []) or []

            for b in bets:
                bid = b.get("id")
                name_raw = str(b.get("name") or "")
                name = clean(name_raw)

                # ----------------
                # 1X2 (Full time)
                # ----------------
                if bid == 1 and data["q1"] == 0:
                    vals = b.get("values", []) or []
                    # mapping robusto
                    for vo in vals:
                        vn = clean(vo.get("value"))
                        odd = ffloat(vo.get("odd") or 0)
                        if odd <= 0:
                            continue
                        if "home" in vn:
                            data["q1"] = odd
                        elif "draw" in vn:
                            data["qx"] = odd
                        elif "away" in vn:
                            data["q2"] = odd
                    # fallback per feed che non etichetta home/draw/away
                    if data["q1"] == 0 and len(vals) >= 3:
                        data["q1"], data["qx"], data["q2"] = ffloat(vals[0].get("odd") or 0), ffloat(vals[1].get("odd") or 0), ffloat(vals[2].get("odd") or 0)

                # ----------------
                # O2.5 (Full time)
                # ----------------
                if data["o25"] == 0:
                    # caso classico: bet id=5 (Over/Under)
                    if bid == 5:
                        o = pick_over(b.get("values", []), "over2.5")
                        if o > 0:
                            data["o25"] = o
                    # fallback: alcuni feed mettono l'OU FT su altri id ma nel nome c'è over/under/total e NON è 1H
                    if data["o25"] == 0:
                        is_total_ft = (("overunder" in name) or ("over/under" in name_raw.lower()) or ("total" in name)) and not any(
                            k in name for k in ["1st", "1h", "firsthalf", "halftime", "half-time"]
                        )
                        if is_total_ft:
                            o = pick_over(b.get("values", []), "over2.5")
                            if o > 0:
                                data["o25"] = o

                # ----------------
                # Mercati 1H (HT)
                # ----------------
                is_1h = any(k in name for k in ["1st", "1h", "firsthalf", "halftime", "half-time"]) and not any(
                    k in name for k in ["2nd", "2h", "secondhalf"]
                )
                if is_1h:
                    # Over HT
                    if ("overunder" in name) or ("over/under" in name_raw.lower()) or ("total" in name):
                        if data["o05ht"] == 0:
                            o = pick_over(b.get("values", []), "over0.5")
                            if 0 < o < 1.75:
                                data["o05ht"] = o
                        if data["o15ht"] == 0:
                            o = pick_over(b.get("values", []), "over1.5")
                            if o > 0:
                                data["o15ht"] = o

                    # BTTS 1H (GG1T)
                    if data["gg_ht"] == 0:
                        # riconoscimento più stretto (niente "goal" generico)
                        is_btts = any(k in name for k in ["btts", "bothteamstoscore", "both", "gg"])
                        is_noise = any(k in name for k in ["firstgoal", "lastgoal", "exact", "correctscore", "multi", "totalgoals"])
                        if (bid == 71 or is_btts) and not is_noise:
                            for x in b.get("values", []) or []:
                                vn = clean(x.get("value"))
                                if vn in ["yes", "si", "oui"]:
                                    val = ffloat(x.get("odd") or 0)
                                    # range coerente con il tuo modello: se 0 è non quotato
                                    if 2.80 <= val <= 8.50:
                                        data["gg_ht"] = val
                                        break

            # condizioni di stop: non usciamo finché non abbiamo i fondamentali
            h_core = (data["q1"] > 0 and data["q2"] > 0)
            h_over = (data["o25"] > 0 and data["o05ht"] > 0)
            h_gate = (data["o15ht"] > 0 or data["gg_ht"] > 0)
            if h_core and h_over and h_gate:
                break
            # hard cap per prestazioni: dopo 6 bookmakers ci fermiamo comunque se abbiamo core+over
            if ibm >= 5 and h_core and h_over:
                break

        return data
    except:
        return None

# ============================
# CORE ENGINE
# ============================
def execute_scan(session, fixtures, snap_mem, excluded, min_rating_val):
    results, pb = [], st.progress(0)
    filtered = [f for f in fixtures if f["league"]["country"] not in excluded and not any(k in f["league"]["name"].lower() for k in LEAGUE_KEYWORDS_BLACKLIST)]

    if not filtered:
        pb.empty()
        return results

    denom = len(filtered)
    for i, m in enumerate(filtered):
        pb.progress((i + 1) / denom)
        try:
            mk = extract_markets(session, m["fixture"]["id"])
            if not mk or mk["q1"] <= 0:
                continue

            fid_s = str(m["fixture"]["id"])
            s_h = get_stats(session, m["teams"]["home"]["id"])
            s_a = get_stats(session, m["teams"]["away"]["id"])

            HT_OK = 1 if ((s_h["ht_std"] and s_a["ht_std"]) or (s_h["is_elite"] or s_a["is_elite"])) else 0
            HAS_DROP = 1 if (fid_s in snap_mem and max(float(snap_mem[fid_s].get("q1", 0)) - mk["q1"], float(snap_mem[fid_s].get("q2", 0)) - mk["q2"]) >= 0.15) else 0

            fav_side = "q1" if mk["q1"] < mk["q2"] else "q2"
            f_stats = s_h if fav_side == "q1" else s_a

            SIG_GG_PT = 1 if (HT_OK and (2.00 <= mk["o15ht"] <= 2.80 or 3.50 <= mk["gg_ht"] <= 6.50) and f_stats["vul_5"] >= 0.60 and s_h["gght_stat_ok"] and s_a["gght_stat_ok"]) else 0
            is_boost = (HT_OK and (1.60 <= mk["o25"] <= 2.15) and (1.20 <= mk["o05ht"] <= 1.55) and (f_stats["vul_5"] >= 0.60 or (s_h["vul_5"] + s_a["vul_5"]) / 2 >= 0.60) and f_stats["o25_8"] >= 0.625)
            boost_tag = ("💣 O25-BOOST+" if (1.40 <= mk[fav_side] <= 1.75) else "💣 O25-BOOST") if is_boost else ""

            is_gold_bool = (1.40 <= mk[fav_side] <= 2.10)
            o25_ok_bool = (1.70 <= mk["o25"] <= 2.10)
            FISH_O = 1 if (1.40 <= mk[fav_side] <= 1.80 and f_stats["o25_8"] >= 0.75) else 0
            is_super_red = 1 if (boost_tag == "💣 O25-BOOST+" and FISH_O) else 0

            det = []
            if HT_OK: det.append("HT-OK")
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
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                    "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}", "O1.5HT": f"{mk['o15ht']:.2f}",
                    "Quota GG1T": f"{mk['gg_ht']:.2f}", "Info": f"[{'|'.join(det)}]", "Rating": rating,
                    "Gold": "✅" if is_gold_bool else "❌",
                    "Is_Gold_Bool": is_gold_bool, "O25_OK": o25_ok_bool, "Is_Super_Red": is_super_red
                })
        except:
            continue

    return results

# ============================
# UI & RENDERING
# ============================
st.sidebar.header("👑 Arab Sniper Console")
HORIZON = st.sidebar.selectbox("Giorno:", options=[1, 2, 3], index=0)
only_fav_gold, only_o25_gold = st.sidebar.toggle("🎯 SOLO SWEET SPOT FAV"), st.sidebar.toggle("⚽ SOLO SWEET SPOT O2.5")
min_rating_ui = st.sidebar.slider("Rating Min", 0, 85, 30)

with st.sidebar.expander("🌍 Filtro Nazioni"):
    if not st.session_state["available_countries"]:
        try:
            with requests.Session() as s:
                d = api_get(s, "fixtures", {"date": target_dates[0], "timezone": "Europe/Rome"})
                st.session_state["available_countries"] = sorted(list(set(f["league"]["country"] for f in d.get("response", []))))
        except:
            pass
    to_ex = st.selectbox("Escludi:", ["--"] + [c for c in st.session_state["available_countries"] if c not in st.session_state["excluded"]])
    if to_ex != "--":
        st.session_state["excluded"].append(to_ex)
        json.dump({"excluded": st.session_state["excluded"]}, open(NAZIONI_FILE, "w"))
        st.rerun()

CUSTOM_CSS = """<style>.stTableContainer { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: 0.82rem; } th { background-color: #1a1c23; color: #00e5ff; padding: 8px; white-space: nowrap; } td { padding: 5px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }</style>"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

def run_scan(is_snap):
    with requests.Session() as s:
        target_date = target_dates[HORIZON - 1]
        data = api_get(s, "fixtures", {"date": target_date, "timezone": "Europe/Rome"})
        day_fx = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS"]

        if is_snap:
            pb_s = st.progress(0)
            for idx, m in enumerate(day_fx):
                pb_s.progress((idx+1)/max(1, len(day_fx)))
                mk = extract_markets(s, m["fixture"]["id"])
                if mk and mk["q1"] > 0:
                    st.session_state["odds_memory"][str(m["fixture"]["id"])] = {"q1": mk["q1"], "q2": mk["q2"]}
            with open(get_snap_db_path(), "w") as f_s:
                json.dump({"odds": st.session_state["odds_memory"], "timestamp": now_rome().strftime("%d/%m/%Y %H:%M")}, f_s)

        new_results = execute_scan(s, day_fx, st.session_state["odds_memory"], st.session_state["excluded"], min_rating_ui)
        existing = st.session_state["scan_results"]
        existing_ids = [r["Fixture_ID"] for r in existing]
        filtered_new = [r for r in new_results if r["Fixture_ID"] not in existing_ids]
        all_res = existing + filtered_new
        st.session_state["scan_results"] = all_res
        with open(get_db_path(), "w") as f_db:
            json.dump({"results": all_res}, f_db)
        st.rerun()

col1, col2 = st.columns(2)
if col1.button("📌 SNAPSHOT + SCAN (MIRATO)"):
    run_scan(True)
if col2.button("🚀 SCAN VELOCE (NO SNAP)"):
    run_scan(False)

if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    df_view = df[df["Data"] == target_dates[HORIZON - 1]]
    if not df_view.empty:
        if only_fav_gold:
            df_view = df_view[df_view["Is_Gold_Bool"]]
        if only_o25_gold:
            df_view = df_view[df_view["O25_OK"] == 1]

        def style_row(row):
            if '🎯 GG-PT' in row['Info']:
                return ['background-color: #38003c; color: #00e5ff;' for _ in row]
            if '💣 O25-BOOST' in row['Info']:
                return ['background-color: #003300; color: #00ff00;' for _ in row]
            return ['' for _ in row]

        DISPLAY_COLS = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "O0.5HT", "O1.5HT", "Quota GG1T", "Info", "Rating", "Gold"]
        st_table = df_view[DISPLAY_COLS].sort_values(["Ora"]).style.apply(style_row, axis=1)
        st.write(st_table.to_html(escape=False, index=False), unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        c1.download_button("💾 CSV AUDITOR", df.to_csv(index=False).encode('utf-8'), f"audit_full_{target_dates[0]}.csv")

        # --- GENERAZIONE REPORT HTML ---
        html_report = f"<html><head>{CUSTOM_CSS}</head><body>{st_table.to_html(escape=False, index=False)}</body></html>"
        c2.download_button("🌐 HTML REPORT", html_report.encode('utf-8'), f"report_{target_dates[HORIZON-1]}.html")

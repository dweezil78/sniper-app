import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path

# ============================
# CONFIGURAZIONE V22.00 - ELITE SNIPER (PUNTO DI INIZIO)
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

st.set_page_config(page_title="ARAB SNIPER V22.00", layout="wide")

# ===== TARGET DATES (sempre disponibili) =====
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
        with open(DB_FILE, "r") as f:
            data = json.load(f).get("results", [])
            st.session_state.scan_results = [r for r in data if r["Data"] >= today] # Sliding Window
    if os.path.exists(SNAP_FILE):
        with open(SNAP_FILE, "r") as f:
            snap_data = json.load(f)
            st.session_state.odds_memory = snap_data.get("odds", {})
            return snap_data.get("timestamp", "N/D")
    return None

last_snap_ts = load_db()

# ============================
# API CORE
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params, retries=2):
    """Wrapper API-Sports con retry base (soprattutto per 429) e gestione errori leggera."""
    last_err = None
    for i in range(retries + 1):
        try:
            r = session.get(
                f"https://v3.football.api-sports.io/{path}",
                headers=HEADERS,
                params=params,
                timeout=25
            )
            if r.status_code == 429 and i < retries:
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            js = r.json()
            # se API-Sports segnala errori logici in payload
            if isinstance(js, dict) and js.get("errors"):
                last_err = RuntimeError(f"API Errors: {js['errors']}")
                if i < retries:
                    time.sleep(1.0 * (i + 1))
                    continue
                raise last_err
            return js
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(1.0 * (i + 1))
                continue
            return None

# ============================
# FASE 4: ANALISI 0.7 HT & STORICO ADATTIVO
# ============================
team_stats_cache = {}

def get_team_performance(session, tid):
    if tid in team_stats_cache: return team_stats_cache[tid]
    # Recupero dinamico (Punto 4.1)
    res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
    fx = res.get("response", []) if res else []
    
    if len(fx) < 3: return None # Sbarramento minimo 3 match
    
    actual = len(fx)
    total_goals_ht = 0
    total_conceded_ft = 0
    o25_count = 0
    gg_count = 0
    
    for f in fx:
        # HT Goals (Media 0.7)
        ht = f.get("score", {}).get("halftime", {})
        total_goals_ht += (ht.get("home") or 0) + (ht.get("away") or 0)
        
        # FT Trends
        goals_h = f.get("goals", {}).get("home") or 0
        goals_a = f.get("goals", {}).get("away") or 0
        if (goals_h + goals_a) >= 3: o25_count += 1
        if goals_h > 0 and goals_a > 0: gg_count += 1
        
        # Vulnerability
        is_h = f["teams"]["home"]["id"] == tid
        total_conceded_ft += goals_a if is_h else goals_h

    avg_ht = total_goals_ht / actual
    avg_vul = total_conceded_ft / actual
    
    stats = {
        "avg_ht": avg_ht,
        "avg_vul": avg_vul,
        "o25_perc": o25_count / actual,
        "gg_perc": gg_count / actual,
        "is_elite": avg_ht >= 1.2
    }
    team_stats_cache[tid] = stats
    return stats

# ============================
# FASE 2 & 3: RICERCA AGGRESSIVA & SWEET SPOT
# ============================
def extract_elite_markets(session, fid):
    """
    Estrazione mercati chiave:
      - 1X2 (Home/Away)
      - Over 2.5 FT
      - Over 0.5 1H
      - BTTS 1H (GG-PT)
    Fix: normalizzazione stringhe + riconoscimento 1H più ampio + fallback O2.5 FT non solo bet id=5.
    """
    res = api_get(session, "odds", {"fixture": fid})
    if not res or not res.get("response"):
        return None

    mk = {"q1": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "gght": 0.0}

    def clean(s: str) -> str:
        return (
            str(s or "")
            .lower()
            .strip()
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .replace("/", "")
            .replace("(", "")
            .replace(")", "")
            .replace(",", ".")
        )

    def to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    def pick_over(values, key_norm: str) -> float:
        # key_norm: "over2.5", "over0.5", ecc.
        for v in values or []:
            if clean(v.get("value")) == key_norm:
                odd = to_float(v.get("odd"))
                if odd > 0:
                    return odd
        return 0.0

    def is_first_half(name_clean: str) -> bool:
        # evita 2nd half
        if any(k in name_clean for k in ["2nd", "2h", "secondhalf"]):
            return False
        return any(k in name_clean for k in ["1st", "1h", "firsthalf", "halftime", "half-time", "1sthalf", "1sthalfgoals"])

    def is_total_market(name_clean: str) -> bool:
        return any(k in name_clean for k in ["total", "overunder", "over/under", "goals"])

    def is_btts_market(name_clean: str) -> bool:
        # attenzione: no "first goal", "correct score", ecc.
        if any(k in name_clean for k in ["firstgoal", "lastgoal", "correctscore", "exact", "result", "winner", "doublechance"]):
            return False
        return any(k in name_clean for k in ["btts", "bothteamstoscore", "bothteams", "both", "gg"])

    # Scansione su più bookmakers: stop solo quando abbiamo i fondamentali
    for ibm, bm in enumerate(res["response"][0].get("bookmakers", []) or []):
        for b in bm.get("bets", []) or []:
            bid = b.get("id")
            name_raw = b.get("name") or ""
            name = clean(name_raw)

            # 1X2
            if bid == 1 and mk["q1"] == 0:
                for v in b.get("values", []) or []:
                    vv = clean(v.get("value"))
                    odd = to_float(v.get("odd"))
                    if odd <= 0:
                        continue
                    if vv in ["home", "1", "team1"]:
                        mk["q1"] = odd
                    elif vv in ["away", "2", "team2"]:
                        mk["q2"] = odd
                # se manca label ma ci sono 3 valori, spesso sono home/draw/away
                if mk["q1"] == 0 and mk["q2"] == 0 and len(b.get("values", []) or []) >= 3:
                    mk["q1"] = to_float(b["values"][0].get("odd"))
                    mk["q2"] = to_float(b["values"][2].get("odd"))

            # Over 2.5 FT (bet id=5 oppure fallback su mercati total FT)
            if mk["o25"] == 0:
                if bid == 5:
                    o = pick_over(b.get("values", []), "over2.5")
                    if o > 0:
                        mk["o25"] = o
                else:
                    # fallback: total/overunder FT (non 1H)
                    if is_total_market(name) and not is_first_half(name):
                        o = pick_over(b.get("values", []), "over2.5")
                        if o > 0:
                            mk["o25"] = o

            # Mercati 1H
            if is_first_half(name):
                # Over 0.5 1H
                if mk["o05ht"] == 0 and is_total_market(name):
                    o = pick_over(b.get("values", []), "over0.5")
                    if o > 0:
                        mk["o05ht"] = o
                # BTTS 1H
                if mk["gght"] == 0 and (bid == 71 or is_btts_market(name)):
                    for v in b.get("values", []) or []:
                        vv = clean(v.get("value"))
                        if vv in ["yes", "si", "oui"]:
                            odd = to_float(v.get("odd"))
                            if odd > 0:
                                mk["gght"] = odd
                                break

        # stop solo quando abbiamo 1X2 + O2.5 + O0.5HT + GGHT
        if mk["q1"] > 0 and mk["q2"] > 0 and mk["o25"] > 0 and mk["o05ht"] > 0 and mk["gght"] > 0:
            break
        # cap prestazioni: dopo 6 bookmakers ci fermiamo se almeno core+o25 presi
        if ibm >= 5 and mk["q1"] > 0 and mk["o25"] > 0:
            break

    # Prefiltro sbilanciamento (Punto 2.3)
    if (1.01 <= mk["q1"] <= 1.10) or (1.01 <= mk["q2"] <= 1.10) or (1.01 <= mk["o25"] <= 1.30):
        return "SKIP"

    return mk

# ============================
# FASE 5: RATING & COLORE
# ============================
def execute_elite_scan(session, fixtures, snap_mem, min_rating_ui):
    final_list = []
    pb = st.progress(0)
    
    for i, f in enumerate(fixtures):
        pb.progress((i+1)/len(fixtures))
        country = f["league"]["country"]
        if country in st.session_state.config["excluded"]: continue
        if any(k in f["league"]["name"].lower() for k in LEAGUE_BLACKLIST): continue
        
        mk = extract_elite_markets(session, f["fixture"]["id"])
        if not mk or mk == "SKIP": continue
        
        # Analisi Statistica
        s_h = get_team_performance(session, f["teams"]["home"]["id"])
        s_a = get_team_performance(session, f["teams"]["away"]["id"])
        
        if not s_h or not s_a: continue
        
        # FILTRO SBARRAMENTO 0.7 HT (Punto 4.2)
        # Passa se entrambe >= 0.7 OPPURE se una è Elite (>= 1.2)
        if not ((s_h["avg_ht"] >= 0.7 and s_a["avg_ht"] >= 0.7) or (s_h["is_elite"] or s_a["is_elite"])):
            continue

        # Calcoli segnali
        fav_odd = mk["q1"] if mk["q1"] < mk["q2"] else mk["q2"]
        f_stats = s_h if mk["q1"] < mk["q2"] else s_a
        
        # Sweet Spots (Punto 3.2 & 3.3)
        gold_zone = 1.40 <= fav_odd <= 1.90
        o25_zone = 1.50 <= mk["o25"] <= 2.20
        
        # Drop (Punto 3.4)
        fid_s = str(f["fixture"]["id"])
        drop_val = 0.0
        if fid_s in snap_mem:
            old_q = float(snap_mem[fid_s].get("q1" if mk["q1"]<mk["q2"] else "q2", 0))
            drop_val = old_q - fav_odd

        # Info Tags
        tags = ["HT-OK"]
        if o25_zone: tags.append("O25-SS")
        if drop_val >= 0.15: tags.append(f"Drop {drop_val:.2f}")
        
        # BOOST & GG-PT (Fase 5)
        is_boost = (o25_zone and f_stats["avg_ht"] >= 0.8 and f_stats["avg_vul"] >= 1.0)
        if is_boost: tags.append("💣 O25-BOOST")
        
        is_gg_pt = (mk["gght"] >= 3.5 and s_h["avg_ht"] >= 0.7 and s_a["avg_ht"] >= 0.7)
        if is_gg_pt: tags.append("🎯 GG-PT")
        
        is_super_red = is_boost and (f_stats["o25_perc"] >= 0.70)

        # Rating Proporzionale (Punto 5.1)
        rating = 45
        rating += (s_h["avg_ht"] + s_a["avg_ht"]) * 10
        if is_boost: rating += 20
        if drop_val >= 0.20: rating += 15
        rating = min(100, int(rating))

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
# SIDEBAR UI
# ============================
st.sidebar.header("👑 Arab Sniper V22.00")

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
        if not res:
            return
        day_fx = [f for f in res.get("response", []) if f["fixture"]["status"]["short"] == "NS"]

        # SNAPSHOT: salva e soprattutto aggiorna la memoria in-session (serve per Drop coerente)
        current_snap = None
        if snap:
            current_snap = {}
            pb_snap = st.progress(0)
            denom = max(1, len(day_fx))
            for j, f in enumerate(day_fx):
                pb_snap.progress((j + 1) / denom)
                m = extract_elite_markets(s, f["fixture"]["id"])
                if m and m != "SKIP":
                    current_snap[str(f["fixture"]["id"])] = {"q1": m["q1"], "q2": m["q2"]}
            # aggiorna memoria runtime e persiste
            st.session_state.odds_memory = current_snap
            with open(SNAP_FILE, "w") as f:
                json.dump({"odds": current_snap, "timestamp": now_rome().strftime("%H:%M")}, f)

        snap_mem = current_snap if current_snap is not None else st.session_state.odds_memory
        new_res = execute_elite_scan(s, day_fx, snap_mem, min_rating)

        existing_ids = [r["Fixture_ID"] for r in st.session_state.scan_results]
        st.session_state.scan_results += [r for r in new_res if r["Fixture_ID"] not in existing_ids]
        with open(DB_FILE, "w") as f:
            json.dump({"results": st.session_state.scan_results}, f)
        st.rerun()

c1, c2 = st.columns(2)
if c1.button("📌 SNAP + SCAN"): run_full_scan(snap=True)
if c2.button("🚀 SCAN VELOCE"): run_full_scan(snap=False)

# ============================
# TABELLA E COLORI
# ============================
if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    view = df[df["Data"] == target_dates[HORIZON-1]]
    
    if not view.empty:
        if only_gold: view = view[view["Is_Gold"]]
        if only_o25: view = view[view["Is_O25SS"]]

        def color_logic(row):
            if row["Is_Super_Red"]: return ['background-color: #8b0000; color: white'] * len(row)
            if row["Is_GGPT"]: return ['background-color: #38003c; color: #00e5ff'] * len(row)
            if row["Is_Boost"]: return ['background-color: #003300; color: #00ff00'] * len(row)
            return ['color: #cccccc'] * len(row)

        cols = ["Data", "Ora", "Lega", "Match", "1X2", "O2.5", "HT_Avg", "Info", "Rating", "Gold"]
        styled = view[cols].sort_values("Rating", ascending=False).style.apply(color_logic, axis=1)
        
        st.markdown("""<style>table { font-size: 13px; font-weight: 600; }</style>""", unsafe_allow_html=True)
        st.write(styled.to_html(escape=False, index=False), unsafe_allow_html=True)
        
        st.markdown("---")
        st.download_button("💾 CSV AUDITOR", df.to_csv(index=False).encode('utf-8'), "audit.csv")
        html_rep = f"<html><body style='background:#0e1117'>{styled.to_html(index=False)}</body></html>"
        st.download_button("🌐 HTML REPORT", html_rep.encode('utf-8'), "report.html")

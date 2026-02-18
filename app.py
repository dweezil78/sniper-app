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

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []
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
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API & PARSING ELASTICO
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
            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
            if bid == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))
            if ("1st" in name or "first" in name or "1h" in name) and ("goals" in name or "over/under" in name):
                for x in b.get("values", []):
                    v_val = str(x.get("value") or "").lower().replace(" ", "")
                    if "over0.5" in v_val and data["o05ht"] == 0: data["o05ht"] = float(x.get("odd") or 0)
                    if "over1.5" in v_val and data["o15ht"] == 0: data["o15ht"] = float(x.get("odd") or 0)
            is_btts = ("both" in name and "team" in name) or "btts" in name
            is_score = "score" in name or "to score" in name or "btts" in name
            is_fh = "1st" in name or "first" in name or "1h" in name or "half" in name
            if bid == 71 or (is_btts and is_score and is_fh):
                if data["gg_ht"] == 0:
                    for x in b.get("values", []):
                        v_label = str(x.get("value") or "").strip().lower()
                        if v_label in ["yes", "si", "oui"] or "yes" in v_label:
                            data["gg_ht"] = float(x.get("odd") or 0); break
        if data["q1"] > 0 and data["gg_ht"] > 0 and data["o15ht"] > 0: break
    return data

# ============================
# LOGICA STATISTICA INTEGRATA (NUOVA)
# ============================
team_stats_cache = {}

def get_comprehensive_stats(session, tid):
    """Analisi unica: HT Ratio, Vulnerabilità (Goal subiti) e Dry Rebound"""
    if tid in team_stats_cache: return team_stats_cache[tid]
    try:
        rx = api_get(session, "fixtures", {"team": tid, "last": 5, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}
        
        ht_hits = 0
        conceded_hits = 0
        goals_scored_list = []
        
        for f in fx:
            # HT Ratio (Goal totali nel primo tempo >= 1)
            h_score = f.get("score",{}).get("halftime",{}).get("home") or 0
            a_score = f.get("score",{}).get("halftime",{}).get("away") or 0
            if (h_score + a_score) >= 1: ht_hits += 1
            
            # Vulnerabilità (La squadra ha subito goal?)
            is_home = (f["teams"]["home"]["id"] == tid)
            g_subiti = f["goals"]["away"] if is_home else f["goals"]["home"]
            if (g_subiti or 0) > 0: conceded_hits += 1
            
            # Per Dry Rebound
            g_fatti = f["goals"]["home"] if is_home else f["goals"]["away"]
            goals_scored_list.append(int(g_fatti or 0))

        # Check Dry Rebound Strict
        is_dry = False
        if len(goals_scored_list) >= 5 and goals_scored_list[0] == 0:
            if sum(1 for g in goals_scored_list if g >= 1) >= 4:
                is_dry = True

        res = {
            "ht_ratio": ht_hits / len(fx),
            "vulnerability": conceded_hits / len(fx),
            "is_dry": is_dry
        }
        team_stats_cache[tid] = res
        return res
    except: return {"ht_ratio": 0.0, "vulnerability": 0.0, "is_dry": False}

def is_allowed_league(league_name, league_country, blocked_user, forced_user):
    name, country = str(league_name or "").lower(), str(league_country or "").strip()
    banned = ["women", "femminile", "u19", "u20", "u21", "u23", "primavera", "youth", "reserve", "friendly"]
    if any(t in name for t in banned): return False
    return True # Tutti i campionati ammessi come da tua richiesta

def calculate_rating(fid, q1, qx, q2, o25, o05ht, snap_data, max_q_gold, inv_margin):
    sc, det = 40, []
    is_gold = (1.40 <= min(q1, q2) <= max_q_gold) if q1 > 0 and q2 > 0 else False
    fid_s, into_trap = str(fid), False
    if fid_s in snap_data:
        old = snap_data[fid_s]
        old_fav, cur_fav = min(old.get("q1", 0), old.get("q2", 0)), min(q1, q2)
        if (old_fav - cur_fav) >= 0.15: sc += 40; det.append("Drop")
        if abs(q1-q2) >= inv_margin:
            fav_snap = "1" if old.get("q1",0) < old.get("q2",0) else "2"
            if (fav_snap == "1" and q2 < q1) or (fav_snap == "2" and q1 < q2): sc += 25; det.append("Inv")
        if cur_fav < 1.40 and old_fav >= 1.40: into_trap = True
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    return min(100, sc), det, is_gold, into_trap

# ============================
# CORE ENGINE
# ============================
def execute_full_scan(session, fixtures, snap_mem, min_rating, max_q_gold, inv_margin):
    results, pb = [], st.progress(0)
    status_txt = st.empty()
    for i, m in enumerate(fixtures):
        pb.progress((i+1)/len(fixtures))
        status_txt.text(f"Analisi GG PT: {m['teams']['home']['name']}...")
        try:
            mk = extract_markets_pro(api_get(session, "odds", {"fixture": m["fixture"]["id"]}))
            if not mk or mk["q1"] <= 0: continue
            
            # Calcolo Rating e Parametri Base
            rating, det, is_gold, into_trap = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], snap_mem, max_q_gold, inv_margin)
            
            h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
            s_home = get_comprehensive_stats(session, h_id)
            s_away = get_comprehensive_stats(session, a_id)

            # Logica Favorita/Underdog per Vulnerabilità
            q_fav = min(mk["q1"], mk["q2"])
            is_home_fav = (mk["q1"] < mk["q2"])
            fav_stats = s_home if is_home_fav else s_away
            dog_stats = s_away if is_home_fav else s_home
            fav_id = h_id if is_home_fav else a_id

            advice = "🔥 TARGET: 0.5 HT / 2.5 FT" if is_gold else ""

            # --- ANALISI GG PT / DIAMOND ---
            if s_home["ht_ratio"] >= 0.6 and s_away["ht_ratio"] >= 0.6:
                rating += 20; det.append("HT")
                
                # TRIGGER DIAMOND (Favorita vulnerabile + Dog che segna + Quota Sweet Spot)
                if fav_stats["vulnerability"] >= 0.8 and dog_stats["ht_ratio"] >= 0.6:
                    if 1.70 <= q_fav <= 2.20:
                        rating = min(100, rating + 25)
                        det.append("🎯 GG-PT")
                        advice = "💎 DIAMOND: GG PT / O1.5 HT"
                    else:
                        det.append("GG-PT-POT")
                        advice = "🔥 TARGET: GG PT"

            # Bonus Dry Rebound
            if fav_stats["is_dry"]:
                rating = min(100, rating + 15)
                det.append("DRY 💧")
            
            if rating >= min_rating:
                results.append({
                    "Ora": m["fixture"]["date"][11:16],
                    "Lega": f"{m['league']['name']} ({m['league']['country']})",
                    "Match_Disp_Raw": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}{' *' if into_trap else ''}",
                    "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}",
                    "O2.5 Finale": f"{mk['o25']:.2f}",
                    "O0.5 PT": f"{mk['o05ht']:.2f}",
                    "O1.5 PT": f"{mk['o15ht']:.2f}" if mk["o15ht"] > 0 else "N/D",
                    "GG PT": f"{mk['gg_ht']:.2f}" if mk["gg_ht"] > 0 else "N/D",
                    "Info": f"[{'|'.join(det)}]",
                    "Rating": rating, "Is_Gold": is_gold, "Advice": advice, "Fixture_ID": str(m["fixture"]["id"])
                })
        except: continue
    return results

# ============================
# UI & AZIONI
# ============================
st.sidebar.header("👑 Configurazione Sniper")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
st.session_state["only_gold_ui"] = st.sidebar.toggle("🎯 SOLO SWEET SPOT", value=st.session_state["only_gold_ui"])
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)

oggi = now_rome().strftime("%Y-%m-%d")
col_b1, col_b2 = st.columns(2)

with col_b1:
    if st.button("📌 SNAPSHOT + SCAN (Integrato)"):
        with requests.Session() as s:
            try:
                data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
                fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"], [], [])]
                scan_res = execute_full_scan(s, fixtures, st.session_state.get("odds_memory", {}), min_rating, max_q_gold, inv_margin)
                new_snap = {r["Fixture_ID"]: {"q1": float(r["1X2"].split("|")[0]), "q2": float(r["1X2"].split("|")[2])} for r in scan_res}
                st.session_state["odds_memory"], st.session_state["snap_time_obj"] = new_snap, now_rome()
                st.session_state["scan_results"] = scan_res
                with open(JSON_FILE, "w") as f: json.dump({"date": oggi, "timestamp": now_rome().isoformat(), "odds": new_snap}, f)
                st.rerun()
            except Exception as e: st.error(f"Errore: {e}")

with col_b2:
    if st.button("🚀 AVVIA SOLO SCANNER (Live)"):
        with requests.Session() as s:
            try:
                data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
                fixtures = [f for f in data.get("response", []) if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"], [], [])]
                st.session_state["scan_results"] = execute_full_scan(s, fixtures, st.session_state["odds_memory"], min_rating, max_q_gold, inv_margin)
                st.rerun()
            except Exception as e: st.error(f"Errore: {e}")

# ============================
# RENDERING TABELLA (ORDINE FISSO)
# ============================
if st.session_state["scan_results"]:
    df = pd.DataFrame(st.session_state["scan_results"])
    df = df[df["Is_Gold"]] if st.session_state["only_gold_ui"] else df
    
    if not df.empty:
        df["Match Disponibili"] = df.apply(lambda r: f"<div class='match-cell'>{'💎 ' if 'DIAMOND' in r['Advice'] else '👑 ' if r['Is_Gold'] else ''}{r['Match_Disp_Raw']}<span class='advice-tag'>{r['Advice']}</span></div>", axis=1)
        df["Rating_Bold"] = df["Rating"].apply(lambda x: f"<b>{x}</b>")
        
        cols_final = ["Ora", "Lega", "Match Disponibili", "1X2", "O2.5 Finale", "O0.5 PT", "O1.5 PT", "GG PT", "Info", "Rating_Bold"]
        df_display = df[cols_final].copy()
        
        def style_rows(row):
            idx = row.name
            r_val, is_gold, info = df.loc[idx, "Rating"], df.loc[idx, "Is_Gold"], df.loc[idx, "Info"]
            if "GG-PT" in info: return ['background-color: #38003c; color: #00e5ff; font-weight: bold;'] * len(row) # Stile Diamond/GG PT
            if r_val >= 85: return ['background-color: #1b4332; color: #ffffff; font-weight: bold;'] * len(row)
            elif is_gold or r_val >= 75 or "DRY" in info: return ['background-color: #2d6a4f; color: #ffffff; font-weight: bold;'] * len(row)
            return [''] * len(row)

        st.write(df_display.style.apply(style_rows, axis=1).to_html(escape=False, index=False), unsafe_allow_html=True)
        
        # Export Buttons
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: st.download_button("💾 CSV PER AUDITOR", data=df.to_csv(index=False).encode('utf-8'), file_name=f"auditor.csv")
        with c2: st.download_button("🌐 REPORT HTML", data=df.to_html().encode('utf-8'), file_name=f"report.html")
        with c3: 
            if os.path.exists(LOG_CSV): st.download_button("🗂️ DATABASE STORICO", data=open(LOG_CSV,"rb").read(), file_name="sniper_history_log.csv")
                

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

# ============================
# TIMEZONE & SESSION STATE
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

st.set_page_config(page_title="ARAB SNIPER V15.47 - GOLD MASTER", layout="wide")

if "odds_memory" not in st.session_state: st.session_state["odds_memory"] = {}
if "snap_time_obj" not in st.session_state: st.session_state["snap_time_obj"] = None
if "scan_results" not in st.session_state: st.session_state["scan_results"] = None
if "found_countries" not in st.session_state: st.session_state["found_countries"] = []

# ============================
# PRELOAD SNAPSHOT
# ============================
snap_status_msg = "⚠️ Nessun Snapshot salvato per oggi"
snap_status_type = "warning"

if os.path.exists(JSON_FILE) and not st.session_state["odds_memory"]:
    try:
        with open(JSON_FILE, "r") as f:
            _d = json.load(f)
            if _d.get("date") == now_rome().strftime("%Y-%m-%d"):
                st.session_state["odds_memory"] = _d.get("odds", {})
                ts = _d.get("timestamp")
                if ts: st.session_state["snap_time_obj"] = datetime.fromisoformat(ts)
                st.session_state["found_countries"] = sorted({v.get("country") for v in st.session_state["odds_memory"].values() if v.get("country")})
    except: pass

if st.session_state["snap_time_obj"]:
    snap_status_msg = f"✅ Snapshot ATTIVO (Ore {st.session_state['snap_time_obj'].strftime('%H:%M')})"
    snap_status_type = "success"

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; }
            table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 8px; text-align: center; border: 1px solid #444; }
            td { padding: 5px 8px; border: 1px solid #ccc; text-align: center; font-weight: 600; white-space: nowrap; }
            .match-cell { text-align: left !important; min-width: 180px; font-weight: 700; color: inherit !important; }
            .advice-tag { display: block; font-size: 0.65rem; color: #00e5ff; font-style: italic; margin-top: 2px; }
            .details-inline { font-size: 0.7rem; font-weight: 800; opacity: 0.9; margin-left: 5px; color: inherit !important; }
            .diag-box { padding: 12px; background: #1a1c23; color: #00e5ff; border-radius: 8px; margin-bottom: 15px; font-family: monospace; font-size: 0.85rem; border: 1px solid #00e5ff; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# API & STATS ENGINES
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    js = r.json()
    if js.get("errors"): raise RuntimeError(f"API Errors: {js['errors']}")
    return js

ht_cache, dry_cache = {}, {}
def get_stats(session, tid, mode="ht"):
    cache = ht_cache if mode=="ht" else dry_cache
    if tid in cache: return cache[tid]
    try:
        limit = 5 if mode == "ht" else 1
        rx = api_get(session, "fixtures", {"team": tid, "last": limit, "status": "FT"})
        fx = rx.get("response", [])
        if not fx: return 0.0
        if mode == "ht":
            res = sum([1 for f in fx if (f.get("score",{}).get("halftime",{}).get("home") or 0) + (f.get("score",{}).get("halftime",{}).get("away") or 0) >= 1]) / len(fx)
        else:
            goals = fx[0]["goals"]["home"] if fx[0]["teams"]["home"]["id"] == tid else fx[0]["goals"]["away"]
            res = 1.0 if (int(goals or 0) == 0) else 0.0
        cache[tid] = res
        return res
    except: return 0.0

def extract_markets_pro(resp_json):
    resp = resp_json.get("response", [])
    if not resp: return None
    data = {"q1":0.0, "qx":0.0, "q2":0.0, "o25":0.0, "o05ht":0.0, "o15ht":0.0, "gg_ht":0.0}
    for bm in resp[0].get("bookmakers", []):
        for b in bm.get("bets", []):
            bid, name = b.get("id"), (b.get("name") or "").lower()

            if bid == 1 and data["q1"] == 0:
                v = b.get("values", [])
                if len(v) >= 3: data["q1"], data["qx"], data["q2"] = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])

            if bid == 5 and data["o25"] == 0:
                data["o25"] = float(next((x["odd"] for x in b.get("values", []) if x["value"] == "Over 2.5"), 0))

            if ("1st" in name or "first" in name or "1h" in name or "half" in name) and ("goals" in name or "over/under" in name):
                for x in b.get("values", []):
                    v_val = (x.get("value") or "").lower().replace(" ", "")
                    if ("over0.5" in v_val or v_val == "over0.5") and data["o05ht"] == 0:
                        data["o05ht"] = float(x.get("odd") or 0)
                    if ("over1.5" in v_val or v_val == "over1.5") and data["o15ht"] == 0:
                        data["o15ht"] = float(x.get("odd") or 0)

            is_btts = ("both" in name and "team" in name) or ("btts" in name)
            is_score = ("score" in name) or ("to score" in name) or ("btts" in name)
            is_fh = ("1st" in name) or ("first" in name) or ("1h" in name) or ("half" in name)
            if bid == 71 or (is_btts and is_score and is_fh):
                if data["gg_ht"] == 0:
                    for x in b.get("values", []):
                        v_label = str(x.get("value") or "").strip().lower()
                        if v_label in ["yes", "si", "oui"] or "yes" in v_label:
                            data["gg_ht"] = float(x.get("odd") or 0); break

        if data["q1"] > 0 and data["o25"] > 0 and data["o05ht"] > 0 and data["o15ht"] > 0 and data["gg_ht"] > 0: break
    return data

def is_allowed_league(league_name, league_country, blocked_user, forced_user):
    name, country = (league_name or "").lower(), (league_country or "").strip()
    banned = ["women", "femminile", "u19", "u20", "u21", "u23", "primavera", "youth", "reserve", "friendly"]
    if any(t in name for t in banned): return False
    if country in forced_user: return True
    if country in blocked_user: return False
    AREAS = {"Italy", "Spain", "France", "Germany", "England", "Portugal", "Netherlands", "Belgium", "Switzerland", "Austria", "Greece", "Turkey", "Scotland", "Denmark", "Norway", "Sweden", "Poland", "Czech Republic", "Slovakia", "Hungary", "Romania", "Croatia", "Serbia", "Brazil", "Argentina", "Uruguay", "Colombia", "Chile", "USA", "Mexico", "Canada", "Japan", "South Korea", "Australia"}
    return country in AREAS

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
            if (fav_snap == "1" and q2 < q1) or (fav_snap == "2" and q1 < q2):
                sc += 25; det.append("Inv")
        if cur_fav < 1.40 and old_fav >= 1.40: into_trap = True
    if 1.70 <= o25 <= 2.15: sc += 20; det.append("Val")
    if 1.30 <= o05ht <= 1.50: sc += 10; det.append("HT-Q")
    return min(100, sc), det, is_gold, into_trap

# ============================
# UI SIDEBAR
# ============================
st.sidebar.header("👑 Configurazione & Legenda")
if snap_status_type == "success": st.sidebar.success(snap_status_msg)
else: st.sidebar.warning(snap_status_msg)

with st.sidebar.expander("📖 LEGENDA SIMBOLI", expanded=True):
    st.markdown("**👑 GOLD**: Favorita 1.40-1.95\n\n**🔄 INV**: Cambio favorito\n\n**📉 Drop**: Crollo quota\n\n**💧💧 DRY**: Favorita a secco\n\n**(*)**: Zona Trap")

min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
max_q_gold = st.sidebar.slider("Sweet Spot Max", 1.70, 2.10, 1.95)
only_gold_ui = st.sidebar.toggle("🎯 SOLO SWEET SPOT (Filtro Live)", value=False)
inv_margin = st.sidebar.slider("Margine inversione", 0.05, 0.30, 0.10, 0.01)
st.sidebar.markdown("---")
blocked_user = st.sidebar.multiselect("🚫 Blocca Paesi", st.session_state.get("found_countries", []), key="blocked_user")
forced_user = st.sidebar.multiselect("✅ Forza Paesi", st.session_state.get("found_countries", []), key="forced_user")

# ============================
# AZIONI SNAPSHOT & SCANSIONE
# ============================
oggi = now_rome().strftime("%Y-%m-%d")

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("📌 SALVA/AGGIORNA SNAPSHOT"):
        with requests.Session() as s:
            try:
                data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
                valid_fx = [m for m in (data.get("response", []) or []) if m['fixture']['status']['short'] == 'NS']
                if not valid_fx: st.warning("Nessun match NS."); st.stop()
                new_snap, pb = {}, st.progress(0)
                txt = st.empty()
                for i, m in enumerate(valid_fx):
                    pb.progress((i+1)/len(valid_fx))
                    txt.text(f"Snapshotting {i+1}/{len(valid_fx)}: {m['teams']['home']['name']}...")
                    mk = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if mk and mk["q1"] > 0: mk["country"] = m["league"]["country"]; new_snap[m["fixture"]["id"]] = mk
                snap_time = now_rome()
                st.session_state["odds_memory"], st.session_state["snap_time_obj"] = new_snap, snap_time
                st.session_state["found_countries"] = sorted({v.get("country") for v in new_snap.values() if v.get("country")})
                with open(JSON_FILE, "w") as f: json.dump({"date": oggi, "timestamp": snap_time.isoformat(), "odds": new_snap}, f)
                st.rerun()
            except Exception as e: st.error(f"Errore: {e}")

if st.button("🚀 AVVIA SCANSIONE MATCH"):
    if not st.session_state["odds_memory"]: st.error("Esegui prima lo Snapshot."); st.stop()
    with requests.Session() as s:
        try:
            all_raw = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"}).get("response", [])
            fixtures = [f for f in all_raw if f["fixture"]["status"]["short"] == "NS" and is_allowed_league(f["league"]["name"], f["league"]["country"], blocked_user, forced_user)]
            results, pb = [], st.progress(0)
            txt = st.empty()
            ball_pool = []
            for i, m in enumerate(fixtures):
                pb.progress((i+1)/len(fixtures))
                txt.text(f"Analisi {i+1}/{len(fixtures)}: {m['teams']['home']['name']}...")
                try:
                    mk = extract_markets_pro(api_get(s, "odds", {"fixture": m["fixture"]["id"]}))
                    if not mk or mk["q1"] <= 0: continue
                    rating, det, is_gold, into_trap = calculate_rating(m["fixture"]["id"], mk["q1"], mk["qx"], mk["q2"], mk["o25"], mk["o05ht"], st.session_state["odds_memory"], max_q_gold, inv_margin)
                    
                    h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
                    ht_ok = False
                    if get_stats(s, h_id, "ht") >= 0.6 and get_stats(s, a_id, "ht") >= 0.6:
                        ht_ok = True
                        rating += 20; det.append("HT")
                        fav_id = h_id if mk["q1"] < mk["q2"] else a_id
                        if get_stats(s, fav_id, "dry") >= 1.0: rating = min(100, rating + 15); det.append("DRY 💧💧")
                    
                    if rating >= min_rating:
                        advice = "🔥 TARGET: 0.5 HT (DRY REBOUND)" if "DRY" in det else "🔥 TARGET: 0.5 HT / 2.5 FT" if is_gold else ""
                        results.append({"Ora": m["fixture"]["date"][11:16], "Lega": f"{m['league']['name']} ({m['league']['country']})", "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}{' *' if into_trap else ''}", "1X2": f"{mk['q1']:.2f}|{mk['qx']:.2f}|{mk['q2']:.2f}", "O2.5": f"{mk['o25']:.2f}", "O0.5HT": f"{mk['o05ht']:.2f}", "Rating": rating, "Info": f"[{'|'.join(det)}]", "Is_Gold": is_gold, "Advice": advice, "Fixture_ID": str(m["fixture"]["id"])})
                        
                        o15 = mk.get("o15ht", 0) or 0
                        gg1t = mk.get("gg_ht", 0) or 0
                        if ht_ok and o15 > 0 and gg1t > 0:
                            if abs(mk.get("q1", 0) - mk.get("q2", 0)) <= 1.10:
                                if 2.20 <= o15 <= 2.80 and 4.20 <= gg1t <= 5.50:
                                    ball_pool.append(str(m["fixture"]["id"]))

                except: continue

            if ball_pool and results:
                top = [r for r in results if r.get("Fixture_ID") in set(ball_pool)]
                top = sorted(top, key=lambda x: x.get("Rating", 0), reverse=True)[:5]
                top_ids = set([t.get("Fixture_ID") for t in top])
                for r in results:
                    if r.get("Fixture_ID") in top_ids:
                        info = r.get("Info","")
                        if info.endswith("]"): r["Info"] = info[:-1] + "|⚽]"
                        else: r["Info"] = info + "⚽"

            st.session_state["scan_results"] = results
            if results:
                new_df = pd.DataFrame(results)
                new_df["Log_Date"] = now_rome().strftime("%Y-%m-%d %H:%M")
                if os.path.exists(LOG_CSV):
                    old = pd.read_csv(LOG_CSV, dtype={"Fixture_ID": str})
                    pd.concat([old, new_df], ignore_index=True).drop_duplicates(subset=["Fixture_ID"]).to_csv(LOG_CSV, index=False)
                else: new_df.to_csv(LOG_CSV, index=False)
        except Exception as e: st.error(f"Errore: {e}")

# ============================
# RENDERING & EXPORT (RIPRISTINATI)
# ============================
if st.session_state["scan_results"]:
    df_raw = pd.DataFrame(st.session_state["scan_results"])
    df_show = df_raw[df_raw["Is_Gold"] == True].copy() if only_gold_ui else df_raw.copy()
    
    def style_rows(row):
        r_val, is_gold, info = row["Rating"], row["Is_Gold"], row["Info"]
        if r_val >= 85: return ['background-color: #1b4332; color: #ffffff; font-weight: bold;'] * len(row)
        elif is_gold or r_val >= 75 or "DRY" in info: return ['background-color: #2d6a4f; color: #ffffff; font-weight: bold;'] * len(row)
        return [''] * len(row)

    if not df_show.empty:
        df_show["Match_Disp"] = df_show.apply(lambda r: f"<div class='match-cell'>{'👑 ' if r['Is_Gold'] else ''}{r['Match']}<span class='advice-tag'>{r['Advice']}</span></div>", axis=1)
        styled = df_show.style.apply(style_rows, axis=1)
        cols = ["Ora", "Lega", "Match_Disp", "1X2", "O2.5", "O0.5HT", "Rating", "Info"]
        st.write(styled.hide(axis="columns", subset=[c for c in df_show.columns if c not in cols]).to_html(escape=False, index=False), unsafe_allow_html=True)

        st.markdown("---")
        col_dl1, col_dl2, col_dl3 = st.columns(3)
        with col_dl1:
            st.download_button("💾 CSV SESSIONE", data=df_raw.to_csv(index=False).encode('utf-8'), file_name=f"session_{oggi}.csv")
        with col_dl2:
            html = df_raw.to_html(escape=False, index=False)
            html_styled = f"<html><head><style>table{{border-collapse:collapse;width:100%;font-family:Arial;}} th,td{{border:1px solid #ddd;padding:8px;text-align:center;}} th{{background-color:#f2f2f2;}}</style></head><body>{html}</body></html>"
            st.download_button("🌐 REPORT HTML", data=html_styled.encode('utf-8'), file_name=f"report_{oggi}.html", mime="text/html")
        with col_dl3:
            if os.path.exists(LOG_CSV):
                with open(LOG_CSV, "rb") as f:
                    st.download_button("🗂️ DATABASE STORICO", data=f.read(), file_name="sniper_history_log.csv")
```0

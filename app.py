import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

# Timezone robust
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

# ============================
# 1) CONFIG PAGINA
# ============================
st.set_page_config(page_title="ARAB SNIPER V13.2", layout="wide")
st.title("🎯 ARAB SNIPER V13.2 - Final Review")
st.markdown("Chronological Order | Market Drop | Offensive Pressure")

# ============================
# 2) CONFIG API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("Manca API_SPORTS_KEY nei Secrets")
    st.stop()

HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = sorted(set([
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42,
    137, 138, 139, 810, 811, 812, 181, 203, 204, 98, 99, 101,
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104,
    283, 284, 285, 197, 198, 71, 72, 73, 128, 129, 118, 144,
    179, 180, 262, 218, 143
]))

EXCLUDE_NAME_TOKENS = ["Women", "Femminile", "U19", "U20", "U21", "U23", "Primavera"]

# ============================
# 3) API HELPERS + CACHE
# ============================
def api_get(session: requests.Session, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600)
def get_spectacle_index(team_id: int) -> float:
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"team": team_id, "last": 5})
    totals = []
    for f in data.get("response", []):
        gh, ga = f.get("goals", {}).get("home"), f.get("goals", {}).get("away")
        if gh is not None and ga is not None:
            totals.append(int(gh) + int(ga))
    return round(sum(totals) / len(totals), 1) if totals else 0.0

@st.cache_data(ttl=6 * 3600)
def get_pressure_stats(team_id: int) -> Tuple[float, float, int]:
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"team": team_id, "last": 5, "status": "FT"})
        fixtures = data.get("response", [])
        if not fixtures: return 0.0, 0.0, 0
        
        shots_list, corners_list = [], []
        with requests.Session() as s_stats:
            for f in fixtures:
                res = api_get(s_stats, "fixtures/statistics", {"fixture": f['fixture']['id'], "team": team_id}).get("response", [])
                if res:
                    stats = {item['type']: item['value'] for item in res[0]['statistics']}
                    s_val = stats.get('Total Shots', 0) or 0
                    c_val = stats.get('Corner Kicks', 0) or 0
                    if s_val or c_val:
                        shots_list.append(int(s_val))
                        corners_list.append(int(c_val))
        
        if not shots_list: return 0.0, 0.0, 0
        return round(sum(shots_list)/len(shots_list), 1), round(sum(corners_list)/len(corners_list), 1), len(shots_list)
    except: return 0.0, 0.0, 0

@st.cache_data(ttl=3600)
def check_last_match_no_goal(team_id: int) -> bool:
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"team": team_id, "last": 1})
        r = data.get("response", [])
        if not r: return False
        is_home = r[0]["teams"]["home"]["id"] == team_id
        return (r[0]["goals"]["home"] if is_home else r[0]["goals"]["away"]) == 0
    except: return False

@st.cache_data(ttl=900)
def get_odds_fixture(fixture_id: int) -> Dict[str, Any]:
    with requests.Session() as s:
        return api_get(s, "odds", {"fixture": fixture_id})

def safe_extract_odds(odds_json: Dict[str, Any]) -> Tuple[float, float, float, float, str]:
    q1 = qx = q2 = q_o25 = 0.0
    drop = "↔️"
    r = odds_json.get("response", [])
    if not r: return q1, qx, q2, q_o25, drop
    
    bookmakers = r[0].get("bookmakers", [])
    if not bookmakers: return q1, qx, q2, q_o25, drop
    
    bets = bookmakers[0].get("bets", [])
    o1x2 = next((b for b in bets if b.get("id") == 1), None)
    if o1x2 and len(o1x2["values"]) >= 3:
        q1, qx, q2 = float(o1x2["values"][0]["odd"]), float(o1x2["values"][1]["odd"]), float(o1x2["values"][2]["odd"])
        if q1 <= 1.80: drop = "🏠📉"
        elif q2 <= 1.90: drop = "🚀📉"

    o25 = next((b for b in bets if b.get("id") == 5), None)
    if o25:
        try: q_o25 = float(next(v["odd"] for v in o25["values"] if v["value"] == "Over 2.5"))
        except: pass
    
    return q1, qx, q2, q_o25, drop

# ============================
# 4) RATING ENGINE
# ============================
def make_rating_cell(rating, details):
    if rating >= 100: bg, txt = "#ff4b4b", "white"
    elif rating >= 85: bg, txt = "#1b4332", "#d8f3dc"
    elif rating >= 70: bg, txt = "#d4edda", "#155724"
    else: bg, txt = "transparent", "inherit"
    
    style = f"background-color: {bg}; color: {txt}; padding: 12px; border-radius: 8px; font-weight: 900; text-align: center; min-width: 60px;"
    res = f"<div style='{style}'>{rating}</div>"
    if details:
        res += "".join([f"<div style='font-size: 0.8em; margin-top: 4px; color: #ccc;'>• {d}</div>" for d in details])
    return res

# ============================
# 5) MAIN
# ============================
st.sidebar.header("⚙️ Filtri")
min_rating = st.sidebar.slider("Rating minimo", 0, 85, 60)

if st.button("🚀 AVVIA ARAB SNIPER V13.2"):
    oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        
        fixtures = [m for m in data.get("response", []) if m["fixture"]["status"]["short"] == "NS" 
                    and not any(x in m["league"]["name"] for x in EXCLUDE_NAME_TOKENS)
                    and (m["league"]["id"] in IDS or m["league"]["country"] == "Italy")]

        if not fixtures:
            st.info("Nessun match trovato.")
            st.stop()

        results = []
        progress = st.progress(0)
        status = st.empty()

        for i, m in enumerate(fixtures):
            h_id, a_id, f_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"], m["fixture"]["id"]
            h_n, a_n = m["teams"]["home"]["name"], m["teams"]["away"]["name"]
            
            status.text(f"Mirino su: {h_n} - {a_n}")
            progress.progress((i + 1) / len(fixtures))

            q1, qx, q2, q_o25, drop_icon = safe_extract_odds(get_odds_fixture(f_id))
            if 0 < q_o25 < 1.50: continue

            sc, details = 40, []
            
            # Quota
            if 1.80 <= q_o25 <= 2.10: sc += 25; details.append("🎯 +25 Sweet Spot")
            elif 2.11 <= q_o25 <= 2.50: sc += 15; details.append("🎯 +15 Value Zone")
            elif 1.50 <= q_o25 <= 1.79: sc += 5; details.append("🎯 +5 Low Odd")

            # S.I. & Fame
            h_si, a_si = get_spectacle_index(h_id), get_spectacle_index(a_id)
            if 2.2 <= (h_si+a_si)/2 < 3.8: sc += 10; details.append("🔥 +10 SI Medio")
            if check_last_match_no_goal(h_id) or check_last_match_no_goal(a_id): sc += 15; details.append("⚽ +15 Sblocco Goal")
            if h_si >= 3.8 or a_si >= 3.8: sc -= 20; details.append("⚠️ -20 Saturazione")

            # Pressione AVG (C)
            if sc >= 55:
                h_sh, h_co, h_sam = get_pressure_stats(h_id)
                a_sh, a_co, a_sam = get_pressure_stats(a_id)
                if h_sam >= 3 and a_sam >= 3:
                    avg_sh, avg_co = (h_sh+a_sh)/2, (h_co+a_co)/2
                    if avg_sh > 12.5: sc += 10; details.append(f"🏹 +10 Tiri AVG ({avg_sh})")
                    if avg_co > 5.5: sc += 10; details.append(f"🚩 +10 Corner AVG ({avg_co})")

            if sc >= min_rating:
                results.append({
                    "Ora": m["fixture"]["date"][11:16],
                    "Lega": m["league"]["name"],
                    "Match": f"<b>{h_n} - {a_n}</b><br><span style='color:#ffa500;'>{drop_icon}</span>",
                    "S.I.": f"{h_si} | {a_si}",
                    "O2.5": f"<b>{q_o25}</b>" if q_o25 > 0 else "",
                    "Rating": make_rating_cell(sc, details)
                })

        status.empty(); progress.empty()
        
        if results:
            df = pd.DataFrame(results).sort_values("Ora") # ORDINAMENTO ORARIO
            st.markdown("""<style>table { width: 100%; border-collapse: collapse; } 
                        th, td { padding: 12px; border: 1px solid #333; vertical-align: top; text-align: left; }
                        th { background: #1a1c23; color: white; position: sticky; top: 0; }</style>""", unsafe_allow_html=True)
            st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else: st.info("Nessun match Elite.")
    except Exception as e: st.error(f"Errore: {e}")

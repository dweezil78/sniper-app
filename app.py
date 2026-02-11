import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Tuple

# ============================
# 1) CONFIG PAGINA
# ============================
st.set_page_config(page_title="ARAB SNIPER", layout="wide")
st.title("🎯 ARAB SNIPER - Goal Hunter Version")
st.markdown("Elite Selection: Market Drop & 'Fame di Goal' Analysis")

# ============================
# 2) CONFIG API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("Manca API_SPORTS_KEY nei Secrets di Streamlit")
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
        gh = f.get("goals", {}).get("home")
        ga = f.get("goals", {}).get("away")
        if gh is not None and ga is not None:
            totals.append(int(gh) + int(ga))
    return round(sum(totals) / len(totals), 1) if totals else 0.0

@st.cache_data(ttl=3600)
def check_last_match_no_goal(team_id: int) -> bool:
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"team": team_id, "last": 1})
        r = data.get("response", [])
        if not r:
            return False
        is_home = r[0]["teams"]["home"]["id"] == team_id
        goals = r[0]["goals"]["home"] if is_home else r[0]["goals"]["away"]
        return goals == 0
    except Exception:
        return False

@st.cache_data(ttl=900)
def get_odds_fixture(fixture_id: int) -> Dict[str, Any]:
    with requests.Session() as s:
        return api_get(s, "odds", {"fixture": fixture_id})

def safe_extract_odds(odds_json: Dict[str, Any]) -> Tuple[float, float, float, float]:
    q1 = qx = q2 = q_o25 = 0.0
    r = odds_json.get("response", [])
    if not r:
        return q1, qx, q2, q_o25
    bookmakers = r[0].get("bookmakers", [])
    for bm in bookmakers:
        bets = bm.get("bets", [])
        if not bets:
            continue
        o1x2 = next((b for b in bets if b.get("id") == 1), None)
        if o1x2 and len(o1x2.get("values", [])) >= 3:
            try:
                q1, qx, q2 = map(float, [o1x2["values"][0]["odd"],
                                         o1x2["values"][1]["odd"],
                                         o1x2["values"][2]["odd"]])
            except Exception:
                pass
        o25 = next((b for b in bets if b.get("id") == 5), None)
        if o25:
            try:
                q_o25 = float(next(v["odd"] for v in o25["values"] if v["value"] == "Over 2.5"))
            except Exception:
                pass
        break
    return q1, qx, q2, q_o25

# ============================
# 4) RATING ENGINE
# ============================
def score_match(h_si, a_si, q1, q2, q_o25, h_fame, a_fame):
    sc = 40
    details = []
    d_icon = "↔️"

    if 0 < q_o25 < 1.50:
        return 0, "🚫", ["⚠️ TRAPPOLA <1.50"], True

    if q1 and q2:
        if q1 <= 1.80:
            sc += 20
            d_icon = "🏠📉"
            details.append("🏠 +20 Fav casa")
        elif q2 <= 1.90:
            sc += 25
            d_icon = "🚀📉"
            details.append("🚀 +25 Fav trasferta")

    if 1.50 <= q_o25 <= 2.15:
        sc += 15
        details.append("🎯 +15 O2.5 value")
        if 2.2 <= (h_si + a_si) / 2 < 3.8:
            sc += 10
            details.append("🔥 +10 SI medio")

    if h_fame or a_fame:
        sc += 15
        details.append("⚽ +15 Fame di goal")

    if h_si >= 3.8 or a_si >= 3.8:
        sc -= 20
        details.append("⚠️ -20 Saturazione")

    sc = int(max(0, min(100, sc)))
    return sc, d_icon, details, False

def make_rating_cell(rating, details):
    if rating >= 100:
        bg_color = "#ff4b4b" 
        text_color = "white"
    elif rating >= 85:
        bg_color = "#1b4332" 
        text_color = "#d8f3dc"
    elif rating >= 70:
        bg_color = "#d4edda" 
        text_color = "#155724"
    else:
        bg_color = "transparent"
        text_color = "inherit"

    style = f"background-color: {bg_color}; color: {text_color}; padding: 10px; border-radius: 5px; font-weight: bold;"
    cell_content = f"<div style='{style}'>{rating}</div>"
    if details:
        details_list = "".join([ f"<div style='font-size: 0.8em; margin-top: 3px;'>• {d}</div>" for d in details])
        return f"{cell_content}{details_list}"
    return cell_content

# ============================
# 5) UI CONTROLS
# ============================
st.sidebar.header("⚙️ Filtri")
min_rating = st.sidebar.slider("Rating minimo", 0, 85, 60)
hide_traps = st.sidebar.checkbox("Nascondi trappole (<1.50)", True)

# ============================
# 6) MAIN
# ============================
if st.button("🚀 AVVIA ARAB SNIPER"):
    oggi = datetime.now().strftime("%Y-%m-%d")

    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
        fixtures = data.get("response", [])

        # --- FILTRO INIZIALE PER LA BARRA ---
        da_analizzare = []
        for m in fixtures:
            if m["fixture"]["status"]["short"] != "NS": continue
            if any(x in m["league"]["name"] for x in EXCLUDE_NAME_TOKENS): continue
            if not (m["league"]["id"] in IDS or m["league"]["country"] == "Italy"): continue
            da_analizzare.append(m)

        if not da_analizzare:
            st.info("Nessun match trovato per oggi.")
            st.stop()

        results = []
        
        # --- RIPRISTINO PROGRESS BAR ---
        progress_bar = st.progress(0)
        status_text = st.empty()
        total_matches = len(da_analizzare)

        for i, m in enumerate(da_analizzare):
            h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
            h_n, a_n = m["teams"]["home"]["name"], m["teams"]["away"]["name"]

            # Feedback visivo
            status_text.text(f"Analisi {i+1}/{total_matches}: {h_n} - {a_n}")
            progress_bar.progress((i + 1) / total_matches)

            h_si = get_spectacle_index(h_id)
            a_si = get_spectacle_index(a_id)
            h_fame = check_last_match_no_goal(h_id)
            a_fame = check_last_match_no_goal(a_id)

            q1, qx, q2, q_o25 = safe_extract_odds(get_odds_fixture(m["fixture"]["id"]))

            rating, drop, details, trap = score_match(h_si, a_si, q1, q2, q_o25, h_fame, a_fame)

            if trap and hide_traps: continue
            if not trap and rating < min_rating: continue

            icon = "⚽" if (h_fame or a_fame) else "🔥" if 2.2 <= (h_si + a_si) / 2 < 3.8 else "↔️"
            if h_si >= 3.8 or a_si >= 3.8: icon = "⚠️"

            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Lega": m["league"]["name"],
                "Match": f"{icon} {h_n} - {a_n}",
                "S.I.": f"{h_si} | {a_si}",
                "Drop": drop,
                "O2.5": q_o25 if q_o25 > 0 else "",
                "Rating": make_rating_cell(rating, details),
                "Rating_Num": rating
            })

        # Pulizia status a fine processo
        status_text.empty()
        progress_bar.empty()

        if not results:
            st.info("Nessun match ha superato i filtri di Rating.")
            st.stop()

        df = pd.DataFrame(results).sort_values("Rating_Num", ascending=False)
        df = df.drop(columns=["Rating_Num"])

        st.markdown(
            """
            <style>
            table { width: 100%; border-collapse: collapse; background-color: #0e1117; color: white; }
            th, td { padding: 12px; border: 1px solid #444; vertical-align: top; text-align: left; }
            td { white-space: normal !important; }
            th { background: #1a1c23; color: #ffffff; position: sticky; top: 0; }
            tr:hover { background-color: #262730; }
            </style>
            """,
            unsafe_allow_html=True
        )

        st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Errore: {e}")

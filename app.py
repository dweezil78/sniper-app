import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import base64
from typing import Any, Dict, List, Tuple

# ============================
# 1) CONFIG PAGINA
# ============================
st.set_page_config(page_title="ARAB SNIPER V14.1", layout="wide")
st.title("🎯 ARAB SNIPER V14.1 - Full Match Analyst")
st.markdown("Analisi contemporanea **Over 2.5** + **BTTS** con rilevamento **Market Drop**.")

# ============================
# 2) CONFIG API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = sorted(set([135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, 137, 138, 139, 810, 811, 812, 181, 203, 204, 98, 99, 101, 106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, 283, 284, 285, 197, 198, 71, 72, 73, 128, 129, 118, 144, 179, 180, 262, 218, 143]))

# ============================
# 3) HELPERS
# ============================
def get_table_download_link(html_content: str, filename: str):
    b64 = base64.b64encode(html_content.encode()).decode()
    return f'<a href="data:text/html;base64,{b64}" download="{filename}" style="text-decoration:none;"><button style="padding:10px 20px; background-color:#1b4332; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">💾 SCARICA ANALISI COMPLETA</button></a>'

@st.cache_data(ttl=3600)
def get_spectacle_index(team_id: int) -> float:
    with requests.Session() as s:
        url = f"https://{HOST}/fixtures"
        r = s.get(url, headers=HEADERS, params={"team": team_id, "last": 5}).json()
    totals = []
    for f in r.get("response", []):
        gh, ga = f.get("goals", {}).get("home"), f.get("goals", {}).get("away")
        if gh is not None and ga is not None: totals.append(int(gh) + int(ga))
    return round(sum(totals) / len(totals), 1) if totals else 0.0

@st.cache_data(ttl=3600)
def team_scored_last_match(team_id: int) -> bool:
    try:
        with requests.Session() as s:
            url = f"https://{HOST}/fixtures"
            r = s.get(url, headers=HEADERS, params={"team": team_id, "last": 1}).json()
        res = r.get("response", [])
        if not res: return True
        is_home = res[0]["teams"]["home"]["id"] == team_id
        g = res[0]["goals"]["home"] if is_home else res[0]["goals"]["away"]
        return g is not None and int(g) > 0
    except: return True

@st.cache_data(ttl=900)
def get_odds(fixture_id: int):
    with requests.Session() as s:
        url = f"https://{HOST}/odds"
        return s.get(url, headers=HEADERS, params={"fixture": fixture_id}).json()

def extract_market_data(odds_json):
    q1 = qx = q2 = q_o25 = 0.0
    drop = "↔️"
    r = odds_json.get("response", [])
    if not r: return q1, qx, q2, q_o25, drop
    
    book = r[0].get("bookmakers", [{}])[0].get("bets", [])
    o1x2 = next((b for b in book if b.get("id") == 1), None)
    if o1x2 and len(o1x2["values"]) >= 3:
        q1, qx, q2 = float(o1x2["values"][0]["odd"]), float(o1x2["values"][1]["odd"]), float(o1x2["values"][2]["odd"])
        if q1 <= 1.70: drop = "🏠📉 (Favorita Casa)"
        elif q2 <= 1.75: drop = "🚀📉 (Favorita Trasferta)"
    
    o25 = next((b for b in book if b.get("id") == 5), None)
    if o25:
        try: q_o25 = float(next(v["odd"] for v in o25["values"] if v.get("value") == "Over 2.5"))
        except: pass
    return q1, qx, q2, q_o25, drop

# ============================
# 4) INTEGRATED RATING ENGINE
# ============================
def get_combined_rating(h_id, a_id, q1, q2, q_o25, h_si, a_si):
    # Logica Over 2.5
    sc_o25, det_o25 = 40, []
    if 0 < q_o25 < 1.50: sc_o25 = 0; det_o25.append("TRAP")
    else:
        if 1.80 <= q_o25 <= 2.10: sc_o25 += 12; det_o25.append("Sweet Q")
        avg_si = (h_si + a_si) / 2
        if 2.4 <= avg_si <= 3.4: sc_o25 += 12; det_o25.append("SI OK")
        if q1 > 1.70 and q2 > 1.70: sc_o25 += 6; det_o25.append("Eq.")

    # Logica BTTS
    sc_btts, det_btts = 40, []
    h_fame = not team_scored_last_match(h_id)
    a_fame = not team_scored_last_match(a_id)
    if h_fame and a_fame: sc_btts += 18; det_btts.append("Fame x2")
    elif h_fame or a_fame: sc_btts += 12; det_btts.append("Fame x1")
    if 2.0 <= (h_si+a_si)/2 <= 3.2: sc_btts += 10; det_btts.append("SI OK")
    
    return int(sc_o25), det_o25, int(sc_btts), det_btts

def format_rating(sc, det):
    color = "#1b4332" if sc >= 85 else ("#d4edda" if sc >= 70 else "transparent")
    txt = "white" if sc >= 85 else ("#155724" if sc >= 70 else "inherit")
    return f"<div style='background:{color}; color:{txt}; padding:5px; border-radius:4px; font-weight:bold;'>{sc}</div><div style='font-size:0.7em;'>{', '.join(det)}</div>"

# ============================
# 5) MAIN UI
# ============================
st.sidebar.header("Parametri")
min_r = st.sidebar.slider("Filtro Rating (mostra se almeno uno è >)", 0, 85, 60)

if st.button("🚀 ANALISI TOTALE MATCH"):
    oggi = datetime.now().strftime("%Y-%m-%d")
    with requests.Session() as s:
        data = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"}).json()
    
    fixtures = [m for m in data.get("response", []) if m["fixture"]["status"]["short"] == "NS" and (m["league"]["id"] in IDS or m["league"]["country"] == "Italy")]
    
    results = []
    progress = st.progress(0)
    for i, m in enumerate(fixtures):
        f_id = m["fixture"]["id"]
        h_n, a_n = m["teams"]["home"]["name"], m["teams"]["away"]["name"]
        progress.progress((i+1)/len(fixtures))
        
        q1, qx, q2, q_o25, drop = extract_market_data(get_odds(f_id))
        h_si, a_si = get_spectacle_index(m["teams"]["home"]["id"]), get_spectacle_index(m["teams"]["away"]["id"])
        
        r_o25, d_o25, r_btts, d_btts = get_combined_rating(m["teams"]["home"]["id"], m["teams"]["away"]["id"], q1, q2, q_o25, h_si, a_si)
        
        if r_o25 >= min_r or r_btts >= min_r:
            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Match": f"<b>{h_n} - {a_n}</b><br><span style='color:#ffa500; font-size:0.8em;'>{drop}</span>",
                "O2.5 Rating": format_rating(r_o25, d_o25),
                "BTTS Rating": format_rating(r_btts, d_btts),
                "O2.5 Quota": q_o25,
                "Lega": m["league"]["name"]
            })

    if results:
        df = pd.DataFrame(results).sort_values("Ora")
        html = df.to_html(escape=False, index=False)
        st.markdown(get_table_download_link(html, f"Analisi_Full_{oggi}.html"), unsafe_allow_html=True)
        st.markdown("""<style>table { width:100%; border-collapse:collapse; } th, td { padding:10px; border:1px solid #444; text-align:center; }</style>""", unsafe_allow_html=True)
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.info("Nessun match rilevante.")
    

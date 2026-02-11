import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import base64
from typing import Any, Dict, List, Tuple

# ============================
# 1) CONFIG PAGINA
# ============================
st.set_page_config(page_title="ARAB SNIPER V14.2", layout="wide")
st.title("🎯 ARAB SNIPER V14.2 - Elite Full Engine")
st.markdown("Analisi Integrata: Rating a destra, graduazione di verde e breakdown dettagliato.")

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
def get_download_link(html, filename):
    b64 = base64.b64encode(html.encode()).decode()
    return f'<a href="data:text/html;base64,{b64}" download="{filename}" style="text-decoration:none;"><button style="padding:10px 20px; background-color:#1b4332; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">💾 SCARICA ANALISI COMPLETA</button></a>'

@st.cache_data(ttl=3600)
def get_spectacle_index(team_id: int) -> float:
    with requests.Session() as s:
        r = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": team_id, "last": 5}).json()
    totals = [int(f["goals"]["home"]) + int(f["goals"]["away"]) for f in r.get("response", []) if f.get("goals", {}).get("home") is not None]
    return round(sum(totals) / len(totals), 1) if totals else 0.0

@st.cache_data(ttl=3600)
def team_scored_last(team_id: int) -> bool:
    with requests.Session() as s:
        r = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": team_id, "last": 1}).json()
    res = r.get("response", [])
    if not res: return True
    is_home = res[0]["teams"]["home"]["id"] == team_id
    g = res[0]["goals"]["home"] if is_home else res[0]["goals"]["away"]
    return g is not None and int(g) > 0

@st.cache_data(ttl=900)
def get_odds_data(fixture_id: int):
    with requests.Session() as s:
        return s.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": fixture_id}).json()

def extract_info(odds_json):
    q1 = qx = q2 = q_o25 = 0.0
    drop = "↔️"
    r = odds_json.get("response", [])
    if not r: return q1, qx, q2, q_o25, drop
    bets = r[0].get("bookmakers", [{}])[0].get("bets", [])
    o1x2 = next((b for b in bets if b.get("id") == 1), None)
    if o1x2:
        q1, qx, q2 = float(o1x2["values"][0]["odd"]), float(o1x2["values"][1]["odd"]), float(o1x2["values"][2]["odd"])
        if q1 <= 1.70: drop = "🏠📉 Drop Casa"
        elif q2 <= 1.75: drop = "🚀📉 Drop Trasferta"
    o25 = next((b for b in bets if b.get("id") == 5), None)
    if o25:
        try: q_o25 = float(next(v["odd"] for v in o25["values"] if v.get("value") == "Over 2.5"))
        except: pass
    return q1, qx, q2, q_o25, drop

# ============================
# 4) ENGINE & STYLING
# ============================
def score_engine(h_id, a_id, q1, q2, q_o25, h_si, a_si):
    # Logica Over 2.5
    sc_o25, d_o = 40, []
    if 0 < q_o25 < 1.50: sc_o25 = 0; d_o.append("TRAP")
    else:
        if 1.80 <= q_o25 <= 2.10: sc_o25 += 12; d_o.append("Sweet Q.")
        if 2.4 <= (h_si+a_si)/2 <= 3.4: sc_o25 += 12; d_o.append("SI OK")
    
    # Logica BTTS
    sc_btts, d_b = 40, []
    if not team_scored_last(h_id) or not team_scored_last(a_id): sc_btts += 15; d_b.append("Fame")
    if 2.0 <= (h_si+a_si)/2 <= 3.2: sc_btts += 10; d_b.append("SI OK")
    
    return sc_o25, d_o, sc_btts, d_b

def format_rating_col(sc, det):
    # Didascalia e badge pulito
    details_str = f"<div style='font-size:0.75em; opacity:0.8; margin-top:2px;'>{', '.join(det)}</div>"
    return f"<b>{sc}</b>{details_str}"

def apply_row_style(row):
    # Determina il colore della riga in base al rating massimo tra O2.5 e BTTS
    r_max = max(row['R_O25_VAL'], row['R_BTTS_VAL'])
    if r_max >= 85: return ['background-color: #1b4332; color: white;'] * len(row)
    if r_max >= 70: return ['background-color: #2d6a4f; color: #d8f3dc;'] * len(row)
    return [''] * len(row)

# ============================
# 5) MAIN
# ============================
if st.button("🚀 AVVIA ANALISI"):
    oggi = datetime.now().strftime("%Y-%m-%d")
    with requests.Session() as s:
        data = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"}).json()
    
    fixtures = [m for m in data.get("response", []) if m["fixture"]["status"]["short"] == "NS" and (m["league"]["id"] in IDS or m["league"]["country"] == "Italy")]
    
    results = []
    progress = st.progress(0)
    for i, m in enumerate(fixtures):
        f_id = m["fixture"]["id"]
        progress.progress((i+1)/len(fixtures))
        
        q1, qx, q2, q_o25, drop = extract_info(get_odds_data(f_id))
        h_si, a_si = get_spectacle_index(m["teams"]["home"]["id"]), get_spectacle_index(m["teams"]["away"]["id"])
        r_o25, d_o, r_btts, d_b = score_engine(m["teams"]["home"]["id"], m["teams"]["away"]["id"], q1, q2, q_o25, h_si, a_si)
        
        if r_o25 >= 60 or r_btts >= 60:
            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Match": f"<b>{m['teams']['home']['name']} - {m['teams']['away']['name']}</b><br><small style='color:#ffcc00'>{drop}</small>",
                "Lega": m["league"]["name"],
                "S.I.": f"{h_si} | {a_si}",
                "O2.5 Quota": q_o25,
                "R_O25_VAL": r_o25, # di servizio
                "R_BTTS_VAL": r_btts, # di servizio
                "Rating O2.5": format_rating_col(r_o25, d_o),
                "Rating BTTS": format_rating_col(r_btts, d_b)
            })

    if results:
        df = pd.DataFrame(results).sort_values("Ora")
        
        # Rendering con righe colorate
        st.markdown(get_download_link(df.to_html(escape=False, index=False), f"Report_{oggi}.html"), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Visualizzazione tabella Streamlit con stili
        styled_df = df.style.apply(apply_row_style, axis=1)
        st.write(styled_df.to_html(escape=False, index=False), unsafe_allow_html=True)
        
        st.markdown("""
        <style>
            table { width: 100%; border-collapse: collapse; font-family: sans-serif; }
            th { background-color: #1a1c23; color: white; padding: 12px; text-align: left; }
            td { padding: 12px; border-bottom: 1px solid #444; vertical-align: top; }
        </style>
        """, unsafe_allow_html=True)
    else:
        st.info("Nessun match rilevante trovato.")

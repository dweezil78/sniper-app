import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import base64
from typing import Any, Dict, List, Tuple, Optional

# Timezone robust
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

# ============================
# 1) CONFIG PAGINA E STILI
# ============================
st.set_page_config(page_title="ARAB SNIPER V14.6", layout="wide")
st.title("🎯 ARAB SNIPER V14.6 - Elite Synthetix")

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #0e1117; }
            table { width: 100%; border-collapse: collapse; color: white; margin-bottom: 20px; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 12px; text-align: center; border: 1px solid #444; }
            td { padding: 12px; border: 1px solid #333; vertical-align: top; text-align: center; }
            .match-cell { text-align: left !important; font-weight: bold; }
            .rating-box { padding: 8px; border-radius: 6px; font-weight: 900; font-size: 1.05em; }
            .details-text { font-size: 0.78em; margin-top: 6px; line-height: 1.25; opacity: 0.9; text-align: left; }
            .tag { font-size: 0.82em; font-weight: 800; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# 2) CONFIG API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = sorted(set([135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, 137, 138, 139, 810, 811, 812, 181, 203, 204, 98, 99, 101, 106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, 283, 284, 285, 197, 198, 71, 72, 73, 128, 129, 118, 144, 179, 180, 262, 218, 143]))

# ============================
# 3) HELPERS & CACHE
# ============================
@st.cache_data(ttl=3600)
def get_team_metrics(team_id: int):
    with requests.Session() as s:
        # SI e Fame
        fx_r = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": team_id, "last": 5, "status": "FT"}).json()
    
    fx = fx_r.get("response", [])
    if not fx: return 0.0, 0.0, 0.0, False
    
    # SI (Media Gol)
    goals = [int(f["goals"]["home"]) + int(f["goals"]["away"]) for f in fx if f["goals"]["home"] is not None]
    avg_si = round(sum(goals)/len(goals), 1) if goals else 0.0
    
    # Fame (Ultima a secco)
    last = fx[0]
    is_h = last["teams"]["home"]["id"] == team_id
    fame = int(last["goals"]["home"] if is_h else last["goals"]["away"]) == 0
    
    # Stats (Tiri/Corner)
    shots, corners = [], []
    with requests.Session() as s2:
        for f in fx[:3]: # Campione di 3 per velocità
            st_r = s2.get(f"https://{HOST}/fixtures/statistics", headers=HEADERS, params={"fixture": f["fixture"]["id"], "team": team_id}).json()
            if st_r.get("response"):
                smap = {x["type"]: x["value"] for x in st_r["response"][0]["statistics"]}
                shots.append(int(smap.get("Total Shots", 0) or 0))
                corners.append(int(smap.get("Corner Kicks", 0) or 0))
                
    avg_sh = sum(shots)/len(shots) if shots else 0
    avg_co = sum(corners)/len(corners) if corners else 0
    return avg_sh, avg_co, avg_si, fame

@st.cache_data(ttl=900)
def fetch_odds(fixture_id: int):
    with requests.Session() as s:
        return s.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": fixture_id}).json()

def get_download_link(html, filename):
    b64 = base64.b64encode(html.encode()).decode()
    return f'<a href="data:text/html;base64,{b64}" download="{filename}" style="text-decoration:none;"><button style="padding:10px 20px; background-color:#1b4332; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">💾 SCARICA ANALISI COMPLETA</button></a>'

# ============================
# 4) UNIFIED ENGINE V14.6
# ============================
def unified_engine(m, q1, q2, q_o25):
    h_sh, h_co, h_si, h_fa = get_team_metrics(m["teams"]["home"]["id"])
    a_sh, a_co, a_si, a_fa = get_team_metrics(m["teams"]["away"]["id"])
    
    # Stats Favorita
    is_h_fav = q1 < q2
    f_sh, f_co = (h_sh, h_co) if is_h_fav else (a_sh, a_co)
    avg_si = (h_si + a_si) / 2

    # Motori
    sc_o, sc_g = 40, 40
    d_o, d_g = [], []
    
    # 1. Bonus Favorita (Casa/Trasferta)
    if 1.60 <= q1 <= 1.85:
        sc_o += 10; sc_g += 10; d_o.append("Fav. Casa (+10)"); d_g.append("Fav. Casa (+10)")
    elif 1.60 <= q2 <= 1.85:
        sc_o += 15; sc_g += 15; d_o.append("Fav. Trasf. (+15)"); d_g.append("Fav. Trasf. (+15)")

    # 2. Pressione (Uniformato)
    t_ok, c_ok = f_sh > 12.5, f_co > 5.5
    p_v = 15 if (t_ok and c_ok) else (8 if t_ok else (7 if c_ok else 0))
    if p_v > 0:
        lab = f"Press. {'Totale' if p_v==15 else ('Tiri' if p_v==8 else 'Corn')} (+{p_v})"
        sc_o += p_v; d_o.append(lab); sc_g += p_v; d_g.append(lab)

    # 3. SI & Fame
    if 2.4 <= avg_si <= 3.4: sc_o += 15; d_o.append("SI OK (+15)")
    if h_fa or a_fa: sc_g += 5; d_g.append("Fame (+5)")

    # 4. Sinergia
    diff = abs(sc_o - sc_g)
    lo, lg = "", ""
    if diff <= 10:
        sc_o += 5; sc_g += 5
        d_o.append("COMBO (+5)"); d_g.append("COMBO (+5)")
    elif sc_o > sc_g + 20: lo = "<br><span class='tag' style='color:#00e5ff;'>🎯 SOLO OVER</span>"
    elif sc_g > sc_o + 20: lg = "<br><span class='tag' style='color:#ff80ab;'>🎯 SOLO GG</span>"

    if 0 < q_o25 < 1.50: sc_o = 0
    return sc_o, d_o, sc_g, d_g, lo, lg, f"{f_sh} tiri | {f_co} corn"

# ============================
# 5) RENDERING & STYLE
# ============================
def apply_row_style(row):
    r_max = max(row['RO_VAL'], row['RG_VAL'])
    if r_max >= 85: return ['background-color: #1b4332; color: white;'] * len(row)
    if r_max >= 70: return ['background-color: #2d6a4f; color: #d8f3dc;'] * len(row)
    return [''] * len(row)

def render_rating_html(sc, det, label):
    details = "".join([f"<div>• {d}</div>" for d in det])
    return f"<div class='rating-box'>{sc}{label}<div class='details-text'>{details}</div></div>"

# ============================
# 6) MAIN EXECUTION
# ============================
st.sidebar.header("⚙️ Settings V14.6")
min_r = st.sidebar.slider("Rating Minimo", 0, 85, 60)

if st.button("🚀 AVVIA ELITE SNIPER"):
    oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
    with requests.Session() as s:
        data = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"}).json()
    
    fixtures = [f for f in (data.get("response", []) or []) if f["fixture"]["status"]["short"] == "NS" and (f["league"]["id"] in IDS or f["league"]["country"] == "Italy")]
    
    if not fixtures: st.info("Nessun match."); st.stop()

    results = []
    progress = st.progress(0)
    for i, m in enumerate(fixtures):
        progress.progress((i+1)/len(fixtures))
        q1, qx, q2, q_o25 = 0.0, 0.0, 0.0, 0.0
        odds_res = fetch_odds(m["fixture"]["id"])
        if odds_res.get("response"):
            bets = odds_res["response"][0].get("bookmakers", [{}])[0].get("bets", [])
            o1x2 = next((b for b in bets if b["id"] == 1), None)
            if o1x2: q1, q2 = float(o1x2["values"][0]["odd"]), float(o1x2["values"][2]["odd"])
            o25 = next((b for b in bets if b["id"] == 5), None)
            if o25: q_o25 = float(next(v["odd"] for v in o25["values"] if v["value"] == "Over 2.5"))

        ro, do, rg, dg, lo, lg, stats = unified_engine(m, q1, q2, q_o25)
        
        if ro >= min_r or rg >= min_r:
            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Match": f"<div class='match-cell'>{m['teams']['home']['name']} - {m['teams']['away']['name']}<br><span style='color:#ffcc00; font-size:0.8em;'>{stats}</span></div>",
                "Lega": m["league"]["name"],
                "Over 2.5": render_rating_html(ro, do, lo),
                "BTTS (GG)": render_rating_html(rg, dg, lg),
                "RO_VAL": ro, "RG_VAL": rg # Di servizio
            })

    if results:
        df = pd.DataFrame(results).sort_values("Ora")
        styled_html = df.drop(columns=["RO_VAL", "RG_VAL"]).style.apply(apply_row_style, axis=1).to_html(escape=False, index=False)
        st.markdown(get_download_link(styled_html, f"Elite_Sniper_{oggi}.html"), unsafe_allow_html=True)
        st.markdown(styled_html, unsafe_allow_html=True)
        

import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import base64
from typing import Any, Dict, List, Tuple, Optional

# Timezone
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

# ============================
# 1) CONFIG PAGINA E STILI V15.1
# ============================
st.set_page_config(page_title="ARAB SNIPER V 15.1", layout="wide")
st.title("🎯 ARAB SNIPER V 15.1 - Professional Summary")

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #f0f2f6; } /* Sfondo app leggermente più chiaro */
            table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-family: 'Segoe UI', sans-serif; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 15px; text-align: center; border: 1px solid #444; }
            
            /* CELLE STANDARD: Testo scuro per massima leggibilità */
            td { padding: 12px; border: 1px solid #ccc; vertical-align: middle; text-align: center; color: #1a1c23 !important; font-weight: 500; }
            
            /* CELLE COLORATE: Testo bianco */
            .rating-badge { padding: 10px; border-radius: 8px; font-weight: 900; font-size: 1.2em; display: inline-block; min-width: 54px; color: #ffffff !important; }
            .match-cell { text-align: left !important; min-width: 260px; color: #1a1c23 !important; }
            
            .summary-box { background-color: #1a1c23; color: #ffffff; padding: 10px; border-radius: 5px; font-weight: bold; font-size: 0.9em; }
            .drop-tag { color: #d68910; font-size: 0.85em; font-weight: bold; margin-top: 4px; display: block; }
            .stats-tag { color: #117a65; font-size: 0.8em; font-weight: bold; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# 2) CONFIG API (Vecchio Sistema Ricerca)
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# Lista campionati estesa (Vecchio Arab Sniper)
IDS = sorted(set([
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42,
    137, 138, 139, 810, 811, 812, 181, 203, 204, 98, 99, 101,
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104,
    283, 284, 285, 197, 198, 71, 72, 73, 128, 129, 118, 144,
    179, 180, 262, 218, 143
]))

# ============================
# 3) HELPERS & CACHE
# ============================
@st.cache_data(ttl=3600)
def get_metrics(team_id: int):
    with requests.Session() as s:
        r = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": team_id, "last": 5, "status": "FT"}).json()
    fx = r.get("response", [])
    if not fx: return 0.0, 0.0, 0.0, False
    avg_si = round(sum([int(f["goals"]["home"]) + int(f["goals"]["away"]) for f in fx if f["goals"]["home"] is not None])/len(fx), 1)
    is_h = fx[0]["teams"]["home"]["id"] == team_id
    fame = int(fx[0]["goals"]["home"] if is_h else fx[0]["goals"]["away"]) == 0
    shots, corners = [], []
    with requests.Session() as s2:
        for f in fx[:3]:
            st_r = s2.get(f"https://{HOST}/fixtures/statistics", headers=HEADERS, params={"fixture": f["fixture"]["id"], "team": team_id}).json()
            if st_r.get("response"):
                smap = {x["type"]: x["value"] for x in st_r["response"][0]["statistics"]}
                shots.append(int(smap.get("Total Shots", 0) or 0)); corners.append(int(smap.get("Corner Kicks", 0) or 0))
    return (sum(shots)/len(shots) if shots else 0), (sum(corners)/len(corners) if corners else 0), avg_si, fame

@st.cache_data(ttl=900)
def fetch_odds(f_id: int):
    with requests.Session() as s: return s.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id}).json()

def get_download_link(html, filename):
    b64 = base64.b64encode(html.encode()).decode()
    return f'<a href="data:text/html;base64,{b64}" download="{filename}" style="text-decoration:none;"><button style="padding:10px 20px; background-color:#1b4332; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">💾 SCARICA ANALISI</button></a>'

# ============================
# 4) ENGINE V15.1
# ============================
def engine_v15_1(m, q1, q2, q_o25):
    h_sh, h_co, h_si, h_fa = get_metrics(m["teams"]["home"]["id"])
    a_sh, a_co, a_si, a_fa = get_metrics(m["teams"]["away"]["id"])
    is_h_fav = q1 < q2
    f_sh, f_co = (h_sh, h_co) if is_h_fav else (a_sh, a_co)
    avg_si = (h_si + a_si) / 2
    drop = "🏠📉 DROP CASA" if q1 <= 1.70 else ("🚀📉 DROP TRASF" if q2 <= 1.75 else "↔️ STABILE")
    
    sc_o, sc_g = 40, 40
    d_o, d_g = [], []
    
    if 1.60 <= q1 <= 1.85: sc_o += 10; sc_g += 10; d_o.append("Fav. Casa (+10)")
    elif 1.60 <= q2 <= 1.85: sc_o += 15; sc_g += 15; d_o.append("Fav. Trasf. (+15)")
    
    t_ok, c_ok = f_sh > 12.5, f_co > 5.5
    p_v = 15 if (t_ok and c_ok) else (8 if t_ok else (7 if c_ok else 0))
    if p_v > 0:
        sc_o += p_v; d_o.append(f"Press. (+{p_v})"); sc_g += p_v; d_g.append(f"Press. (+{p_v})")
        
    if 2.4 <= avg_si <= 3.4: sc_o += 15; d_o.append("SI OK (+15)")
    if h_fa or a_fa: sc_g += 5; d_g.append("Fame (+5)")
    
    if abs(sc_o - sc_g) <= 10: sc_o += 5; sc_g += 5; d_o.append("COMBO (+5)")
    
    if 0 < q_o25 < 1.50: sc_o = 0
    
    # Riepilogo finale
    res_max = max(sc_o, sc_g)
    tipo = "🔥 COMBO" if abs(sc_o - sc_g) <= 5 else ("⚽ GOAL" if sc_g > sc_o else "📈 OVER")
    summary = f"<div class='summary-box'>{tipo}<br>{res_max} pts</div>"
    
    return sc_o, d_o, sc_g, d_g, summary, f"{round(f_sh,1)} tiri | {round(f_co,1)} corn", drop

def render_rating(sc, det):
    bg = "#1b4332" if sc >= 85 else ("#2d6a4f" if sc >= 70 else "transparent")
    color = "#ffffff" if sc >= 70 else "#1a1c23"
    details = "".join([f"<div>• {d}</div>" for d in det])
    return f"<div class='rating-badge' style='background:{bg}; color:{color} !important;'>{sc}</div><div class='details-list' style='color:{color} !important;'>{details}</div>"

# ============================
# 5) MAIN
# ============================
if st.button("🚀 AVVIA ANALISI PROFESSIONAL"):
    oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")
    with requests.Session() as s:
        data = s.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"}).json()
    
    # Filtro Leghe (Vecchio sistema IDS + Italy)
    fixtures = [f for f in (data.get("response", []) or []) if f["fixture"]["status"]["short"] == "NS" and (f["league"]["id"] in IDS or f["league"]["country"] == "Italy")]
    
    results = []
    for i, m in enumerate(fixtures):
        q1, qx, q2, q_o25 = 0.0, 0.0, 0.0, 0.0
        odds_res = fetch_odds(m["fixture"]["id"])
        if odds_res.get("response"):
            try:
                bets = odds_res["response"][0].get("bookmakers", [{}])[0].get("bets", [])
                o1x2 = next((b for b in bets if b["id"] == 1), None)
                if o1x2: q1, qx, q2 = float(o1x2["values"][0]["odd"]), float(o1x2["values"][1]["odd"]), float(o1x2["values"][2]["odd"])
                o25 = next((b for b in bets if b["id"] == 5), None)
                if o25: q_o25 = float(next((v["odd"] for v in o25["values"] if v["value"] == "Over 2.5"), 0))
            except: pass

        ro, do, rg, dg, sum_txt, stats, drop = engine_v15_1(m, q1, q2, q_o25)
        
        if (ro >= 60 or rg >= 60):
            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Match": f"<div class='match-cell'>{m['teams']['home']['name']} - {m['teams']['away']['name']}<br><span class='drop-tag'>{drop}</span><br><span class='stats-tag'>{stats}</span></div>",
                "Lega": m["league"]["name"],
                "1X2": f"<b>{q1} | {qx} | {q2}</b>",
                "Q. O2.5": f"<b>{q_o25}</b>",
                "Rating Over": render_rating(ro, do),
                "Rating GG": render_rating(rg, dg),
                "Riepilogo": sum_txt,
                "R_VAL": max(ro, rg)
            })

    if results:
        df = pd.DataFrame(results).sort_values("Ora")
        def style_rows(row):
            rm = row['R_VAL']
            if rm >= 85: return ['background-color: #1b4332; color: #ffffff !important;'] * len(row)
            if rm >= 70: return ['background-color: #143628; color: #ffffff !important;'] * len(row)
            return ['color: #1a1c23 !important;'] * len(row)

        styler = df.style.apply(style_rows, axis=1).hide(subset=["R_VAL"], axis=1)
        html = styler.to_html(escape=False, index=False)
        st.markdown(get_download_link(html, f"Arab_Sniper_V15.1_{oggi}.html"), unsafe_allow_html=True)
        st.markdown(html, unsafe_allow_html=True)
                    

import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="SNIPER ARAB PRO", layout="wide")

# --- 2. STILE CSS PERSONALIZZATO ---
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #004b23; color: white; font-weight: bold; }
    .stDataFrame { border: 1px solid #e6e9ef; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🎯 SNIPER ARAB V12.8")
st.subheader("Professional Radar: Stats Live & Elite Selection")

# --- 3. CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, 
    137, 138, 139, 810, 811, 812, 181, 
    203, 204, 98, 99, 101, 
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, 
    283, 284, 285, 197, 198, 203, 204, 
    71, 72, 73, 128, 129, 118, 144, 
    179, 180, 262, 218, 143
]

def get_form(team_id):
    """Recupera la media gol delle ultime 5 partite"""
    try:
        res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": team_id, "last": 5})
        matches = res.json().get('response', [])
        if not matches: return "N.D."
        goals = sum([(f['goals']['home'] if f['teams']['home']['id'] == team_id else f['goals']['away']) for f in matches if f['goals']['home'] is not None])
        return round(goals / len(matches), 1)
    except: return "0.0"

def style_rows(row):
    if row.Rating >= 75: return ['background-color: #1b4332; color: #d8f3dc; font-weight: bold'] * len(row)
    elif row.Rating >= 60: return ['background-color: #d8f3dc; color: #081c15'] * len(row)
    elif any(x in str(row.Lega) for x in ["Serie C", "Lega Pro", "Serie B"]): return ['background-color: #caf0f8; color: #03045e'] * len(row)
    return [''] * len(row)

if st.button('🚀 AVVIA ANALISI ARAB PRO'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    try:
        res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
        partite = res.json().get('response', [])
        
        da_analizzare = [
            m for m in partite 
            if (m['league']['id'] in IDS or m['league']['country'] == 'Italy') 
            and m['fixture']['status']['short'] == 'NS'
            and not any(x in m['league']['name'] for x in ["Women", "Femminile", "U19", "U20", "U21", "U23", "Primavera"])
        ]
        
        if not da_analizzare:
            st.warning("Nessun match rilevato per oggi.")
        else:
            results = []
            bar = st.progress(0)
            status = st.empty()
            
            for i, m in enumerate(da_analizzare):
                f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
                h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
                status.text(f"Analisi Pro: {h_n} - {a_n}")
                
                sc = 40
                d_icon, q1, qx, q2, q_o25 = "⚪", 0.0, 0.0, 0.0, 0.0
                
                # --- STATS LIVE (MEDIA GOL) ---
                h_avg = get_form(h_id)
                a_avg = get_form(a_id)
                
                try:
                    r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                    o_data = r_o.json().get('response', [])
                    if o_data:
                        bets = o_data[0]['bookmakers'][0]['bets']
                        o1x2 = next((b for b in bets if b['id'] == 1), None)
                        if o1x2:
                            v = o1x2['values']
                            q1, qx, q2 = float(v[0]['odd']), float(v[1]['odd']), float(v[2]['odd'])
                            if q1 <= 1.80: d_icon, sc = "🏠📉", sc + 20
                            elif q2 <= 1.90: d_icon, sc = "🚀📉", sc + 25

                        o25 = next((b for b in bets if b['id'] == 5), None)
                        if o25:
                            q_o25 = float(next((v['odd'] for v in o25['values'] if v['value'] == 'Over 2.5'), 0))
                            if 1.40 <= q_o25 <= 1.95: sc += 15
                            elif q_o25 > 2.20: sc -= 25
                    else:
                        if m['league']['country'] in ['Italy', 'Australia', 'Japan']: sc = 1
                except: sc = 1

                results.append({
                    "Ora": m['fixture']['date'][11:16],
                    "Lega": m['league']['name'],
                    "Match": f"{h_n} - {a_n}",
                    "Forma (H/A)": f"{h_avg} | {a_avg}",
                    "1X2": f"{q1}|{qx}|{q2}" if q1 > 0 else "N.D.",
                    "Drop": d_icon,
                    "O2.5": q_o25,
                    "Rating": sc
                })
                time.sleep(0.1)
                bar.progress((i+1)/len(da_analizzare))

            if results:
                df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
                st.dataframe(
                    df.style.apply(style_rows, axis=1),
                    use_container_width=True,
                    column_config={
                        "Rating": st.column_config.ProgressColumn("Rating Sniper", format="%d", min_value=0, max_value=100),
                        "Forma (H/A)": st.column_config.TextColumn("⚽ Media Gol (L5)"),
                        "Ora": "⏰", "O2.5": st.column_config.NumberColumn("Quota O2.5", format="%.2f")
                    }
                )
    except Exception as e:
        st.error(f"Errore: {e}")
                    "Forma (H/A)": f"{h_avg} | {a_avg}",

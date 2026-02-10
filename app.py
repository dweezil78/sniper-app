import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="ARAB SNIPER", layout="wide")

st.title("🎯 ARAB SNIPER - Official Version")
st.markdown("Elite Selection: Drop Analysis & Regression Control")

# --- 2. CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# IDS SELEZIONATI (Top Europe + Serie C + Pacific)
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, 
    137, 138, 139, 810, 811, 812, 181, 203, 204, 98, 99, 101, 
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, 
    283, 284, 285, 197, 198, 203, 204, 71, 72, 73, 128, 129, 118, 144, 
    179, 180, 262, 218, 143
]

def get_spectacle_index(team_id):
    """Media totale gol (Fatti + Subiti) ultime 5 partite"""
    try:
        res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": team_id, "last": 5})
        matches = res.json().get('response', [])
        if not matches: return 0.0
        total_g = sum([(f['goals']['home'] + f['goals']['away']) for f in matches if f['goals']['home'] is not None])
        return round(total_g / len(matches), 1)
    except: return 0.0

def style_rows(row):
    """Schema Colori Arab Sniper"""
    if row.Rating >= 85: return ['background-color: #1b4332; color: #d8f3dc; font-weight: bold'] * len(row)
    elif row.Rating >= 70: return ['background-color: #d4edda; color: #155724'] * len(row)
    return [''] * len(row)

# --- 3. LOGICA DI ANALISI ---
if st.button('🚀 AVVIA ARAB SNIPER'):
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
            st.warning("Nessun match rilevato per i parametri Arab Sniper.")
        else:
            results = []
            bar = st.progress(0)
            status = st.empty()
            
            for i, m in enumerate(da_analizzare):
                f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
                h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
                status.text(f"Puntando il mirino: {h_n} - {a_n}")
                
                h_si = get_spectacle_index(h_id)
                a_si = get_spectacle_index(a_id)
                
                # PARAMETRI ARAB SNIPER
                is_saturated = (h_si >= 3.8 or a_si >= 3.8) # Regressione verso la media
                is_dead_match = (h_si < 2.0 or a_si < 2.0)  # Sbarramento Under
                
                icona_special = "↔️"
                if 2.0 <= h_si < 3.8 and 2.0 <= a_si < 3.8:
                    icona_special = "🔥"
                    if h_si >= 3.0 and a_si >= 3.0:
                        icona_special = "💥"
                elif is_saturated:
                    icona_special = "⚠️"
                elif is_dead_match:
                    icona_special = "🧊"

                sc = 40
                d_icon, q1, qx, q2, q_o25 = "↔️", 0.0, 0.0, 0.0, 0.0
                
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
                            if 1.40 <= q_o25 <= 2.10:
                                sc += 15
                                if 2.2 <= (h_si + a_si) / 2 < 3.8 and not is_dead_match:
                                    sc += 10
                                if is_dead_match: sc -= 30
                                elif is_saturated: sc -= 20
                    else:
                        if m['league']['country'] in ['Italy', 'Australia', 'Japan']: sc = 1
                except: sc = 1

                results.append({
                    "Ora": m['fixture']['date'][11:16],
                    "Lega": m['league']['name'],
                    "Match": f"{icona_special} {h_n} - {a_n}",
                    "S.I. (H|A)": f"{h_si} | {a_si}",
                    "1X2": f"{q1}|{qx}|{q2}" if q1 > 0 else "N.D.",
                    "Drop": d_icon,
                    "O2.5": q_o25,
                    "Rating": sc
                })
                time.sleep(0.12)
                bar.progress((i+1)/len(da_analizzare))

            if results:
                df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
                st.dataframe(
                    df.style.apply(style_rows, axis=1),
                    use_container_width=True,
                    column_config={
                        "Rating": st.column_config.ProgressColumn("Sniper Rating", format="%d", min_value=0, max_value=100),
                        "Ora": "⏰", "O2.5": st.column_config.NumberColumn("Quota O2.5", format="%.2f")
                    }
                )
    except Exception as e:
        st.error(f"Errore: {e}")

import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.7.1 - Deep Vision", layout="wide")
st.title("🎯 SNIPER V12.7.1 - Deep Vision")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# IDS AGGIORNATI (Inclusi ID specifici Serie C e leghe minori)
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, # Top Europe
    137, 138, 139, 810, 811, 812, # SERIE C (Vari ID storici/correnti)
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, # Europa
    283, 284, 285, 197, 198, 203, 204, # Est + Turchia
    71, 72, 73, 128, 129, 118, 101, 144, # Sud America
    179, 180, 262, 218, 143 # Extra
]

def style_rating(v):
    if v >= 75: return "background-color: #1e7e34; color: white; font-weight: bold;"
    if v >= 60: return "background-color: #d4edda; color: #155724;"
    return ""

if st.button('🚀 AVVIA ANALISI PROFONDA'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    # Debug: quante partite totali vede l'API prima del filtro?
    st.sidebar.info(f"Partite totali nel mondo oggi: {len(partite)}")
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning(f"Nessun match trovato per i campionati selezionati. Controlla se gli ID della Serie C sono cambiati.")
    else:
        results = []
        progress_bar = st.progress(0)
        
        for i, m in enumerate(da_analizzare):
            f_id = m['fixture']['id']
            sc = 40
            d_icon, q1, qx, q2, q_o25 = "⚪", 0.0, 0.0, 0.0, 0.0
            
            try:
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    # 1X2
                    o1x2 = next((b for b in bets if b['id'] == 1), None)
                    if o1x2:
                        vals = o1x2['values']
                        q1, q2 = float(vals[0]['odd']), float(vals[2]['odd'])
                        qx = float(vals[1]['odd'])
                        if q1 <= 1.80: d_icon, sc = "🏠📉", sc + 20
                        elif q2 <= 1.90: d_icon, sc = "🚀📉", sc + 25

                    # Over 2.5
                    o25_bet = next((b for b in bets if b['id'] == 5), None)
                    if o25_bet:
                        q_o25 = float(next((v['odd'] for v in o25_bet['values'] if v['value'] == 'Over 2.5'), 0))
                        if 1.40 <= q_o25 <= 1.95: sc += 15
                        elif q_o25 > 2.20: sc -= 25
            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": m['league']['name'],
                "Match": f"{m['teams']['home']['name']} - {m['teams']['away']['name']}",
                "1X2": f"{q1} | {qx} | {q2}",
                "Drop": d_icon,
                "O2.5": q_o25,
                "Rating": sc
            })
            time.sleep(0.1)
            progress_bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            
            # --- NUOVA GRAFICA AVANZATA ---
            st.dataframe(
                df.style.applymap(style_rating, subset=['Rating']),
                use_container_width=True,
                column_config={
                    "Rating": st.column_config.ProgressColumn(
                        "Rating %", help="Affidabilità del segnale",
                        format="%d", min_value=0, max_value=100
                    ),
                    "O2.5": st.column_config.NumberColumn("Quota O2.5", format="%.2f"),
                    "Ora": st.column_config.TextColumn("⏰"),
                    "1X2": st.column_config.TextColumn("📊 Quote 1X2"),
                }
            )
        else:
            st.error("Nessun dato recuperabile per i match di oggi.")

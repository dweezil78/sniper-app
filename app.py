import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.5.1 - 3 Days", layout="wide")
st.title("🎯 SNIPER V12.5.1 - Multi-Day Elite Selection")

# --- SIDEBAR PER FILTRI ---
st.sidebar.header("Filtri Visualizzazione")
giorno_filtro = st.sidebar.selectbox(
    "Scegli il giorno da visualizzare:",
    ["Tutti i giorni", "Oggi", "Domani", "Dopodomani"]
)

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = [135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 95, 114, 128, 71, 72, 281, 98, 99]

if st.button('🚀 AVVIA ANALISI GLOBALE (3 GIORNI)'):
    results = []
    date_da_controllare = [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(3)]
    
    bar = st.progress(0)
    placeholder = st.empty()
    total_matches_to_analyze = []

    # 1. RECUPERO PALINSESTO
    for data_str in date_da_controllare:
        placeholder.text(f"Recupero palinsesto del: {data_str}...")
        try:
            res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": data_str, "timezone": "Europe/Rome"})
            partite = res.json().get('response', [])
            per_data = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
            total_matches_to_analyze.extend(per_data)
        except: pass

    if not total_matches_to_analyze:
        st.warning("Nessun match trovato.")
    else:
        # 2. ANALISI PROFONDA
        for i, m in enumerate(total_matches_to_analyze):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            placeholder.text(f"Analisi Elite ({i+1}/{len(total_matches_to_analyze)}): {h_n}-{a_n}")
            
            sc = 40
            d_icon, f_icon = "⚪", "⚪"
            q1, qx, q2, q_o25 = 0.0, 0.0, 0.0, 0.0
            
            try:
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, qx, q2 = float(o1x2[0]['odd']), float(o1x2[1]['odd']), float(o1x2[2]['odd'])
                    
                    if q1 <= 1.80: d_icon, sc = "🏠📉", sc + 20
                    elif q2 <= 1.90: d_icon, sc = "🚀📉", sc + 25

                    o25 = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25 if v['value'] == 'Over 2.5'))
                    if q_o25 <= 1.95: sc += 15
                    elif q_o25 > 2.20: sc -= 25 
            except: pass

            if 75 <= sc <= 80:
                results.append({
                    "Data": m['fixture']['date'][:10],
                    "Giorno": "Oggi" if m['fixture']['date'][:10] == date_da_controllare[0] else "Domani" if m['fixture']['date'][:10] == date_da_controllare[1] else "Dopodomani",
                    "Ora": m['fixture']['date'][11:16],
                    "Match": f"{h_n}-{a_n}",
                    "1X2": f"{q1}|{qx}|{q2}",
                    "Drop": d_icon,
                    "O2.5": q_o25,
                    "Rating": sc
                })
            
            time.sleep(0.3)
            bar.progress((i+1)/len(total_matches_to_analyze))

        if results:
            df = pd.DataFrame(results)
            
            # Applicazione filtro sidebar
            if giorno_filtro != "Tutti i giorni":
                df = df[df['Giorno'] == giorno_filtro]
            
            st.success(f"Trovati {len(df)} match per la selezione: {giorno_filtro}")
            st.dataframe(df.sort_values(["Data", "Ora"]), use_container_width=True)
        else:
            st.info("Nessun match Pure Elite trovato.")

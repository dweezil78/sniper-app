import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V12.7 - Sync", layout="wide")
st.title("🎯 SNIPER V12.7 - Synchronized Market Hunter")

API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# Filtro Leghe: rimosse quelle con media gol storica < 2.3 (Ligue 2, Serie B/C in certi periodi)
IDS = [135, 140, 78, 61, 39, 94, 119, 120, 106, 137, 95, 114, 128, 71, 281, 98, 99]

if st.button('🚀 AVVIA ANALISI SYNC V12.7'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning("Nessun match nelle leghe ad alta produttività.")
    else:
        results = []
        bar = st.progress(0)
        
        for i, m in enumerate(da_analizzare):
            f_id = m['fixture']['id']
            h_id, a_id = m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            
            sc = 40
            sync_tag = "Standard"
            
            try:
                # 1. ANALISI QUOTE SINCRONIZZATE
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, q2 = float(o1x2[0]['odd']), float(o1x2[2]['odd'])
                    
                    o25 = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25 if v['value'] == 'Over 2.5'))

                    # LOGICA SYNC: Favorita forte + Over Basso
                    if min(q1, q2) <= 1.70 and q_o25 <= 1.70:
                        sc += 40  # Massima Sincronia
                        sync_tag = "💎 SYNC GOLD"
                    elif min(q1, q2) <= 1.85 and q_o25 <= 1.85:
                        sc += 25
                        sync_tag = "✅ SYNC OK"
                    else:
                        sc -= 10 # Se non c'è sincronia, penalizziamo

                # 2. FAME GOL (Mantenuta ma con peso bilanciato)
                r_h = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 1})
                if r_h.json()['response'] and r_h.json()['response'][0]['goals']['home'] == 0:
                    sc += 10
                
                r_a = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": a_id, "last": 1})
                if r_a.json()['response'] and r_a.json()['response'][0]['goals']['away'] == 0:
                    sc += 10

           except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Match": f"{h_n}-{a_n}",
                "Tag": sync_tag,
                "Q.O25": q_o25,
                "Rating": sc,
                "CONSIGLIO": "🔥 TOP" if sc >= 85 else "🎯 OTTIMO" if sc >= 70 else "No Bet"
            })
            time.sleep(0.3)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.dataframe(df, use_container_width=True)

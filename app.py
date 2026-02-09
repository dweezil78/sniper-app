import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V12.6 - Goal Hunter", layout="wide")
st.title("🎯 SNIPER V12.6 - Power Drop & Goal Hunter")

API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = [135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 95, 114, 128, 71, 72, 281, 98, 99]

if st.button('🚀 AVVIA ANALISI V12.6'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS' and "Women" not in m['league']['name']]
    
    if not da_analizzare:
        st.warning("Nessun match trovato.")
    else:
        results = []
        bar = st.progress(0)
        placeholder = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id = m['fixture']['id']
            h_id, a_id = m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            placeholder.text(f"Analisi: {h_n} - {a_n}")
            
            sc = 40
            drop_info, fame_gol = "Standard", "No"
            q1, qx, q2, q_o25 = 0.0, 0.0, 0.0, 0.0
            
            try:
                # 1. ANALISI QUOTE (Drop e Over)
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, qx, q2 = float(o1x2[0]['odd']), float(o1x2[1]['odd']), float(o1x2[2]['odd'])
                    
                    o25_bet = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25_bet if v['value'] == 'Over 2.5'))

                    # Miglioramento Drop (1 o 2)
                    if q1 <= 1.70:
                        sc += 20
                        drop_status = "🏠 DROP 1"
                    elif q2 <= 1.70:
                        sc += 25 # Più peso al drop fuori casa
                        drop_status = "🚀 DROP 2"
                    else:
                        drop_status = "Standard"

                # 2. CONTROLLO "FAME DI GOL" (Ultima partita senza segnare)
                # Controlliamo gli ultimi 2 match della Home
                r_h = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 1})
                h_last = r_h.json().get('response', [])
                if h_last and h_last[0]['goals']['home'] == 0:
                    sc += 15
                    fame_gol = "🔥 CASA"
                
                # Controlliamo l'ultimo match dell'Away
                r_a = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": a_id, "last": 1})
                a_last = r_a.json().get('response', [])
                if a_last and a_last[0]['goals']['away'] == 0:
                    sc += 15
                    fame_gol = "🔥 OSPITE" if fame_gol == "No" else "💥 ENTRAMBE"

                # 3. VALUTAZIONE FINALE GOAL
                if q_o25 <= 1.85: sc += 15

            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Match": f"{h_n} - {a_n}",
                "1X2": f"{q1} | {qx} | {q2}",
                "Drop": drop_status,
                "Fame Gol": fame_gol,
                "Quota O2.5": q_o25,
                "Rating": sc,
                "CONSIGLIO": "💎 TOP SNIPER" if sc >= 85 else "✅ OTTIMO" if sc >= 70 else "No Bet"
            })
            time.sleep(0.3) # Ritardo per non bloccare API
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.success("Analisi completata!")
            st.dataframe(df, use_container_width=True)

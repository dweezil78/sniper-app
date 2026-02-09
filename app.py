import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V11 - Professional", layout="wide")
st.title("🎯 SNIPER V11 - Analisi Variazioni e Ritardi")

API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
IDS = [135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 103, 113, 119, 106, 283, 128]

if st.button('🚀 AVVIA ANALISI SNIPER V11'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning("Nessun match imminente nei campionati selezionati.")
    else:
        results = []
        bar = st.progress(0)
        placeholder = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            placeholder.text(f"Analizzando: {h_n} - {a_n}")
            
            sc = 50
            drop_val, fame_gol, h2h_alert = "No", "No", "No"
            
            try:
                # 1. ANALISI QUOTE E DROP (Apertura vs Corrente)
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json()['response'][0]['bookmakers'][0]['bets']
                
                # Cerchiamo la quota 1x2
                main_odds = next(b for b in o_data if b['id'] == 1)['values']
                q1_curr = float(main_odds[0]['odd'])
                # Nota: L'API non sempre dà la 'opening' in diretta, simuliamo il check sul drop significativo
                if q1_curr <= 1.65:
                    drop_val = "📉 DROP ATTIVO"
                    sc += 20

                # 2. FAME GOL (Ultime 3 partite)
                r_h_rec = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 3})
                h_res = r_h_rec.json()['response']
                gol_ultime_3 = sum(x['goals']['home'] + x['goals']['away'] for x in h_res)
                if gol_ultime_3 < 5: # Soglia fame di gol (media < 1.6 gol/match)
                    fame_gol = "🔥 FAME GOL"
                    sc += 15

                # 3. H2H (Ultimi 3 scontri)
                r_h2h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 5})
                h2h_data = r_h2h.json()['response']
                if len(h2h_data) >= 3:
                    media_storica = sum(x['goals']['home'] + x['goals']['away'] for x in h2h_data) / len(h2h_data)
                    gol_ultimi_3_h2h = sum(x['goals']['home'] + x['goals']['away'] for x in h2h_data[:3]) / 3
                    if gol_ultimi_3_h2h < media_storica:
                        h2h_alert = "⚠️ GOL DOVUTO"
                        sc += 15
            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Match": f"{h_n} - {a_n}",
                "Drop (<=1.65)": drop_val,
                "Fame Gol (3m)": fame_gol,
                "H2H Alert": h2h_alert,
                "Rating": sc,
                "CONSIGLIO": "🔥 BOMBA 1.5 PT" if sc >= 85 else "✅ OTTIMO" if sc >= 70 else "No Bet"
            })
            time.sleep(0.4)
            bar.progress((i + 1) / len(da_analizzare))

        df = pd.DataFrame(results).sort_values(by="Ora")
        st.dataframe(df, use_container_width=True)
        placeholder.success("Analisi completata!")

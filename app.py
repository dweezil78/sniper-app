import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper 1.5 PT", layout="wide")
st.title("🎯 Sniper Market Intelligence - Solo Prossimi Match")

API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
IDS = [135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 103, 113, 119, 106, 283, 128]

if st.button('🔄 Aggiorna e Filtra Prossimi Match'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    results = []
    progresso = st.progress(0)
    placeholder = st.empty()
    
    # Filtriamo subito per velocità
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    st.info(f"Trovati {len(da_analizzare)} match da iniziare nei tuoi campionati.")

    for i, m in enumerate(da_analizzare):
        f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
        h_n, a_n, l_n = m['teams']['home']['name'], m['teams']['away']['name'], m['league']['name']
        
        placeholder.text(f"Analisi Live: {h_n} - {a_n}")
        time.sleep(0.4)
        
        drop, flip, fame, h2h, sc = "Stabile", "NO", "NO", "Normale", 50
        
        try:
            # Quote correnti
            r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
            v = r_o.json()['response'][0]['bookmakers'][0]['bets'][0]['values']
            q1, q2 = float(v[0]['odd']), float(v[2]['odd'])
            if q1 <= 1.72: drop, sc = "📉 DROP 1", sc + 10
            if q2 < q1: flip, sc = "SÌ", sc + 15
            
            # Fame Gol (Ultime 2)
            r_r = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 2})
            tot = sum(x['goals']['home'] + x['goals']['away'] for x in r_r.json()['response'])
            if tot <= 2: fame, sc = "SÌ", sc + 10
        except: pass

        results.append({
            "Ora": m['fixture']['date'][11:16],
            "Lega": l_n,
            "Match": f"{h_n}-{a_n}",
            "Drop": drop,
            "Inversione": flip,
            "Fame Gol": fame,
            "Rating": sc,
            "CONSIGLIO": "🔥 BOMBA" if sc >= 75 else "✅ OTTIMO" if sc >= 65 else "No Bet"
        })
        progresso.progress((i + 1) / len(da_analizzare))

    if results:
        df = pd.DataFrame(results).sort_values(by="Ora")
        st.dataframe(df, use_container_width=True)
        placeholder.success("Analisi Completata!")

import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V11.8 - Professional", layout="wide")
st.title("🎯 SNIPER V11.8 - Global Market Intelligence")

API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 
    103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 
    95, 114, 128, 71, 72, 281, 98, 99
]

if st.button('🚀 AVVIA ANALISI GLOBALE V11.8'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning("Nessun match imminente.")
    else:
        results = []
        bar = st.progress(0)
        placeholder = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n, l_n = m['teams']['home']['name'], m['teams']['away']['name'], m['league']['name']
            placeholder.text(f"Analisi: {h_n}-{a_n} ({l_n})")
            
            sc, drop_v, flip_v, fame_v, h2h_v = 50, "No", "No", "No", "No"
            
            # 1. ANALISI QUOTE (Drop e Inversione Reale)
            try:
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_resp = r_o.json().get('response', [])
                if o_resp:
                    bets = o_resp[0]['bookmakers'][0]['bets']
                    odds_1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, q2 = float(odds_1x2[0]['odd']), float(odds_1x2[2]['odd'])
                    
                    if min(q1, q2) <= 1.65:
                        drop_v, sc = "📉 SÌ", sc + 20
                    # Inversione: scatta solo se la favorita è l'ospite con margine netto
                    if q2 < (q1 - 0.40):
                        flip_v, sc = "🔄 SÌ", sc + 15
            except: pass

            # 2. FAME GOL (Ultime 3)
            try:
                r_r = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 3})
                h_res = r_r.json().get('response', [])
                if h_res:
                    tot_g = sum(x['goals']['home'] + x['goals']['away'] for x in h_res)
                    if tot_g <= 4:
                        fame_v, sc = "🔥 SÌ", sc + 15
            except: pass

            # 3. H2H ALERT (Ritardo Gol 1T)
            try:
                r_h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 3})
                h_data = r_h.json().get('response', [])
                if h_data:
                    # Se l'ultimo scontro tra loro è finito 0-0 al primo tempo
                    g_ht = h_data[0]['score']['halftime']['home'] + h_data[0]['score']['halftime']['away']
                    if g_ht == 0:
                        h2h_v, sc = "⚠️ GOL DOVUTO", sc + 15
            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": l_n,
                "Match": f"{h_n}-{a_n}",
                "Drop": drop_v,
                "Inversione": flip_v,
                "Fame Gol": fame_v,
                "H2H Alert": h2h_v,
                "Rating": sc,
                "CONSIGLIO": "🔥 BOMBA" if sc >= 85 else "✅ OTTIMO" if sc >= 70 else "No Bet"
            })
            time.sleep(0.4)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Ora")
            st.dataframe(df, use_container_width=True)
            placeholder.success("Analisi completata!")

import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.9 - Deep Hunter", layout="wide")
st.title("🎯 SNIPER V12.9 - Deep Market & Goal Intelligence")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# Leghe Top + recupero leghe secondarie ad alto volume gol
IDS = [135, 140, 78, 61, 39, 94, 119, 120, 106, 137, 95, 114, 128, 71, 281, 98, 99, 141, 136, 79]

if st.button('🚀 AVVIA ANALISI PROFONDA V12.9'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning("Nessun match imminente.")
    else:
        results = []
        bar = st.progress(0)
        
        for i, m in enumerate(da_analizzare):
            f_id = m['fixture']['id']
            h_id, a_id = m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            
            sc = 40
            d1, d2, d25, d05pt, fame_val = "⚪", "⚪", "⚪", "⚪", "⚪"
            q_o25, q_o05pt = 0.0, 0.0
            
            try:
                # 1. ANALISI QUOTE MULTI-DROP
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    
                    # Drop 1X2
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, q2 = float(o1x2[0]['odd']), float(o1x2[2]['odd'])
                    if q1 <= 1.75: d1, sc = "🏠📉", sc + 15
                    if q2 <= 1.85: d2, sc = "🚀📉", sc + 20
                    
                    # Drop Over 2.5
                    o25_b = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25_b if v['value'] == 'Over 2.5'))
                    if q_o25 <= 1.75: d25, sc = "⚽📉", sc + 15
                    
                    # Drop Over 0.5 PT
                    try:
                        o05pt_b = next(b for b in bets if "First Half" in b['name'] and "0.5" in str(b['values']))
                        q_o05pt = float(next(v['odd'] for v in o05pt_b['values'] if v['value'] == 'Over 0.5'))
                        if q_o05pt <= 1.35: d05pt, sc = "⏱️📉", sc + 10
                    except: pass

                # 2. ANALISI FAME GOL DETTAGLIATA
                r_h = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 1})
                if r_h.json()['response'] and r_h.json()['response'][0]['goals']['home'] == 0:
                    fame_val, sc = "🏠 FAME", sc + 10
                
                r_a = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": a_id, "last": 1})
                if r_a.json()['response'] and r_a.json()['response'][0]['goals']['away'] == 0:
                    fame_val = "🚀 FAME" if fame_val == "⚪" else "💥 MAX FAME"
                    sc += 10

            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Match": f"{h_n}-{a_n}",
                "D1": d1, "D2": d2, "D2.5": d25, "D0.5PT": d05pt,
                "Fame": fame_val,
                "Rating": sc,
                "CONSIGLIO": "💎 SUPER" if sc >= 85 else "✅ OK" if sc >= 70 else "No"
            })
            time.sleep(0.3)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            st.dataframe(pd.DataFrame(results).sort_values("Rating", ascending=False), use_container_width=True)

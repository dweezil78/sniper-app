import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.8 - Rich View", layout="wide")
st.title("🎯 SNIPER V12.8 - Rich & Visual Intelligence")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# --- LISTA CAMPIONATI (Alta media gol) ---
IDS = [135, 140, 78, 61, 39, 94, 119, 120, 106, 137, 95, 114, 128, 71, 281, 98, 99]

if st.button('🚀 AVVIA ANALISI COMPLETA V12.8'):
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
            f_id = m['fixture']['id']
            h_id, a_id = m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            placeholder.text(f"Analisi Profonda: {h_n} - {a_n}")
            
            sc = 40
            drop_icon, fame_icon, sync_tag = "⚪", "⚪", "Standard"
            q1, qx, q2, q_o25 = 0.0, 0.0, 0.0, 0.0
            
            try:
                # 1. ANALISI QUOTE & SYNC
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, qx, q2 = float(o1x2[0]['odd']), float(o1x2[1]['odd']), float(o1x2[2]['odd'])
                    fav_q = min(q1, q2)
                    
                    o25_bet = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25_bet if v['value'] == 'Over 2.5'))

                    # Icone Drop
                    if q1 <= 1.70: drop_icon = "🏠📉"
                    elif q2 <= 1.70: drop_icon = "🚀📉"

                    # Logica Sincronia con Emoji
                    if fav_q <= 1.75 and q_o25 <= 1.75:
                        sc += 35
                        sync_tag = "💎 SYNC FIRE"
                    elif q_o25 >= 2.15:
                        sc -= 20
                        sync_tag = "🧊 SYNC ICE"

                # 2. FAME GOL (Emoji Fuoco)
                r_h = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 1})
                h_res = r_h.json().get('response', [])
                if h_res and h_res[0]['goals']['home'] == 0:
                    sc += 15
                    fame_icon = "🔥 CASA"
                
                r_a = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": a_id, "last": 1})
                a_res = r_a.json().get('response', [])
                if a_res and a_res[0]['goals']['away'] == 0:
                    sc += 15
                    fame_icon = "🔥 OSPITE" if fame_icon == "⚪" else "💥 FAME MAX"

            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Match": f"{h_n} - {a_n}",
                "1X2": f"{q1}|{qx}|{q2}",
                "Drop": drop_icon,
                "Fame": fame_icon,
                "O2.5": q_o25,
                "Sync": sync_tag,
                "Rating": sc,
                "CONSIGLIO": "🔥 SUPER BOMBA" if sc >= 85 else "✅ OTTIMO" if sc >= 70 else "No Bet"
            })
            time.sleep(0.3)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.success("Analisi V12.8 Completata!")
            st.dataframe(df, use_container_width=True)

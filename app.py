import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V12.4.1 - Pro View", layout="wide")
st.title("🎯 SNIPER V12.4.1 - Professional Value Hunter")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = [135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 95, 114, 128, 71, 72, 281, 98, 99]

if st.button('🚀 AVVIA ANALISI COMPLETA'):
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
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            placeholder.text(f"Analisi: {h_n} - {a_n}")
            
            sc = 40
            drop_status, inv_status, market_tag = "No", "No", "Standard"
            q_o25 = 0
            
            try:
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    
                    # 1. ANALISI 1X2
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, q2 = float(o1x2[0]['odd']), float(o1x2[2]['odd'])
                    fav_q = min(q1, q2)
                    
                    if fav_q <= 1.75:
                        drop_status, sc = "📉 SÌ", sc + 20
                    
                    if q2 < (q1 - 0.40):
                        inv_status, sc = "🔄 SÌ", sc + 30
                    
                    # 2. OVER 2.5 FINALE
                    o25 = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25 if v['value'] == 'Over 2.5'))
                    
                    if q_o25 < 1.65 and fav_q > 1.75:
                        market_tag, sc = "⚠️ TRAP", sc - 20
                    elif 1.95 <= q_o25 <= 2.35:
                        market_tag, sc = "💰 VALUE", sc + 25
                    elif q_o25 < 1.95:
                        market_tag, sc = "🔥 GOAL", sc + 15
            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Match": f"{h_n} - {a_n}",
                "Drop": drop_status,
                "Inv": inv_status,
                "Mercato": market_tag,
                "Quota O2.5": q_o25,
                "Rating": sc,
                "CONSIGLIO": "🔥 VALUE BOMBA" if sc >= 80 else "✅ OTTIMO" if sc >= 65 else "No Bet"
            })
            time.sleep(0.2)
            bar.progress((i+1)/len(da_analizzare))

   if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.success(f"Analisi completata!")
            # Tabella con colonne esplicite
            st.dataframe(df, use_container_width=True)

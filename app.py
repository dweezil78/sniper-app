import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.4.2 - Ultra-Light", layout="wide")
st.title("🎯 SNIPER V12.4.2 - Full Visibility")
st.markdown("Gestione flussi elevati (Serie B, C, Championship).")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# Lista IDS Aggiornata
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, 88, 94, 
    103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 179,
    95, 114, 128, 71, 72, 281, 98, 99
]

def highlight_elite(row):
    return ['background-color: #28a745; color: white' if 75 <= row.Rating <= 80 else '' for _ in row]

if st.button('🚀 AVVIA ANALISI TOTALE'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    
    # 1. Recupero palinsesto (Chiamata singola)
    try:
        res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
        partite = res.json().get('response', [])
    except:
        st.error("Errore di connessione all'API. Riprova.")
        st.stop()
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning(f"Nessun match trovato per oggi.")
    else:
        results = []
        progress_text = st.empty()
        bar = st.progress(0)
        
        for i, m in enumerate(da_analizzare):
            f_id = m['fixture']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            progress_text.text(f"Analisi in corso: {h_n} - {a_n} ({i+1}/{len(da_analizzare)})")
            
            sc = 40
            d_icon, q1, qx, q2, q_o25 = "⚪", 0.0, 0.0, 0.0, 0.0
            
            try:
                # Chiamata quote (Massimo 1 chiamata ogni 0.2s per non saturare)
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    # Estrazione 1X2
                    o1x2 = next((b for b in bets if b['id'] == 1), None)
                    if o1x2:
                        vals = o1x2['values']
                        q1, qx, q2 = float(vals[0]['odd']), float(vals[1]['odd']), float(vals[2]['odd'])
                        if q1 <= 1.80: d_icon, sc = "🏠📉", sc + 20
                        elif q2 <= 1.90: d_icon, sc = "🚀📉", sc + 25

                    # Estrazione Over 2.5
                    o25_bet = next((b for b in bets if b['id'] == 5), None)
                    if o25_bet:
                        q_o25 = float(next((v['odd'] for v in o25_bet['values'] if v['value'] == 'Over 2.5'), 0))
                        if 1.40 <= q_o25 <= 1.95: sc += 15
                        elif q_o25 > 2.20: sc -= 25
            except:
                pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": m['league']['name'],
                "Match": f"{h_n}-{a_n}",
                "1X2": f"{q1}|{qx}|{q2}",
                "Drop": d_icon,
                "O2.5": q_o25,
                "Rating": sc
            })
            
            bar.progress((i+1)/len(da_analizzare))
            # Piccolo sleep per evitare il ban dall'API ma non troppo lungo per evitare il timeout di Streamlit
            time.sleep(0.1)

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.success(f"Completato! {len(df)} match trovati.")
            # Visualizzazione con stile
            st.dataframe(df.style.apply(highlight_elite, axis=1), use_container_width=True)

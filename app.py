import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.4.1 - Full View", layout="wide")
st.title("🎯 SNIPER V12.4.1 - Full Visibility Mode")
st.markdown("Monitoraggio completo Serie B, C e Leghe Inglesi. I match **Elite (75-80)** sono evidenziati.")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# Lista IDS Completa (Inclusi match di oggi)
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, 88, 94, 
    103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 179,
    95, 114, 128, 71, 72, 281, 98, 99
]

def highlight_elite(row):
    """Funzione per colorare di verde le righe Elite 75-80"""
    return ['background-color: #d4edda; color: #155724' if 75 <= row.Rating <= 80 else '' for _ in row]

if st.button('🚀 AVVIA ANALISI COMPLETA'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning(f"Nessun match trovato per oggi ({oggi}).")
    else:
        results = []
        bar = st.progress(0)
        
        for i, m in enumerate(da_analizzare):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            
            sc = 40
            d_icon, f_icon = "⚪", "⚪"
            q1, qx, q2, q_o25 = 0.0, 0.0, 0.0, 0.0
            
            try:
                # 1. ANALISI QUOTE
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

                # 2. FAME GOL (Check veloce)
                # Nota: per velocizzare il caricamento di molti match, abbiamo rimosso i check extra API sulle ultime partite qui,
                # ma se ti servono possiamo riattivarli.
            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": m['league']['name'],
                "Match": f"{h_n}-{a_n}",
                "1X2": f"{q1}|{qx}|{q2}",
                "Drop": d_icon,
                "O2.5": q_o25,
                "Rating": sc,
                "Status": "💎 ELITE" if 75 <= sc <= 80 else "Monitor"
            })
            
            time.sleep(0.2)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by=["Rating", "Ora"], ascending=[False, True])
            # Applicazione dello stile verde
            st.success(f"Analisi completata! {len(df)} match monitorati.")
            st.dataframe(df.style.apply(highlight_elite, axis=1), use_container_width=True)
        else:
            st.info("Nessun match trovato per i parametri selezionati.")

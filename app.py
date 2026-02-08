import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper Over 1.5 PT", layout="wide")
st.title("🎯 Sniper Market Intelligence - Live")

# --- PARAMETRI ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
IDS = [135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 103, 113, 119, 106, 283, 128]

def fetch_data():
    oggi = datetime.now().strftime('%Y-%m-%d')
    url = f"https://{HOST}/fixtures"
    res = requests.get(url, headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    return res.json().get('response', [])

# --- INTERFACCIA ---
if st.button('🔄 Aggiorna Analisi'):
    partite = fetch_data()
    results = []
    
    progresso = st.progress(0)
    placeholder = st.empty()
    
    for i, m in enumerate(partite):
        if m['league']['id'] in IDS:
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n, l_n = m['teams']['home']['name'], m['teams']['away']['name'], m['league']['name']
            
            placeholder.text(f"Analizzando: {h_n} vs {a_n}")
            time.sleep(0.4)
            
            # --- LOGICA SNIPER (Semplificata per velocità web) ---
            drop, flip, fame, vel, h2h, sc = "Stabile", "NO", "NO", "Media", "Normale", 50
            
            try:
                # Quote
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                v = r_o.json()['response'][0]['bookmakers'][0]['bets'][0]['values']
                q1, q2 = float(v[0]['odd']), float(v[2]['odd'])
                if q1 <= 1.72: drop, sc = "📉 DROP 1", sc + 10
                if q2 < q1: flip, sc = "SÌ", sc + 15
                
                # Fame Gol (Ultime 2)
                r_r = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"team": h_id, "last": 2})
                tot = sum(x['goals']['home'] + x['goals']['away'] for x in r_r.json()['response'])
                if tot <= 2: fame, sc = "SÌ", sc + 10
                
                # H2H
                r_h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 5})
                d = r_h.json()['response']
                if len(d) >= 2:
                    avg = sum(x['goals']['home']+x['goals']['away'] for x in d)/len(d)
                    if (d[0]['goals']['home']+d[0]['goals']['away']) < avg: h2h, sc = "GOL DOVUTO", sc + 5
            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": l_n,
                "Match": f"{h_n}-{a_n}",
                "Drop": drop,
                "Inversione": flip,
                "Fame Gol": fame,
                "H2H": h2h,
                "Rating": sc,
                "CONSIGLIO": "🔥 BOMBA" if sc >= 80 else "✅ OTTIMO" if sc >= 70 else "No Bet"
            })
            progresso.progress((i + 1) / len(partite))

    if results:
        df = pd.DataFrame(results).sort_values(by="Ora")
        
        # Colora la tabella
        def color_rows(val):
            if val == "🔥 BOMBA": return 'background-color: #ff4b4b; color: white'
            if val == "✅ OTTIMO": return 'background-color: #2ecc71; color: white'
            return ''
        
        st.dataframe(df.style.applymap(color_rows, subset=['CONSIGLIO']), use_container_width=True)
    else:
        st.warning("Nessun match trovato per i parametri impostati.")

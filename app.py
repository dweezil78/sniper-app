import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.4 - Value Hunter", layout="wide")
st.title("🎯 SNIPER V12.4 - Professional Value Hunter")
st.markdown("Analisi avanzata basata su **Drop Quota**, **Inversione di Mercato** e **Filtro Anti-Trappola Over 2.5**.")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# --- LISTA CAMPIONATI (29 Leghe Top Selezionate) ---
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 
    103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 
    95, 114, 128, 71, 72, 281, 98, 99
]

if st.button('🚀 AVVIA ANALISI GLOBALE'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    # Filtro: Campionati in lista, stato 'Not Started' e NO Femminili
    da_analizzare = [
        m for m in partite 
        if m['league']['id'] in IDS 
        and m['fixture']['status']['short'] == 'NS' 
        and all(x not in m['league']['name'] for x in ["Women", "Femminile"])
    ]
    
    if not da_analizzare:
        st.warning("Nessun match imminente trovato nei campionati selezionati.")
    else:
        results = []
        bar = st.progress(0)
        placeholder = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id = m['fixture']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            l_n = m['league']['name']
            placeholder.text(f"Analisi in corso: {h_n} vs {a_n} ({l_n})")
            
            sc = 40 # Rating Base
            q_o25 = 0
            
            try:
                # Recupero Quote
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    
                    # 1. Analisi 1X2 per Drop e Inversione
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, q2 = float(o1x2[0]['odd']), float(o1x2[2]['odd'])
                    fav_q = min(q1, q2)
                    
                    # 2. Analisi Over 2.5 Finale
                    o25 = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25 if v['value'] == 'Over 2.5'))
                    
                    # --- CORE LOGIC V12.4 ---
                    
                    # Filtro Anti-Trappola: Over basso ma favorita 'pigra'
                    if q_o25 < 1.65 and fav_q > 1.75:
                        sc -= 20 
                    
                    # Bonus Inversione (Fattore Campo annullato o ribaltato)
                    if q2 < (q1 - 0.40): 
                        sc += 30
                    elif fav_q <= 1.75: 
                        sc += 20
                    
                    # Value Bonus per Quote Interessanti (Raddoppi)
                    if 1.95 <= q_o25 <= 2.35:
                        sc += 25
                    elif q_o25 < 1.95:
                        sc += 15
            except:
                pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": l_n,
                "Match": f"{h_n} - {a_n}",
                "Rating": sc,
                "Quota O2.5": q_o25,
                "CONSIGLIO": "🔥 VALUE BOMBA" if sc >= 80 else "✅ OTTIMO" if sc >= 65 else "No Bet"
            })
            
            # Pausa tecnica per limiti API e aggiornamento barra
            time.sleep(0.3)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            
            # Visualizzazione tabella
            st.success(f"Analisi completata su {len(da_analizzare)} match!")
            
            # Evidenzia i risultati migliori
            st.dataframe(df.style.apply(lambda x: ['background-color: #2e7d32' if v == "🔥 VALUE BOMBA" 
                                                    else 'background-color: #1565c0' if v == "✅ OTTIMO" 
                                                    else '' for v in x], subset=['CONSIGLIO']), 
                         use_container_width=True)

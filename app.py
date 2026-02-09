import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.2 - Gold Edition", layout="wide")
st.title("🎯 SNIPER V12.2 - Gold Edition")
st.markdown("Ripristino della logica **Gold**: Convergenza 1X2, Aspettativa Over 2.5 e Filtro H2H.")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# --- LISTA CAMPIONATI (29 Leghe Selezionate) ---
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 
    103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 
    95, 114, 128, 71, 72, 281, 98, 99
]

if st.button('🚀 AVVIA ANALISI GOLD V12.2'):
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
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            placeholder.text(f"Analisi Gold: {h_n} vs {a_n}")
            
            sc = 40 # Rating Base
            combo_v = "Standard"
            q_o25 = 0.0
            
            try:
                # 1. ANALISI QUOTE GOLD (1X2 + Over 2.5)
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    
                    # Logica Favorita e Inversione
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, q2 = float(o1x2[0]['odd']), float(o1x2[2]['odd'])
                    if min(q1, q2) <= 1.65: sc += 25
                    if q2 < (q1 - 0.30): sc += 20
                    
                    # Aspettativa Gol (Filtro Over 2.5)
                    o25 = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25 if v['value'] == 'Over 2.5'))
                    if q_o25 <= 1.75:
                        sc += 15
                        combo_v = "🔥 ALTO"
                    elif q_o25 >= 2.15:
                        sc -= 20
                        combo_v = "🧊 BASSO"

                # 2. FILTRO SICUREZZA H2H (Scontri Diretti)
                r_h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 2})
                h_data = r_h.json().get('response', [])
                if h_data and (h_data[0]['score']['halftime']['home'] + h_data[0]['score']['halftime']['away'] == 0):
                    sc -= 10 # Penalità se l'ultimo scontro diretto è stato uno 0-0 PT
            except:
                pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Match": f"{h_n} - {a_n}",
                "Rating": sc,
                "Aspettativa": combo_v,
                "Quota O2.5": q_o25,
                "CONSIGLIO": "💎 BOMBA GOLD" if sc >= 75 else "✅ OTTIMO" if sc >= 60 else "No Bet"
            })
            
            time.sleep(0.3)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.success("Analisi V12.2 Gold completata!")
            st.dataframe(df, use_container_width=True)

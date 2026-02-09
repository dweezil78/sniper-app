import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V12.1 - Aggressive", layout="wide")
st.title("🎯 SNIPER V12.1 - Inversion & League Filter")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# --- LISTA CAMPIONATI (Senza Femminili e filtrata) ---
# Ho rimosso i codici che solitamente corrispondono a leghe femminili o minori stitiche
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 
    103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 
    95, 114, 128, 71, 72, 281, 98, 99
]

if st.button('🚀 AVVIA ANALISI AFFINATA V12.1'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    # FILTRO: No campionati femminili (controllo nel nome della lega)
    da_analizzare = [
        m for m in partite 
        if m['league']['id'] in IDS 
        and m['fixture']['status']['short'] == 'NS'
        and "Women" not in m['league']['name']
        and "Femminile" not in m['league']['name']
    ]
    
    if not da_analizzare:
        st.warning("Nessun match imminente nei campionati selezionati.")
    else:
        results = []
        bar = st.progress(0)
        placeholder = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n, l_n = m['teams']['home']['name'], m['teams']['away']['name'], m['league']['name']
            placeholder.text(f"Analisi: {h_n}-{a_n}")
            
            sc, drop_v, flip_v, h2h_v = 40, "No", "No", "Ok"
            
            # 1. ANALISI QUOTE + VALORIZZAZIONE INVERSIONE
            try:
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_resp = r_o.json().get('response', [])
                if o_resp:
                    bets = o_resp[0]['bookmakers'][0]['bets']
                    odds_1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, q2 = float(odds_1x2[0]['odd']), float(odds_1x2[2]['odd'])
                    
                    # DROP (Favorita netta)
                    if min(q1, q2) <= 1.65:
                        drop_v, sc = "📉 SÌ", sc + 30
                    
                    # INVERSIONE (Spostamento verso l'Ospite o forte gap)
                    # Ora diamo più punti all'inversione rispetto a prima
                    if q2 < (q1 - 0.30): 
                        flip_v, sc = "🔄 SÌ", sc + 25 
            except: pass

            # 2. H2H (Solo come Alert visivo, non affossa il rating)
            try:
                r_h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 2})
                h_data = r_h.json().get('response', [])
                if h_data:
                    g_ht = (h_data[0]['score']['halftime']['home'] or 0) + (h_data[0]['score']['halftime']['away'] or 0)
                    if g_ht == 0:
                        h2h_v, sc = "⚠️ 0-0 HT Prec.", sc - 5 # Penalità minima
            except: pass

            # Verdetto con soglia più flessibile per l'Inversione
            consiglio = "No Bet"
            if sc >= 80: consiglio = "🔥 BOMBA"
            elif sc >= 65: consiglio = "✅ OTTIMO"

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": l_n,
                "Match": f"{h_n}-{a_n}",
                "Drop": drop_v,
                "Inversione": flip_v,
                "Nota H2H": h2h_v,
                "Rating": sc,
                "CONSIGLIO": consiglio
            })
            time.sleep(0.3)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.dataframe(df, use_container_width=True)

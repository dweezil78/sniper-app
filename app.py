import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V12.3 - The Master", layout="wide")
st.title("🎯 SNIPER V12.3 - The Master Intelligence")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# --- LISTA CAMPIONATI GLOBALE ---
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 
    103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 
    95, 114, 128, 71, 72, 281, 98, 99
]

if st.button('🚀 AVVIA ANALISI MASTER V12.3'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    # Filtro Leghe Maschili Selezionate
    da_analizzare = [
        m for m in partite 
        if m['league']['id'] in IDS 
        and m['fixture']['status']['short'] == 'NS'
        and all(x not in m['league']['name'] for x in ["Women", "Femminile"])
    ]
    
    if not da_analizzare:
        st.warning("Nessun match imminente nei campionati selezionati.")
    else:
        results = []
        bar = st.progress(0)
        placeholder = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n, l_id = m['teams']['home']['name'], m['teams']['away']['name'], m['league']['id']
            placeholder.text(f"Analisi: {h_n}-{a_n}")
            
            # Punteggio base aggressivo
            sc, drop_v, flip_v, h2h_v, combo_v = 40, "No", "No", "Ok", "Standard"
            
            # 1. ANALISI QUOTE (1X2 + Over 2.5 Finale + Bonus Trasferta)
            try:
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_resp = r_o.json().get('response', [])
                if o_resp:
                    bookies = o_resp[0]['bookmakers'][0]['bets']
                    
                    # Logica 1X2 e Inversione
                    odds_1x2 = next(b for b in bookies if b['id'] == 1)['values']
                    q1, q2 = float(odds_1x2[0]['odd']), float(odds_1x2[2]['odd'])
                    
                    if min(q1, q2) <= 1.65:
                        drop_v, sc = "📉 SÌ", sc + 25
                    
                    if q2 < (q1 - 0.30):
                        flip_v, sc = "🔄 SÌ", sc + 20
                        
                    # BONUS V12.3: AGGRESSIVITÀ FUORI CASA
                    if q2 <= 1.70:
                        sc += 10

                    # Over 2.5 Finale (Aspettativa Gol Totale)
                    o25_bet = next(b for b in bookies if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25_bet if v['value'] == 'Over 2.5'))
                    if q_o25 <= 1.75:
                        sc, combo_v = sc + 15, "🔥 ALTO GOL"
                    elif q_o25 >= 2.15:
                        sc, combo_v = sc - 25, "🧊 BASSO GOL"
            except: pass

            # 2. FILTRO SICUREZZA H2H (Sottrazione punti per blocco storico)
            try:
                r_h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 2})
                h_data = r_h.json().get('response', [])
                if h_data:
                    g_ht = (h_data[0]['score']['halftime']['home'] or 0) + (h_data[0]['score']['halftime']['away'] or 0)
                    if g_ht == 0:
                        h2h_v, sc = "⚠️ 0-0 HT Prec.", sc - 15
            except: pass

            # Verdetto Finale
            consiglio = "No Bet"
            if sc >= 90: consiglio = "💎 SUPER BOMBA"
            elif sc >= 75: consiglio = "🔥 BOMBA"
            elif sc >= 65: consiglio = "✅ OTTIMO"

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": m['league']['name'],
                "Match": f"{h_n}-{a_n}",
                "Drop": drop_v,
                "Inv": flip_v,
                "Aspett.": combo_v,
                "Rating": sc,
                "CONSIGLIO": consiglio
            })
            time.sleep(0.3)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)
            st.dataframe(df, use_container_width=True)
            placeholder.success("Analisi completata con successo!")

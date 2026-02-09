import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V11.3 - Global", layout="wide")
st.title("🎯 SNIPER V11.3 - Global Professional")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# --- LISTA CAMPIONATI COMPLETA ---
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, # Top Euro & Portogallo 1
    103, 113, 119, 120, 110, # Nordici (Norvegia, Svezia, Danimarca 1-2, Finlandia)
    106, 283, 137, 138, 139, # Polonia, Romania, Serie C (A, B, C)
    95, 114, 128, 71, 72, 281, # Portogallo 2, Australia, Argentina, Brasile A-B, Perù
    98, 99 # Giappone 1-2
]

if st.button('🚀 AVVIA ANALISI GLOBALE'):
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
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n, l_n = m['teams']['home']['name'], m['teams']['away']['name'], m['league']['name']
            placeholder.text(f"Analisi: {h_n}-{a_n} ({l_n})")
            
            sc, drop_v, flip_v, fame_v, h2h_v = 50, "No", "No", "No", "No"
            
            # 1. ANALISI QUOTE
            # --- NUOVA LOGICA DI ANALISI ---
try:
    r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
    o_resp = r_o.json().get('response', [])
    if o_resp:
        bets = o_resp[0]['bookmakers'][0]['bets']
        odds_1x2 = next(b for b in bets if b['id'] == 1)['values']
        q1, q2 = float(odds_1x2[0]['odd']), float(odds_1x2[2]['odd'])
        
        # DROP: La favorita (casa o fuori) deve avere una quota molto bassa
        if min(q1, q2) <= 1.65:
            drop_v, sc = "📉 SÌ", sc + 20
        
        # INVERSIONE: La squadra ospite (q2) è favorita "a sorpresa" sulla carta (q2 < q1)
        # o c'è un forte movimento rispetto alla media 1X2
        if q2 < (q1 - 0.40): 
            flip_v, sc = "🔄 SÌ", sc + 15
except Exception: pass

# --- NUOVO H2H (RITARDO GOL 1T) ---
try:
    r_h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 3})
    h_data = r_h.json().get('response', [])
    if h_data:
        # Se l'ultimo match tra loro è finito 0-0 al primo tempo
        if (h_data[0]['score']['halftime']['home'] + h_data[0]['score']['halftime']['away']) == 0:
            h2h_v, sc = "⚠️ GOL DOVUTO", sc + 15
except Exception: pass

            # 3. H2H ALERT
            try:
                r_h = requests.get(f"https://{HOST}/fixtures/headtohead", headers=HEADERS, params={"h2h": f"{h_id}-{a_id}", "last": 5})
                h_data = r_h.json().get('response', [])
                if len(h_data) >= 3:
                    avg_5 = sum(x['goals']['home']+x['goals']['away'] for x in h_data)/len(h_data)
                    avg_3 = sum(x['goals']['home']+x['goals']['away'] for x in h_data[:3])/3
                    if avg_3 < avg_5:
                        h2h_v, sc = "⚠️ SÌ", sc + 10
            except Exception:
                pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": l_n,
                "Match": f"{h_n}-{a_n}",
                "Drop": drop_v,
                "Inversione": flip_v,
                "Fame Gol": fame_v,
                "H2H Alert": h2h_v,
                "Rating": sc,
                "CONSIGLIO": "🔥 BOMBA" if sc >= 85 else "✅ OTTIMO" if sc >= 70 else "No Bet"
            })
            time.sleep(0.4)
            bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Ora")
            st.dataframe(df, use_container_width=True)
            placeholder.success(f"Analisi completata!")

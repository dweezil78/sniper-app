import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Sniper V12.4 - Pure Elite", layout="wide")
st.title("🎯 SNIPER V12.4 - Pure Elite Selection")
st.markdown("Focus sulla **Sincronia di Mercato**. Rating 75-80 = Massima Precisione.")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# Campionati ad alta produttività
IDS = [135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, 103, 113, 119, 120, 110, 106, 283, 137, 138, 139, 95, 114, 128, 71, 72, 281, 98, 99]

if st.button('🚀 AVVIA ANALISI PURE ELITE'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning("Nessun match trovato per i parametri Elite.")
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
                # 1. ANALISI QUOTE DINAMICHE
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    o1x2 = next(b for b in bets if b['id'] == 1)['values']
                    q1, qx, q2 = float(o1x2[0]['odd']), float(o1x2[1]['odd']), float(o1x2[2]['odd'])
                    
                    # DROP DINAMICO (Assegnazione Rating rigida)
                    if q1 <= 1.80: d_icon, sc = "🏠📉", sc + 20
                    elif q2 <= 1.90: d_icon, sc = "🚀📉", sc + 25

                    # OVER 2.5 SYNC (+15)
                    o25 = next(b for b in bets if b['id'] == 5)['values']
                    q_o25 = float(next(v['odd'] for v in o25 if v['value'] == 'Over 2.5'))
                    if q_o25 <= 1.95: sc += 15
                    elif q_o25 > 2.20: sc -= 25 # Penalità se il mercato non crede

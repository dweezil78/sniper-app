import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

st.set_page_config(page_title="Sniper V11.2 - Global Professional", layout="wide")
st.title("🎯 SNIPER V11.2 - Global Market Intelligence")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# --- LISTA CAMPIONATI AGGIORNATA ---
# Include: Top Euro, Nordici, Portogallo 1&2, Danimarca 1&2, Polonia, Romania, Serie C, Sudamerica (Arg, Bra, Perù), Asia (Giappone), Australia
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 88, 94, # Base (A, B, Top Euro, Eredivisie, Portogallo 1)
    103, 113, 119, 120, 110, # Nordici: Norvegia, Svezia, Danimarca 1 & 2, Finlandia
    106, 283, 137, 138, 139, # Polonia, Romania, Serie C (A, B, C)
    95, 114, 128, 71, 72, 281, # Portogallo 2, Australia, Argentina, Brasile A & B, Perù
    98, 99 # Giappone 1 & 2
]

if st.button('🚀 AVVIA ANALISI GLOBALE V11.2'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning("Nessun match imminente nei campionati selezionati.")
    else:
        results = []
        bar = st.progress(0)
        placeholder = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n, l_n = m['teams']['home']['name'], m['teams']['away']['name'], m['league']['name']
            placeholder.text(f"Analisi: {h_n} - {a_n} ({l_n})")
            
            sc = 50
            drop_v, flip_v, fame_v, h2h_v = "No", "No", "No", "No"
            
            try:
                # 1. ANALISI QUOTE (Drop e Inversione)
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    odds_list = o_data[0]['bookmakers'][0]['bets']
                    odds_1x2 = next(b for b in odds_list if b['id'] == 1)['values']
                    q1, q2 = float(odds_1x2[0]['odd']), float(odds_1x2[2]['odd'])

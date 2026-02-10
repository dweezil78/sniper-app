import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.7 - Global Hunter", layout="wide")
st.title("🎯 SNIPER V12.7 - Global Hunter")
st.markdown("Monitoraggio Totale: Top Leghe, Serie B/C, Championship, Est Europa e Sud America.")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# IDS TOTALI (Espansi al massimo per includere Serie C e minori)
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, # Top Europe + Eng Minori
    137, 138, 139, # SERIE C ITALIA (Girone A, B, C)
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, # Europa Mid
    283, 284, 285, 197, 198, 203, 204, # Est + Turchia + Grecia
    71, 72, 73, 128, 129, 118, 101, 144, # Sud America (Bra A/B, Arg, Col, Cile)
    179, 180, 262, 218, 143 # Extra: Scozia, Austria, Belgio, Svizzera
]

def style_rows(row):
    """Colorazione dinamica: Verde Scuro per Elite, Verde Chiaro per Buoni"""
    if row.Rating >= 75:
        return ['background-color: #1e7e34; color: white'] * len(row)
    elif row.Rating >= 60:
        return ['background-color: #d4edda; color: #155724'] * len(row)
    return [''] * len(row)

if st.button('🚀 AVVIA RADAR GLOBALE'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
    
    if not da_analizzare:
        st.warning(f"Nessun match trovato per oggi nelle leghe selezionate.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, m in enumerate(da_analizzare):
            f_id, h_id, a_id = m['fixture']['id'], m['teams']['home']['id'], m['teams']['away']['id']
            h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
            
            status_text.text(f"Analizzando: {h_n} - {a_n} ({m['league']['name']})")
            sc = 40
            d_icon, q1, qx, q2, q_o25 = "⚪", 0.0, 0.0, 0.0, 0.0
            
            try:
                # Recupero Quote
                r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                o_data = r_o.json().get('response', [])
                if o_data:
                    bets = o_data[0]['bookmakers'][0]['bets']
                    # 1X2
                    o1x2 = next((b for b in bets if b['id'] == 1), None)
                    if o1x2:
                        vals = o1x2['values']
                        q1, qx, q2 = float(vals[0]['odd']), float(vals[1]['odd']), float(vals[2]['odd'])
                        if q1 <= 1.80: d_icon, sc = "🏠📉", sc + 20
                        elif q2 <= 1.90: d_icon, sc = "🚀📉", sc + 25

                    # Over 2.5
                    o25_bet = next((b for b in bets if b['id'] == 5), None)
                    if o25_bet:
                        q_o25 = float(next((v['odd'] for v in o25_bet['values'] if v['value'] == 'Over 2.5'), 0))
                        if 1.40 <= q_o25 <= 1.95: sc += 15
                        elif q_o25 > 2.20: sc -= 25
            except: pass

            results.append({
                "Ora": m['fixture']['date'][11:16],
                "Lega": m['league']['name'],
                "Match": f"{h_n}-{a_n}",
                "1X2": f"{q1}|{qx}|{q2}",
                "Drop": d_icon,
                "O2.5": q_o25,
                "Rating": sc
            })
            
            time.sleep(0.15) # Ottimizzato per velocità
            progress_bar.progress((i+1)/len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by=["Rating", "Ora"], ascending=[False, True])
            st.success(f"Radar completato: {len(df)} match pronti.")
            st.dataframe(df.style.apply(style_rows, axis=1), use_container_width=True)
            
            # Download per backup
            st.download_button("📥 Scarica Report CSV", df.to_csv(index=False), "radar_sniper.csv", "text/csv")

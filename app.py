import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.7.3 - Full Palinsesto", layout="wide")
st.title("🎯 SNIPER V12.7.3 - Radar Serie C & Global")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# IDS TOTALI (Inclusi ID Serie C e Lega Pro 2026)
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, 
    137, 138, 139, 810, 811, 812, 181, 
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, 
    283, 284, 285, 197, 198, 203, 204, 
    71, 72, 73, 128, 129, 118, 101, 144, 
    179, 180, 262, 218, 143
]

def style_rows(row):
    if row.Rating >= 75:
        return ['background-color: #1e7e34; color: white'] * len(row)
    elif row.Rating >= 60:
        return ['background-color: #d4edda; color: #155724'] * len(row)
    elif row.Rating == 1: # Match senza quote ancora
        return ['background-color: #f8f9fa; color: #6c757d; font-style: italic'] * len(row)
    elif any(x in str(row.Lega) for x in ["Serie C", "Lega Pro", "Group C", "Serie B"]):
        return ['background-color: #e3f2fd; color: #0d47a1'] * len(row)
    return [''] * len(row)

if st.button('🚀 AVVIA RADAR TOTALE'):
    oggi = datetime.now().strftime('%Y-%m-%d')
    try:
        res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
        partite = res.json().get('response', [])
        
        st.sidebar.write(f"Match totali oggi: {len(partite)}")
        da_analizzare = [m for m in partite if m['league']['id'] in IDS and m['fixture']['status']['short'] == 'NS']
        
        if not da_analizzare:
            st.warning(f"Nessun match trovato per i campionati selezionati oggi.")
        else:
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, m in enumerate(da_analizzare):
                f_id = m['fixture']['id']
                h_n, a_n = m['teams']['home']['name'], m['teams']['away']['name']
                lega_n = m['league']['name']
                status_text.text(f"Analisi: {h_n} - {a_n}")
                
                sc = 0
                d_icon, q1, qx, q2, q_o25 = "⚪", 0.0, 0.0, 0.0, 0.0
                
                try:
                    r_o = requests.get(f"https://{HOST}/odds", headers=HEADERS, params={"fixture": f_id})
                    o_data = r_o.json().get('response', [])
                    
                    if o_data:
                        sc = 40
                        bets = o_data[0]['bookmakers'][0]['bets']
                        o1x2 = next((b for b in bets if b['id'] == 1), None)
                        if o1x2:
                            vals = o1x2['values']
                            q1, qx, q2 = float(vals[0]['odd']), float(vals[1]['odd']), float(vals[2]['odd'])
                            if q1 <= 1.80: d_icon, sc = "🏠📉", sc + 20
                            elif q2 <= 1.90: d_icon, sc = "🚀📉", sc + 25

                        o25_bet = next((b for b in bets if b['id'] == 5), None)
                        if o25_bet:
                            q_o25 = float(next((v['odd'] for v in o25_bet['values'] if v['value'] == 'Over 2.5'), 0))
                            if 1.40 <= q_o25 <= 1.95: sc += 15
                            elif q_o25 > 2.20: sc -= 25
                    else:
                        # MATCH TROVATO MA SENZA QUOTE (TIPICO SERIE C MATTUTINA)
                        sc = 1
                        d_icon = "⏳"
                except:
                    sc = 1
                    d_icon = "⏳"

                results.append({
                    "Ora": m['fixture']['date'][11:16],
                    "Lega": lega_n,
                    "Match": f"{h_n} - {a_n}",
                    "1X2": f"{q1} | {qx} | {q2}" if q1 > 0 else "N.D.",
                    "Drop": d_icon,
                    "O2.5": q_o25 if q_o25 > 0 else 0.0,
                    "Rating": sc
                })
                time.sleep(0.12)
                progress_bar.progress((i+1)/len(da_analizzare))

            if results:
                df = pd.DataFrame(results).sort_values(by=["Rating", "Ora"], ascending=[False, True])
                st.dataframe(
                    df.style.apply(style_rows, axis=1),
                    use_container_width=True,
                    column_config={
                        "Rating": st.column_config.ProgressColumn("Rating Sniper", format="%d", min_value=0, max_value=100),
                        "Ora": "⏰", "O2.5": st.column_config.NumberColumn("Quota O2.5", format="%.2f"), "Drop": "📉"
                    }
                )
    except Exception as e:
        st.error(f"Errore: {e}")

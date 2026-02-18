import streamlit as st
import pandas as pd
import requests
import os
from pathlib import Path
from datetime import datetime

# ============================
# CONFIGURAZIONE PATH
# ============================
BASE_DIR = Path(__file__).resolve().parent
LOG_CSV = str(BASE_DIR / "sniper_history_log.csv")

st.set_page_config(page_title="ARAB AUDITOR V3.0", layout="wide")

# Configurazione API
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 Arab Auditor V3.0 - Analisi Correlazioni Odds")
st.info("Analisi avanzata: Risultati vs Quote (1X2, GG HT, Over 1.5 HT)")

# ============================
# SORGENTE DATI
# ============================
st.sidebar.header("📂 Sorgente Dati")
uploaded_file = st.sidebar.file_uploader("Carica CSV Sniper", type=["csv"])

df_log = None
if uploaded_file:
    df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
    st.success(f"✅ Analizzando: {uploaded_file.name}")
elif os.path.exists(LOG_CSV):
    df_log = pd.read_csv(LOG_CSV, dtype={"Fixture_ID": str})
    st.info("🔄 Utilizzo database sniper_history_log.csv")

# ============================
# FUNZIONI DI ESTRAZIONE ODDS
# ============================
def get_specific_odds(fixture_id):
    """Estrae 1X2, GG HT e O1.5 HT dall'API Odds"""
    odds_data = {"1X2": "N/D", "GG_HT": "N/D", "O1.5_HT": "N/D"}
    try:
        url = f"https://v3.football.api-sports.io/odds?fixture={fixture_id}"
        resp = requests.get(url, headers=HEADERS, timeout=10).json()
        if not resp.get("response"): return odds_data
        
        bookmaker = resp["response"][0].get("bookmakers", [{}])[0]
        for bet in bookmaker.get("bets", []):
            # 1X2 (ID 1)
            if bet["id"] == 1:
                v = bet["values"]
                odds_data["1X2"] = f"{v[0]['odd']}|{v[1]['odd']}|{v[2]['odd']}"
            # Over/Under 1st Half (ID 59) - Cerchiamo Over 1.5
            if bet["id"] == 59:
                for val in bet["values"]:
                    if val["value"] == "Over 1.5": odds_data["O1.5_HT"] = val["odd"]
            # Both Teams To Score 1st Half (ID 71)
            if bet["id"] == 71:
                for val in bet["values"]:
                    if val["value"] == "Yes": odds_data["GG_HT"] = val["odd"]
        return odds_data
    except: return odds_data

# ============================
# LOGICA DI REVISIONE
# ============================
if df_log is not None:
    df_log = df_log.dropna(subset=['Fixture_ID'])
    
    st.sidebar.subheader("🎯 Filtri Analisi")
    q_min = st.sidebar.number_input("Quota Minima (Favorito)", value=1.40)
    q_max = st.sidebar.number_input("Quota Massima (Favorito)", value=1.95)

    if st.button("🧐 AVVIA REVISIONE INTEGRATA"):
        # Pulizia Fixture_ID (rimozione .0 se presente)
        df_log['Fixture_ID'] = df_log['Fixture_ID'].apply(lambda x: str(x).split('.')[0])
        
        results = []
        progress_bar = st.progress(0)
        total = len(df_log)
        
        with requests.Session() as s:
            for i, row in enumerate(df_log.itertuples()):
                progress_bar.progress((i + 1) / total)
                f_id = row.Fixture_ID
                
                try:
                    # 1. Recupero Risultati
                    res_url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                    f_data = s.get(res_url, headers=HEADERS).json()["response"][0]
                    
                    score = f_data.get("score", {})
                    ht_h = (score.get("halftime", {}) or {}).get("home", 0) or 0
                    ht_a = (score.get("halftime", {}) or {}).get("away", 0) or 0
                    
                    # 2. Recupero Quote Pre-Match (Nuova funzione)
                    odds = get_specific_odds(f_id)
                    
                    # 3. Analisi Esiti
                    is_gg_ht = "✅" if (ht_h > 0 and ht_a > 0) else "❌"
                    is_o15_ht = "✅" if (ht_h + ht_a) >= 2 else "❌"
                    
                    results.append({
                        "Match": row.Match,
                        "Ris. HT": f"{ht_h}-{ht_a}",
                        "1X2 Odds": odds["1X2"],
                        "GG HT Odds": odds["GG_HT"],
                        "O1.5 HT Odds": odds["O1.5_HT"],
                        "GG HT?": is_gg_ht,
                        "O1.5 HT?": is_o15_ht,
                        "Tag Sniper": getattr(row, "Tag", getattr(row, "Info", ""))
                    })
                except: continue

        if results:
            res_df = pd.DataFrame(results)
            st.subheader("📋 Tabella Comparativa Quote/Risultati")
            st.dataframe(res_df, use_container_width=True)
            
            # Statistiche Veloci
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                win_gg = (res_df["GG HT?"] == "✅").sum()
                st.metric("Successo GG HT", f"{win_gg}/{len(res_df)}", f"{(win_gg/len(res_df)*100):.1f}%")
            with col2:
                win_o15 = (res_df["O1.5 HT?"] == "✅").sum()
                st.metric("Successo Over 1.5 HT", f"{win_o15}/{len(res_df)}", f"{(win_o15/len(res_df)*100):.1f}%")

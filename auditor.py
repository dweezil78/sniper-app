import streamlit as st
import pandas as pd
import requests
import os
from datetime import datetime

# Configurazione API (Usa le stesse chiavi dello Sniper)
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}
LOG_CSV = "sniper_history_log.csv"

st.set_page_config(page_title="ARAB AUDITOR V1.0", layout="wide")

st.title("📊 Arab Auditor - Verifica Performance")

if not os.path.exists(LOG_CSV):
    st.error(f"File {LOG_CSV} non trovato. Devi prima fare una scansione con lo Sniper!")
    st.stop()

# Caricamento log
df_log = pd.read_csv(LOG_CSV)
df_log['Fixture_ID'] = df_log['Fixture_ID'].astype(str)

# Filtro per data (ieri)
date_scelte = st.multiselect("Seleziona le date da analizzare", df_log['Log_Date'].str[:10].unique())

if st.button("🧐 ANALIZZA RISULTATI REALI"):
    if not date_scelte:
        st.warning("Seleziona almeno una data.")
        st.stop()

    filtered_log = df_log[df_log['Log_Date'].str[:10].isin(date_scelte)]
    results = []
    
    with requests.Session() as s:
        pb = st.progress(0)
        total = len(filtered_log)
        
        for i, row in enumerate(filtered_log.itertuples()):
            pb.progress((i + 1) / total)
            f_id = row.Fixture_ID
            
            try:
                # Chiamata API per il risultato finale
                url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                resp = s.get(url, headers=HEADERS).json()
                
                if resp.get("response"):
                    f_data = resp["response"][0]
                    score = f_data.get("score", {})
                    
                    # Gol Primo Tempo
                    ht_home = score.get("halftime", {}).get("home", 0) or 0
                    ht_away = score.get("halftime", {}).get("away", 0) or 0
                    total_ht = ht_home + ht_away
                    
                    # Gol Finali
                    ft_home = score.get("fulltime", {}).get("home", 0) or 0
                    ft_away = score.get("fulltime", {}).get("away", 0) or 0
                    total_ft = ft_home + ft_away
                    
                    # Verifica Esiti
                    win_05ht = "✅" if total_ht >= 1 else "❌"
                    win_15ht = "✅" if total_ht >= 2 else "❌"
                    win_25ft = "✅" if total_ft >= 3 else "❌"
                    
                    results.append({
                        "Match": row.Match,
                        "Tag": row.Info,
                        "Risultato HT": f"{ht_home}-{ht_away}",
                        "Risultato FT": f"{ft_home}-{ft_away}",
                        "O0.5 HT": win_05ht,
                        "O2.5 FT": win_25ft,
                        "Rating": row.Rating
                    })
            except:
                continue

    if results:
        res_df = pd.DataFrame(results)
        st.write("### Dettaglio Match Analizzati")
        st.dataframe(res_df, use_container_width=True)
        
        # --- STATISTICHE PER TAG (Quello che ti serve per il DRY) ---
        st.markdown("---")
        st.write("### 📈 Performance per Categoria")
        
        # Creiamo mini-statistiche
        categories = ["DRY", "HT", "Drop", "Inv"]
        stats_list = []
        
        for cat in categories:
            cat_df = res_df[res_df['Tag'].str.contains(cat)]
            if not cat_df.empty:
                win_rate_ht = (cat_df['O0.5 HT'] == "✅").mean() * 100
                win_rate_ft = (cat_df['O2.5 FT'] == "✅").mean() * 100
                stats_list.append({
                    "Categoria": cat,
                    "Campioni": len(cat_df),
                    "Win Rate O0.5 HT": f"{win_rate_ht:.1f}%",
                    "Win Rate O2.5 FT": f"{win_rate_ft:.1f}%"
                })
        
        st.table(pd.DataFrame(stats_list))

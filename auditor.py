import streamlit as st
import pandas as pd
import requests
import os  # <--- Fondamentale per evitare il NameError
from datetime import datetime

# Configurazione API
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}
LOG_CSV = "sniper_history_log.csv"

st.set_page_config(page_title="ARAB AUDITOR V1.1", layout="wide")

st.title("📊 Arab Auditor - Verifica Performance")

# DEBUG: Vediamo cosa vede il server
st.write("📁 File presenti sul server:", os.listdir("."))

if not os.path.exists(LOG_CSV):
    st.error(f"❌ Il file '{LOG_CSV}' non esiste ancora in questa sessione.")
    st.info("💡 Consiglio: Se sei su Streamlit Cloud, apri prima l'app principale, fai uno Scan per generare il file, e poi torna qui senza chiudere il browser.")
    st.stop()

# Caricamento log
df_log = pd.read_csv(LOG_CSV)
df_log['Fixture_ID'] = df_log['Fixture_ID'].astype(str)

# Filtro per data (prendiamo le prime 10 cifre della colonna Log_Date)
# Se la colonna Log_Date non esiste, usiamo un fallback
if 'Log_Date' in df_log.columns:
    date_unche = df_log['Log_Date'].str[:10].unique()
    date_scelte = st.multiselect("📅 Seleziona le date da analizzare", date_unche)
else:
    st.warning("Colonna Log_Date non trovata. Analizzo tutti i match.")
    date_scelte = []

if st.button("🧐 ANALIZZA RISULTATI REALI"):
    filtered_log = df_log
    if date_scelte:
        filtered_log = df_log[df_log['Log_Date'].str[:10].isin(date_scelte)]
    
    results = []
    pb = st.progress(0)
    total = len(filtered_log)
    
    with requests.Session() as s:
        for i, row in enumerate(filtered_log.itertuples()):
            pb.progress((i + 1) / total)
            f_id = row.Fixture_ID
            
            try:
                url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                resp = s.get(url, headers=HEADERS).json()
                
                if resp.get("response"):
                    f_data = resp["response"][0]
                    score = f_data.get("score", {})
                    
                    # Dati Gol
                    ht_home = score.get("halftime", {}).get("home", 0) or 0
                    ht_away = score.get("halftime", {}).get("away", 0) or 0
                    total_ht = ht_home + ht_away
                    
                    ft_home = f_data.get("goals", {}).get("home", 0) or 0
                    ft_away = f_data.get("goals", {}).get("away", 0) or 0
                    total_ft = ft_home + ft_away
                    
                    results.append({
                        "Match": row.Match,
                        "Tag": getattr(row, "Info", ""),
                        "Risultato HT": f"{ht_home}-{ht_away}",
                        "Risultato FT": f"{ft_home}-{ft_away}",
                        "O0.5 HT": "✅" if total_ht >= 1 else "❌",
                        "O2.5 FT": "✅" if total_ft >= 3 else "❌",
                        "Rating": row.Rating
                    })
            except Exception as e:
                continue

    if results:
        res_df = pd.DataFrame(results)
        st.write("### 📝 Dettaglio Match Analizzati")
        st.dataframe(res_df, use_container_width=True)
        
        # Statistiche Categorie
        st.markdown("---")
        st.subheader("📈 Performance per Tag (HT vs DRY)")
        stats_list = []
        for cat in ["DRY", "HT", "Drop", "Inv"]:
            cat_df = res_df[res_df['Tag'].str.contains(cat, na=False)]
            if not cat_df.empty:
                win_ht = (cat_df['O0.5 HT'] == "✅").mean() * 100
                win_ft = (cat_df['O2.5 FT'] == "✅").mean() * 100
                stats_list.append({
                    "Categoria": cat,
                    "Campioni": len(cat_df),
                    "Win Rate HT": f"{win_ht:.1f}%",
                    "Win Rate O2.5 FT": f"{win_ft:.1f}%"
                })
        if stats_list:
            st.table(pd.DataFrame(stats_list))

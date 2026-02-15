import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# Configurazione API (Assicurati che la chiave sia nei Secrets di Streamlit)
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.set_page_config(page_title="ARAB AUDITOR V1.3", layout="wide")

st.title("📊 Arab Auditor - Verifica Risultati")
st.markdown("Carica il file `.csv` scaricato dallo Sniper per confrontare le previsioni con i risultati reali.")

# --- CARICAMENTO FILE ---
uploaded_file = st.file_uploader("📂 Carica CSV Sessione o Database Storico", type="csv")

if uploaded_file is not None:
    # Lettura forzando Fixture_ID come stringa per coerenza con lo Sniper
    df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
    
    st.success(f"✅ Caricati {len(df_log)} match dal file.")

    # Selezione date disponibili nel file
    if 'Log_Date' in df_log.columns:
        date_disponibili = sorted(df_log['Log_Date'].str[:10].unique(), reverse=True)
        date_scelte = st.multiselect("📅 Seleziona le date da analizzare", date_disponibili, default=date_disponibili[:1])
    else:
        st.warning("⚠️ Colonna 'Log_Date' non trovata. Verranno analizzati tutti i match nel file.")
        date_scelte = []

    if st.button("🧐 AVVIA VERIFICA REALE"):
        # Filtriamo i match in base alle date scelte
        if date_scelte:
            work_df = df_log[df_log['Log_Date'].str[:10].isin(date_scelte)]
        else:
            work_df = df_log

        if work_df.empty:
            st.error("Nessun match trovato per le date selezionate.")
        else:
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with requests.Session() as s:
                for i, row in enumerate(work_df.itertuples()):
                    # Update Progress
                    prog = (i + 1) / len(work_df)
                    progress_bar.progress(prog)
                    status_text.text(f"Analisi match {i+1} di {len(work_df)}: {row.Match}")
                    
                    try:
                        # Chiamata API per il risultato della fixture
                        url = f"https://v3.football.api-sports.io/fixtures?id={row.Fixture_ID}"
                        resp = s.get(url, headers=HEADERS, timeout=10).json()
                        
                        if resp.get("response"):
                            data = resp["response"][0]
                            status_short = data["fixture"]["status"]["short"]
                            
                            # Verifichiamo solo match terminati (FT) o in corso ma con dati score
                            if status_short in ["FT", "AET", "PEN", "1H", "HT", "2H"]:
                                score = data.get("score", {})
                                goals = data.get("goals", {})
                                
                                # Gol Primo Tempo
                                ht_h = score.get("halftime", {}).get("home", 0) or 0
                                ht_a = score.get("halftime", {}).get("away", 0) or 0
                                tot_ht = ht_h + ht_a
                                
                                # Gol Finali
                                ft_h = goals.get("home", 0) or 0
                                ft_a = goals.get("away", 0) or 0
                                tot_ft = ft_h + ft_a
                                
                                results.append({
                                    "Ora": getattr(row, "Ora", "--:--"),
                                    "Match": row.Match,
                                    "Tag": getattr(row, "Info", ""),
                                    "Esito HT": f"{ht_h}-{ht_a}",
                                    "Esito FT": f"{ft_h}-{ft_a}",
                                    "O0.5 HT": "✅ WIN" if tot_ht >= 1 else "❌ LOSS",
                                    "O2.5 FT": "✅ WIN" if tot_ft >= 3 else "❌ LOSS",
                                    "Rating": row.Rating
                                })
                    except Exception as e:
                        continue

            if results:
                res_df = pd.DataFrame(results)
                
                # --- VISUALIZZAZIONE RISULTATI ---
                st.subheader("📝 Dettaglio Esiti Reali")
                
                # Funzione per colorare le celle degli esiti
                def color_result(val):
                    color = '#2ecc71' if '✅' in str(val) else '#e74c3c'
                    return f'color: {color}; font-weight: bold'

                st.dataframe(res_df.style.applymap(color_result, subset=['O0.5 HT', 'O2.5 FT']), use_container_width=True)

                # --- STATISTICHE AGGREGATE PER TAG ---
                st.markdown("---")
                st.subheader("📈 Analisi Performance per Strategia")
                
                summary = []
                for tag in ["DRY", "HT", "Drop", "Inv"]:
                    tag_df = res_df[res_df['Tag'].str.contains(tag, na=False)]
                    if not tag_df.empty:
                        win_ht = (tag_df['O0.5 HT'] == "✅ WIN").sum()
                        total = len(tag_df)
                        wr_ht = (win_ht / total) * 100
                        wr_ft = (tag_df['O2.5 FT'] == "✅ WIN").mean() * 100
                        
                        summary.append({
                            "Strategia": tag,
                            "Match Totali": total,
                            "Win Over 0.5 HT": f"{win_ht} / {total}",
                            "Win Rate HT": f"{wr_ht:.1f}%",
                            "Win Rate Over 2.5 FT": f"{wr_ft:.1f}%"
                        })
                
                if summary:
                    st.table(pd.DataFrame(
                        

import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# ============================
# CONFIGURAZIONE API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.set_page_config(page_title="ARAB AUDITOR V1.4 - HIGH COMPATIBILITY", layout="wide")

st.title("📊 Arab Auditor - Verifica Risultati")
st.markdown("""
    In questa pagina puoi caricare il database salvato dallo Sniper per verificare gli esiti reali delle partite.
    Assicurati che il file scaricato termini con **.csv**.
""")

# --- CARICAMENTO FILE (COMPATIBILITÀ ESTESA) ---
uploaded_file = st.file_uploader(
    "📂 Carica CSV Sessione o Database Storico", 
    type=["csv", "txt"], 
    help="Se il file non è selezionabile, prova a rinominarlo in .csv o trascinalo qui."
)

if uploaded_file is not None:
    try:
        # Lettura con gestione errori di codifica
        df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str}, encoding='utf-8')
        st.success(f"✅ File caricato correttamente! Rilevati {len(df_log)} match.")

        # --- SELEZIONE DATE ---
        if 'Log_Date' in df_log.columns:
            # Pulizia e ordinamento date
            date_raw = df_log['Log_Date'].dropna().str[:10].unique()
            date_disponibili = sorted(date_raw, reverse=True)
            date_scelte = st.multiselect("📅 Seleziona le date da analizzare", date_disponibili, default=date_disponibili[:1])
        else:
            st.warning("⚠️ Colonna 'Log_Date' non trovata. Verranno analizzati tutti i match presenti.")
            date_scelte = []

        if st.button("🧐 AVVIA VERIFICA REALE"):
            if date_scelte:
                work_df = df_log[df_log['Log_Date'].str[:10].isin(date_scelte)]
            else:
                work_df = df_log

            if work_df.empty:
                st.error("Nessun match trovato per i criteri selezionati.")
            else:
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                with requests.Session() as s:
                    total_match = len(work_df)
                    for i, row in enumerate(work_df.itertuples()):
                        # Update Progress
                        prog = (i + 1) / total_match
                        progress_bar.progress(prog)
                        status_text.text(f"Recupero dati match {i+1}/{total_match}: {row.Match}")
                        
                        try:
                            # Chiamata API Fixture
                            url = f"https://v3.football.api-sports.io/fixtures?id={row.Fixture_ID}"
                            resp = s.get(url, headers=HEADERS, timeout=12).json()
                            
                            if resp.get("response"):
                                data = resp["response"][0]
                                status_short = data["fixture"]["status"]["short"]
                                
                                # Consideriamo match conclusi o live con dati parziali
                                score = data.get("score", {})
                                goals = data.get("goals", {})
                                
                                # Gol Primo Tempo (Halftime)
                                ht_h = score.get("halftime", {}).get("home", 0) or 0
                                ht_a = score.get("halftime", {}).get("away", 0) or 0
                                tot_ht = ht_h + ht_a
                                
                                # Gol Finali (Fulltime)
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
                        except:
                            continue

                if results:
                    res_df = pd.DataFrame(results)
                    st.subheader("📝 Dettaglio Esiti Acquisiti")
                    
                    # Funzione stile per tabella
                    def style_results(val):
                        if '✅' in str(val): return 'color: #2ecc71; font-weight: bold'
                        if '❌' in str(val): return 'color: #e74c3c; font-weight: bold'
                        return ''

                    st.dataframe(res_df.style.applymap(style_results, subset=['O0.5 HT', 'O2.5 FT']), use_container_width=True)

                    # --- ANALISI STATISTICA PER TAG ---
                    st.markdown("---")
                    st.subheader("📈 Analisi Performance per Strategia")
                    
                    summary = []
                    for tag in ["DRY", "HT", "Drop", "Inv"]:
                        tag_df = res_df[res_df['Tag'].str.contains(tag, na=False)]
                        if not tag_df.empty:
                            total = len(tag_df)
                            win_ht = (tag_df['O0.5 HT'] == "✅ WIN").sum()
                            wr_ht = (win_ht / total) * 100
                            wr_ft = (tag_df['O2.5 FT'] == "✅ WIN").mean() * 100
                            
                            summary.append({
                                "Strategia": tag,
                                "Match": total,
                                "Win HT": f"{win_ht}/{total}",
                                "WR HT %": f"{wr_ht:.1f}%",
                                "WR O2.5 FT %": f"{wr_ft:.1f}%"
                            })
                    
                    if summary:
                        st.table(pd.DataFrame(summary))
                    
                    # Esportazione report verificato
                    final_csv = res_df.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Scarica Audit Verificato (CSV)", final_csv, f"audit_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
                else:
                    st.info("Nessun match terminato trovato nel file caricato.")
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        st.info("Prova a scaricare nuovamente il file dallo Sniper e caricalo senza aprirlo con Excel.")

else:
    st.info("👋 In attesa del file CSV. Trascina qui il file scaricato dallo Sniper.")


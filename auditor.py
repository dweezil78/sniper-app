import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

# ============================
# CONFIGURAZIONE API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.set_page_config(page_title="ARAB AUDITOR V1.6", layout="wide")

st.title("📊 Arab Auditor - Verifica Risultati")

# --- CARICAMENTO FILE ---
uploaded_file = st.file_uploader(
    "📂 Seleziona il file CSV dai tuoi Download", 
    type=None,
    help="Seleziona il file scaricato dallo Sniper"
)

if uploaded_file is not None:
    try:
        # Caricamento flessibile
        df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
        
        if "Fixture_ID" not in df_log.columns:
            st.error("⚠️ Il file non contiene la colonna 'Fixture_ID'. Assicurati di aver scaricato il CSV corretto dallo Sniper.")
        else:
            st.success(f"✅ File caricato: {len(df_log)} match pronti.")

            # Selezione date (se presenti)
            date_scelte = []
            if 'Log_Date' in df_log.columns:
                date_disponibili = sorted(df_log['Log_Date'].dropna().str[:10].unique(), reverse=True)
                date_scelte = st.multiselect("📅 Seleziona date da analizzare", date_disponibili, default=date_disponibili[:1])

            if st.button("🧐 AVVIA VERIFICA REALE"):
                # Filtro dati
                work_df = df_log[df_log['Log_Date'].str[:10].isin(date_scelte)] if date_scelte else df_log
                
                if work_df.empty:
                    st.warning("Nessun match trovato per i criteri selezionati.")
                else:
                    results = []
                    progress_bar = st.progress(0)
                    status_text = st.empty() # Messaggio di stato live
                    
                    with requests.Session() as s:
                        total_match = len(work_df)
                        for i, row in enumerate(work_df.itertuples()):
                            # Aggiornamento UI
                            current_prog = (i + 1) / total_match
                            progress_bar.progress(current_prog)
                            status_text.markdown(f"🔍 **Analisi {i+1}/{total_match}**: {getattr(row, 'Match', 'Sconosciuto')}")
                            
                            try:
                                f_id = str(getattr(row, "Fixture_ID")).strip()
                                url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                                resp = s.get(url, headers=HEADERS, timeout=10).json()
                                
                                if resp.get("response"):
                                    f_data = resp["response"][0]
                                    score = f_data.get("score", {})
                                    goals = f_data.get("goals", {})
                                    
                                    # Dati Gol HT
                                    ht_h = score.get("halftime", {}).get("home", 0) or 0
                                    ht_a = score.get("halftime", {}).get("away", 0) or 0
                                    tot_ht = ht_h + ht_a
                                    
                                    # Dati Gol FT
                                    ft_h = goals.get("home", 0) or 0
                                    ft_a = goals.get("away", 0) or 0
                                    tot_ft = ft_h + ft_a
                                    
                                    results.append({
                                        "Ora": getattr(row, "Ora", "--:--"),
                                        "Match": getattr(row, "Match", "N/A"),
                                        "Tag": getattr(row, "Info", ""),
                                        "HT": f"{ht_h}-{ht_a}",
                                        "FT": f"{ft_h}-{ft_a}",
                                        "O0.5 HT": "✅ WIN" if tot_ht >= 1 else "❌ LOSS",
                                        "O2.5 FT": "✅ WIN" if tot_ft >= 3 else "❌ LOSS",
                                        "Rating": getattr(row, "Rating", 0)
                                    })
                                    
                                    # Piccola pausa per non sovraccaricare l'API su mobile
                                    if i % 10 == 0: time.sleep(0.1)
                                    
                            except Exception:
                                continue

                    status_text.success("✅ Analisi completata!")
                    
                    if results:
                        res_df = pd.DataFrame(results)
                        
                        # Visualizzazione Tabella Dettagliata
                        st.subheader("📝 Dettaglio Risultati")
                        def style_win_loss(val):
                            if '✅' in str(val): return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                            if '❌' in str(val): return 'background-color: #f8d7da; color: #721c24; font-weight: bold;'
                            return ''
                        
                        st.dataframe(res_df.style.applymap(style_win_loss, subset=['O0.5 HT', 'O2.5 FT']), use_container_width=True)

                        # Statistiche per Strategia
                        st.markdown("---")
                        st.subheader("📈 Performance Strategie")
                        summary = []
                        for tag in ["DRY", "HT", "Drop", "Inv"]:
                            tag_df = res_df[res_df['Tag'].str.contains(tag, na=False)]
                            if not tag_df.empty:
                                n = len(tag_df)
                                w_ht = (tag_df['O0.5 HT'] == "✅ WIN").sum()
                                wr_ht = (w_ht / n) * 100
                                wr_ft = (tag_df['O2.5 FT'] == "✅ WIN").mean() * 100
                                summary.append({
                                    "Strategia": tag, 
                                    "Match": n, 
                                    "Win HT": f"{w_ht}/{n}", 
                                    "WR HT %": f"{wr_ht:.1f}%", 
                                    "WR FT %": f"{wr_ft:.1f}%"
                                })
                        
                        if summary:
                            st.table(pd.DataFrame(summary))
                        
                        # Download Report Finale
                        csv_final = res_df.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 SCARICA AUDIT FINALE", csv_final, f"audit_{datetime.now().strftime('%d_%m')}.csv", "text/csv")
                    else:
                        st.info("Nessun dato recuperato. Verifica che le partite siano concluse o iniziate.")
    except Exception as e:
        st.error(f"Errore critico: {e}")
else:
    st.info("👋 Carica il file per iniziare la verifica reale.")

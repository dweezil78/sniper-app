import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# ============================
# CONFIGURAZIONE API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.set_page_config(page_title="ARAB AUDITOR V1.5", layout="wide")

st.title("📊 Arab Auditor - Verifica Risultati")

# --- FIX PER ANDROID: Rimosso 'type' restrittivo per permettere la selezione ---
uploaded_file = st.file_uploader(
    "📂 Seleziona il file CSV dai tuoi Download", 
    type=None, # Rende cliccabili tutti i file su Android
    help="Seleziona il file scaricato dallo Sniper (es. session_results...)"
)

if uploaded_file is not None:
    try:
        # Tentativo di lettura flessibile
        df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
        
        # Verifica minima colonne per confermare sia il file giusto
        if "Fixture_ID" not in df_log.columns or "Match" not in df_log.columns:
            st.error("⚠️ Il file selezionato non sembra essere un report valido dello Sniper.")
        else:
            st.success(f"✅ File caricato: {len(df_log)} match pronti.")

            # --- SELEZIONE DATE ---
            if 'Log_Date' in df_log.columns:
                date_raw = df_log['Log_Date'].dropna().str[:10].unique()
                date_disponibili = sorted(date_raw, reverse=True)
                date_scelte = st.multiselect("📅 Seleziona date", date_disponibili, default=date_disponibili[:1])
            else:
                date_scelte = []

            if st.button("🧐 AVVIA VERIFICA REALE"):
                work_df = df_log[df_log['Log_Date'].str[:10].isin(date_scelte)] if date_scelte else df_log

                if work_df.empty:
                    st.error("Nessun match trovato.")
                else:
                    results = []
                    progress_bar = st.progress(0)
                    
                    with requests.Session() as s:
                        total_match = len(work_df)
                        for i, row in enumerate(work_df.itertuples()):
                            progress_bar.progress((i + 1) / total_match)
                            
                            try:
                                url = f"https://v3.football.api-sports.io/fixtures?id={row.Fixture_ID}"
                                resp = s.get(url, headers=HEADERS, timeout=12).json()
                                
                                if resp.get("response"):
                                    data = resp["response"][0]
                                    score = data.get("score", {})
                                    goals = data.get("goals", {})
                                    
                                    ht_h = score.get("halftime", {}).get("home", 0) or 0
                                    ht_a = score.get("halftime", {}).get("away", 0) or 0
                                    tot_ht = ht_h + ht_a
                                    
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
                        st.subheader("📝 Dettaglio Esiti")
                        
                        def style_results(val):
                            if '✅' in str(val): return 'color: #2ecc71; font-weight: bold'
                            if '❌' in str(val): return 'color: #e74c3c; font-weight: bold'
                            return ''

                        st.dataframe(res_df.style.applymap(style_results, subset=['O0.5 HT', 'O2.5 FT']), use_container_width=True)

                        # --- ANALISI PER STRATEGIA ---
                        st.markdown("---")
                        summary = []
                        for tag in ["DRY", "HT", "Drop", "Inv"]:
                            tag_df = res_df[res_df['Tag'].str.contains(tag, na=False)]
                            if not tag_df.empty:
                                total = len(tag_df)
                                win_ht = (tag_df['O0.5 HT'] == "✅ WIN").sum()
                                wr_ht = (win_ht / total) * 100
                                wr_ft = (tag_df['O2.5 FT'] == "✅ WIN").mean() * 100
                                summary.append({"Strategia": tag, "Match": total, "Win HT": f"{win_ht}/{total}", "WR HT %": f"{wr_ht:.1f}%", "WR O2.5 FT %": f"{wr_ft:.1f}%"})
                        
                        if summary:
                            st.table(pd.DataFrame(summary))
                        
                        final_csv = res_df.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Scarica Audit", final_csv, "audit_finale.csv", "text/csv")
    except Exception as e:
        st.error(f"Errore: {e}")
else:
    st.info("👋 Android: Clicca sopra e seleziona il file .csv dalla cartella Download.")
    

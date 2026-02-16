import streamlit as st
import pandas as pd
import requests
import os
from pathlib import Path
from datetime import datetime

# ============================
# CONFIGURAZIONE PATH ASSOLUTI
# ============================
BASE_DIR = Path(__file__).resolve().parent
LOG_CSV = str(BASE_DIR / "sniper_history_log.csv")

st.set_page_config(page_title="ARAB AUDITOR V2.3", layout="wide")

# Configurazione API
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 Arab Auditor - Analisi Professionale")

# ============================
# SELEZIONE SORGENTE DATI
# ============================
st.sidebar.header("📂 Sorgente Dati")
uploaded_file = st.sidebar.file_uploader("Carica CSV manualmente (opzionale)", type=["csv"])

df_log = None

if uploaded_file is not None:
    # MODO 1: CARICAMENTO MANUALE
    try:
        df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
        st.success(f"✅ File caricato manualmente: {uploaded_file.name}")
    except Exception as e:
        st.error(f"Errore nel caricamento del file manuale: {e}")
else:
    # MODO 2: CARICAMENTO AUTOMATICO SINCRONIZZATO
    if os.path.exists(LOG_CSV):
        try:
            df_log = pd.read_csv(LOG_CSV, dtype={"Fixture_ID": str})
            st.info(f"🔄 Utilizzo database sincronizzato: `{os.path.basename(LOG_CSV)}`")
        except Exception as e:
            st.error(f"Errore nella lettura del database automatico: {e}")
    else:
        st.warning("⚠️ Nessun database trovato. Carica un file manualmente o esegui lo Sniper.")

# ============================
# LOGICA DI ANALISI (Se i dati sono presenti)
# ============================
if df_log is not None:
    # Pulizia e Parsing
    df_log = df_log.dropna(subset=['Fixture_ID', 'Match'])
    
    def get_fav_odd(val):
        try:
            odds = [float(x) for x in str(val).split('|')]
            return min(odds[0], odds[2])
        except: return 0.0

    df_log['Quota_Fav'] = df_log['1X2'].apply(get_fav_odd)

    # Sidebar Filtri
    st.sidebar.subheader("🎯 Filtri Analisi")
    q_min = st.sidebar.number_input("Quota Minima", value=1.40, step=0.05)
    q_max = st.sidebar.number_input("Quota Massima", value=1.95, step=0.05)
    
    if 'Log_Date' in df_log.columns:
        date_raw = df_log['Log_Date'].dropna().str[:10].unique()
        date_disponibili = sorted(date_raw, reverse=True)
        date_scelte = st.multiselect("📅 Date", date_disponibili, default=date_disponibili[:1])
    else:
        date_scelte = []

    if st.button("🧐 AVVIA REVISIONE REALE"):
        work_df = df_log[(df_log['Quota_Fav'] >= q_min) & (df_log['Quota_Fav'] <= q_max)]
        if date_scelte:
            work_df = work_df[work_df['Log_Date'].str[:10].isin(date_scelte)]

        if work_df.empty:
            st.warning("Nessun match trovato per questi filtri.")
        else:
            results = []
            progress_bar = st.progress(0)
            
            with requests.Session() as s:
                total_work = len(work_df)
                for i, row in enumerate(work_df.itertuples()):
                    progress_bar.progress((i + 1) / total_work)
                    f_id = str(row.Fixture_ID).split('.')[0].strip()
                    
                    try:
                        url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                        resp = s.get(url, headers=HEADERS, timeout=12).json()
                        
                        if resp.get("response"):
                            f_data = resp["response"][0]
                            score = f_data.get("score", {})
                            goals = f_data.get("goals", {})
                            
                            ht_h = (score.get("halftime", {}) or {}).get("home", 0) or 0
                            ht_a = (score.get("halftime", {}) or {}).get("away", 0) or 0
                            ft_h = goals.get("home", 0) or 0
                            ft_a = goals.get("away", 0) or 0
                            
                            results.append({
                                "Data": getattr(row, "Log_Date", "--"),
                                "Match": row.Match,
                                "Q": row.Quota_Fav,
                                "Tag": getattr(row, "Info", ""),
                                "HT": f"{ht_h}-{ht_a}",
                                "FT": f"{ft_h}-{ft_a}",
                                "O0.5 HT": "✅ WIN" if (ht_h+ht_a) >= 1 else "❌ LOSS",
                                "O2.5 FT": "✅ WIN" if (ft_h+ft_a) >= 3 else "❌ LOSS"
                            })
                    except: continue

            if results:
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                
                # Statistiche
                summary = []
                for tag in ["DRY", "HT", "Drop", "Inv"]:
                    tag_df = res_df[res_df['Tag'].str.contains(tag, na=False)]
                    if not tag_df.empty:
                        n = len(tag_df)
                        w_ht = (tag_df['O0.5 HT'] == "✅ WIN").sum()
                        summary.append({"Strategia": tag, "Match": n, "WR HT %": f"{(w_ht/n*100):.1f}%"})
                st.table(pd.DataFrame(summary))

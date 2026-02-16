import streamlit as st
import pandas as pd
import requests
import os
from pathlib import Path
from datetime import datetime

# ============================
# CONFIGURAZIONE PATH ASSOLUTI
# ============================
# IDENTICO allo Sniper per garantire la sincronizzazione totale
BASE_DIR = Path(__file__).resolve().parent
LOG_CSV = str(BASE_DIR / "sniper_history_log.csv")

st.set_page_config(page_title="ARAB AUDITOR V2.2 - GOLD SYNC", layout="wide")

# UI SIDEBAR CON DEBUG PERCORSI
st.sidebar.header("⚙️ Auditor Settings")
st.sidebar.caption(f"📁 BASE_DIR: {BASE_DIR}")
st.sidebar.caption(f"📝 LOG_CSV: {LOG_CSV}")

# Configurazione API (dallo stesso Secret dello Sniper)
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 Arab Auditor - Analisi Sweet Spot")
st.markdown(f"Revisione dei risultati reali basata sul database: `{os.path.basename(LOG_CSV)}`")

# ============================
# LOGICA DI CARICAMENTO
# ============================
if not os.path.exists(LOG_CSV):
    st.error(f"⚠️ Database non trovato!")
    st.info(f"Il file {LOG_CSV} non esiste ancora. Esegui prima una scansione con Arab Sniper per generare i dati.")
    st.stop()

try:
    # Caricamento database con Fixture_ID come stringa per evitare decimali
    df_log = pd.read_csv(LOG_CSV, dtype={"Fixture_ID": str})
    
    # Pulizia dati: rimuoviamo eventuali righe corrotte
    df_log = df_log.dropna(subset=['Fixture_ID', 'Match'])
    
    st.success(f"✅ Database sincronizzato: {len(df_log)} match totali rilevati.")

    # --- FILTRO RANGE QUOTA ---
    # Estrarre la quota del favorito dal formato "1.60|3.40|4.50"
    def get_fav_odd(val):
        try:
            odds = [float(x) for x in str(val).split('|')]
            return min(odds[0], odds[2])
        except: return 0.0

    df_log['Quota_Fav'] = df_log['1X2'].apply(get_fav_odd)

    st.sidebar.subheader("🎯 Filtri Analisi")
    q_min = st.sidebar.number_input("Quota Minima", value=1.40, step=0.05)
    q_max = st.sidebar.number_input("Quota Massima", value=1.95, step=0.05)
    
    # Selezione Date
    if 'Log_Date' in df_log.columns:
        date_raw = df_log['Log_Date'].str[:10].unique()
        date_disponibili = sorted(date_raw, reverse=True)
        date_scelte = st.multiselect("📅 Seleziona date da revisionare", date_disponibili, default=date_disponibili[:1])
    else:
        date_scelte = []

    # --- ESECUZIONE AUDIT ---
    if st.button("🧐 AVVIA REVISIONE REALE"):
        # Applichiamo i filtri definiti
        work_df = df_log[(df_log['Quota_Fav'] >= q_min) & (df_log['Quota_Fav'] <= q_max)]
        if date_scelte:
            work_df = work_df[work_df['Log_Date'].str[:10].isin(date_scelte)]

        if work_df.empty:
            st.warning("Nessun match trovato per i criteri di quota/data selezionati.")
        else:
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with requests.Session() as s:
                total = len(work_df)
                for i, row in enumerate(work_df.itertuples()):
                    progress_bar.progress((i + 1) / total)
                    f_id = str(row.Fixture_ID).split('.')[0].strip()
                    status_text.text(f"Recupero esito {i+1}/{total}: {row.Match}")
                    
                    try:
                        url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                        resp = s.get(url, headers=HEADERS, timeout=12).json()
                        
                        if resp.get("response"):
                            data = resp["response"][0]
                            score = data.get("score", {})
                            goals = data.get("goals", {})
                            
                            ht_h = (score.get("halftime", {}) or {}).get("home", 0) or 0
                            ht_a = (score.get("halftime", {}) or {}).get("away", 0) or 0
                            ft_h = goals.get("home", 0) or 0
                            ft_a = goals.get("away", 0) or 0
                            
                            results.append({
                                "Data": row.Log_Date,
                                "Match": row.Match,
                                "Quota": row.Quota_Fav,
                                "Tag": getattr(row, "Info", ""),
                                "HT": f"{ht_h}-{ht_a}",
                                "FT": f"{ft_h}-{ft_a}",
                                "O0.5 HT": "✅ WIN" if (ht_h + ht_a) >= 1 else "❌ LOSS",
                                "O2.5 FT": "✅ WIN" if (ft_h + ft_a) >= 3 else "❌ LOSS",
                                "Rating": row.Rating
                            })
                    except: continue

            status_text.empty()
            
            if results:
                res_df = pd.DataFrame(results)
                st.subheader("📝 Dettaglio Esiti")
                
                # Colorazione tabellare
                def style_results(val):
                    if '✅' in str(val): return 'color: #2ecc71; font-weight: bold'
                    if '❌' in str(val): return 'color: #e74c3c; font-weight: bold'
                    return ''

                st.dataframe(res_df.style.applymap(style_results, subset=['O0.5 HT', 'O2.5 FT']), use_container_width=True)

                # --- STATISTICHE AGGREGATE ---
                st.markdown("---")
                st.subheader("📈 Performance per Strategia")
                summary = []
                for tag in ["DRY", "HT", "Drop", "Inv"]:
                    tag_df = res_df[res_df['Tag'].str.contains(tag, na=False)]
                    if not tag_df.empty:
                        n = len(tag_df)
                        w_ht = (tag_df['O0.5 HT'] == "✅ WIN").sum()
                        w_ft = (tag_df['O2.5 FT'] == "✅ WIN").sum()
                        summary.append({
                            "Strategia": tag, "Match": n, 
                            "Win HT": f"{w_ht}/{n}", 
                            "WR HT %": f"{(w_ht/n*100):.1f}%",
                            "WR FT %": f"{(w_ft/n*100):.1f}%"
                        })
                
                if summary:
                    st.table(pd.DataFrame(summary))
                
                # Export
                st.download_button("📥 Scarica Report Revisionato", res_df.to_csv(index=False).encode('utf-8'), f"audit_{datetime.now().strftime('%d_%m')}.csv", "text/csv")

except Exception as e:
    st.error(f"Errore durante l'analisi: {e}")

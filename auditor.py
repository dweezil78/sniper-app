import streamlit as st
import pandas as pd
import requests
import os
from pathlib import Path
from datetime import datetime

# ============================
# CONFIGURAZIONE
# ============================
BASE_DIR = Path(__file__).resolve().parent
LOG_CSV = str(BASE_DIR / "sniper_history_log.csv")

st.set_page_config(page_title="ARAB AUDITOR V3.1 - CORRELATION PRO", layout="wide")

API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 Arab Auditor V3.1")
st.markdown("### Analisi Correlazioni Quote (GG PT / O1.5 PT) vs Risultati Reali")

# ============================
# CARICAMENTO DATI
# ============================
st.sidebar.header("📂 Sorgente Dati")
uploaded_file = st.sidebar.file_uploader("Carica CSV generato dallo Sniper", type=["csv"])

df_log = None
if uploaded_file:
    df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
    st.success(f"✅ File caricato: {uploaded_file.name}")
elif os.path.exists(LOG_CSV):
    df_log = pd.read_csv(LOG_CSV, dtype={"Fixture_ID": str})
    st.info("🔄 Utilizzo database storico locale")

# ============================
# MOTORE DI REVISIONE
# ============================
if df_log is not None:
    # Pulizia nomi colonne (rimozione spazi se presenti)
    df_log.columns = df_log.columns.str.strip()
    
    if st.button("🧐 AVVIA AUDIT SUI RISULTATI DI IERI"):
        results = []
        progress_bar = st.progress(0)
        total = len(df_log)
        
        with requests.Session() as s:
            for i, row in enumerate(df_log.itertuples()):
                progress_bar.progress((i + 1) / total)
                f_id = str(row.Fixture_ID).split('.')[0]
                
                try:
                    # Recupero esito reale del match
                    res_url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                    resp = s.get(res_url, headers=HEADERS).json()
                    if not resp.get("response"): continue
                    
                    data = resp["response"][0]
                    score = data.get("score", {})
                    ht_res = score.get("halftime", {})
                    ht_h = ht_res.get("home", 0) if ht_res.get("home") is not None else 0
                    ht_a = ht_res.get("away", 0) if ht_res.get("away") is not None else 0
                    
                    # Analisi Esiti
                    win_05_ht = (ht_h + ht_a) >= 1
                    win_15_ht = (ht_h + ht_a) >= 2
                    win_gg_ht = (ht_h > 0 and ht_a > 0)
                    
                    results.append({
                        "Ora": row.Ora,
                        "Match": row.Match_Disp_Raw if hasattr(row, 'Match_Disp_Raw') else row.Match,
                        "Esito HT": f"{ht_h}-{ht_a}",
                        "Q. GG PT": getattr(row, "GG PT", "N/D"),
                        "Q. O1.5 PT": getattr(row, "O1.5 PT", "N/D"),
                        "O0.5 HT": "✅" if win_05_ht else "❌",
                        "O1.5 HT": "✅" if win_15_ht else "❌",
                        "GG HT": "✅" if win_gg_ht else "❌",
                        "Rating": row.Rating,
                        "Tag": row.Info
                    })
                except: continue

        if results:
            res_df = pd.DataFrame(results)
            st.subheader("📋 Analisi Incrociata: Quote Sniper vs Esiti Reali")
            
            # Formattazione per visualizzazione
            st.dataframe(res_df.style.applymap(
                lambda x: 'background-color: #1b4332; color: white' if x == "✅" else ('background-color: #431b1b; color: white' if x == "❌" else ''),
                subset=["O0.5 HT", "O1.5 HT", "GG HT"]
            ), use_container_width=True)

            # ============================
            # STATISTICHE DI CORRELAZIONE
            # ============================
            st.markdown("---")
            st.subheader("🎯 Insights Strategici")
            c1, c2, c3 = st.columns(3)
            
            with c1:
                wr_05 = (res_df["O0.5 HT"] == "✅").mean() * 100
                st.metric("Win Rate O0.5 HT", f"{wr_05:.1f}%")
            
            with c2:
                # Filtro: Successo Over 1.5 HT quando la quota era < 3.00
                df_o15_guide = res_df[pd.to_numeric(res_df["Q. O1.5 PT"], errors='coerce') <= 3.00]
                if not df_o15_guide.empty:
                    wr_o15 = (df_o15_guide["O1.5 HT"] == "✅").mean() * 100
                    st.metric("WR O1.5 HT (Quota ≤ 3.00)", f"{wr_o15:.1f}%")
                else:
                    st.metric("WR O1.5 HT", "Dati insuf.")

            with c3:
                # Filtro: Successo GG HT quando la quota era < 5.00
                df_gg_guide = res_df[pd.to_numeric(res_df["Q. GG PT"], errors='coerce') <= 5.00]
                if not df_gg_guide.empty:
                    wr_gg = (df_gg_guide["GG HT"] == "✅").mean() * 100
                    st.metric("WR GG HT (Quota ≤ 5.00)", f"{wr_gg:.1f}%")
                else:
                    st.metric("WR GG HT", "Dati insuf.")

            st.download_button("💾 SCARICA AUDIT COMPLETO", data=res_df.to_csv(index=False).encode('utf-8'), file_name=f"audit_results_{datetime.now().strftime('%Y%m%d')}.csv")
else:
    st.warning("Carica un file CSV per iniziare l'analisi.")

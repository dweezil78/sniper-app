import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

# Configurazione API
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.set_page_config(page_title="ARAB AUDITOR V2.1", layout="wide")
st.title("📊 Arab Auditor - Sweet Spot Analysis")
st.markdown("Verifica delle performance nella fascia di quota favorita: **1.45 - 1.89**")

uploaded_file = st.file_uploader("📂 Carica il file CSV dello Sniper", type=None)

if uploaded_file is not None:
    try:
        # Caricamento e parsing quote
        df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
        
        def get_fav_odd(row):
            try:
                # Spacca la stringa "1.60|3.40|4.50" salvata dallo Sniper
                odds = [float(x) for x in str(row['1X2']).split('|')]
                return min(odds[0], odds[2]) # Identifica la quota del favorito (1 o 2)
            except: return 0.0

        df_log['Quota_Fav'] = df_log.apply(get_fav_odd, axis=1)
        
        # Filtro automatico nel range richiesto
        df_filtered = df_log[(df_log['Quota_Fav'] >= 1.45) & (df_log['Quota_Fav'] <= 1.89)]
        
        st.success(f"✅ Database caricato: {len(df_log)} match totali.")
        st.info(f"🎯 Match nel range 1.45 - 1.89: **{len(df_filtered)}**")

        if st.button("🧐 AVVIA VERIFICA SWEET SPOT"):
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with requests.Session() as s:
                total_match = len(df_filtered)
                for i, row in enumerate(df_filtered.itertuples()):
                    progress_bar.progress((i + 1) / total_match)
                    f_id = str(row.Fixture_ID).split('.')[0].strip()
                    status_text.text(f"Verifica {i+1}/{total_match}: {row.Match} (Q: {row.Quota_Fav:.2f})")
                    
                    try:
                        url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                        resp = s.get(url, headers=HEADERS, timeout=12).json()
                        
                        if resp.get("response") and len(resp["response"]) > 0:
                            f_data = resp["response"][0]
                            goals = f_data.get("goals", {})
                            score = f_data.get("score", {})
                            
                            ht_h = (score.get("halftime", {}) or {}).get("home", 0) or 0
                            ht_a = (score.get("halftime", {}) or {}).get("away", 0) or 0
                            ft_h = goals.get("home", 0) or 0
                            ft_a = goals.get("away", 0) or 0
                            
                            results.append({
                                "Match": row.Match,
                                "Quota_Fav": row.Quota_Fav,
                                "Tag": getattr(row, "Info", "N/A"),
                                "HT": f"{ht_h}-{ht_a}",
                                "FT": f"{ft_h}-{ft_a}",
                                "O0.5 HT": "✅ WIN" if (ht_h + ht_a) >= 1 else "❌ LOSS",
                                "O2.5 FT": "✅ WIN" if (ft_h + ft_a) >= 3 else "❌ LOSS"
                            })
                    except: continue

            status_text.empty()
            
            if results:
                res_df = pd.DataFrame(results)
                st.subheader(f"📝 Esiti nel range 1.45 - 1.89 ({len(res_df)} match)")
                st.dataframe(res_df, use_container_width=True)
                
                # --- STATISTICHE PER STRATEGIA ---
                st.markdown("---")
                st.subheader("📈 Performance Strategie nel Range")
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
            else:
                st.warning("Nessun dato trovato per i criteri selezionati.")

    except Exception as e:
        st.error(f"Errore: {e}")

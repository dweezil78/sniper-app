import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

# Configurazione API
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.set_page_config(page_title="ARAB AUDITOR V1.9", layout="wide")
st.title("📊 Arab Auditor - Analisi & Debug")

uploaded_file = st.file_uploader("📂 Carica il file CSV dello Sniper", type=["csv", "txt"])

if uploaded_file is not None:
    try:
        # Caricamento forzando Fixture_ID come stringa
        df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
        st.success(f"✅ Database caricato: {len(df_log)} match pronti.")

        if st.button("🧐 AVVIA REVISIONE TOTALE"):
            results = []
            errors_log = {"429_quota": 0, "404_not_found": 0, "other": 0}
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with requests.Session() as s:
                total_match = len(df_log)
                for i, row in enumerate(df_log.itertuples()):
                    progress_bar.progress((i + 1) / total_match)
                    
                    # Pulizia ID: rimuove decimali .0 e spazi
                    f_id = str(row.Fixture_ID).split('.')[0].strip()
                    status_text.text(f"Verifica Match {i+1}/{total_match}: {row.Match}")
                    
                    try:
                        url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                        resp_raw = s.get(url, headers=HEADERS, timeout=12)
                        
                        if resp_raw.status_code == 429:
                            errors_log["429_quota"] += 1
                            continue
                        
                        resp = resp_raw.json()
                        
                        if resp.get("response") and len(resp["response"]) > 0:
                            f_data = resp["response"][0]
                            goals = f_data.get("goals", {})
                            score = f_data.get("score", {})
                            
                            # Estrazione Gol Sicura
                            ht_h = (score.get("halftime", {}) or {}).get("home", 0) or 0
                            ht_a = (score.get("halftime", {}) or {}).get("away", 0) or 0
                            tot_ht = ht_h + ht_a
                            
                            ft_h = goals.get("home", 0) or 0
                            ft_a = goals.get("away", 0) or 0
                            tot_ft = ft_h + ft_a
                            
                            results.append({
                                "Match": row.Match,
                                "Tag": getattr(row, "Info", "N/A"),
                                "HT": f"{ht_h}-{ht_a}",
                                "FT": f"{ft_h}-{ft_a}",
                                "O0.5 HT": "✅ WIN" if tot_ht >= 1 else "❌ LOSS",
                                "O2.5 FT": "✅ WIN" if tot_ft >= 3 else "❌ LOSS",
                                "Rating": row.Rating
                            })
                        else:
                            errors_log["404_not_found"] += 1
                            
                    except Exception:
                        errors_log["other"] += 1
                        continue
            
            status_text.empty()
            
            # --- SEZIONE DEBUG ---
            if errors_log["429_quota"] > 0:
                st.error(f"🚫 LIMITE QUOTA RAGGIUNTO: {errors_log['429_quota']} match saltati per limite API giornaliero.")
            
            if results:
                res_df = pd.DataFrame(results)
                st.subheader("📝 Risultati Reali")
                
                def color_results(val):
                    if '✅' in str(val): return 'color: #2ecc71; font-weight: bold'
                    if '❌' in str(val): return 'color: #e74c3c; font-weight: bold'
                    return ''
                
                st.dataframe(res_df.style.applymap(color_results, subset=['O0.5 HT', 'O2.5 FT']), use_container_width=True)
                
                # Performance per Strategia
                st.markdown("---")
                summary = []
                for tag in ["DRY", "HT", "Drop", "Inv"]:
                    tag_df = res_df[res_df['Tag'].str.contains(tag, na=False)]
                    if not tag_df.empty:
                        total = len(tag_df)
                        win_ht = (tag_df['O0.5 HT'] == "✅ WIN").sum()
                        summary.append({
                            "Strategia": tag, "Match": total, 
                            "Win HT": f"{win_ht}/{total}", 
                            "WR HT %": f"{(win_ht/total*100):.1f}%",
                            "WR FT %": f"{(tag_df['O2.5 FT'] == '✅ WIN').mean()*100:.1f}%"
                        })
                st.table(pd.DataFrame(summary))
            else:
                st.error(f"❌ Nessun dato recuperato. Debug: {errors_log}")

    except Exception as e:
        st.error(f"Errore: {e}")

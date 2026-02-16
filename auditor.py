import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

# Configurazione API
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.set_page_config(page_title="ARAB AUDITOR V1.8", layout="wide")
st.title("📊 Arab Auditor - Analisi Definitiva Ieri")

uploaded_file = st.file_uploader("📂 Carica il file CSV dello Sniper", type=["csv", "txt"])

if uploaded_file is not None:
    try:
        # Carichiamo il file assicurandoci che Fixture_ID sia letto come stringa pura
        df_log = pd.read_csv(uploaded_file, dtype={"Fixture_ID": str})
        st.success(f"✅ Database caricato: {len(df_log)} match pronti.")

        if st.button("🧐 AVVIA REVISIONE TOTALE"):
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with requests.Session() as s:
                total_match = len(df_log)
                for i, row in enumerate(df_log.itertuples()):
                    progress_bar.progress((i + 1) / total_match)
                    
                    # Pulizia ID: fondamentale per evitare errori di chiamata API
                    f_id = str(row.Fixture_ID).strip().replace(".0", "")
                    status_text.text(f"Verifica Match {i+1}/{total_match}: {row.Match}")
                    
                    try:
                        # Chiamata API Fixture
                        url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
                        resp = s.get(url, headers=HEADERS, timeout=12).json()
                        
                        if resp.get("response") and len(resp["response"]) > 0:
                            f_data = resp["response"][0]
                            goals = f_data.get("goals", {})
                            score = f_data.get("score", {})
                            
                            # Estraiamo i gol in modo ultra-sicuro
                            ht_h = (score.get("halftime", {}) or {}).get("home", 0) if score.get("halftime") else 0
                            ht_a = (score.get("halftime", {}) or {}).get("away", 0) if score.get("halftime") else 0
                            tot_ht = (ht_h or 0) + (ht_a or 0)
                            
                            ft_h = goals.get("home", 0) if goals.get("home") is not None else 0
                            ft_a = goals.get("away", 0) if goals.get("away") is not None else 0
                            tot_ft = (ft_h or 0) + (ft_a or 0)
                            
                            results.append({
                                "Match": row.Match,
                                "Tag": getattr(row, "Info", "N/A"),
                                "HT": f"{ht_h}-{ht_a}",
                                "FT": f"{ft_h}-{ft_a}",
                                "O0.5 HT": "✅ WIN" if tot_ht >= 1 else "❌ LOSS",
                                "O2.5 FT": "✅ WIN" if tot_ft >= 3 else "❌ LOSS",
                                "Rating": row.Rating
                            })
                        
                        # Piccola pausa ogni 10 match per non saturare la connessione mobile
                        if i % 10 == 0:
                            time.sleep(0.05)
                            
                    except Exception:
                        continue
            
            status_text.empty()
            
            if results:
                res_df = pd.DataFrame(results)
                st.subheader("📝 Risultati Reali Acquisiti")
                
                # Visualizzazione tabella con stili
                def color_results(val):
                    if '✅' in str(val): return 'color: #2ecc71; font-weight: bold'
                    if '❌' in str(val): return 'color: #e74c3c; font-weight: bold'
                    return ''
                
                st.dataframe(res_df.style.applymap(color_results, subset=['O0.5 HT', 'O2.5 FT']), use_container_width=True)
                
                # --- STATISTICHE PER STRATEGIA ---
                st.markdown("---")
                st.subheader("📈 Analisi Performance")
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
                            "WR FT %": f"{wr_ft:.1f}%"
                        })
                
                if summary:
                    st.table(pd.DataFrame(summary))
                
                st.download_button("📥 Scarica Report Finale", res_df.to_csv(index=False).encode('utf-8'), "audit_completo.csv", "text/csv")
            else:
                st.error("❌ Errore: Nessun dato recuperato. Controlla che le API Keys siano attive e che il file CSV contenga i Fixture_ID corretti.")

    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")

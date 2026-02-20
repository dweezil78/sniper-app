import streamlit as st
import pandas as pd
import requests
import os
from pathlib import Path
from datetime import datetime, timedelta
import json

# ============================
# CONFIGURAZIONE
# ============================
BASE_DIR = Path(__file__).resolve().parent
LOG_CSV = str(BASE_DIR / "sniper_history_log.csv")

st.set_page_config(page_title="ARAB AUDITOR V3.2 - SNIPER SYNC", layout="wide")

API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 Arab Auditor V3.2")
st.markdown("### Audit esiti reali vs quote Sniper (GG PT / O1.5 PT) — allineato alla versione Sniper attuale")

# ============================
# TIMEZONE (ROME) - light
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

def parse_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s in ["", "N/D", "ND", "nan", "None"]:
        return None
    try:
        return float(s.replace(",", "."))
    except:
        return None

def safe_col(df, candidates):
    # ritorna il primo nome colonna presente
    for c in candidates:
        if c in df.columns:
            return c
    return None

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
# MOTORE AUDIT
# ============================
if df_log is not None:
    df_log.columns = df_log.columns.astype(str).str.strip()

    # Mappatura colonne (supporta più versioni)
    col_fixture = safe_col(df_log, ["Fixture_ID", "fixture_id", "FixtureId"])
    col_match = safe_col(df_log, ["Match_Disp_Raw", "Match", "Match_Disp", "Match Disponibili"])
    col_info = safe_col(df_log, ["Info", "Tag"])
    col_rating = safe_col(df_log, ["Rating", "rating"])
    col_time = safe_col(df_log, ["Ora", "Time", "Kickoff"])
    col_logdate = safe_col(df_log, ["Log_Date", "LogDate", "log_date", "Timestamp"])

    col_o05 = safe_col(df_log, ["O0.5 PT", "O0.5HT", "O0.5 HT", "O0.5 1T"])
    col_o15 = safe_col(df_log, ["O1.5 PT", "O1.5HT", "O1.5 HT", "O1.5 1T"])
    col_gg  = safe_col(df_log, ["GG PT", "GG HT", "GG 1T", "Q. GG PT"])
    col_o25 = safe_col(df_log, ["O2.5 Finale", "O2.5", "O2.5 FT"])

    if col_fixture is None:
        st.error("❌ Nel CSV manca la colonna Fixture_ID. Impossibile auditare.")
        st.stop()

    # ---- filtro "ieri" robusto ----
    st.sidebar.markdown("---")
    st.sidebar.subheader("🗓️ Filtro Giorno")

    yesterday = (now_rome().date() - timedelta(days=1))
    default_day = yesterday

    if col_logdate is not None:
        # provo a parse Log_Date
        dt_parsed = pd.to_datetime(df_log[col_logdate], errors="coerce")
        df_log["_log_dt"] = dt_parsed
        df_log["_log_day"] = df_log["_log_dt"].dt.date
        available_days = sorted([d for d in df_log["_log_day"].dropna().unique()])
        if available_days:
            chosen_day = st.sidebar.selectbox("Seleziona giorno (da Log_Date)", options=available_days, index=min(len(available_days)-1, max(0, available_days.index(default_day) if default_day in available_days else len(available_days)-1)))
            df_day = df_log[df_log["_log_day"] == chosen_day].copy()
        else:
            chosen_day = st.sidebar.date_input("Seleziona giorno", value=default_day)
            df_day = df_log.copy()
    else:
        chosen_day = st.sidebar.date_input("Seleziona giorno (Log_Date non trovato)", value=default_day)
        df_day = df_log.copy()

    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Gate Sniper 1–1 HT (quote)")
    gate_o15_min = st.sidebar.number_input("O1.5 PT min", value=2.20, step=0.05, format="%.2f")
    gate_o15_max = st.sidebar.number_input("O1.5 PT max", value=2.80, step=0.05, format="%.2f")
    gate_gg_min  = st.sidebar.number_input("GG PT min", value=4.20, step=0.05, format="%.2f")
    gate_gg_max  = st.sidebar.number_input("GG PT max", value=5.50, step=0.05, format="%.2f")

    only_ball = st.sidebar.toggle("Mostra solo match ⚽ (se presente in Info)", value=False)

    # de-dup fixture id (evita doppie chiamate)
    df_day[col_fixture] = df_day[col_fixture].astype(str).str.split(".").str[0]
    df_day = df_day.dropna(subset=[col_fixture]).copy()
    df_day = df_day.drop_duplicates(subset=[col_fixture]).copy()

    st.write(f"Match nel dataset (giorno selezionato): **{len(df_day)}**")

    def has_ball(info_val):
        return "⚽" in str(info_val or "")

    if only_ball and col_info is not None:
        df_day = df_day[df_day[col_info].apply(has_ball)].copy()
        st.write(f"Filtro ⚽ attivo → match rimasti: **{len(df_day)}**")

    # Pulsante audit
    if st.button("🧐 AVVIA AUDIT (esiti reali)"):
        results = []
        progress_bar = st.progress(0)
        total = len(df_day)

        # cache per evitare richieste duplicate
        fixture_cache = {}

        def fetch_fixture(session, f_id):
            if f_id in fixture_cache:
                return fixture_cache[f_id]
            try:
                resp = session.get("https://v3.football.api-sports.io/fixtures", headers=HEADERS, params={"id": f_id}, timeout=25)
                js = resp.json()
                if not js.get("response"):
                    fixture_cache[f_id] = None
                    return None
                fixture_cache[f_id] = js["response"][0]
                return fixture_cache[f_id]
            except:
                fixture_cache[f_id] = None
                return None

        with requests.Session() as s:
            for i, (_, row) in enumerate(df_day.iterrows()):
                progress_bar.progress((i + 1) / max(1, total))
                f_id = str(row[col_fixture]).split(".")[0].strip()
                if not f_id or f_id == "nan":
                    continue

                data = fetch_fixture(s, f_id)
                if not data:
                    continue

                score = data.get("score", {}) or {}
                ht_res = (score.get("halftime", {}) or {})
                ht_h = ht_res.get("home", 0) if ht_res.get("home") is not None else 0
                ht_a = ht_res.get("away", 0) if ht_res.get("away") is not None else 0

                win_05_ht = (ht_h + ht_a) >= 1
                win_15_ht = (ht_h + ht_a) >= 2
                win_gg_ht = (ht_h > 0 and ht_a > 0)

                # quote dal log (supporta N/D)
                q_o05 = parse_float(row[col_o05]) if col_o05 else None
                q_o15 = parse_float(row[col_o15]) if col_o15 else None
                q_gg  = parse_float(row[col_gg])  if col_gg  else None
                q_o25 = parse_float(row[col_o25]) if col_o25 else None

                # gate sniper 1-1 HT (quote + esistenza quote)
                gate_ok = (q_o15 is not None and q_gg is not None and (gate_o15_min <= q_o15 <= gate_o15_max) and (gate_gg_min <= q_gg <= gate_gg_max))

                match_name = str(row[col_match]) if col_match else f"Fixture {f_id}"
                info_val = str(row[col_info]) if col_info else ""
                rating_val = row[col_rating] if col_rating else None
                ora_val = row[col_time] if col_time else ""

                results.append({
                    "Fixture_ID": f_id,
                    "Ora": ora_val,
                    "Match": match_name,
                    "Esito HT": f"{ht_h}-{ht_a}",
                    "Q O0.5 PT": q_o05,
                    "Q O1.5 PT": q_o15,
                    "Q GG PT": q_gg,
                    "Q O2.5": q_o25,
                    "Gate 1-1 HT": "✅" if gate_ok else "❌",
                    "O0.5 HT": "✅" if win_05_ht else "❌",
                    "O1.5 HT": "✅" if win_15_ht else "❌",
                    "GG HT": "✅" if win_gg_ht else "❌",
                    "Rating": rating_val,
                    "Info": info_val
                })

        if not results:
            st.warning("Nessun dato auditabile trovato (fixture mancanti o API senza response).")
            st.stop()

        res_df = pd.DataFrame(results)

        st.subheader("📋 Quote Sniper vs Esiti Reali (HT)")
        st.dataframe(
            res_df.style.applymap(
                lambda x: 'background-color: #1b4332; color: white' if x == "✅" else ('background-color: #431b1b; color: white' if x == "❌" else ''),
                subset=["Gate 1-1 HT", "O0.5 HT", "O1.5 HT", "GG HT"]
            ),
            use_container_width=True
        )

        # ============================
        # STATISTICHE MIRATE (coerenti con Sniper)
        # ============================
        st.markdown("---")
        st.subheader("🎯 Insights (allineati alla strategia)")

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            wr_05 = (res_df["O0.5 HT"] == "✅").mean() * 100
            st.metric("Win Rate O0.5 HT", f"{wr_05:.1f}%")

        with c2:
            wr_15 = (res_df["O1.5 HT"] == "✅").mean() * 100
            st.metric("Win Rate O1.5 HT", f"{wr_15:.1f}%")

        with c3:
            wr_gg = (res_df["GG HT"] == "✅").mean() * 100
            st.metric("Win Rate GG HT", f"{wr_gg:.1f}%")

        with c4:
            df_gate = res_df[res_df["Gate 1-1 HT"] == "✅"].copy()
            st.metric("Match in Gate", f"{len(df_gate)}/{len(res_df)}")

        # Performance del gate (questa è la metrica chiave per noi)
        st.markdown("### 🔥 Performance del Gate 1–1 HT (quote)")
        g1, g2, g3 = st.columns(3)

        if not df_gate.empty:
            with g1:
                st.metric("WR O1.5 HT (Gate)", f"{((df_gate['O1.5 HT']=='✅').mean()*100):.1f}%")
            with g2:
                st.metric("WR GG HT (Gate)", f"{((df_gate['GG HT']=='✅').mean()*100):.1f}%")
            with g3:
                # vero target "1-1 HT": entrambe segnano + 2+ gol
                target_11 = ((df_gate["O1.5 HT"]=="✅") & (df_gate["GG HT"]=="✅")).mean() * 100
                st.metric("WR Target 1–1 HT", f"{target_11:.1f}%")
        else:
            st.info("Nessun match ha soddisfatto il Gate con i range attuali.")

        # download
        st.download_button(
            "💾 SCARICA AUDIT COMPLETO",
            data=res_df.to_csv(index=False).encode('utf-8'),
            file_name=f"audit_results_{now_rome().strftime('%Y%m%d')}.csv"
        )

else:
    st.warning("Carica un file CSV per iniziare l'analisi.")

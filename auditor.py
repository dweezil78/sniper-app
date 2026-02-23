import streamlit as st
import pandas as pd
import requests
import os
from pathlib import Path
from datetime import datetime

# ============================
# CONFIG
# ============================
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = str(BASE_DIR / "auditor_full.csv")  # opzionale, se vuoi un default
st.set_page_config(page_title="ARAB AUDITOR V16.00 - DAY AFTER", layout="wide")

API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 ARAB AUDITOR V16.00 - Day After")
st.markdown("Audit risultati reali: **Tag/Flag/Quote** (da V16.00 PURE) vs **Esiti HT/FT**")

# ============================
# HELPERS
# ============================
def safe_float(x):
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s in ["", "N/D", "ND", "None", "nan", "NaN"]:
            return None
        s = s.replace(",", ".")
        return float(s)
    except:
        return None

def has_tag(info_str, token):
    return token in str(info_str or "")

def bucketize(series, bins, labels):
    vals = pd.to_numeric(series, errors="coerce")
    return pd.cut(vals, bins=bins, labels=labels, include_lowest=True)

def style_ok_fail(x):
    if x == "✅":
        return "background-color:#1b4332; color:white; font-weight:700;"
    if x == "❌":
        return "background-color:#431b1b; color:white; font-weight:700;"
    return ""

def api_fixture_result(session, fixture_id: str):
    # ritorna ht_h, ht_a, ft_h, ft_a oppure None
    url = f"https://v3.football.api-sports.io/fixtures?id={fixture_id}"
    r = session.get(url, headers=HEADERS, timeout=25)
    js = r.json()
    if not js.get("response"):
        return None
    data = js["response"][0]
    score = data.get("score", {}) or {}
    ht = score.get("halftime", {}) or {}
    ft = score.get("fulltime", {}) or {}

    ht_h = ht.get("home", 0) if ht.get("home") is not None else 0
    ht_a = ht.get("away", 0) if ht.get("away") is not None else 0
    ft_h = ft.get("home", 0) if ft.get("home") is not None else 0
    ft_a = ft.get("away", 0) if ft.get("away") is not None else 0
    return ht_h, ht_a, ft_h, ft_a

# Tag che ci aspettiamo da V16.00
KNOWN_TAGS = [
    "HT-OK", "O25-OK", "O25-VAL", "O05-OK", "GATE-11",
    "🎯 GG-PT", "GG-PT-POT", "🔥 OVER-PRO", "OVER-PRO+",
    "DRY 💧", "Drop", "⚽"
]

# ============================
# LOAD CSV
# ============================
st.sidebar.header("📂 Dati in input")
uploaded = st.sidebar.file_uploader("Carica CSV esportato da V16.00 (auditor_full_YYYYMMDD.csv)", type=["csv"])

df = None
if uploaded:
    df = pd.read_csv(uploaded, dtype={"Fixture_ID": str})
    st.success(f"✅ Caricato: {uploaded.name}")
elif os.path.exists(DEFAULT_CSV):
    df = pd.read_csv(DEFAULT_CSV, dtype={"Fixture_ID": str})
    st.info("🔄 Caricato CSV default locale (auditor_full.csv)")
else:
    st.warning("Carica un CSV per iniziare.")
    st.stop()

df.columns = df.columns.str.strip()
if "Fixture_ID" not in df.columns:
    st.error("CSV non valido: manca la colonna Fixture_ID.")
    st.stop()

# Normalize / fix types
df["Fixture_ID"] = df["Fixture_ID"].astype(str).str.split(".").str[0].str.strip()
df["Info"] = df.get("Info", "").astype(str)

# Quote numeriche (da V16.00)
df["Q_O25"] = df.get("O2.5 Finale", None).apply(safe_float)
df["Q_O05HT"] = df.get("O0.5 PT", None).apply(safe_float)
df["Q_O15HT"] = df.get("O1.5 PT", None).apply(safe_float)
df["Q_GGHT"] = df.get("GG PT", None).apply(safe_float)

# Flags (da V16.00)
if "ScoreOV" not in df.columns:
    df["ScoreOV"] = 0
if "ScoreGG" not in df.columns:
    df["ScoreGG"] = 0

df["ScoreOV"] = pd.to_numeric(df["ScoreOV"], errors="coerce").fillna(0).astype(int)
df["ScoreGG"] = pd.to_numeric(df["ScoreGG"], errors="coerce").fillna(0).astype(int)

# Tag flags
for t in KNOWN_TAGS:
    df[f"TAG__{t}"] = df["Info"].apply(lambda x: has_tag(x, t))

# ============================
# FILTERS
# ============================
st.sidebar.markdown("---")
st.sidebar.subheader("🎛️ Filtri Audit")
only_gold = st.sidebar.toggle("Solo Sweet Spot (Is_Gold=True)", value=False)
only_ball = st.sidebar.toggle("Solo ⚽ (Top5 Gate)", value=False)
only_over = st.sidebar.toggle("Solo OVER-PRO / OVER-PRO+", value=False)
only_gg = st.sidebar.toggle("Solo 🎯 GG-PT", value=False)

df_f = df.copy()
if only_gold and "Is_Gold" in df_f.columns:
    df_f = df_f[df_f["Is_Gold"] == True]
if only_ball:
    df_f = df_f[df_f["TAG__⚽"] == True]
if only_over:
    df_f = df_f[(df_f["TAG__🔥 OVER-PRO"] == True) | (df_f["TAG__OVER-PRO+"] == True)]
if only_gg:
    df_f = df_f[df_f["TAG__🎯 GG-PT"] == True]

st.markdown("#### 📌 Dataset selezionato")
st.write(f"Match nel CSV: **{len(df)}** | Match dopo filtri: **{len(df_f)}**")

# ============================
# RUN AUDIT
# ============================
st.markdown("---")
st.subheader("🧐 Avvia audit su risultati reali (API-Sports)")

cA, cB = st.columns([1, 2])
with cA:
    go = st.button("🚀 AVVIA AUDIT")
with cB:
    st.caption("Suggerimento: filtra prima (es. solo OVER-PRO) per non stressare l’API.")

if not go:
    st.stop()

if df_f.empty:
    st.warning("Nessun match dopo i filtri.")
    st.stop()

results = []
pb = st.progress(0)
total = len(df_f)

with requests.Session() as s:
    for i, row in enumerate(df_f.itertuples(index=False)):
        pb.progress((i + 1) / total)
        fid = str(getattr(row, "Fixture_ID", "")).strip()
        if not fid:
            continue

        try:
            r = api_fixture_result(s, fid)
            if not r:
                continue
            ht_h, ht_a, ft_h, ft_a = r

            win_o05_ht = (ht_h + ht_a) >= 1
            win_o15_ht = (ht_h + ht_a) >= 2
            win_gg_ht = (ht_h > 0 and ht_a > 0)
            win_o25_ft = (ft_h + ft_a) >= 3

            info = getattr(row, "Info", "")
            results.append({
                "Fixture_ID": fid,
                "Ora": getattr(row, "Ora", ""),
                "Lega": getattr(row, "Lega", ""),
                "Match": getattr(row, "Match", ""),
                "Esito HT": f"{ht_h}-{ht_a}",
                "Esito FT": f"{ft_h}-{ft_a}",

                "Q O2.5 FT": getattr(row, "Q_O25", None),
                "Q O0.5 HT": getattr(row, "Q_O05HT", None),
                "Q O1.5 HT": getattr(row, "Q_O15HT", None),
                "Q GG HT": getattr(row, "Q_GGHT", None),

                "O0.5 HT": "✅" if win_o05_ht else "❌",
                "O1.5 HT": "✅" if win_o15_ht else "❌",
                "GG HT": "✅" if win_gg_ht else "❌",
                "O2.5 FT": "✅" if win_o25_ft else "❌",

                "ScoreOV": int(getattr(row, "ScoreOV", 0)),
                "ScoreGG": int(getattr(row, "ScoreGG", 0)),
                "Info": info
            })
        except:
            continue

if not results:
    st.error("Nessun risultato recuperato (possibile limite API o fixture non validi).")
    st.stop()

res_df = pd.DataFrame(results)

# ============================
# TABLE
# ============================
st.markdown("---")
st.subheader("📋 Quote/Tag vs Risultati (HT + FT)")

view_cols = [
    "Ora", "Lega", "Match",
    "Esito HT", "Esito FT",
    "Q O2.5 FT", "Q O0.5 HT", "Q O1.5 HT", "Q GG HT",
    "O0.5 HT", "O1.5 HT", "GG HT", "O2.5 FT",
    "ScoreOV", "ScoreGG", "Info"
]
for c in view_cols:
    if c not in res_df.columns:
        res_df[c] = None

st.dataframe(
    res_df[view_cols].style.applymap(
        style_ok_fail,
        subset=["O0.5 HT", "O1.5 HT", "GG HT", "O2.5 FT"]
    ),
    use_container_width=True
)

# ============================
# GLOBAL METRICS
# ============================
st.markdown("---")
st.subheader("🎯 Win Rate globali (dataset filtrato)")

def wr(col):
    return (res_df[col] == "✅").mean() * 100 if len(res_df) else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("WR O0.5 HT", f"{wr('O0.5 HT'):.1f}%")
m2.metric("WR O1.5 HT", f"{wr('O1.5 HT'):.1f}%")
m3.metric("WR GG HT", f"{wr('GG HT'):.1f}%")
m4.metric("WR O2.5 FT", f"{wr('O2.5 FT'):.1f}%")

# ============================
# TAG IMPACT (O2.5 FT)
# ============================
st.markdown("---")
st.subheader("🧩 Impatto tag su O2.5 FT (WR per tag)")

tag_rows = []
for t in KNOWN_TAGS:
    mask = res_df["Info"].apply(lambda x: has_tag(x, t))
    n = int(mask.sum())
    if n < 3:
        continue
    tag_rows.append({
        "Tag": t,
        "Match (n)": n,
        "WR O2.5 FT": (res_df.loc[mask, "O2.5 FT"] == "✅").mean() * 100,
        "WR O1.5 HT": (res_df.loc[mask, "O1.5 HT"] == "✅").mean() * 100,
        "WR GG HT": (res_df.loc[mask, "GG HT"] == "✅").mean() * 100,
    })

tag_df = pd.DataFrame(tag_rows).sort_values(["WR O2.5 FT", "Match (n)"], ascending=[False, False])
if tag_df.empty:
    st.info("Non ci sono abbastanza match (n>=3) per calcolare WR per tag con i filtri attuali.")
else:
    st.dataframe(tag_df, use_container_width=True)

# ============================
# SCORE FLAGS IMPACT
# ============================
st.markdown("---")
st.subheader("📌 Impatto flag ScoreOV / ScoreGG su O2.5 FT")

c1, c2 = st.columns(2)
with c1:
    g = res_df.groupby("ScoreOV").agg(
        n=("O2.5 FT", "size"),
        wr_o25=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
    ).reset_index().sort_values("ScoreOV", ascending=False)
    g = g[g["n"] >= 2]
    st.markdown("**WR O2.5 FT per ScoreOV** (min 2 match)")
    st.dataframe(g, use_container_width=True)

with c2:
    g2 = res_df.groupby("ScoreGG").agg(
        n=("O2.5 FT", "size"),
        wr_o25=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
    ).reset_index().sort_values("ScoreGG", ascending=False)
    g2 = g2[g2["n"] >= 2]
    st.markdown("**WR O2.5 FT per ScoreGG** (min 2 match)")
    st.dataframe(g2, use_container_width=True)

# ============================
# QUOTE BUCKETS
# ============================
st.markdown("---")
st.subheader("💰 Bucket quote: dove migliora l’O2.5 FT?")

tmp = res_df.copy()
tmp["Q O2.5 FT"] = pd.to_numeric(tmp["Q O2.5 FT"], errors="coerce")
tmp["Q O0.5 HT"] = pd.to_numeric(tmp["Q O0.5 HT"], errors="coerce")
tmp["Q O1.5 HT"] = pd.to_numeric(tmp["Q O1.5 HT"], errors="coerce")
tmp["Q GG HT"] = pd.to_numeric(tmp["Q GG HT"], errors="coerce")

bins_o25 = [0, 1.60, 1.70, 1.80, 1.95, 2.00, 2.10, 2.25, 99]
labels_o25 = ["<1.60", "1.60-1.70", "1.70-1.80", "1.80-1.95", "1.95-2.00", "2.00-2.10", "2.10-2.25", ">2.25"]
tmp["BUCKET_O25"] = bucketize(tmp["Q O2.5 FT"], bins_o25, labels_o25)

bins_o05 = [0, 1.25, 1.30, 1.40, 1.55, 1.70, 99]
labels_o05 = ["<1.25", "1.25-1.30", "1.30-1.40", "1.40-1.55", "1.55-1.70", ">1.70"]
tmp["BUCKET_O05"] = bucketize(tmp["Q O0.5 HT"], bins_o05, labels_o05)

b1 = tmp.groupby("BUCKET_O25").agg(
    n=("O2.5 FT", "size"),
    wr=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
).reset_index().dropna().sort_values("wr", ascending=False)

st.markdown("**WR O2.5 FT per bucket quota O2.5** (min 3 match)")
st.dataframe(b1[b1["n"] >= 3], use_container_width=True)

b2 = tmp.groupby("BUCKET_O05").agg(
    n=("O2.5 FT", "size"),
    wr=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
).reset_index().dropna().sort_values("wr", ascending=False)

st.markdown("**WR O2.5 FT per bucket quota O0.5 HT** (min 3 match)")
st.dataframe(b2[b2["n"] >= 3], use_container_width=True)

# ============================
# SWEET SPOT CHECK (la tua regola)
# ============================
st.markdown("---")
st.subheader("⭐ Verifica regola Sweet Spot O2.5 (1.70–2.00 + O0.5HT 1.30–1.55 + HT-OK)")

sweet_mask = (
    (tmp["Q O2.5 FT"].between(1.70, 2.00, inclusive="both")) &
    (tmp["Q O0.5 HT"].between(1.30, 1.55, inclusive="both")) &
    (tmp["Info"].apply(lambda x: has_tag(x, "HT-OK")))
)

n_sweet = int(sweet_mask.sum())
if n_sweet == 0:
    st.info("Nessun match nel dataset filtrato che rispetta la regola Sweet Spot.")
else:
    wr_sweet = (tmp.loc[sweet_mask, "O2.5 FT"] == "✅").mean() * 100
    st.write(f"Match sweet spot: **{n_sweet}** | WR O2.5 FT: **{wr_sweet:.1f}%**")
    st.dataframe(tmp.loc[sweet_mask, ["Match", "Q O2.5 FT", "Q O0.5 HT", "Info", "O2.5 FT"]], use_container_width=True)

# ============================
# DOWNLOAD
# ============================
st.markdown("---")
out_name = f"audit_v1600_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
st.download_button(
    "💾 SCARICA AUDIT COMPLETO (CSV)",
    data=res_df.to_csv(index=False).encode("utf-8"),
    file_name=out_name
)

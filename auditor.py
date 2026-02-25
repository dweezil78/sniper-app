import streamlit as st
import pandas as pd
import requests
import os
import time
from pathlib import Path
from datetime import datetime

# ============================
# CONFIG
# ============================
BASE_DIR = Path(__file__).resolve().parent
st.set_page_config(page_title="ARAB AUDITOR V17.00 - DAY AFTER", layout="wide")

API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 ARAB AUDITOR - Day After")
st.caption("Carichi il CSV esportato dall'app principale → recupero risultati HT/FT via API-Sports → statistiche su tag, quote, rating.")

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

def style_ok_fail(x):
    if x == "✅":
        return "background-color:#1b4332; color:white; font-weight:700;"
    if x == "❌":
        return "background-color:#431b1b; color:white; font-weight:700;"
    return ""

def api_get(session, url, retries=2):
    for i in range(retries + 1):
        r = session.get(url, headers=HEADERS, timeout=25)
        if r.status_code == 429 and i < retries:
            time.sleep(1.5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    return None

@st.cache_data(show_spinner=False, ttl=60 * 60)
def fetch_fixture_result_cached(fixture_id: str):
    # Cache 1h per evitare di bruciare chiamate quando ricarichi la pagina
    with requests.Session() as s:
        js = api_get(s, f"https://v3.football.api-sports.io/fixtures?id={fixture_id}", retries=2)
    if not js or not js.get("response"):
        return None
    data = js["response"][0]
    score = data.get("score", {}) or {}
    ht = (score.get("halftime", {}) or {})
    ft = (score.get("fulltime", {}) or {})

    ht_h = ht.get("home", 0) if ht.get("home") is not None else 0
    ht_a = ht.get("away", 0) if ht.get("away") is not None else 0
    ft_h = ft.get("home", 0) if ft.get("home") is not None else 0
    ft_a = ft.get("away", 0) if ft.get("away") is not None else 0
    return ht_h, ht_a, ft_h, ft_a

def pick_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def bucketize(series, bins, labels):
    vals = pd.to_numeric(series, errors="coerce")
    return pd.cut(vals, bins=bins, labels=labels, include_lowest=True)

# Tag che riconosciamo (allinea ai tuoi det in V17.x)
KNOWN_TAGS = [
    "HT-OK", "O25-OK", "GATE-11", "Drop",
    "🎯 GG-PT", "💣 O25-BOOST", "🔥 OVER-PRO"
]

# ============================
# LOAD CSV
# ============================
st.sidebar.header("📂 Input")
uploaded = st.sidebar.file_uploader("Carica CSV completo (auditor_full.csv)", type=["csv"])

if not uploaded:
    st.warning("Carica un CSV per iniziare.")
    st.stop()

df = pd.read_csv(uploaded, dtype={"Fixture_ID": str})
df.columns = df.columns.str.strip()

if "Fixture_ID" not in df.columns:
    st.error("CSV non valido: manca la colonna Fixture_ID (serve per interrogare i risultati).")
    st.stop()

# normalize
df["Fixture_ID"] = df["Fixture_ID"].astype(str).str.split(".").str[0].str.strip()
df["Info"] = df.get("Info", "").astype(str)

# prova a leggere quote da nomi diversi (così non rompi se cambi intestazioni)
col_o25 = pick_col(df, ["O2.5", "O2.5 FT", "Q O2.5 FT", "O2.5 Finale", "O2.5_FT"])
col_o05 = pick_col(df, ["O0.5HT", "O0.5 HT", "Q O0.5 HT", "O0.5 PT", "O05HT"])
col_o15 = pick_col(df, ["O1.5HT", "O1.5 HT", "Q O1.5 HT", "O1.5 PT", "O15HT"])
col_gght = pick_col(df, ["GGPT", "GG HT", "Q GG HT", "GG PT", "GGHT_Raw", "GGHT"])

df["Q_O25"] = df[col_o25].apply(safe_float) if col_o25 else None
df["Q_O05HT"] = df[col_o05].apply(safe_float) if col_o05 else None
df["Q_O15HT"] = df[col_o15].apply(safe_float) if col_o15 else None
df["Q_GGHT"] = df[col_gght].apply(safe_float) if col_gght else None

# rating
if "Rating" in df.columns:
    df["Rating"] = pd.to_numeric(df["Rating"], errors="coerce")
else:
    df["Rating"] = None

# tag flags
for t in KNOWN_TAGS:
    df[f"TAG__{t}"] = df["Info"].apply(lambda x: has_tag(x, t))

st.sidebar.markdown("---")
st.sidebar.subheader("🎛️ Filtri audit")
only_gold = st.sidebar.toggle("Solo Gold ✅", value=False)
only_overboost = st.sidebar.toggle("Solo 💣 O25-BOOST", value=False)
only_overpro = st.sidebar.toggle("Solo 🔥 OVER-PRO", value=False)
only_ggpt = st.sidebar.toggle("Solo 🎯 GG-PT", value=False)

df_f = df.copy()
if only_gold and "Gold" in df_f.columns:
    df_f = df_f[df_f["Gold"].astype(str).str.contains("✅", na=False)]
if only_overboost:
    df_f = df_f[df_f["TAG__💣 O25-BOOST"] == True]
if only_overpro:
    df_f = df_f[df_f["TAG__🔥 OVER-PRO"] == True]
if only_ggpt:
    df_f = df_f[df_f["TAG__🎯 GG-PT"] == True]

st.markdown("### 📌 Dataset")
st.write(f"Match nel CSV: **{len(df)}**  |  Dopo filtri: **{len(df_f)}**")

# ============================
# RUN AUDIT
# ============================
st.markdown("---")
st.subheader("🧾 Audit risultati reali (HT/FT)")

c1, c2 = st.columns([1, 2])
with c1:
    go = st.button("🚀 AVVIA AUDIT")
with c2:
    st.caption("Consiglio: se hai tanti match, filtra prima per non stressare l’API.")

if not go:
    st.stop()

if df_f.empty:
    st.warning("Nessun match dopo i filtri.")
    st.stop()

rows = []
pb = st.progress(0.0)
total = len(df_f)

for i, r in enumerate(df_f.itertuples(index=False)):
    pb.progress((i + 1) / total)
    fid = str(getattr(r, "Fixture_ID", "")).strip()
    if not fid:
        continue

    res = fetch_fixture_result_cached(fid)
    if not res:
        continue

    ht_h, ht_a, ft_h, ft_a = res

    win_o05_ht = (ht_h + ht_a) >= 1
    win_o15_ht = (ht_h + ht_a) >= 2
    win_gg_ht = (ht_h > 0 and ht_a > 0)
    win_o25_ft = (ft_h + ft_a) >= 3

    info = getattr(r, "Info", "")
    rows.append({
        "Fixture_ID": fid,
        "Data": getattr(r, "Data", ""),
        "Ora": getattr(r, "Ora", ""),
        "Lega": getattr(r, "Lega", ""),
        "Match": getattr(r, "Match", ""),
        "Rating": getattr(r, "Rating", None),
        "Gold": getattr(r, "Gold", ""),

        "Esito HT": f"{ht_h}-{ht_a}",
        "Esito FT": f"{ft_h}-{ft_a}",

        "Q O2.5": getattr(r, "Q_O25", None),
        "Q O0.5HT": getattr(r, "Q_O05HT", None),
        "Q O1.5HT": getattr(r, "Q_O15HT", None),
        "Q GGHT": getattr(r, "Q_GGHT", None),

        "O0.5 HT": "✅" if win_o05_ht else "❌",
        "O1.5 HT": "✅" if win_o15_ht else "❌",
        "GG HT": "✅" if win_gg_ht else "❌",
        "O2.5 FT": "✅" if win_o25_ft else "❌",

        "Info": info
    })

if not rows:
    st.error("Nessun risultato recuperato (fixture non chiuse, id errati o limite API).")
    st.stop()

res_df = pd.DataFrame(rows)

# ============================
# TABLE
# ============================
st.markdown("---")
st.subheader("📋 Quote/Tag vs Risultati")

view_cols = [
    "Data", "Ora", "Lega", "Match", "Rating", "Gold",
    "Esito HT", "Esito FT",
    "Q O2.5", "Q O0.5HT", "Q O1.5HT", "Q GGHT",
    "O0.5 HT", "O1.5 HT", "GG HT", "O2.5 FT",
    "Info"
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
st.subheader("🎯 Win rate globali (dataset filtrato)")

def wr(col):
    return (res_df[col] == "✅").mean() * 100 if len(res_df) else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("WR O0.5 HT", f"{wr('O0.5 HT'):.1f}%")
m2.metric("WR O1.5 HT", f"{wr('O1.5 HT'):.1f}%")
m3.metric("WR GG HT", f"{wr('GG HT'):.1f}%")
m4.metric("WR O2.5 FT", f"{wr('O2.5 FT'):.1f}%")

# ============================
# TAG IMPACT
# ============================
st.markdown("---")
st.subheader("🧩 Impatto tag (WR su O2.5 FT)")

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
    st.info("Non ci sono abbastanza match (n>=3) per stimare WR per tag.")
else:
    st.dataframe(tag_df, use_container_width=True)

# ============================
# RATING BUCKETS
# ============================
st.markdown("---")
st.subheader("📈 Rating: dove rende di più l’O2.5 FT?")

tmp = res_df.copy()
tmp["Rating"] = pd.to_numeric(tmp["Rating"], errors="coerce")
tmp = tmp.dropna(subset=["Rating"])

if tmp.empty:
    st.info("Nel CSV non c'è Rating numerico (o è vuoto).")
else:
    bins_r = [0, 55, 65, 75, 85, 100]
    labels_r = ["<55", "55-65", "65-75", "75-85", "85-100"]
    tmp["BUCKET_R"] = bucketize(tmp["Rating"], bins_r, labels_r)

    g = tmp.groupby("BUCKET_R").agg(
        n=("O2.5 FT", "size"),
        wr=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
    ).reset_index().dropna().sort_values("wr", ascending=False)

    st.dataframe(g[g["n"] >= 3], use_container_width=True)

# ============================
# QUOTE BUCKETS
# ============================
st.markdown("---")
st.subheader("💰 Bucket quote: dove migliora l’O2.5 FT?")

tmp2 = res_df.copy()
for c in ["Q O2.5", "Q O0.5HT", "Q O1.5HT", "Q GGHT"]:
    tmp2[c] = pd.to_numeric(tmp2[c], errors="coerce")

bins_o25 = [0, 1.60, 1.70, 1.80, 1.95, 2.00, 2.10, 2.25, 99]
labels_o25 = ["<1.60", "1.60-1.70", "1.70-1.80", "1.80-1.95", "1.95-2.00", "2.00-2.10", "2.10-2.25", ">2.25"]
tmp2["BUCKET_O25"] = bucketize(tmp2["Q O2.5"], bins_o25, labels_o25)

b1 = tmp2.groupby("BUCKET_O25").agg(
    n=("O2.5 FT", "size"),
    wr=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
).reset_index().dropna().sort_values("wr", ascending=False)

st.markdown("**WR O2.5 FT per bucket quota O2.5** (min 3 match)")
st.dataframe(b1[b1["n"] >= 3], use_container_width=True)

bins_o05 = [0, 1.25, 1.30, 1.40, 1.55, 1.70, 99]
labels_o05 = ["<1.25", "1.25-1.30", "1.30-1.40", "1.40-1.55", "1.55-1.70", ">1.70"]
tmp2["BUCKET_O05"] = bucketize(tmp2["Q O0.5HT"], bins_o05, labels_o05)

b2 = tmp2.groupby("BUCKET_O05").agg(
    n=("O2.5 FT", "size"),
    wr=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
).reset_index().dropna().sort_values("wr", ascending=False)

st.markdown("**WR O2.5 FT per bucket quota O0.5HT** (min 3 match)")
st.dataframe(b2[b2["n"] >= 3], use_container_width=True)

# ============================
# SWEET SPOT CHECK (tua regola)
# ============================
st.markdown("---")
st.subheader("⭐ Check regola Sweet Spot (O2.5 1.70–2.00 + O0.5HT 1.30–1.55 + HT-OK)")

sweet_mask = (
    (tmp2["Q O2.5"].between(1.70, 2.00, inclusive="both")) &
    (tmp2["Q O0.5HT"].between(1.30, 1.55, inclusive="both")) &
    (tmp2["Info"].apply(lambda x: has_tag(x, "HT-OK")))
)

n_sweet = int(sweet_mask.sum())
if n_sweet == 0:
    st.info("Nessun match nel dataset filtrato rispetta la regola Sweet Spot.")
else:
    wr_sweet = (tmp2.loc[sweet_mask, "O2.5 FT"] == "✅").mean() * 100
    st.write(f"Match sweet spot: **{n_sweet}** | WR O2.5 FT: **{wr_sweet:.1f}%**")
    st.dataframe(tmp2.loc[sweet_mask, ["Match", "Q O2.5", "Q O0.5HT", "Info", "O2.5 FT"]], use_container_width=True)

# ============================
# DOWNLOAD
# ============================
st.markdown("---")
out_name = f"arab_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
st.download_button(
    "💾 SCARICA AUDIT COMPLETO (CSV)",
    data=res_df.to_csv(index=False).encode("utf-8"),
    file_name=out_name
)

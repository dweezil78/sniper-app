import streamlit as st
import pandas as pd
import requests
import os
import time
from pathlib import Path
from datetime import datetime

# ============================
# ARAB AUDITOR - STANDALONE APP
# ============================

BASE_DIR = Path(__file__).resolve().parent
st.set_page_config(page_title="ARAB AUDITOR - DAY AFTER", layout="wide")

API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

st.title("📊 ARAB AUDITOR - Day After (Standalone)")
st.markdown("Carica il **CSV** esportato da Arab Sniper e ottieni statistiche su **HT/FT reali** + impatto **Tag/Rating/Gold/Quote**.")

# ----------------------------
# Helpers
# ----------------------------
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

def has_tag(info_str: str, token: str) -> bool:
    return token in str(info_str or "")

def parse_signals(info_str: str):
    # info tipo: [HT-OK|O25-OK|Drop|💣 O25-BOOST|🔥 OVER-PRO]
    if not isinstance(info_str, str):
        return []
    s = info_str.strip().strip("[]").strip()
    if not s:
        return []
    return [x.strip() for x in s.split("|") if x.strip()]

def bucketize(series, bins, labels):
    vals = pd.to_numeric(series, errors="coerce")
    return pd.cut(vals, bins=bins, labels=labels, include_lowest=True)

def style_ok_fail(x):
    if x == "✅":
        return "background-color:#1b4332; color:white; font-weight:700;"
    if x == "❌":
        return "background-color:#431b1b; color:white; font-weight:700;"
    return ""

def api_fixture_result(session: requests.Session, fixture_id: str, retries=2):
    """
    Ritorna dict con:
      status_short, ht_home, ht_away, ft_home, ft_away
    oppure None
    """
    url = "https://v3.football.api-sports.io/fixtures"
    params = {"id": fixture_id, "timezone": "Europe/Rome"}

    for i in range(retries + 1):
        try:
            r = session.get(url, headers=HEADERS, params=params, timeout=25)

            # Basic anti-429
            if r.status_code == 429 and i < retries:
                time.sleep(1.5 * (i + 1))
                continue

            r.raise_for_status()
            js = r.json()
            resp = js.get("response", [])
            if not resp:
                return None

            data = resp[0]
            status_short = (data.get("fixture", {}).get("status", {}) or {}).get("short", "")

            score = data.get("score", {}) or {}
            ht = score.get("halftime", {}) or {}
            ft = score.get("fulltime", {}) or {}

            ht_h = ht.get("home", 0) if ht.get("home") is not None else 0
            ht_a = ht.get("away", 0) if ht.get("away") is not None else 0
            ft_h = ft.get("home", 0) if ft.get("home") is not None else 0
            ft_a = ft.get("away", 0) if ft.get("away") is not None else 0

            return {
                "Status": status_short,
                "HT_H": int(ht_h), "HT_A": int(ht_a),
                "FT_H": int(ft_h), "FT_A": int(ft_a),
            }

        except Exception:
            if i == retries:
                return None
            time.sleep(1)

# Tag che ti interessano davvero (aderenti al tuo Info attuale)
DEFAULT_TAGS = [
    "HT-OK",
    "O25-OK",
    "GATE-11",
    "Drop",
    "🎯 GG-PT",
    "💣 O25-BOOST",
    "🔥 OVER-PRO",
]

# ----------------------------
# Sidebar: Load CSV
# ----------------------------
st.sidebar.header("📂 Input")
uploaded = st.sidebar.file_uploader("Carica CSV esportato (auditor_full.csv)", type=["csv"])

if not uploaded:
    st.info("Carica un CSV per iniziare.")
    st.stop()

df_raw = pd.read_csv(uploaded, dtype={"Fixture_ID": str})
st.success(f"✅ Caricato: {uploaded.name}")

df_raw.columns = df_raw.columns.str.strip()

if "Fixture_ID" not in df_raw.columns:
    st.error("CSV non valido: manca la colonna Fixture_ID.")
    st.stop()

# Normalize
df_raw["Fixture_ID"] = df_raw["Fixture_ID"].astype(str).str.split(".").str[0].str.strip()
df_raw["Info"] = df_raw.get("Info", "").astype(str)
df_raw["Gold"] = df_raw.get("Gold", "").astype(str)  # ✅ / ❌ (se presente)
df_raw["Rating"] = pd.to_numeric(df_raw.get("Rating", None), errors="coerce")

# Quote mapping (V17.40: O2.5, O0.5HT, O1.5HT, GGPT)
df_raw["Q_O25"] = df_raw.get("O2.5", None).apply(safe_float) if "O2.5" in df_raw.columns else None
df_raw["Q_O05HT"] = df_raw.get("O0.5HT", None).apply(safe_float) if "O0.5HT" in df_raw.columns else None
df_raw["Q_O15HT"] = df_raw.get("O1.5HT", None).apply(safe_float) if "O1.5HT" in df_raw.columns else None
df_raw["Q_GGHT"] = df_raw.get("GGPT", None).apply(safe_float) if "GGPT" in df_raw.columns else None

# ----------------------------
# Sidebar: Filters
# ----------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("🎛️ Filtri Audit")

only_gold = st.sidebar.toggle("Solo Gold ✅", value=False)
min_rating = st.sidebar.slider("Rating minimo (se presente)", 0, 100, 0)
tag_filter = st.sidebar.multiselect("Mostra solo match con questi tag (Info):", DEFAULT_TAGS, default=[])

df = df_raw.copy()

if only_gold and "Gold" in df.columns:
    df = df[df["Gold"].astype(str).str.contains("✅", na=False)]

if "Rating" in df.columns and min_rating > 0:
    df = df[df["Rating"].fillna(0) >= min_rating]

if tag_filter:
    for t in tag_filter:
        df = df[df["Info"].apply(lambda x: has_tag(x, t))]

st.markdown("### 📌 Dataset selezionato")
st.write(f"Match nel CSV: **{len(df_raw)}** | Match dopo filtri: **{len(df)}**")

# ----------------------------
# Run Audit
# ----------------------------
st.markdown("---")
st.subheader("🚀 Audit su risultati reali (API-Sports)")

cA, cB, cC = st.columns([1, 1, 2])
with cA:
    go = st.button("AVVIA AUDIT")
with cB:
    only_finished = st.toggle("Considera solo match finiti (FT/AET/PEN)", value=True)
with cC:
    st.caption("Suggerimento: filtra prima (es. solo 💣 O25-BOOST) per ridurre chiamate API.")

if not go:
    st.stop()

if df.empty:
    st.warning("Nessun match dopo i filtri.")
    st.stop()

pb = st.progress(0)
total = len(df)

results = []
errors = 0

with requests.Session() as s:
    for i, row in enumerate(df.itertuples(index=False)):
        pb.progress((i + 1) / max(1, total))
        fid = str(getattr(row, "Fixture_ID", "")).strip()
        if not fid:
            continue

        fx = api_fixture_result(s, fid)
        if not fx:
            errors += 1
            continue

        status = fx["Status"]
        if only_finished and status not in ["FT", "AET", "PEN"]:
            # match non finito: salta
            continue

        ht_h, ht_a = fx["HT_H"], fx["HT_A"]
        ft_h, ft_a = fx["FT_H"], fx["FT_A"]

        win_o05_ht = (ht_h + ht_a) >= 1
        win_o15_ht = (ht_h + ht_a) >= 2
        win_gg_ht = (ht_h > 0 and ht_a > 0)
        win_o25_ft = (ft_h + ft_a) >= 3

        info = getattr(row, "Info", "")
        results.append({
            "Fixture_ID": fid,
            "Data": getattr(row, "Data", ""),
            "Ora": getattr(row, "Ora", ""),
            "Lega": getattr(row, "Lega", ""),
            "Match": getattr(row, "Match", ""),

            "Status": status,
            "Esito HT": f"{ht_h}-{ht_a}",
            "Esito FT": f"{ft_h}-{ft_a}",

            "Q O2.5": safe_float(getattr(row, "Q_O25", None)),
            "Q O0.5HT": safe_float(getattr(row, "Q_O05HT", None)),
            "Q O1.5HT": safe_float(getattr(row, "Q_O15HT", None)),
            "Q GGHT": safe_float(getattr(row, "Q_GGHT", None)),

            "O0.5 HT": "✅" if win_o05_ht else "❌",
            "O1.5 HT": "✅" if win_o15_ht else "❌",
            "GG HT": "✅" if win_gg_ht else "❌",
            "O2.5 FT": "✅" if win_o25_ft else "❌",

            "Rating": getattr(row, "Rating", None),
            "Gold": getattr(row, "Gold", ""),
            "Info": info,
        })

if not results:
    st.error("Nessun risultato recuperato (fixture non finiti o problemi API).")
    st.stop()

res_df = pd.DataFrame(results)

st.caption(f"Audit completato. Fixture analizzati: {len(res_df)} | errori/skip API: {errors}")

# ----------------------------
# Table
# ----------------------------
st.markdown("---")
st.subheader("📋 Quote/Info vs Risultati (HT + FT)")

view_cols = [
    "Data", "Ora", "Lega", "Match",
    "Status", "Esito HT", "Esito FT",
    "Q O2.5", "Q O0.5HT", "Q O1.5HT", "Q GGHT",
    "O0.5 HT", "O1.5 HT", "GG HT", "O2.5 FT",
    "Rating", "Gold", "Info"
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

# ----------------------------
# Global Metrics
# ----------------------------
st.markdown("---")
st.subheader("🎯 Win Rate globali (dataset filtrato)")

def wr(col):
    return (res_df[col] == "✅").mean() * 100 if len(res_df) else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("WR O0.5 HT", f"{wr('O0.5 HT'):.1f}%")
m2.metric("WR O1.5 HT", f"{wr('O1.5 HT'):.1f}%")
m3.metric("WR GG HT", f"{wr('GG HT'):.1f}%")
m4.metric("WR O2.5 FT", f"{wr('O2.5 FT'):.1f}%")

# ----------------------------
# Tag Impact
# ----------------------------
st.markdown("---")
st.subheader("🧩 Impatto tag (WR per tag)")

tags_custom = st.multiselect(
    "Tag da analizzare (presenti in Info):",
    options=sorted(set(DEFAULT_TAGS + ["HT-OK", "O25-OK", "GATE-11", "Drop", "🎯 GG-PT", "💣 O25-BOOST", "🔥 OVER-PRO"])),
    default=DEFAULT_TAGS
)

tag_rows = []
for t in tags_custom:
    mask = res_df["Info"].apply(lambda x: has_tag(x, t))
    n = int(mask.sum())
    if n < 3:
        continue
    tag_rows.append({
        "Tag": t,
        "Match (n)": n,
        "WR O2.5 FT": (res_df.loc[mask, "O2.5 FT"] == "✅").mean() * 100,
        "WR O1.5 HT": (res_df.loc[mask, "O1.5 HT"] == "✅").mean() * 100,
        "WR O0.5 HT": (res_df.loc[mask, "O0.5 HT"] == "✅").mean() * 100,
        "WR GG HT": (res_df.loc[mask, "GG HT"] == "✅").mean() * 100,
    })

tag_df = pd.DataFrame(tag_rows).sort_values(["WR O2.5 FT", "Match (n)"], ascending=[False, False])

if tag_df.empty:
    st.info("Non ci sono abbastanza match (n>=3) per calcolare WR per tag con questi filtri.")
else:
    st.dataframe(tag_df, use_container_width=True)

# ----------------------------
# Rating Bands
# ----------------------------
st.markdown("---")
st.subheader("📈 Performance per fascia Rating")

if res_df["Rating"].notna().sum() == 0:
    st.info("Nel CSV non c’è Rating (o non è numerico).")
else:
    tmp = res_df.copy()
    tmp["Rating"] = pd.to_numeric(tmp["Rating"], errors="coerce")
    bins = [0, 60, 70, 80, 90, 101]
    labels = ["<60", "60-69", "70-79", "80-89", "90+"]
    tmp["RatingBand"] = pd.cut(tmp["Rating"], bins=bins, labels=labels, right=False)

    band = tmp.groupby("RatingBand").agg(
        n=("Fixture_ID", "count"),
        wr_o25=("O2.5 FT", lambda x: (x == "✅").mean() * 100),
        wr_ht05=("O0.5 HT", lambda x: (x == "✅").mean() * 100),
        wr_ht15=("O1.5 HT", lambda x: (x == "✅").mean() * 100),
    ).reset_index()

    band = band[band["n"] >= 3]
    st.dataframe(band, use_container_width=True)

# ----------------------------
# Gold vs Non-Gold
# ----------------------------
st.markdown("---")
st.subheader("⭐ Gold vs Non-Gold")

if "Gold" not in res_df.columns or res_df["Gold"].astype(str).str.len().sum() == 0:
    st.info("Colonna Gold non presente (o vuota).")
else:
    g = res_df.groupby("Gold").agg(
        n=("Fixture_ID", "count"),
        wr_o25=("O2.5 FT", lambda x: (x == "✅").mean() * 100),
        wr_ht05=("O0.5 HT", lambda x: (x == "✅").mean() * 100),
        wr_ht15=("O1.5 HT", lambda x: (x == "✅").mean() * 100),
    ).reset_index().sort_values("n", ascending=False)
    st.dataframe(g, use_container_width=True)

# ----------------------------
# Quote Buckets
# ----------------------------
st.markdown("---")
st.subheader("💰 Bucket quote: dove migliora l’O2.5 FT?")

tmp = res_df.copy()
for c in ["Q O2.5", "Q O0.5HT", "Q O1.5HT", "Q GGHT"]:
    tmp[c] = pd.to_numeric(tmp[c], errors="coerce")

if tmp["Q O2.5"].notna().sum() == 0:
    st.info("Quote O2.5 non presenti/parseabili nel CSV.")
else:
    bins_o25 = [0, 1.60, 1.70, 1.80, 1.95, 2.00, 2.10, 2.25, 99]
    labels_o25 = ["<1.60", "1.60-1.70", "1.70-1.80", "1.80-1.95", "1.95-2.00", "2.00-2.10", "2.10-2.25", ">2.25"]
    tmp["BUCKET_O25"] = bucketize(tmp["Q O2.5"], bins_o25, labels_o25)

    b1 = tmp.groupby("BUCKET_O25").agg(
        n=("O2.5 FT", "size"),
        wr=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
    ).reset_index().dropna().sort_values("wr", ascending=False)

    st.markdown("**WR O2.5 FT per bucket quota O2.5** (min 3 match)")
    st.dataframe(b1[b1["n"] >= 3], use_container_width=True)

if tmp["Q O0.5HT"].notna().sum() > 0:
    bins_o05 = [0, 1.20, 1.25, 1.30, 1.40, 1.55, 1.70, 99]
    labels_o05 = ["<1.20", "1.20-1.25", "1.25-1.30", "1.30-1.40", "1.40-1.55", "1.55-1.70", ">1.70"]
    tmp["BUCKET_O05"] = bucketize(tmp["Q O0.5HT"], bins_o05, labels_o05)

    b2 = tmp.groupby("BUCKET_O05").agg(
        n=("O2.5 FT", "size"),
        wr=("O2.5 FT", lambda x: (x == "✅").mean() * 100)
    ).reset_index().dropna().sort_values("wr", ascending=False)

    st.markdown("**WR O2.5 FT per bucket quota O0.5HT** (min 3 match)")
    st.dataframe(b2[b2["n"] >= 3], use_container_width=True)

# ----------------------------
# Sweet Spot Check (tua regola)
# ----------------------------
st.markdown("---")
st.subheader("✅ Verifica regola Sweet Spot O2.5 (tua)")

# regola: O2.5 1.70–2.00 + O0.5HT 1.30–1.55 + HT-OK (tag)
if tmp["Q O2.5"].notna().sum() == 0 or tmp["Q O0.5HT"].notna().sum() == 0:
    st.info("Impossibile valutare Sweet Spot: mancano quote O2.5 e/o O0.5HT.")
else:
    sweet_mask = (
        (tmp["Q O2.5"].between(1.70, 2.00, inclusive="both")) &
        (tmp["Q O0.5HT"].between(1.30, 1.55, inclusive="both")) &
        (tmp["Info"].apply(lambda x: has_tag(x, "HT-OK")))
    )

    n_sweet = int(sweet_mask.sum())
    if n_sweet == 0:
        st.info("Nessun match che rispetta la regola Sweet Spot nel dataset filtrato.")
    else:
        wr_sweet = (tmp.loc[sweet_mask, "O2.5 FT"] == "✅").mean() * 100
        st.write(f"Match sweet spot: **{n_sweet}** | WR O2.5 FT: **{wr_sweet:.1f}%**")

        cols = ["Data", "Ora", "Match", "Q O2.5", "Q O0.5HT", "Info", "O2.5 FT", "Esito FT"]
        cols = [c for c in cols if c in tmp.columns]
        st.dataframe(tmp.loc[sweet_mask, cols].sort_values(["Data", "Ora"]), use_container_width=True)

# ----------------------------
# Download
# ----------------------------
st.markdown("---")
out_name = f"audit_{uploaded.name.replace('.csv','')}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
st.download_button(
    "💾 SCARICA AUDIT COMPLETO (CSV)",
    data=res_df.to_csv(index=False).encode("utf-8"),
    file_name=out_name
)

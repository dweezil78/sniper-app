import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import json
import os
from pathlib import Path

# ==========================================
# AUDITOR - verifica segnali vs risultati (ieri)
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "arab_sniper_database.json")

API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY}

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

def api_get(session, path, params):
    r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
    if r.status_code != 200:
        return None
    return r.json()

def load_db_results():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
        return data.get("results", []) or []
    except:
        return []

def parse_1x2(s):
    # "6.2|4.0|1.5" -> q1,qx,q2
    try:
        parts = str(s).split("|")
        return float(parts[0]), float(parts[1]), float(parts[2])
    except:
        return None, None, None

def safe_float(x):
    try:
        return float(str(x).replace(",", "."))
    except:
        return None

def build_results_map(session, fixture_ids):
    """
    Ritorna dict fixture_id -> {ht_home, ht_away, ft_home, ft_away}
    """
    out = {}
    # API-Sports non permette batch IDs in un colpo solo in modo standard qui,
    # quindi facciamo chiamate singole (ieri di solito poche centinaia max).
    for fid in fixture_ids:
        res = api_get(session, "fixtures", {"id": fid})
        if not res or not res.get("response"):
            continue
        fx = res["response"][0]
        ht = fx.get("score", {}).get("halftime", {}) or {}
        ft = fx.get("score", {}).get("fulltime", {}) or {}

        # In alcuni casi HT/FT può essere None: gestiamo.
        ht_home = ht.get("home")
        ht_away = ht.get("away")
        ft_home = ft.get("home")
        ft_away = ft.get("away")

        # fallback: goals FT (alcuni feed hanno sempre goals)
        goals = fx.get("goals", {}) or {}
        if ft_home is None:
            ft_home = goals.get("home")
        if ft_away is None:
            ft_away = goals.get("away")

        out[str(fid)] = {
            "HT_H": ht_home, "HT_A": ht_away,
            "FT_H": ft_home, "FT_A": ft_away,
            "Status": fx.get("fixture", {}).get("status", {}).get("short")
        }
    return out

def compute_outcomes(row):
    ht_h = row.get("HT_H")
    ht_a = row.get("HT_A")
    ft_h = row.get("FT_H")
    ft_a = row.get("FT_A")

    def to_int(v):
        try:
            if v is None:
                return None
            return int(v)
        except:
            return None

    ht_h = to_int(ht_h); ht_a = to_int(ht_a)
    ft_h = to_int(ft_h); ft_a = to_int(ft_a)

    # Totali
    ht_total = (ht_h + ht_a) if (ht_h is not None and ht_a is not None) else None
    ft_total = (ft_h + ft_a) if (ft_h is not None and ft_a is not None) else None

    # Hit mercati
    o05ht_hit = (ht_total is not None and ht_total >= 1)
    gght_hit  = (ht_h is not None and ht_a is not None and ht_h >= 1 and ht_a >= 1)
    o25_hit   = (ft_total is not None and ft_total >= 3)

    return pd.Series({
        "HT_Total": ht_total,
        "FT_Total": ft_total,
        "O0.5HT_HIT": o05ht_hit,
        "GGHT_HIT": gght_hit,
        "O2.5_HIT": o25_hit
    })

# ==========================================
# UI
# ==========================================
st.set_page_config(page_title="Arab Sniper Auditor (Ieri)", layout="wide")
st.title("🧪 Arab Sniper Auditor - Verifica Segnali vs Risultati (Ieri)")

yesterday = (now_rome().date() - timedelta(days=1)).strftime("%Y-%m-%d")

st.caption(f"Data audit: **{yesterday}** (timezone Europe/Rome)")

raw = load_db_results()
if not raw:
    st.error("Non trovo arab_sniper_database.json o è vuoto. Prima fai uno scan che salva nel DB.")
    st.stop()

df = pd.DataFrame(raw)
if "Data" not in df.columns or "Fixture_ID" not in df.columns:
    st.error("Nel DB non ci sono le colonne minime (Data / Fixture_ID).")
    st.stop()

df_y = df[df["Data"] == yesterday].copy()
if df_y.empty:
    st.warning(f"Nessun record nel DB per {yesterday}. (Hai fatto lo scan ieri?)")
    st.stop()

# Normalizziamo colonne odds/quote se presenti
if "1X2" in df_y.columns:
    df_y[["q1", "qx", "q2"]] = df_y["1X2"].apply(lambda s: pd.Series(parse_1x2(s)))

for c in ["O2.5", "O0.5H", "GGH"]:
    if c in df_y.columns:
        df_y[c] = df_y[c].apply(safe_float)

# Recupero risultati reali via API
fixture_ids = df_y["Fixture_ID"].astype(str).unique().tolist()

with st.spinner("Recupero risultati (HT/FT) dall'API..."):
    with requests.Session() as s:
        results_map = build_results_map(s, fixture_ids)

# Merge risultati
res_df = pd.DataFrame.from_dict(results_map, orient="index").reset_index().rename(columns={"index": "Fixture_ID"})
df_y["Fixture_ID"] = df_y["Fixture_ID"].astype(str)
res_df["Fixture_ID"] = res_df["Fixture_ID"].astype(str)

audit = df_y.merge(res_df, on="Fixture_ID", how="left")

# Calcolo outcome hit/miss
audit = pd.concat([audit, audit.apply(compute_outcomes, axis=1)], axis=1)

# Colonne utili
audit["FT_Score"] = audit.apply(
    lambda r: f"{r['FT_H']}-{r['FT_A']}" if pd.notna(r.get("FT_H")) and pd.notna(r.get("FT_A")) else "N/D",
    axis=1
)
audit["HT_Score"] = audit.apply(
    lambda r: f"{r['HT_H']}-{r['HT_A']}" if pd.notna(r.get("HT_H")) and pd.notna(r.get("HT_A")) else "N/D",
    axis=1
)

# ==========================================
# KPI GENERALI
# ==========================================
st.subheader("📊 KPI Generali (ieri)")

col1, col2, col3, col4 = st.columns(4)

n_total = len(audit)
n_ft_ok = audit["FT_Total"].notna().sum()
n_ht_ok = audit["HT_Total"].notna().sum()

col1.metric("Match in audit", n_total)
col2.metric("Match con FT disponibile", n_ft_ok)
col3.metric("Match con HT disponibile", n_ht_ok)

# Hit-rate complessivi (su match con dato disponibile)
def hit_rate(series_bool):
    valid = series_bool.dropna()
    if len(valid) == 0:
        return None
    return 100.0 * (valid == True).mean()

hr_o25 = hit_rate(audit.loc[audit["FT_Total"].notna(), "O2.5_HIT"])
hr_o05ht = hit_rate(audit.loc[audit["HT_Total"].notna(), "O0.5HT_HIT"])
hr_gght = hit_rate(audit.loc[audit["HT_Total"].notna(), "GGHT_HIT"])

col4.metric("Hit-rate O2.5 / O0.5HT / GGHT", f"{hr_o25:.1f}% | {hr_o05ht:.1f}% | {hr_gght:.1f}%")

# ==========================================
# KPI PER TAG (Info)
# ==========================================
st.subheader("🏷️ KPI per Tag (Info)")

def has_tag(info, tag):
    return (tag in (info or ""))

tags_to_check = ["⚽⭐", "⚽", "🚀", "🎯PT", "🐟O", "🐟G"]

rows = []
for t in tags_to_check:
    sub = audit[audit["Info"].apply(lambda x: has_tag(x, t))].copy()
    if sub.empty:
        continue

    # hit-rate su subset
    o25 = hit_rate(sub.loc[sub["FT_Total"].notna(), "O2.5_HIT"])
    o05 = hit_rate(sub.loc[sub["HT_Total"].notna(), "O0.5HT_HIT"])
    gg  = hit_rate(sub.loc[sub["HT_Total"].notna(), "GGHT_HIT"])

    rows.append({
        "Tag": t,
        "N": len(sub),
        "Hit O2.5": None if o25 is None else round(o25, 1),
        "Hit O0.5HT": None if o05 is None else round(o05, 1),
        "Hit GGHT": None if gg is None else round(gg, 1),
    })

kpi_tags = pd.DataFrame(rows).sort_values("N", ascending=False)
st.dataframe(kpi_tags, use_container_width=True)

# ==========================================
# TABELLA DETTAGLIO + FILTRI
# ==========================================
st.subheader("🔎 Dettaglio Match (ieri)")

fcol1, fcol2, fcol3 = st.columns(3)
flt_tag = fcol1.selectbox("Filtro Tag (Info contiene)", ["(tutti)"] + tags_to_check)
flt_league = fcol2.text_input("Filtro Lega contiene", "")
only_missing = fcol3.checkbox("Mostra solo match con dati mancanti (HT/FT)", value=False)

view = audit.copy()
if flt_tag != "(tutti)":
    view = view[view["Info"].apply(lambda x: has_tag(x, flt_tag))]

if flt_league.strip():
    view = view[view["Lega"].astype(str).str.lower().str.contains(flt_league.strip().lower(), na=False)]

if only_missing:
    view = view[(view["FT_Total"].isna()) | (view["HT_Total"].isna())]

# Colonne “auditor”
cols = [
    "Ora", "Lega", "Match", "Info",
    "1X2", "O2.5", "O0.5H", "GGH",
    "HT_Score", "FT_Score",
    "O0.5HT_HIT", "GGHT_HIT", "O2.5_HIT",
    "Fixture_ID"
]
cols = [c for c in cols if c in view.columns]

st.dataframe(view[cols].sort_values("Ora"), use_container_width=True)

# Export
st.download_button(
    "💾 Scarica Audit CSV",
    view.to_csv(index=False).encode("utf-8"),
    file_name=f"audit_{yesterday}.csv",
    mime="text/csv"
)

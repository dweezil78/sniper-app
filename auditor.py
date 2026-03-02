import streamlit as st
import pandas as pd
import requests
import time
from pathlib import Path

st.set_page_config(page_title="Arab Audit CSV + Risultati API", layout="wide")
st.title("📊 Arab Auditor — CSV scan + risultati via API")

# =========================
# Config API
# =========================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("Manca API_SPORTS_KEY in st.secrets.")
    st.stop()

HEADERS = {"x-apisports-key": API_KEY}
BASE_URL = "https://v3.football.api-sports.io"

# =========================
# Helpers
# =========================
def to_float(x):
    try:
        if x is None or pd.isna(x):
            return None
        s = str(x).strip().replace(",", ".")
        if s == "" or s.lower() in {"nan", "none"}:
            return None
        return float(s)
    except Exception:
        return None

def to_int(x):
    try:
        if x is None or pd.isna(x):
            return None
        return int(x)
    except Exception:
        return None

def parse_1x2(s):
    # "2.1|3.2|3.4"
    try:
        if s is None or pd.isna(s):
            return None, None, None
        parts = str(s).split("|")
        if len(parts) != 3:
            return None, None, None
        return to_float(parts[0]), to_float(parts[1]), to_float(parts[2])
    except Exception:
        return None, None, None

def is_gold(info):
    return isinstance(info, str) and ("⚽⭐" in info)

def gold_bucket_o05ht(o05):
    if o05 is None or o05 <= 0:
        return "missing"
    if 1.25 <= o05 <= 1.35:
        return "PREMIUM 1.25–1.35"
    if 1.25 <= o05 <= 1.40:
        return "OTTIMO 1.25–1.40"
    if o05 < 1.25:
        return "<1.25 (bassa)"
    if o05 <= 1.45:
        return "1.40–1.45 (rischio)"
    return ">1.45 (alta)"

def compute_hits(ht_h, ht_a, ft_h, ft_a):
    hit_o05ht = None
    hit_gght  = None
    hit_o25   = None
    if ht_h is not None and ht_a is not None:
        hit_o05ht = (ht_h + ht_a) >= 1
        hit_gght  = (ht_h >= 1 and ht_a >= 1)
    if ft_h is not None and ft_a is not None:
        hit_o25 = (ft_h + ft_a) >= 3
    return hit_o05ht, hit_o25, hit_gght

def roi_stake1(odds_series, hit_series):
    sub = pd.DataFrame({"odd": odds_series, "hit": hit_series}).dropna()
    sub = sub[(sub["odd"] > 1.0)]
    if sub.empty:
        return None, None, 0
    profit = ((sub.loc[sub["hit"] == True, "odd"] - 1).sum() - (sub["hit"] == False).sum())
    roi = profit / len(sub)
    return float(roi), float(profit), int(len(sub))

def api_get(session, path, params, retries=3):
    url = f"{BASE_URL}/{path}"
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            # rate limit / transient
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.2 + attempt * 0.8)
                continue
            return None
        except Exception:
            time.sleep(1.0 + attempt * 0.6)
    return None

def fetch_fixture_result(session, fixture_id: int):
    """
    Ritorna dict con:
      status_short, ht_home, ht_away, ft_home, ft_away
    """
    js = api_get(session, "fixtures", {"id": fixture_id, "timezone": "Europe/Rome"})
    if not js or not js.get("response"):
        return None

    f = js["response"][0]
    status = (f.get("fixture", {}) or {}).get("status", {}) or {}
    short = status.get("short")

    score = f.get("score", {}) or {}
    ht = score.get("halftime", {}) or {}
    ft = score.get("fulltime", {}) or {}
    goals = f.get("goals", {}) or {}

    ht_h = to_int(ht.get("home"))
    ht_a = to_int(ht.get("away"))

    ft_h = to_int(ft.get("home"))
    ft_a = to_int(ft.get("away"))
    # fallback
    if ft_h is None:
        ft_h = to_int(goals.get("home"))
    if ft_a is None:
        ft_a = to_int(goals.get("away"))

    return {
        "status_short": short,
        "HT_H": ht_h,
        "HT_A": ht_a,
        "FT_H": ft_h,
        "FT_A": ft_a,
    }

# =========================
# Input CSV
# =========================
st.sidebar.header("📥 Input")
up = st.sidebar.file_uploader("Carica CSV scan (arab_YYYY-MM-DD.csv)", type=["csv"])
default_path = "/mnt/data/arab_2026-03-02 (1).csv"
path_in = st.sidebar.text_input("Oppure path locale", value=default_path)

if up is None and not Path(path_in).exists():
    st.info("Carica un CSV o inserisci un path valido.")
    st.stop()

df = pd.read_csv(up) if up is not None else pd.read_csv(path_in)
st.write("Colonne:", list(df.columns))

if "Fixture_ID" not in df.columns:
    st.error("Nel CSV non trovo la colonna 'Fixture_ID'.")
    st.stop()

# Normalizza odds dal tuo export
if "O0.5H" in df.columns:
    df["O0.5HT"] = df["O0.5H"].apply(to_float)
elif "O0.5HT" in df.columns:
    df["O0.5HT"] = df["O0.5HT"].apply(to_float)
else:
    df["O0.5HT"] = None

df["O2.5_num"] = df["O2.5"].apply(to_float) if "O2.5" in df.columns else None
df["GGHT_num"] = df["GGH"].apply(to_float) if "GGH" in df.columns else (df["GGHT"].apply(to_float) if "GGHT" in df.columns else None)

if "1X2" in df.columns:
    q = df["1X2"].apply(parse_1x2)
    df["Q1"] = [x[0] for x in q]
    df["QX"] = [x[1] for x in q]
    df["Q2"] = [x[2] for x in q]

df["IsGold"] = df["Info"].apply(is_gold) if "Info" in df.columns else False
df["Gold_O05_bucket"] = df["O0.5HT"].apply(gold_bucket_o05ht)

# =========================
# Fetch results
# =========================
st.sidebar.header("⚙️ Fetch risultati")
max_calls = st.sidebar.slider("Max fixture da interrogare (per sicurezza)", 10, 1000, min(300, len(df)), 10)
sleep_s = st.sidebar.slider("Sleep tra chiamate (sec)", 0.0, 1.5, 0.15, 0.05)
only_missing = st.sidebar.checkbox("Interroga solo fixture senza risultati già presenti", value=True)

run = st.button("🚀 Avvia Audit (CSV + risultati API)", type="primary")

if run:
    df = df.copy()

    # se il CSV già avesse HT/FT, puoi usare only_missing=True per completare
    if only_missing:
        have_cols = all(c in df.columns for c in ["HT_H","HT_A","FT_H","FT_A"])
        if have_cols:
            missing_mask = df["FT_H"].isna() | df["FT_A"].isna() | df["HT_H"].isna() | df["HT_A"].isna()
        else:
            missing_mask = pd.Series([True]*len(df))
    else:
        missing_mask = pd.Series([True]*len(df))

    fixture_ids = df.loc[missing_mask, "Fixture_ID"].dropna().astype(int).unique().tolist()
    fixture_ids = fixture_ids[:max_calls]

    st.write(f"Fixture da interrogare via API: **{len(fixture_ids)}**")

    results_map = {}
    with requests.Session() as session:
        pb = st.progress(0.0)
        for i, fid in enumerate(fixture_ids, start=1):
            pb.progress(i / len(fixture_ids) if fixture_ids else 1.0)
            r = fetch_fixture_result(session, int(fid))
            if r:
                results_map[int(fid)] = r
            time.sleep(sleep_s)

    # Merge results into df
    # crea colonne se non esistono
    for col in ["status_short","HT_H","HT_A","FT_H","FT_A"]:
        if col not in df.columns:
            df[col] = None

    for idx, row in df.iterrows():
        fid = row.get("Fixture_ID")
        fid_int = int(fid) if pd.notna(fid) else None
        if fid_int in results_map:
            r = results_map[fid_int]
            df.at[idx, "status_short"] = r["status_short"]
            df.at[idx, "HT_H"] = r["HT_H"]
            df.at[idx, "HT_A"] = r["HT_A"]
            df.at[idx, "FT_H"] = r["FT_H"]
            df.at[idx, "FT_A"] = r["FT_A"]

    # Compute HIT
    hits = df.apply(lambda r: compute_hits(to_int(r["HT_H"]), to_int(r["HT_A"]), to_int(r["FT_H"]), to_int(r["FT_A"])), axis=1)
    df["HIT_O0.5HT"] = [h[0] for h in hits]
    df["HIT_O2.5"] = [h[1] for h in hits]
    df["HIT_GGHT"] = [h[2] for h in hits]

    # =========================
    # Dashboard KPI
    # =========================
    st.divider()
    st.subheader("📌 KPI Globali (solo match con risultato disponibile)")

    df_ht = df[df["HIT_O0.5HT"].notna()].copy()
    df_ft = df[df["HIT_O2.5"].notna()].copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Match CSV", len(df))
    c2.metric("Con HT", len(df_ht))
    c3.metric("Con FT", len(df_ft))
    c4.metric("Gold (⚽⭐)", int(df["IsGold"].sum()))

    def hr(sub, col):
        s = sub[col].dropna()
        return None if s.empty else 100.0 * (s == True).mean()

    st.write(
        f"**Hit-rate**  O0.5HT: `{(hr(df_ht,'HIT_O0.5HT') or 0):.1f}%`  |  "
        f"O2.5: `{(hr(df_ft,'HIT_O2.5') or 0):.1f}%`  |  "
        f"GGHT: `{(hr(df_ht,'HIT_GGHT') or 0):.1f}%`"
    )

    roi_all, prof_all, n_all = roi_stake1(df_ht["O0.5HT"], df_ht["HIT_O0.5HT"])
    if roi_all is not None:
        st.write(f"**ROI O0.5HT (stake 1)** su {n_all} match: `{roi_all*100:.2f}%` (profit `{prof_all:.2f}`)")

    # =========================
    # Gold KPI
    # =========================
    st.subheader("⭐ KPI Gold (⚽⭐)")

    gold = df[df["IsGold"] == True].copy()
    gold_ht = gold[gold["HIT_O0.5HT"].notna()].copy()
    gold_ft = gold[gold["HIT_O2.5"].notna()].copy()

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Gold totali", len(gold))
    g2.metric("Gold con HT", len(gold_ht))
    g3.metric("Gold con FT", len(gold_ft))
    roi_g, prof_g, n_g = roi_stake1(gold_ht["O0.5HT"], gold_ht["HIT_O0.5HT"])
    g4.metric("ROI Gold O0.5HT", f"{(roi_g*100):.2f}%" if roi_g is not None else "n/a")

    st.write(
        f"**Hit-rate Gold**  O0.5HT: `{(hr(gold_ht,'HIT_O0.5HT') or 0):.1f}%`  |  "
        f"O2.5: `{(hr(gold_ft,'HIT_O2.5') or 0):.1f}%`  |  "
        f"GGHT: `{(hr(gold_ht,'HIT_GGHT') or 0):.1f}%`"
    )

    st.subheader("🏷️ Gold per bucket O0.5HT (Premium/Ottimo ecc.)")
    rows = []
    for bucket in ["PREMIUM 1.25–1.35", "OTTIMO 1.25–1.40", "<1.25 (bassa)", "1.40–1.45 (rischio)", ">1.45 (alta)", "missing"]:
        sub = gold[gold["Gold_O05_bucket"] == bucket].copy()
        sub_ht = sub[sub["HIT_O0.5HT"].notna()].copy()
        if sub.empty:
            continue
        roi_b, prof_b, n_b = roi_stake1(sub_ht["O0.5HT"], sub_ht["HIT_O0.5HT"]) if not sub_ht.empty else (None, None, 0)
        rows.append({
            "Bucket": bucket,
            "N": len(sub),
            "Hit O0.5HT %": round((hr(sub_ht,"HIT_O0.5HT") or 0), 2),
            "Avg O0.5HT": round(sub["O0.5HT"].dropna().mean() or 0, 3),
            "ROI O0.5HT %": round((roi_b or 0) * 100, 2) if roi_b is not None else None,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.subheader("🔎 Tabella dettagli (con risultati)")
    show_cols = [c for c in [
        "Ora","Lega","Match","Info","1X2","O2.5","O0.5H","GGH",
        "status_short","HT_H","HT_A","FT_H","FT_A",
        "HIT_O0.5HT","HIT_O2.5","HIT_GGHT",
        "Fixture_ID","Gold_O05_bucket"
    ] if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True)

    st.subheader("💾 Export")
    st.download_button(
        "Scarica CSV arricchito (quote + risultati + hit)",
        df.to_csv(index=False).encode("utf-8"),
        file_name="audit_full_enriched.csv",
        mime="text/csv"
    )

import os
import time
import json
import requests
import pandas as pd
import matplotlib.pyplot as plt

# =========================
# CONFIG
# =========================
CSV_AUDIT_PATH = "arab_audit_20260227_0644.csv"   # <-- metti qui il tuo file
OUT_MERGED_CSV = "audit_merged_with_results.csv"
CACHE_FILE = "api_results_cache.json"

API_KEY = os.getenv("API_SPORTS_KEY", "").strip()
if not API_KEY:
    # In alternativa: incolla qui la key (sconsigliato se condividi il file)
    API_KEY = "INCOLLA_LA_TUA_API_KEY_QUI"

API_BASE = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

REQUEST_SLEEP = 0.55  # per evitare rate-limit
MAX_RETRIES = 3

# =========================
# Helpers
# =========================
def load_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def api_get_fixtures_by_id(session: requests.Session, fixture_id: int) -> dict | None:
    url = f"{API_BASE}/fixtures"
    params = {"id": int(fixture_id)}
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, headers=HEADERS, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            js = r.json()
            resp = js.get("response", [])
            if not resp:
                return None
            return resp[0]
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"[ERROR] fixture {fixture_id}: {e}")
                return None
            time.sleep(1.0 * (attempt + 1))
    return None

def safe_int(x):
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        return int(x)
    except Exception:
        return None

def contains_tag(info: str, tag: str) -> bool:
    return isinstance(info, str) and (tag in info)

# =========================
# Load audit
# =========================
df = pd.read_csv(CSV_AUDIT_PATH)
if "Fixture_ID" not in df.columns:
    raise RuntimeError("CSV senza colonna Fixture_ID. Assicurati di esportare l'audit con Fixture_ID.")

# Cache per evitare chiamate ripetute su fixture già risolti
cache = load_cache(CACHE_FILE)

fixture_ids = df["Fixture_ID"].dropna().astype(int).unique().tolist()
print(f"Fixture unici nel CSV: {len(fixture_ids)}")

rows = []
with requests.Session() as session:
    for i, fid in enumerate(fixture_ids, start=1):
        fid_s = str(fid)
        if fid_s in cache:
            rows.append({"Fixture_ID": fid, **cache[fid_s]})
            continue

        time.sleep(REQUEST_SLEEP)
        fx = api_get_fixtures_by_id(session, fid)
        if not fx:
            payload = {
                "status": None,
                "ft_home": None, "ft_away": None,
                "ht_home": None, "ht_away": None,
                "date": None
            }
            cache[fid_s] = payload
            rows.append({"Fixture_ID": fid, **payload})
            continue

        status = fx.get("fixture", {}).get("status", {}).get("short")
        date = fx.get("fixture", {}).get("date")

        # FT spesso sta in goals oppure score.fulltime
        goals = fx.get("goals", {})
        ft_home = goals.get("home", None)
        ft_away = goals.get("away", None)

        ht = fx.get("score", {}).get("halftime", {}) or {}
        ht_home = ht.get("home", None)
        ht_away = ht.get("away", None)

        payload = {
            "status": status,
            "ft_home": safe_int(ft_home),
            "ft_away": safe_int(ft_away),
            "ht_home": safe_int(ht_home),
            "ht_away": safe_int(ht_away),
            "date": date
        }
        cache[fid_s] = payload
        rows.append({"Fixture_ID": fid, **payload})

# Salva cache
save_cache(CACHE_FILE, cache)

df_res = pd.DataFrame(rows)
dfm = df.merge(df_res, on="Fixture_ID", how="left")

# =========================
# Compute outcomes
# =========================
def over25_ft(row):
    if row["status"] != "FT":
        return None
    if pd.isna(row["ft_home"]) or pd.isna(row["ft_away"]):
        return None
    return (int(row["ft_home"]) + int(row["ft_away"])) >= 3

def gg_ft(row):
    if row["status"] != "FT":
        return None
    if pd.isna(row["ft_home"]) or pd.isna(row["ft_away"]):
        return None
    return (int(row["ft_home"]) > 0) and (int(row["ft_away"]) > 0)

def goal_by_ht(row):
    # metrica robusta per GG-PT: "c'è stato almeno 1 gol entro HT"
    if row["status"] != "FT":
        return None
    if pd.isna(row["ht_home"]) or pd.isna(row["ht_away"]):
        return None
    return (int(row["ht_home"]) + int(row["ht_away"])) >= 1

dfm["Over25_FT"] = dfm.apply(over25_ft, axis=1)
dfm["GG_FT"] = dfm.apply(gg_ft, axis=1)
dfm["GoalByHT"] = dfm.apply(goal_by_ht, axis=1)

# =========================
# Signal subsets
# =========================
dfm["is_GGPT"] = dfm["Info"].apply(lambda s: contains_tag(s, "🎯 GG-PT"))
dfm["is_O25BOOST"] = dfm["Info"].apply(lambda s: contains_tag(s, "💣 O25-BOOST"))
dfm["is_OVERPRO"] = dfm["Info"].apply(lambda s: contains_tag(s, "🔥 OVER-PRO"))
dfm["is_Drop"] = dfm["Info"].apply(lambda s: contains_tag(s, "Drop"))
dfm["is_R80"] = dfm["Rating"].apply(lambda x: (pd.notna(x) and float(x) >= 80))

def pct_true(series: pd.Series):
    s = series.dropna()
    if len(s) == 0:
        return None
    return float(s.mean() * 100.0)

def summarize(mask, outcome_col):
    sub = dfm[mask]
    return {
        "count": len(sub),
        "ft_count": int((sub["status"] == "FT").sum()),
        "pct": pct_true(sub[outcome_col])
    }

summary = {
    "GG-PT (GoalByHT)": summarize(dfm["is_GGPT"], "GoalByHT"),
    "O25-BOOST (Over2.5 FT)": summarize(dfm["is_O25BOOST"], "Over25_FT"),
    "OVER-PRO (Over2.5 FT)": summarize(dfm["is_OVERPRO"], "Over25_FT"),
    "Rating>=80 (Over2.5 FT)": summarize(dfm["is_R80"], "Over25_FT"),
    "DROP (Over2.5 FT)": summarize(dfm["is_Drop"], "Over25_FT"),
    "NO-DROP (Over2.5 FT)": summarize(~dfm["is_Drop"], "Over25_FT"),
}

print("\n=== DAY-AFTER SUMMARY ===")
print(f"Totale righe audit: {len(dfm)}")
print(f"FT disponibili: {(dfm['status'] == 'FT').sum()} / {len(dfm)}")
for k, v in summary.items():
    pct = v["pct"]
    pct_s = "N/D" if pct is None else f"{pct:.2f}%"
    print(f"- {k}: count={v['count']} | FT={v['ft_count']} | success={pct_s}")

# Esporta merged
dfm.to_csv(OUT_MERGED_CSV, index=False, encoding="utf-8")
print(f"\n✅ Salvato: {OUT_MERGED_CSV}")
print(f"✅ Cache: {CACHE_FILE}")

# =========================
# Charts (matplotlib, no colors specified)
# =========================
# 1) Success rate per signal (solo dove pct disponibile)
labels = []
pcts = []
counts = []
for k in ["GG-PT (GoalByHT)", "O25-BOOST (Over2.5 FT)", "OVER-PRO (Over2.5 FT)", "Rating>=80 (Over2.5 FT)"]:
    pct = summary[k]["pct"]
    if pct is None:
        continue
    labels.append(k.split(" (")[0])
    pcts.append(pct)
    counts.append(summary[k]["ft_count"])

plt.figure()
plt.bar(labels, pcts)
plt.ylim(0, 100)
plt.ylabel("Success rate (%)")
plt.title("Day-after: Success rate per segnale (solo match FT)")
for i, (pct, n) in enumerate(zip(pcts, counts)):
    plt.text(i, pct + 1, f"{pct:.1f}%\n(n={n})", ha="center", va="bottom")
plt.tight_layout()
plt.savefig("chart_success_by_signal.png", dpi=160)

# 2) Drop vs No-Drop (Over2.5 FT)
dv = []
dl = []
for k in ["DROP (Over2.5 FT)", "NO-DROP (Over2.5 FT)"]:
    pct = summary[k]["pct"]
    if pct is None:
        continue
    dl.append(k.split(" ")[0])
    dv.append(pct)

plt.figure()
plt.bar(dl, dv)
plt.ylim(0, 100)
plt.ylabel("Over2.5 FT success (%)")
plt.title("Day-after: Drop vs No-Drop (Over 2.5 FT)")
for i, pct in enumerate(dv):
    plt.text(i, pct + 1, f"{pct:.1f}%", ha="center", va="bottom")
plt.tight_layout()
plt.savefig("chart_drop_vs_nodrop.png", dpi=160)

# 3) Rating distribution (count)
# (solo FT per avere coerenza)
dft = dfm[dfm["status"] == "FT"].copy()
if not dft.empty:
    bins = [0, 40, 55, 65, 75, 85, 101]
    labels_bins = ["<=40", "41-55", "56-65", "66-75", "76-85", "86-100"]
    dft["rating_bin"] = pd.cut(dft["Rating"], bins=bins, labels=labels_bins, include_lowest=True)
    dist = dft["rating_bin"].value_counts().sort_index()

    plt.figure()
    plt.bar(dist.index.astype(str), dist.values)
    plt.ylabel("Match count (FT)")
    plt.title("Distribuzione Rating (solo match FT)")
    for i, v in enumerate(dist.values):
        plt.text(i, v + 0.2, str(v), ha="center", va="bottom")
    plt.tight_layout()
    plt.savefig("chart_rating_distribution.png", dpi=160)

print("\n✅ Grafici salvati:")
print("- chart_success_by_signal.png")
print("- chart_drop_vs_nodrop.png")
print("- chart_rating_distribution.png (se c'erano match FT)")

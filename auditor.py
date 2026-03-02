import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import re
from typing import Any

# =========================================================
# Arab RetroScan + Auditor (ODDS-aware, Tunable)
# =========================================================

st.set_page_config(page_title="Arab RetroScan + Auditor (Tunable)", layout="wide")
st.title("🕰️ Arab RetroScan + Auditor (solo match con odds)")

# --------------------------
# TZ (Rome)
# --------------------------
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

def now_rome():
    return datetime.now(ROME_TZ) if ROME_TZ else datetime.now()

# --------------------------
# API
# --------------------------
API_KEY = st.secrets.get("API_SPORTS_KEY")
HEADERS = {"x-apisports-key": API_KEY} if API_KEY else {}

def api_get(session, path, params):
    try:
        r = session.get(f"https://v3.football.api-sports.io/{path}", headers=HEADERS, params=params, timeout=25)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

# --------------------------
# Robust parsing utils
# --------------------------
def _norm_any(s: Any) -> str:
    try:
        if s is None:
            return ""
        return str(s).strip().lower()
    except Exception:
        return ""

def _extract_value_from_v(v: Any) -> str:
    try:
        if v is None:
            return ""
        if isinstance(v, dict):
            for k in ("value", "name", "label"):
                if k in v and v.get(k) is not None:
                    return str(v.get(k))
            return str(v)
        return str(v)
    except Exception:
        return ""

def _to_float(x):
    try:
        if x is None:
            return None
        return float(str(x).replace(",", "."))
    except Exception:
        return None

def _is_over_value(val_norm: str, line: str) -> bool:
    # accetta: Over 0.5 / Over(0.5) / Over 0,5 etc
    if "over" not in val_norm:
        return False
    m = re.search(r"(\d+(?:[.,]\d+)?)", val_norm)
    if not m:
        return False
    num = m.group(1).replace(",", ".")
    return num == line

def _is_yes(val_norm: str) -> bool:
    return val_norm in {"yes", "si", "sì", "y", "1", "true"}

def _is_first_half_text(txt: str) -> bool:
    t = _norm_any(txt)
    return any(k in t for k in ["1st half", "first half", "1h", "ht", "half time", "halftime", "1° tempo"])

def _maybe_set_max(mk: dict, key: str, odd_val):
    odd = _to_float(odd_val)
    if odd is None or odd <= 0:
        return
    cur = float(mk.get(key, 0) or 0)
    if odd > cur:
        mk[key] = odd

# --------------------------
# Market extraction (q1,qx,q2,o25,o05ht,gght)
# --------------------------
def extract_markets_from_odds_response(odds_json) -> dict:
    mk = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "gght": 0.0}
    if not odds_json or not odds_json.get("response"):
        return mk

    try:
        resp0 = odds_json["response"][0]
    except Exception:
        return mk

    bookmakers = resp0.get("bookmakers", []) or []

    for bm in bookmakers:
        bets = bm.get("bets", []) if isinstance(bm, dict) else []
        if not bets:
            continue

        for b in bets:
            if not isinstance(b, dict):
                continue

            b_id = b.get("id")
            b_name = _norm_any(b.get("name", ""))

            values = b.get("values", []) or []
            for v in values:
                vv_raw = _extract_value_from_v(v)
                vv = _norm_any(vv_raw)
                odd = v.get("odd") if isinstance(v, dict) else None
                # some feeds could use other keys
                if odd is None and isinstance(v, dict):
                    odd = v.get("price") or v.get("odds")

                # 1X2
                if b_id == 1 or any(k in b_name for k in ["match winner", "1x2", "winner", "full time result"]):
                    if vv in {"home", "1", "local", "casa"}:
                        _maybe_set_max(mk, "q1", odd)
                    elif vv in {"draw", "x", "pareggio"}:
                        _maybe_set_max(mk, "qx", odd)
                    elif vv in {"away", "2", "visitors", "trasferta"}:
                        _maybe_set_max(mk, "q2", odd)

                # Over 2.5 FT
                if (b_id == 5) or (
                    ("over/under" in b_name or "over under" in b_name or "totals" in b_name)
                    and not any(k in b_name for k in ["1st half", "first half", "half time", "1h", "ht"])
                ):
                    if _is_over_value(vv, "2.5"):
                        _maybe_set_max(mk, "o25", odd)

                # Over 0.5 HT
                if (b_id == 13) or (_is_first_half_text(b_name) and any(k in b_name for k in ["total", "over/under", "over under", "ou", "goals"])):
                    # evita team totals
                    if "team" in b_name:
                        pass
                    else:
                        if _is_over_value(vv, "0.5"):
                            _maybe_set_max(mk, "o05ht", odd)

                # BTTS 1H (GGHT) tollerante
                is_btts = any(k in b_name for k in ["both teams", "both team", "btts", "gg", "to score", "gol/gol", "entrambe segnano"])
                if is_btts:
                    bet_is_1h = _is_first_half_text(b_name)
                    if _is_yes(vv) and (bet_is_1h or _is_first_half_text(vv_raw) or b_id in [40, 71]):
                        _maybe_set_max(mk, "gght", odd)

    return mk

# --------------------------
# Team stats
# --------------------------
def get_team_performance(session, tid: int):
    if tid is None:
        return None
    res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
    fx = res.get("response", []) if res else []
    if not fx:
        return None

    act = len(fx)
    tht, gf, gs = 0, 0, 0
    for f in fx:
        ht = (f.get("score", {}) or {}).get("halftime", {}) or {}
        tht += (ht.get("home") or 0) + (ht.get("away") or 0)

        is_home = (f.get("teams", {}) or {}).get("home", {}).get("id") == tid
        goals = f.get("goals", {}) or {}
        gh = goals.get("home") or 0
        ga = goals.get("away") or 0

        if is_home:
            gf += gh
            gs += ga
        else:
            gf += ga
            gs += gh

    return {"avg_ht": tht / act, "avg_total": (gf + gs) / act}

# --------------------------
# Tag logic (tunable)
# --------------------------
def compute_tags(mk, s_h, s_a, ggpt_threshold: float, gold_ht_threshold: float, gold_requires_ht: bool):
    tags = ["HT-OK"]
    h_p, h_o, h_g = False, False, False

    fav = min(mk["q1"], mk["q2"]) if (mk["q1"] > 0 and mk["q2"] > 0) else 999.0

    # Pressure/fav logic (🐟O / 🐟G)
    if (fav < 1.75) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0):
        tags.append("🐟O"); h_p = True
    if (2.0 <= mk["q1"] <= 3.5) and (2.0 <= mk["q2"] <= 3.5) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0):
        tags.append("🐟G"); h_p = True

    # Over standard/boost
    if (s_h["avg_total"] >= 2.0 and s_a["avg_total"] >= 2.0):
        if mk["o25"] > 1.80 and mk["o05ht"] > 1.30:
            tags.append("⚽"); h_o = True
        elif (mk["o25"] > 0 and mk["o05ht"] > 0) and mk["o25"] <= 1.80 and mk["o05ht"] <= 1.30:
            tags.append("🚀"); h_o = True

    # GGPT threshold (tunable)
    if (s_h["avg_total"] >= ggpt_threshold) and (s_a["avg_total"] >= ggpt_threshold):
        tags.append("🎯PT"); h_g = True

    # Gold (tunable)
    if h_p and h_o and h_g:
        if gold_requires_ht:
            if (s_h["avg_ht"] >= gold_ht_threshold) and (s_a["avg_ht"] >= gold_ht_threshold):
                tags.insert(0, "⚽⭐")
        else:
            tags.insert(0, "⚽⭐")

    return " ".join(tags)

# --------------------------
# Outcomes (HIT/MISS)
# --------------------------
def compute_outcomes(ht_h, ht_a, ft_h, ft_a):
    def to_int(v):
        try:
            if v is None:
                return None
            return int(v)
        except Exception:
            return None

    ht_h = to_int(ht_h); ht_a = to_int(ht_a)
    ft_h = to_int(ft_h); ft_a = to_int(ft_a)

    ht_total = (ht_h + ht_a) if (ht_h is not None and ht_a is not None) else None
    ft_total = (ft_h + ft_a) if (ft_h is not None and ft_a is not None) else None

    hit_o05ht = (ht_total is not None and ht_total >= 1)
    hit_gght  = (ht_h is not None and ht_a is not None and ht_h >= 1 and ht_a >= 1)
    hit_o25   = (ft_total is not None and ft_total >= 3)

    return ht_total, ft_total, hit_o05ht, hit_gght, hit_o25

# =========================================================
# UI Controls
# =========================================================
today = now_rome().date()
default_day = today - timedelta(days=1)

st.sidebar.header("⚙️ Parametri test (replica Sniper)")
audit_day = st.sidebar.date_input("Data da auditare", value=default_day, max_value=today)

ggpt_threshold = st.sidebar.slider("Soglia 🎯PT (avg_total)", 1.0, 2.0, 1.2, 0.1)
gold_requires_ht = st.sidebar.checkbox("Gold richiede avg_ht min", value=False)
gold_ht_threshold = st.sidebar.slider("Soglia Gold avg_ht", 0.5, 1.2, 0.8, 0.1)

only_finished = st.sidebar.checkbox("Solo match FT", value=True)
max_fixtures = st.sidebar.slider("Limite match", 50, 500, 250, 50)

with st.sidebar.expander("Filtri", expanded=False):
    excluded_countries_str = st.text_input("Escludi nazioni (virgole)", value="")
    league_blacklist_str = st.text_input("Blacklist leghe contiene (virgole)", value="u19,u20,youth,women,friendly")

excluded_countries = [x.strip() for x in excluded_countries_str.split(",") if x.strip()]
league_blacklist = [x.strip().lower() for x in league_blacklist_str.split(",") if x.strip()]

run = st.button("🧪 Avvia RetroScan + Audit", type="primary")

# =========================================================
# Run
# =========================================================
if run:
    dstr = audit_day.strftime("%Y-%m-%d")

    with st.spinner(f"Scarico fixtures del {dstr}..."):
        with requests.Session() as session:
            fx_res = api_get(session, "fixtures", {"date": dstr, "timezone": "Europe/Rome"})
            if not fx_res or not fx_res.get("response"):
                st.error("Nessun fixture trovato o errore API.")
                st.stop()

            fixtures = fx_res["response"]

            rows = []
            for f in fixtures:
                status = (f.get("fixture", {}) or {}).get("status", {}).get("short")
                if only_finished and status != "FT":
                    continue

                country = (f.get("league", {}) or {}).get("country", "") or ""
                league_name = (f.get("league", {}) or {}).get("name", "") or ""

                if excluded_countries and country in excluded_countries:
                    continue

                if any(b in league_name.lower() for b in league_blacklist):
                    continue

                rows.append(f)

            rows = rows[:max_fixtures]
            if not rows:
                st.warning("Dopo i filtri non resta nessun match.")
                st.stop()

            out = []
            pb = st.progress(0.0)

            for i, f in enumerate(rows, start=1):
                pb.progress(i / len(rows))

                fid = int((f.get("fixture", {}) or {}).get("id"))
                dt_iso = (f.get("fixture", {}) or {}).get("date", "")
                ora = dt_iso[11:16] if dt_iso else ""

                country = (f.get("league", {}) or {}).get("country", "")
                lega = f"{(f.get('league', {}) or {}).get('name','')} ({country})"
                home = (f.get("teams", {}) or {}).get("home", {}).get("name", "Home")
                away = (f.get("teams", {}) or {}).get("away", {}).get("name", "Away")
                match = f"{home} - {away}"

                # results
                sc = f.get("score", {}) or {}
                ht = sc.get("halftime", {}) or {}
                ft = sc.get("fulltime", {}) or {}
                goals = f.get("goals", {}) or {}

                ht_h, ht_a = ht.get("home"), ht.get("away")
                ft_h, ft_a = ft.get("home"), ft.get("away")
                if ft_h is None:
                    ft_h = goals.get("home")
                if ft_a is None:
                    ft_a = goals.get("away")

                # odds
                odds_json = api_get(session, "odds", {"fixture": fid})
                mk = extract_markets_from_odds_response(odds_json)

                odds_ok = not (mk["q1"] == 0 and mk["q2"] == 0 and mk["o25"] == 0 and mk["o05ht"] == 0 and mk["gght"] == 0)

                # team stats
                hid = (f.get("teams", {}) or {}).get("home", {}).get("id")
                aid = (f.get("teams", {}) or {}).get("away", {}).get("id")
                s_h = get_team_performance(session, hid)
                s_a = get_team_performance(session, aid)

                info = "NO-STATS"
                if s_h and s_a:
                    info = compute_tags(mk, s_h, s_a, ggpt_threshold, gold_ht_threshold, gold_requires_ht)

                ht_total, ft_total, hit_o05ht, hit_gght, hit_o25 = compute_outcomes(ht_h, ht_a, ft_h, ft_a)

                fav = min(mk["q1"], mk["q2"]) if (mk["q1"] > 0 and mk["q2"] > 0) else 0
                is_gold_zone = (1.40 <= fav <= 1.90) if fav > 0 else False

                out.append({
                    "Data": dstr,
                    "Ora": ora,
                    "Lega": lega,
                    "Match": match,
                    "Fixture_ID": fid,

                    "ODDS_OK": odds_ok,
                    "Fav": fav,
                    "GoldZone": "✅" if is_gold_zone else "❌",

                    "Q1": mk["q1"], "QX": mk["qx"], "Q2": mk["q2"],
                    "O2.5": mk["o25"],
                    "O0.5HT": mk["o05ht"],
                    "GGHT": mk["gght"],

                    "HT_H": ht_h, "HT_A": ht_a,
                    "FT_H": ft_h, "FT_A": ft_a,
                    "HT_Total": ht_total,
                    "FT_Total": ft_total,

                    "HIT_O0.5HT": hit_o05ht,
                    "HIT_GGHT": hit_gght,
                    "HIT_O2.5": hit_o25,

                    "Info": info,
                    "HT_AVG_H": None if not s_h else round(s_h["avg_ht"], 2),
                    "HT_AVG_A": None if not s_a else round(s_a["avg_ht"], 2),
                    "TOT_AVG_H": None if not s_h else round(s_h["avg_total"], 2),
                    "TOT_AVG_A": None if not s_a else round(s_a["avg_total"], 2),
                })

            df = pd.DataFrame(out)

    st.divider()
    st.subheader("📌 KPI (SOLO match con ODDS_OK = True)")
    df_ok = df[df["ODDS_OK"] == True].copy()

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Match totali", len(df))
    a2.metric("Match con ODDS_OK", len(df_ok))
    a3.metric("HT disponibili (ODDS_OK)", int(df_ok["HT_Total"].notna().sum()))
    a4.metric("FT disponibili (ODDS_OK)", int(df_ok["FT_Total"].notna().sum()))

    def hit_rate(subdf, col, avail_col):
        s = subdf[subdf[avail_col].notna()][col].dropna()
        if s.empty:
            return None
        return 100.0 * (s == True).mean()

    hr_o25 = hit_rate(df_ok, "HIT_O2.5", "FT_Total")
    hr_o05 = hit_rate(df_ok, "HIT_O0.5HT", "HT_Total")
    hr_gg  = hit_rate(df_ok, "HIT_GGHT", "HT_Total")

    st.write(
        f"**Hit-rate (ODDS_OK)**  O2.5: `{(hr_o25 or 0):.1f}%`  |  "
        f"O0.5HT: `{(hr_o05 or 0):.1f}%`  |  "
        f"GGHT: `{(hr_gg or 0):.1f}%`"
    )

    st.subheader("🏷️ KPI per Tag (ODDS_OK)")
    tags_to_check = ["⚽⭐", "⚽", "🚀", "🎯PT", "🐟O", "🐟G"]

    rows = []
    for t in tags_to_check:
        sub = df_ok[df_ok["Info"].astype(str).str.contains(re.escape(t), na=False)]
        if sub.empty:
            continue
        rows.append({
            "Tag": t,
            "N": len(sub),
            "Hit O2.5 %": round(hit_rate(sub, "HIT_O2.5", "FT_Total") or 0, 1),
            "Hit O0.5HT %": round(hit_rate(sub, "HIT_O0.5HT", "HT_Total") or 0, 1),
            "Hit GGHT %": round(hit_rate(sub, "HIT_GGHT", "HT_Total") or 0, 1),
        })

    kpi_tags = pd.DataFrame(rows).sort_values("N", ascending=False) if rows else pd.DataFrame()
    st.dataframe(kpi_tags, use_container_width=True)

    st.subheader("🔎 Dettaglio match (ODDS_OK)")
    f1, f2, f3 = st.columns([1.2, 1.2, 1.6])
    flt_tag = f1.selectbox("Filtro Tag", ["(tutti)"] + tags_to_check, index=0)
    only_tagged = f2.checkbox("Solo match con almeno 1 tag", value=False)
    only_goldzone = f3.checkbox("Solo GoldZone ✅", value=False)

    view = df_ok.copy()
    if flt_tag != "(tutti)":
        view = view[view["Info"].astype(str).str.contains(re.escape(flt_tag), na=False)]
    if only_tagged:
        view = view[view["Info"].astype(str).str.contains("⚽⭐|⚽|🚀|🎯PT|🐟O|🐟G", regex=True, na=False)]
    if only_goldzone:
        view = view[view["GoldZone"] == "✅"]

    show_cols = [
        "Ora", "Lega", "Match", "Info",
        "Fav", "GoldZone",
        "Q1", "QX", "Q2", "O2.5", "O0.5HT", "GGHT",
        "HT_H", "HT_A", "FT_H", "FT_A",
        "HIT_O0.5HT", "HIT_GGHT", "HIT_O2.5",
        "Fixture_ID"
    ]
    st.dataframe(view[show_cols].sort_values("Ora"), use_container_width=True)

    st.download_button(
        "💾 Scarica CSV (ODDS_OK)",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"retro_audit_oddsok_{dstr}.csv",
        mime="text/csv"
    )

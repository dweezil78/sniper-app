# retrocan_auditor_fixed.py
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, date
import re
from typing import Any

# =========================================================
# RetroScan + Auditor (API-Sports) - standalone - FIXED
# =========================================================

st.set_page_config(page_title="Arab RetroScan + Auditor (fixed)", layout="wide")
st.title("🕰️ Arab RetroScan + Auditor (FIXED)")

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
# Helpers parsing odds (robuste)
# --------------------------
def _norm_any(s: Any) -> str:
    """
    Normalizza qualunque valore a stringa lowercase sicura.
    Se s è dict e ha 'value' prova a usarlo.
    """
    try:
        if s is None:
            return ""
        # se è dict e ha key 'value'
        if isinstance(s, dict):
            v = s.get("value", "") or ""
            return str(v).strip().lower()
        # ansonsten cast a str
        return str(s).strip().lower()
    except Exception:
        return ""

def _extract_value_from_v(v: Any) -> str:
    """
    Riceve l'elemento v dalla lista 'values' e restituisce il 'value' come stringa
    Gestisce più formati possibili (dict con 'value', stringa, list, etc.)
    """
    try:
        if v is None:
            return ""
        if isinstance(v, dict):
            # possono esserci diverse chiavi: 'value', 'name', 'label'
            for k in ("value", "name", "label"):
                if k in v and v.get(k) is not None:
                    return str(v.get(k))
            # come fallback prova a serializzare
            return str(v)
        # se è str o numero
        return str(v)
    except Exception:
        return ""

def _extract_odd_from_v(v: Any):
    """
    Estrae la quota 'odd' da un elemento value della response.
    Restituisce None se non è convertibile.
    """
    try:
        if v is None:
            return None
        if isinstance(v, dict):
            # chiavi possibili: 'odd', 'price', 'odds'
            for k in ("odd", "price", "odds", "value"):
                if k in v and v.get(k) is not None:
                    try:
                        return float(str(v.get(k)).replace(",", "."))
                    except Exception:
                        continue
            # fallback: cerca in tutto il dict la prima cosa convertibile a float
            for vv in v.values():
                try:
                    return float(str(vv).replace(",", "."))
                except Exception:
                    continue
            return None
        # se è già un numero o stringa convertibile
        try:
            return float(str(v).replace(",", "."))
        except Exception:
            return None
    except Exception:
        return None

def _to_float_safe(x):
    try:
        if x is None:
            return None
        return float(str(x).replace(",", "."))
    except Exception:
        return None

def _is_over_value(val_norm: str, line: str) -> bool:
    if "over" not in val_norm:
        return False
    m = re.search(r"(\d+(?:[.,]\d+)?)", val_norm)
    if not m:
        return False
    num = m.group(1).replace(",", ".")
    return num == line

def _is_btts_yes(val_norm: str) -> bool:
    return val_norm in {"yes", "si", "sì", "y", "true", "1"}

def _is_first_half_text(txt: str) -> bool:
    t = _norm_any(txt)
    return any(k in t for k in ["1st half", "first half", "1h", "ht", "half time", "halftime"])

def _maybe_set_max(mk: dict, key: str, odd_val):
    odd = _to_float_safe(odd_val)
    if odd is None or odd <= 0:
        return
    cur = float(mk.get(key, 0) or 0)
    if odd > cur:
        mk[key] = odd

# --------------------------
# Market extraction (robusto)
# --------------------------
def extract_markets_from_odds_response(odds_json) -> dict:
    """
    Estrae mercati dalla response /odds in maniera robusta.
    Ritorna mk con q1,qx,q2,o25,o05ht,gght (0.0 se non trovati)
    """
    mk = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0, "o05ht": 0.0, "gght": 0.0}

    if not odds_json or not odds_json.get("response"):
        return mk

    try:
        resp0 = odds_json["response"][0]
    except Exception:
        return mk

    bookmakers = resp0.get("bookmakers", []) or []

    for bm in bookmakers:
        # protezione: bookmaker inattesi
        try:
            bets = bm.get("bets", []) or []
        except Exception:
            # se il bookmaker è inatteso skip
            continue

        for b in bets:
            # protezioni sui tipi
            try:
                b_id = b.get("id") if isinstance(b, dict) else None
                b_name = _norm_any(b.get("name") if isinstance(b, dict) else b)
            except Exception:
                b_id = None
                b_name = ""

            # prendi valori in modo sicuro
            try:
                values = b.get("values", []) if isinstance(b, dict) else []
                if values is None:
                    values = []
            except Exception:
                values = []

            # SCORRI values difendendoti da formati strani
            for v in values:
                v_val_raw = _extract_value_from_v(v)
                vv = _norm_any(v_val_raw)
                odd = _extract_odd_from_v(v)

                # 1X2 - match winner
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

                # Over 0.5 HT (1st half totals)
                if (b_id == 13) or (_is_first_half_text(b_name) and any(k in b_name for k in ["over/under", "over under", "totals", "goals"])):
                    if _is_over_value(vv, "0.5"):
                        _maybe_set_max(mk, "o05ht", odd)

                # BTTS 1H (GGHT) - tollerante name/value
                is_btts = any(k in b_name for k in ["both teams", "both team", "btts", "gg", "to score"])
                if is_btts:
                    bet_is_1h = _is_first_half_text(b_name)
                    # se value dice "yes" e bet è 1H o value contiene 1H
                    if _is_btts_yes(vv) and (bet_is_1h or _is_first_half_text(v_val_raw)):
                        _maybe_set_max(mk, "gght", odd)

            # Fine for values
        # Fine for bets
    # Fine for bookmakers

    return mk

def get_fixture_odds(session, fixture_id: int):
    return api_get(session, "odds", {"fixture": fixture_id})

# --------------------------
# Team stats (same style)
# --------------------------
def get_team_performance(session, tid: int):
    try:
        res = api_get(session, "fixtures", {"team": tid, "last": 8, "status": "FT"})
        fx = res.get("response", []) if res else []
        if not fx:
            return None
    except Exception:
        return None

    act = len(fx)
    tht, gf, gs = 0, 0, 0
    for f in fx:
        ht = f.get("score", {}).get("halftime", {}) or {}
        tht += (ht.get("home") or 0) + (ht.get("away") or 0)
        is_home = f.get("teams", {}).get("home", {}).get("id") == tid
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
# Tag logic (replica)
# --------------------------
def compute_tags(mk, s_h, s_a):
    tags = ["HT-OK"]
    h_p, h_o, h_g = False, False, False

    q1, q2 = mk.get("q1", 0), mk.get("q2", 0)
    o25, o05ht = mk.get("o25", 0), mk.get("o05ht", 0)

    if (min(q1, q2) > 0 and min(q1, q2) < 1.75) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0):
        tags.append("🐟O")
        h_p = True

    if (2.0 <= q1 <= 3.5) and (2.0 <= q2 <= 3.5) and (s_h["avg_total"] >= 1.0 and s_a["avg_total"] >= 1.0):
        tags.append("🐟G")
        h_p = True

    if (s_h["avg_total"] >= 2.0 and s_a["avg_total"] >= 2.0):
        if (o25 > 1.80) and (o05ht > 1.30):
            tags.append("⚽")
            h_o = True
        elif (o25 > 0 and o05ht > 0) and (o25 <= 1.80) and (o05ht <= 1.30):
            tags.append("🚀")
            h_o = True

    if (s_h["avg_total"] >= 1.2 and s_a["avg_total"] >= 1.2):
        tags.append("🎯PT")
        h_g = True

    if h_p and h_o and h_g:
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

    o05ht_hit = (ht_total is not None and ht_total >= 1)
    gght_hit  = (ht_h is not None and ht_a is not None and ht_h >= 1 and ht_a >= 1)
    o25_hit   = (ft_total is not None and ft_total >= 3)

    return ht_total, ft_total, o05ht_hit, gght_hit, o25_hit

# =========================================================
# UI Controls
# =========================================================
today = now_rome().date()
default_day = today - timedelta(days=1)

c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 1.4])

audit_day = c1.date_input("Data da auditare", value=default_day, max_value=today)
timezone = c2.selectbox("Timezone fixtures", ["Europe/Rome"], index=0)
max_fixtures = c3.slider("Limite match (per velocità)", min_value=50, max_value=500, value=250, step=50)
only_finished = c4.checkbox("Solo match FT", value=True)

with st.expander("⚙️ Filtri (opzionali)", expanded=False):
    excluded_countries_str = st.text_input(
        "Escludi nazioni (separate da virgola). Esempio: Thailand, Indonesia",
        value=""
    )
    league_blacklist_str = st.text_input(
        "Escludi leghe se contengono (separati da virgola). Esempio: u19, women, friendly",
        value="u19,u20,youth,women,friendly"
    )

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
            fx_res = api_get(session, "fixtures", {"date": dstr, "timezone": timezone})
            if not fx_res or not fx_res.get("response"):
                st.error("Nessun fixture trovato o errore API.")
                st.stop()

            fixtures = fx_res["response"]

            # Filtri
            rows = []
            for f in fixtures:
                status = f.get("fixture", {}).get("status", {}).get("short")
                if only_finished and status != "FT":
                    continue

                country = f.get("league", {}).get("country", "") or ""
                league_name = f.get("league", {}).get("name", "") or ""

                if excluded_countries and country in excluded_countries:
                    continue

                if any(b in (league_name.lower()) for b in league_blacklist):
                    continue

                rows.append(f)

            # Limite
            rows = rows[:max_fixtures]

            if not rows:
                st.warning("Dopo i filtri non resta nessun match.")
                st.stop()

            st.success(f"Fixture selezionati: {len(rows)}")

            # Process
            out = []
            pb = st.progress(0.0)
            for i, f in enumerate(rows, start=1):
                pb.progress(i / len(rows))

                try:
                    fid = int(f["fixture"]["id"])
                except Exception:
                    continue

                dt_iso = f["fixture"].get("date", "")
                ora = dt_iso[11:16] if dt_iso else ""
                country = f["league"].get("country", "")
                lega = f"{f['league'].get('name','')} ({country})"
                home = f["teams"].get("home", {}).get("name", "Home")
                away = f["teams"].get("away", {}).get("name", "Away")
                match = f"{home} - {away}"

                # risultati
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

                # odds + mercati
                odds_json = get_fixture_odds(session, fid)
                mk = extract_markets_from_odds_response(odds_json)

                odds_missing = (mk["q1"] == 0 and mk["q2"] == 0 and mk["o25"] == 0 and mk["o05ht"] == 0 and mk["gght"] == 0)

                # stats team
                s_h = get_team_performance(session, f["teams"].get("home", {}).get("id"))
                s_a = get_team_performance(session, f["teams"].get("away", {}).get("id"))

                # tag (solo se ho stats)
                info = ""
                if s_h and s_a:
                    info = compute_tags(mk, s_h, s_a)
                else:
                    info = "NO-STATS"

                # outcomes
                ht_total, ft_total, hit_o05ht, hit_gght, hit_o25 = compute_outcomes(ht_h, ht_a, ft_h, ft_a)

                out.append({
                    "Data": dstr,
                    "Ora": ora,
                    "Lega": lega,
                    "Match": match,
                    "Fixture_ID": fid,

                    "Q1": mk["q1"],
                    "QX": mk["qx"],
                    "Q2": mk["q2"],
                    "O2.5": mk["o25"],
                    "O0.5HT": mk["o05ht"],
                    "GGHT": mk["gght"],
                    "ODDS_MISSING": odds_missing,

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
    st.subheader("📌 KPI Generali")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Match auditati", len(df))
    k2.metric("Odds missing", int(df["ODDS_MISSING"].sum()) if not df.empty else 0)
    k3.metric("Con HT disponibile", int(df["HT_Total"].notna().sum()) if not df.empty else 0)
    k4.metric("Con FT disponibile", int(df["FT_Total"].notna().sum()) if not df.empty else 0)

    def hit_rate(mask, col):
        s = df.loc[mask, col].dropna()
        if s.empty:
            return None
        return 100.0 * (s == True).mean()

    hr_o25 = hit_rate(df["FT_Total"].notna(), "HIT_O2.5")
    hr_o05 = hit_rate(df["HT_Total"].notna(), "HIT_O0.5HT")
    hr_gg  = hit_rate(df["HT_Total"].notna(), "HIT_GGHT")

    st.write(
        f"**Hit-rate**  O2.5: `{(hr_o25 if hr_o25 is not None else 0):.1f}%`   |   "
        f"O0.5HT: `{(hr_o05 if hr_o05 is not None else 0):.1f}%`   |   "
        f"GGHT: `{(hr_gg if hr_gg is not None else 0):.1f}%`"
    )

    st.subheader("🏷️ KPI per Tag")
    tags_to_check = ["⚽⭐", "⚽", "🚀", "🎯PT", "🐟O", "🐟G"]

    rows = []
    for t in tags_to_check:
        sub = df[df["Info"].astype(str).str.contains(re.escape(t), na=False)]
        if sub.empty:
            continue
        o25 = (100.0 * (sub.loc[sub["FT_Total"].notna(), "HIT_O2.5"] == True).mean()) if sub["FT_Total"].notna().any() else None
        o05 = (100.0 * (sub.loc[sub["HT_Total"].notna(), "HIT_O0.5HT"] == True).mean()) if sub["HT_Total"].notna().any() else None
        gg  = (100.0 * (sub.loc[sub["HT_Total"].notna(), "HIT_GGHT"] == True).mean()) if sub["HT_Total"].notna().any() else None
        rows.append({
            "Tag": t,
            "N": len(sub),
            "Odds missing (N)": int(sub["ODDS_MISSING"].sum()),
            "Hit O2.5 %": None if o25 is None else round(o25, 1),
            "Hit O0.5HT %": None if o05 is None else round(o05, 1),
            "Hit GGHT %": None if gg is None else round(gg, 1),
        })

    kpi_tags = pd.DataFrame(rows).sort_values("N", ascending=False) if rows else pd.DataFrame()
    st.dataframe(kpi_tags, use_container_width=True)

    st.subheader("🔎 Dettaglio match")
    f1, f2, f3 = st.columns([1.2, 1.2, 1.6])
    flt_tag = f1.selectbox("Filtro Tag", ["(tutti)"] + tags_to_check, index=0)
    only_tagged = f2.checkbox("Solo match con almeno 1 tag", value=False)
    only_odds_missing = f3.checkbox("Solo ODDS_MISSING", value=False)

    view = df.copy()
    if flt_tag != "(tutti)":
        view = view[view["Info"].astype(str).str.contains(re.escape(flt_tag), na=False)]
    if only_tagged:
        view = view[view["Info"].astype(str).str.contains("⚽⭐|⚽|🚀|🎯PT|🐟O|🐟G", regex=True, na=False)]
    if only_odds_missing:
        view = view[view["ODDS_MISSING"] == True]

    # ordina per ora e mostra colonne principali
    show_cols = [
        "Ora", "Lega", "Match", "Info",
        "Q1", "QX", "Q2", "O2.5", "O0.5HT", "GGHT", "ODDS_MISSING",
        "HT_H", "HT_A", "FT_H", "FT_A",
        "HIT_O0.5HT", "HIT_GGHT", "HIT_O2.5",
        "Fixture_ID"
    ]
    st.dataframe(view[show_cols].sort_values("Ora"), use_container_width=True)

    st.download_button(
        "💾 Scarica CSV audit",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"retro_audit_{dstr}.csv",
        mime="text/csv"
    )

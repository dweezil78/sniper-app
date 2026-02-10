import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ----------------------------
# 1) CONFIG PAGINA
# ----------------------------
st.set_page_config(page_title="ARAB SNIPER", layout="wide")
st.title("🎯 ARAB SNIPER - Official Version")
st.markdown("Elite Selection: Drop Analysis & Regression Control")

# ----------------------------
# 2) CONFIG API
# ----------------------------
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error('Manca API_SPORTS_KEY in .streamlit/secrets.toml (es. API_SPORTS_KEY="xxxx")')
    st.stop()

HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# Top Europe + Serie C + Pacific (come tuo elenco, ripulito con set)
IDS = sorted(set([
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42,
    137, 138, 139, 810, 811, 812, 181, 203, 204, 98, 99, 101,
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104,
    283, 284, 285, 197, 198, 71, 72, 73, 128, 129, 118, 144,
    179, 180, 262, 218, 143
]))

EXCLUDE_NAME_TOKENS = ["Women", "Femminile", "U19", "U20", "U21", "U23", "Primavera"]

# ----------------------------
# 3) HELPERS
# ----------------------------
def api_get(session: requests.Session, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Wrapper requests: timeout + raise_for_status + json safe."""
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=60 * 60)  # 1 ora: SI non cambia ogni minuto
def get_spectacle_index(team_id: int) -> float:
    """Media gol totali (home+away) sulle ultime 5 partite VALIDE."""
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"team": team_id, "last": 5})
    matches = data.get("response", [])

    totals: List[int] = []
    for f in matches:
        gh = f.get("goals", {}).get("home")
        ga = f.get("goals", {}).get("away")
        if gh is None or ga is None:
            continue
        totals.append(int(gh) + int(ga))

    if not totals:
        return 0.0
    return round(sum(totals) / len(totals), 1)


@st.cache_data(ttl=15 * 60)  # 15 min: odds possono variare
def get_odds_fixture(fixture_id: int) -> Dict[str, Any]:
    with requests.Session() as s:
        return api_get(s, "odds", {"fixture": fixture_id})


def pick_icon(h_si: float, a_si: float) -> Tuple[str, bool]:
    """
    Eliminata funzione 'ghiaccio' (dead match).
    Rimane:
    - 🔥 / 💥 se SI in range "buono"
    - ⚠️ se match 'saturo' (regressione)
    - ↔️ default
    """
    is_saturated = (h_si >= 3.8 or a_si >= 3.8)

    icon = "↔️"
    if 2.0 <= h_si < 3.8 and 2.0 <= a_si < 3.8:
        icon = "🔥"
        if h_si >= 3.0 and a_si >= 3.0:
            icon = "💥"
    elif is_saturated:
        icon = "⚠️"

    return icon, is_saturated


def safe_extract_odds(odds_json: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """
    Estrae q1, qx, q2 e quota Over 2.5 in modo robusto.
    Se manca qualcosa -> 0.0
    """
    q1 = qx = q2 = q_o25 = 0.0
    o_data = odds_json.get("response") or []
    if not o_data:
        return q1, qx, q2, q_o25

    bookmakers = o_data[0].get("bookmakers") or []
    if not bookmakers:
        return q1, qx, q2, q_o25

    # prendi il primo bookmaker con bets non vuoto
    bets = None
    for bm in bookmakers:
        b = bm.get("bets") or []
        if b:
            bets = b
            break
    if not bets:
        return q1, qx, q2, q_o25

    # 1X2
    o1x2 = next((b for b in bets if b.get("id") == 1), None)
    if o1x2 and o1x2.get("values") and len(o1x2["values"]) >= 3:
        v = o1x2["values"]
        try:
            q1, qx, q2 = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
        except Exception:
            q1 = qx = q2 = 0.0

    # Over/Under 2.5 (id 5 in API-Sports)
    o25 = next((b for b in bets if b.get("id") == 5), None)
    if o25 and o25.get("values"):
        try:
            q_o25 = float(next((x["odd"] for x in o25["values"] if x.get("value") == "Over 2.5"), 0))
        except Exception:
            q_o25 = 0.0

    return q1, qx, q2, q_o25


def score_match(
    h_si: float,
    a_si: float,
    q1: float,
    q2: float,
    q_o25: float,
    is_saturated: bool
) -> Tuple[int, str, str]:
    """
    Calcolo rating + drop icon + motivi.
    Eliminata penalità 'ghiaccio/dead match'.
    """
    sc = 40
    reasons: List[str] = []

    d_icon = "↔️"

    # 1X2 favorito
    if q1 > 0 and q2 > 0:
        if q1 <= 1.80:
            d_icon = "🏠📉"
            sc += 20
            reasons.append("+20 fav casa (≤1.80)")
        elif q2 <= 1.90:
            d_icon = "🚀📉"
            sc += 25
            reasons.append("+25 fav trasf (≤1.90)")

    # Over 2.5 in range
    if 1.40 <= q_o25 <= 2.10:
        sc += 15
        reasons.append("+15 O2.5 in range")

        avg_si = (h_si + a_si) / 2
        if 2.2 <= avg_si < 3.8:
            sc += 10
            reasons.append("+10 SI medio ok")

    # Saturazione (regressione)
    if is_saturated:
        sc -= 20
        reasons.append("-20 SI saturo (regressione)")

    # clamp 0..100
    sc = int(max(0, min(100, sc)))

    if not reasons:
        reasons_txt = "—"
    else:
        reasons_txt = "; ".join(reasons)

    return sc, d_icon, reasons_txt


def style_rows(row):
    if row.Rating >= 85:
        return ['background-color: #1b4332; color: #d8f3dc; font-weight: bold'] * len(row)
    elif row.Rating >= 70:
        return ['background-color: #d4edda; color: #155724'] * len(row)
    return [''] * len(row)


# ----------------------------
# 4) UI: diagnostica quota API (opzionale)
# ----------------------------
with st.expander("📡 Diagnostica API (facoltativa)"):
    if st.button("Controlla /status"):
        try:
            with requests.Session() as s:
                st_json = api_get(s, "status", {})
            st.json(st_json)
        except Exception as e:
            st.error(f"Errore /status: {e}")

# ----------------------------
# 5) LOGICA PRINCIPALE
# ----------------------------
if st.button("🚀 AVVIA ARAB SNIPER (Tutti i match)"):
    oggi = datetime.now().strftime("%Y-%m-%d")

    try:
        with requests.Session() as session:
            data = api_get(session, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            partite = data.get("response", [])

        # Filtra match NS + leghe selezionate (o Italy) + escludi Women/Uxx
        da_analizzare = []
        for m in partite:
            league = m.get("league", {})
            fixture = m.get("fixture", {})
            status = fixture.get("status", {}).get("short")

            if status != "NS":
                continue

            league_name = league.get("name", "")
            if any(x in league_name for x in EXCLUDE_NAME_TOKENS):
                continue

            if league.get("id") in IDS or league.get("country") == "Italy":
                da_analizzare.append(m)

        if not da_analizzare:
            st.warning("Nessun match rilevato per i parametri Arab Sniper.")
            st.stop()

        results = []
        bar = st.progress(0)
        status_box = st.empty()

        for i, m in enumerate(da_analizzare):
            f_id = m["fixture"]["id"]
            h_id = m["teams"]["home"]["id"]
            a_id = m["teams"]["away"]["id"]
            h_n = m["teams"]["home"]["name"]
            a_n = m["teams"]["away"]["name"]

            status_box.text(f"Puntando il mirino: {h_n} - {a_n}")

            # SI (cached)
            h_si = get_spectacle_index(h_id)
            a_si = get_spectacle_index(a_id)
            icon, is_saturated = pick_icon(h_si, a_si)

            # Odds (cached 15 min)
            q1 = qx = q2 = q_o25 = 0.0
            try:
                odds_json = get_odds_fixture(f_id)
                q1, qx, q2, q_o25 = safe_extract_odds(odds_json)
            except Exception:
                # se odds falliscono, restano 0.0 e rating verrà calcolato più neutro
                pass

            rating, drop_icon, reasons = score_match(
                h_si=h_si,
                a_si=a_si,
                q1=q1,
                q2=q2,
                q_o25=q_o25,
                is_saturated=is_saturated
            )

            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Lega": m["league"]["name"],
                "Match": f"{icon} {h_n} - {a_n}",
                "S.I. (H|A)": f"{h_si} | {a_si}",
                "1X2": f"{q1}|{qx}|{q2}" if q1 > 0 else "N.D.",
                "Drop": drop_icon,
                "O2.5": q_o25 if q_o25 > 0 else None,
                "Rating": rating,
                "Motivi": reasons
            })

            bar.progress((i + 1) / len(da_analizzare))

        df = pd.DataFrame(results).sort_values(by="Rating", ascending=False)

        st.dataframe(
            df.style.apply(style_rows, axis=1),
            use_container_width=True,
            column_config={
                "Rating": st.column_config.ProgressColumn("Sniper Rating", format="%d", min_value=0, max_value=100),
                "Ora": "⏰",
                "O2.5": st.column_config.NumberColumn("Quota O2.5", format="%.2f"),
                "Motivi": st.column_config.TextColumn("Perché (breakdown)")
            }
        )

    except requests.HTTPError as e:
        st.error(f"Errore HTTP: {e}")
    except Exception as e:
        st.error(f"Errore: {e}")

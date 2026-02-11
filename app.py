import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Tuple

# ============================
# 1) CONFIG PAGINA
# ============================
st.set_page_config(page_title="ARAB SNIPER V14", layout="wide")
st.title("🎯 ARAB SNIPER V14 - Dual Engine (O2.5 + BTTS)")
st.markdown("Due motori separati: **Over 2.5** (partite aperte) e **BTTS** (gol da entrambe).")

# ============================
# 2) CONFIG API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("Manca API_SPORTS_KEY nei Secrets")
    st.stop()

HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

IDS = sorted(set([
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42,
    137, 138, 139, 810, 811, 812, 181, 203, 204, 98, 99, 101,
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104,
    283, 284, 285, 197, 198, 71, 72, 73, 128, 129, 118, 144,
    179, 180, 262, 218, 143
]))

EXCLUDE_NAME_TOKENS = ["Women", "Femminile", "U19", "U20", "U21", "U23", "Primavera"]

# ============================
# 3) API HELPERS + CACHE
# ============================
def api_get(session: requests.Session, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600)
def get_spectacle_index(team_id: int) -> float:
    """Media gol totali (home+away) ultime 5 partite con goals validi."""
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"team": team_id, "last": 5})
    totals: List[int] = []
    for f in data.get("response", []):
        gh = f.get("goals", {}).get("home")
        ga = f.get("goals", {}).get("away")
        if gh is None or ga is None:
            continue
        totals.append(int(gh) + int(ga))
    return round(sum(totals) / len(totals), 1) if totals else 0.0

@st.cache_data(ttl=3600)
def team_scored_last_match(team_id: int) -> bool:
    """True se la squadra ha segnato almeno 1 goal nell'ultima partita (last=1)."""
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"team": team_id, "last": 1})
        r = data.get("response", [])
        if not r:
            return True  # neutro
        is_home = r[0]["teams"]["home"]["id"] == team_id
        goals = r[0]["goals"]["home"] if is_home else r[0]["goals"]["away"]
        return (goals is not None and int(goals) > 0)
    except Exception:
        return True

@st.cache_data(ttl=900)
def get_odds_fixture(fixture_id: int) -> Dict[str, Any]:
    with requests.Session() as s:
        return api_get(s, "odds", {"fixture": fixture_id})

def safe_extract_odds(odds_json: Dict[str, Any]) -> Tuple[float, float, float, float, bool]:
    """Ritorna q1,qx,q2,q_o25,odds_ok."""
    q1 = qx = q2 = q_o25 = 0.0
    r = odds_json.get("response", []) or []
    if not r:
        return q1, qx, q2, q_o25, False

    bookmakers = r[0].get("bookmakers", []) or []
    if not bookmakers:
        return q1, qx, q2, q_o25, False

    bets = None
    for bm in bookmakers:
        b = bm.get("bets", []) or []
        if b:
            bets = b
            break
    if not bets:
        return q1, qx, q2, q_o25, False

    # 1X2
    o1x2 = next((b for b in bets if b.get("id") == 1), None)
    if o1x2 and o1x2.get("values") and len(o1x2["values"]) >= 3:
        try:
            v = o1x2["values"]
            q1 = float(v[0]["odd"]); qx = float(v[1]["odd"]); q2 = float(v[2]["odd"])
        except Exception:
            q1 = qx = q2 = 0.0

    # Over 2.5
    o25 = next((b for b in bets if b.get("id") == 5), None)
    if o25 and o25.get("values"):
        try:
            q_o25 = float(next(v["odd"] for v in o25["values"] if v.get("value") == "Over 2.5"))
        except Exception:
            q_o25 = 0.0

    odds_ok = (q_o25 > 0 or q1 > 0 or q2 > 0)
    return q1, qx, q2, q_o25, odds_ok

# ============================
# 4) DUAL ENGINE (O2.5 + BTTS)
# ============================
def score_over25(h_si: float, a_si: float, q1: float, q2: float, q_o25: float) -> Tuple[int, List[str], bool]:
    """
    Motore Over2.5: favorisce partite aperte + equilibrio.
    - Fame di goal NON usata (dal test risulta dannosa per O2.5).
    - Penalizza favorito troppo forte (match controllato).
    """
    sc = 40
    details: List[str] = []

    # Trap: O2.5 troppo basso
    if 0 < q_o25 < 1.50:
        return 0, ["⚠️ TRAP <1.50"], True

    # Quota O2.5 (peso ridotto)
    if 1.80 <= q_o25 <= 2.10:
        sc += 12; details.append("🎯 +12 O2.5 sweet")
    elif 2.10 < q_o25 <= 2.40:
        sc += 8; details.append("🎯 +8 O2.5 value")
    elif 1.50 <= q_o25 < 1.80:
        sc += 3; details.append("🎯 +3 O2.5 low")
    elif q_o25 == 0:
        details.append("🧩 O2.5 N.D.")

    # SI medio (range più stretto)
    avg_si = (h_si + a_si) / 2
    if 2.4 <= avg_si <= 3.4:
        sc += 12; details.append("🔥 +12 SI ok")
    elif avg_si < 2.0:
        sc -= 10; details.append("🧊 -10 SI basso")
    elif avg_si >= 3.8:
        sc -= 15; details.append("⚠️ -15 saturazione")

    # Anti-1-0: favorito troppo forte -> rischio match controllato
    if q1 > 0 and q2 > 0:
        if q1 <= 1.60 or q2 <= 1.60:
            sc -= 10; details.append("🧱 -10 fav troppo forte")
        # equilibrio (entrambi non favoriti estremi)
        if q1 >= 2.20 and q2 >= 2.20:
            sc += 6; details.append("⚖️ +6 equilibrio")

    sc = int(max(0, min(100, sc)))
    return sc, details, False

def score_btts(h_si: float, a_si: float, q_o25: float, h_scored_last: bool, a_scored_last: bool) -> Tuple[int, List[str], bool]:
    """
    Motore BTTS:
    - Fame: se una squadra NON ha segnato nell'ultima -> bonus (reazione).
    - Usa SI medio ma più permissivo.
    """
    sc = 40
    details: List[str] = []

    # Trap: spesso O2.5 troppo basso = mercato vede match chiuso
    if 0 < q_o25 < 1.50:
        return 0, ["⚠️ TRAP <1.50"], True

    # Quote over come filtro soft (BTTS spesso lavora bene con over non troppo basso)
    if q_o25 >= 1.70:
        sc += 6; details.append("🎯 +6 O2.5>=1.70")
    elif 0 < q_o25 < 1.70:
        sc -= 4; details.append("🎯 -4 O2.5 basso")
    elif q_o25 == 0:
        details.append("🧩 O2.5 N.D.")

    avg_si = (h_si + a_si) / 2
    if 2.0 <= avg_si <= 3.2:
        sc += 10; details.append("🔥 +10 SI ok")
    elif avg_si < 1.8:
        sc -= 12; details.append("🧊 -12 SI troppo basso")
    elif avg_si >= 3.8:
        sc -= 8; details.append("⚠️ -8 saturazione")

    # Fame (in BTTS ha senso): se non ha segnato -> bonus
    h_fame = not h_scored_last
    a_fame = not a_scored_last
    if h_fame and a_fame:
        sc += 18; details.append("⚽ +18 fame doppia")
    elif h_fame or a_fame:
        sc += 12; details.append("⚽ +12 fame singola")

    sc = int(max(0, min(100, sc)))
    return sc, details, False

def make_cell(rating: int, details: List[str]) -> str:
    if rating >= 85:
        bg, txt = "#1b4332", "#d8f3dc"
    elif rating >= 70:
        bg, txt = "#d4edda", "#155724"
    else:
        bg, txt = "transparent", "inherit"

    res = f"<div style='background:{bg};color:{txt};padding:8px;border-radius:6px;font-weight:800'>{rating}</div>"
    if details:
        res += "".join([f"<div style='font-size:0.80em;margin-top:3px;'>• {d}</div>" for d in details])
    return res

# ============================
# 5) UI
# ============================
st.sidebar.header("⚙️ Filtri")
target = st.sidebar.radio("Modalità", ["Over 2.5", "BTTS"], index=0)
min_rating = st.sidebar.slider("Rating minimo", 0, 85, 60)
show_debug = st.sidebar.checkbox("Mostra Debug", value=True)

# ============================
# 6) MAIN
# ============================
if st.button("🚀 AVVIA ARAB SNIPER V14"):
    oggi = datetime.now().strftime("%Y-%m-%d")

    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})

        all_resp = data.get("response", []) or []
        fixtures = [
            m for m in all_resp
            if m.get("fixture", {}).get("status", {}).get("short") == "NS"
            and not any(x in m.get("league", {}).get("name", "") for x in EXCLUDE_NAME_TOKENS)
            and (m.get("league", {}).get("id") in IDS or m.get("league", {}).get("country") == "Italy")
        ]

        if not fixtures:
            st.info("Nessun match trovato.")
            st.stop()

        progress_bar = st.progress(0)
        status_text = st.empty()

        results = []
        cnt_trap = 0
        cnt_low = 0
        cnt_odds_nd = 0

        for i, m in enumerate(fixtures):
            h_id = m["teams"]["home"]["id"]
            a_id = m["teams"]["away"]["id"]
            f_id = m["fixture"]["id"]
            h_n = m["teams"]["home"]["name"]
            a_n = m["teams"]["away"]["name"]

            status_text.text(f"Analisi {i+1}/{len(fixtures)}: {h_n} - {a_n}")
            progress_bar.progress((i + 1) / len(fixtures))

            q1 = qx = q2 = q_o25 = 0.0
            odds_ok = False
            try:
                odds_json = get_odds_fixture(f_id)
                q1, qx, q2, q_o25, odds_ok = safe_extract_odds(odds_json)
            except Exception:
                odds_ok = False

            if not odds_ok:
                cnt_odds_nd += 1

            h_si = get_spectacle_index(h_id)
            a_si = get_spectacle_index(a_id)

            if target == "Over 2.5":
                rating, details, trap = score_over25(h_si, a_si, q1, q2, q_o25)
            else:
                h_scored = team_scored_last_match(h_id)
                a_scored = team_scored_last_match(a_id)
                rating, details, trap = score_btts(h_si, a_si, q_o25, h_scored, a_scored)

            if trap:
                cnt_trap += 1
                continue

            if rating < min_rating:
                cnt_low += 1
                continue

            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Lega": m["league"]["name"],
                "Match": f"{h_n} - {a_n}",
                "S.I.": f"{h_si} | {a_si}",
                "O2.5": f"{q_o25:.2f}" if q_o25 > 0 else "",
                "1X2": f"{q1:.2f}|{qx:.2f}|{q2:.2f}" if q1 > 0 else "N.D.",
                "Rating": make_cell(rating, details),
                "R_Num": rating
            })

        status_text.empty()
        progress_bar.empty()

        if show_debug:
            st.write({
                "modalità": target,
                "fixtures_totali_api": len(all_resp),
                "fixtures_filtrate": len(fixtures),
                "risultati_finali": len(results),
                "scartati_trap": cnt_trap,
                "scartati_sotto_min": cnt_low,
                "odds_non_disponibili": cnt_odds_nd,
                "min_rating": min_rating
            })

        if not results:
            st.info("Nessun match trovato con i filtri attuali (prova ad abbassare il rating minimo).")
            st.stop()

        df = pd.DataFrame(results).sort_values("R_Num", ascending=False).drop(columns=["R_Num"])

        st.markdown(
            """
            <style>
              table { width: 100%; border-collapse: collapse; background-color: #0e1117; color: white; }
              th, td { padding: 12px; border: 1px solid #444; vertical-align: top; }
              th { background: #1a1c23; position: sticky; top: 0; }
            </style>
            """,
            unsafe_allow_html=True
        )
        st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Errore: {e}")

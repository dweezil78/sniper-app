import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Tuple

# ----------------------------
# 1) CONFIG PAGINA
# ----------------------------
st.set_page_config(page_title="ARAB SNIPER", layout="wide")
st.title("🎯 ARAB SNIPER - Goal Hunter Version")
st.markdown("Elite Selection: Market Drop & 'Fame di Goal' Analysis")

# ----------------------------
# 2) CONFIG API
# ----------------------------
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("Manca API_SPORTS_KEY nei Secrets di Streamlit")
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

# ----------------------------
# 3) HELPERS & CACHING
# ----------------------------
def api_get(session: requests.Session, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600)
def get_spectacle_index(team_id: int) -> float:
    """Media gol totali (home+away) su ultime 5 partite VALIDE."""
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"team": team_id, "last": 5})
    matches = data.get("response", [])

    totals: List[int] = []
    for f in matches:
        gh = f.get("goals", {}).get("home")
        ga = f.get("goals", {}).get("away")
        if gh is not None and ga is not None:
            totals.append(int(gh) + int(ga))

    return round(sum(totals) / len(totals), 1) if totals else 0.0

@st.cache_data(ttl=3600)
def check_last_match_no_goal(team_id: int) -> bool:
    """True se la squadra NON ha segnato nell’ultima partita giocata."""
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"team": team_id, "last": 1})
        match = data.get("response", [])
        if not match:
            return False

        is_home = match[0]["teams"]["home"]["id"] == team_id
        goals = match[0]["goals"]["home"] if is_home else match[0]["goals"]["away"]
        return goals == 0
    except Exception:
        return False

@st.cache_data(ttl=900)
def get_odds_fixture(fixture_id: int) -> Dict[str, Any]:
    with requests.Session() as s:
        return api_get(s, "odds", {"fixture": fixture_id})

def safe_extract_odds(odds_json: Dict[str, Any]) -> Tuple[float, float, float, float]:
    q1 = qx = q2 = q_o25 = 0.0
    o_data = odds_json.get("response") or []
    if not o_data:
        return q1, qx, q2, q_o25

    bookmakers = o_data[0].get("bookmakers") or []
    if not bookmakers:
        return q1, qx, q2, q_o25

    bets = None
    for bm in bookmakers:
        b = bm.get("bets") or []
        if b:
            bets = b
            break
    if not bets:
        return q1, qx, q2, q_o25

    o1x2 = next((b for b in bets if b.get("id") == 1), None)
    if o1x2 and o1x2.get("values") and len(o1x2["values"]) >= 3:
        v = o1x2["values"]
        try:
            q1, qx, q2 = float(v[0]["odd"]), float(v[1]["odd"]), float(v[2]["odd"])
        except Exception:
            q1 = qx = q2 = 0.0

    o25 = next((b for b in bets if b.get("id") == 5), None)
    if o25 and o25.get("values"):
        try:
            q_o25 = float(next((x["odd"] for x in o25["values"] if x.get("value") == "Over 2.5"), 0))
        except Exception:
            q_o25 = 0.0

    return q1, qx, q2, q_o25

# ----------------------------
# 4) LOGICA RATING (Goal Hunter)
# ----------------------------
def score_match(
    h_si: float,
    a_si: float,
    q1: float,
    q2: float,
    q_o25: float,
    h_fame: bool,
    a_fame: bool
) -> Tuple[int, str, List[str], bool]:
    """
    Ritorna:
    - rating_num (0..100)
    - drop_icon
    - details (lista)
    - trap (bool)
    """
    sc = 40
    details: List[str] = []
    d_icon = "↔️"

    # TRAPPOLA: quota over troppo bassa
    is_trap = 0 < q_o25 < 1.50
    if is_trap:
        # non faccio calcoli inutili: segno e stoppo
        return 0, "🚫", ["⚠️ TRAPPOLA <1.50"], True

    # DROP / favorito
    if q1 > 0 and q2 > 0:
        if q1 <= 1.80:
            d_icon = "🏠📉"
            sc += 20
            details.append("🏠 +20 (fav casa)")
        elif q2 <= 1.90:
            d_icon = "🚀📉"
            sc += 25
            details.append("🚀 +25 (fav trasf)")

    # OVER 2.5 value
    if 1.50 <= q_o25 <= 2.15:
        sc += 15
        details.append("🎯 +15 (O2.5 value)")
        avg_si = (h_si + a_si) / 2
        if 2.2 <= avg_si < 3.8:
            sc += 10
            details.append("🔥 +10 (SI medio ok)")

    # FAME DI GOAL (sblocco)
    if h_fame or a_fame:
        sc += 15
        details.append("⚽ +15 (sblocco goal)")

    # Saturazione
    if h_si >= 3.8 or a_si >= 3.8:
        sc -= 20
        details.append("⚠️ -20 (saturazione)")

    sc = int(max(0, min(100, sc)))
    return sc, d_icon, details, False

def style_rows(row):
    # usa Rating_Num per colorare correttamente
    r = row.get("Rating_Num", 0)
    if r >= 85:
        return ['background-color: #1b4332; color: #d8f3dc; font-weight: bold'] * len(row)
    elif r >= 70:
        return ['background-color: #d4edda; color: #155724'] * len(row)
    return [''] * len(row)

def make_rating_cell(rating_num: int, details: List[str]) -> str:
    """Cella multilinea: rating + bullet breakdown."""
    if not details:
        return str(rating_num)
    bullets = "\n".join([f"• {d}" for d in details])
    return f"{rating_num}\n{bullets}"

# ----------------------------
# 5) UI
# ----------------------------
st.sidebar.header("⚙️ Filtri Selezione")
min_rating = st.sidebar.slider("Rating Minimo", 0, 85, 60)
hide_traps = st.sidebar.checkbox("Nascondi Quote Trappola (<1.50)", value=True)

if st.button("🚀 AVVIA ARAB SNIPER"):
    oggi = datetime.now().strftime("%Y-%m-%d")

    try:
        with requests.Session() as session:
            data = api_get(session, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
            partite = data.get("response", [])

        da_analizzare = [
            m for m in partite
            if m.get("fixture", {}).get("status", {}).get("short") == "NS"
            and not any(x in m.get("league", {}).get("name", "") for x in EXCLUDE_NAME_TOKENS)
            and (m.get("league", {}).get("id") in IDS or m.get("league", {}).get("country") == "Italy")
        ]

        if not da_analizzare:
            st.warning("Nessun match rilevato.")
            st.stop()

        results = []
        bar = st.progress(0)
        status_box = st.empty()

        for i, m in enumerate(da_analizzare):
            fixture_id = m["fixture"]["id"]
            h_id, a_id = m["teams"]["home"]["id"], m["teams"]["away"]["id"]
            h_n, a_n = m["teams"]["home"]["name"], m["teams"]["away"]["name"]
            status_box.text(f"Puntando il mirino: {h_n} - {a_n}")

            h_si = get_spectacle_index(h_id)
            a_si = get_spectacle_index(a_id)

            # Fame di goal (bonus)
            h_fame = check_last_match_no_goal(h_id)
            a_fame = check_last_match_no_goal(a_id)

            # Icona match (solo estetica)
            icon = "⚽" if (h_fame or a_fame) else ("🔥" if 2.2 <= (h_si + a_si) / 2 < 3.8 else "↔️")
            if h_si >= 3.8 or a_si >= 3.8:
                icon = "⚠️"

            q1 = qx = q2 = q_o25 = 0.0
            try:
                odds_json = get_odds_fixture(fixture_id)
                q1, qx, q2, q_o25 = safe_extract_odds(odds_json)
            except Exception:
                pass

            rating_num, d_icon, details, trap = score_match(h_si, a_si, q1, q2, q_o25, h_fame, a_fame)

            # Regola inclusione:
            # - se è trap e hide_traps=True -> scarta
            # - se è trap e hide_traps=False -> MOSTRA SEMPRE (anche se rating basso)
            # - altrimenti applica filtro min_rating
            if trap:
                if hide_traps:
                    bar.progress((i + 1) / len(da_analizzare))
                    continue
                include = True
            else:
                include = rating_num >= min_rating

            if include:
                results.append({
                    "Ora": m["fixture"]["date"][11:16],
                    "Lega": m["league"]["name"],
                    "Match": f"{icon} {h_n} - {a_n}",
                    "S.I. (H|A)": f"{h_si} | {a_si}",
                    "Drop": d_icon,
                    "O2.5": q_o25 if q_o25 > 0 else None,
                    "Rating": make_rating_cell(rating_num, details),  # <-- rating + breakdown in cella
                    "Rating_Num": rating_num                           # <-- solo per sorting/styling
                })

            bar.progress((i + 1) / len(da_analizzare))

        if results:
            df = pd.DataFrame(results).sort_values(by="Rating_Num", ascending=False)
            df_show = df.drop(columns=["Rating_Num"])

            # --- al posto di st.dataframe(...) ---
df = pd.DataFrame(results).sort_values(by="Rating_Num", ascending=False)

# mostra senza la colonna tecnica
df_show = df.drop(columns=["Rating_Num"]).copy()

# converti i newline in <br> per l'HTML
for col in ["Rating", "Match", "S.I. (H|A)"]:
    if col in df_show.columns:
        df_show[col] = df_show[col].astype(str).str.replace("\n", "<br>", regex=False)

html = df_show.to_html(escape=False, index=False)

st.markdown(
    """
    <style>
      table { width: 100%; border-collapse: collapse; }
      th, td { padding: 8px; border: 1px solid #33333322; vertical-align: top; }
      td { white-space: normal !important; word-wrap: break-word; }
      th { position: sticky; top: 0; background: #0e1117; color: #ffffff; }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(html, unsafe_allow_html=True)

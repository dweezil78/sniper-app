import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

# Timezone robust (Streamlit Cloud spesso è UTC)
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

# ============================
# 1) CONFIG PAGINA
# ============================
st.set_page_config(page_title="ARAB SNIPER V13.1", layout="wide")
st.title("🎯 ARAB SNIPER V13.1 - Elite Pressure (C)")
st.markdown("Market Efficiency, Goal Hunger & Offensive Pressure (Home+Away Avg)")

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
    """Media gol totali (home+away) su ultime 5 partite con goals validi."""
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
def check_last_match_no_goal(team_id: int) -> bool:
    """True se la squadra NON ha segnato nell'ultima partita (last=1)."""
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"team": team_id, "last": 1})
        r = data.get("response", [])
        if not r:
            return False
        is_home = r[0]["teams"]["home"]["id"] == team_id
        goals = r[0]["goals"]["home"] if is_home else r[0]["goals"]["away"]
        return goals == 0
    except Exception:
        return False

@st.cache_data(ttl=900)
def get_odds_fixture(fixture_id: int) -> Dict[str, Any]:
    with requests.Session() as s:
        return api_get(s, "odds", {"fixture": fixture_id})

def safe_extract_odds(odds_json: Dict[str, Any]) -> Tuple[float, float, float, float, bool]:
    """
    Ritorna q1,qx,q2,q_o25, odds_ok
    odds_ok=False se non ci sono odds affidabili.
    """
    q1 = qx = q2 = q_o25 = 0.0
    r = odds_json.get("response", [])
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
            q1 = float(v[0]["odd"])
            qx = float(v[1]["odd"])
            q2 = float(v[2]["odd"])
        except Exception:
            q1 = qx = q2 = 0.0

    # Over 2.5
    o25 = next((b for b in bets if b.get("id") == 5), None)
    if o25 and o25.get("values"):
        try:
            q_o25 = float(next(v["odd"] for v in o25["values"] if v.get("value") == "Over 2.5"))
        except Exception:
            q_o25 = 0.0

    odds_ok = (q1 > 0 or q2 > 0 or q_o25 > 0)
    return q1, qx, q2, q_o25, odds_ok

# ---- PRESSURE (C) ----
@st.cache_data(ttl=6 * 3600)
def get_last_ft_fixture_ids(team_id: int, n: int = 5) -> List[int]:
    """Lista fixture_id delle ultime N partite FT per team."""
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"team": team_id, "last": n, "status": "FT"})
    out: List[int] = []
    for f in data.get("response", []):
        try:
            out.append(int(f["fixture"]["id"]))
        except Exception:
            pass
    return out

@st.cache_data(ttl=24 * 3600)
def get_fixture_stats_raw(fixture_id: int) -> List[Dict[str, Any]]:
    """
    Ritorna la response grezza di /fixtures/statistics?fixture=...
    Cache 24h: stesso fixture non cambia più.
    """
    with requests.Session() as s:
        data = api_get(s, "fixtures/statistics", {"fixture": fixture_id})
    return data.get("response", []) or []

def extract_team_pressure_from_fixture_stats(raw: List[Dict[str, Any]], team_id: int) -> Tuple[int, int]:
    """
    raw: lista di 2 item (home+away) spesso, ognuno con statistics.
    Ritorna (total_shots, corners) per il team richiesto, 0 se non trovati.
    """
    for item in raw:
        try:
            if int(item["team"]["id"]) != int(team_id):
                continue
            stats_list = item.get("statistics", []) or []
            stats_map = {s.get("type"): s.get("value") for s in stats_list}
            shots = stats_map.get("Total Shots", 0) or 0
            corners = stats_map.get("Corner Kicks", 0) or 0
            return int(shots), int(corners)
        except Exception:
            continue
    return 0, 0

def get_pressure_avg(team_id: int, n: int = 5) -> Tuple[float, float, int]:
    """
    Media tiri + media corner sulle ultime N FT.
    Ritorna (avg_shots, avg_corners, sample_size).
    """
    fixture_ids = get_last_ft_fixture_ids(team_id, n=n)
    if not fixture_ids:
        return 0.0, 0.0, 0

    shots_list: List[int] = []
    corners_list: List[int] = []

    for fid in fixture_ids:
        raw = get_fixture_stats_raw(fid)
        shots, corners = extract_team_pressure_from_fixture_stats(raw, team_id)
        # accetta solo se almeno uno è presente (evita falsi 0)
        if shots == 0 and corners == 0:
            continue
        shots_list.append(shots)
        corners_list.append(corners)

    if not shots_list:
        return 0.0, 0.0, 0

    avg_shots = sum(shots_list) / len(shots_list)
    avg_corners = sum(corners_list) / len(corners_list)
    return round(avg_shots, 1), round(avg_corners, 1), len(shots_list)

# ============================
# 4) RATING ENGINE V13.1 (C)
# ============================
def make_rating_cell(rating: int, details: List[str]) -> str:
    if rating >= 100:
        bg, txt = "#ff4b4b", "white"
    elif rating >= 85:
        bg, txt = "#1b4332", "#d8f3dc"
    elif rating >= 70:
        bg, txt = "#d4edda", "#155724"
    else:
        bg, txt = "transparent", "inherit"

    style = f"background-color: {bg}; color: {txt}; padding: 10px; border-radius: 6px; font-weight: 800;"
    res = f"<div style='{style}'>{rating}</div>"
    if details:
        res += "".join([f"<div style='font-size: 0.80em; margin-top: 3px;'>• {d}</div>" for d in details])
    return res

# ============================
# 5) UI
# ============================
st.sidebar.header("⚙️ Filtri Elite")
min_rating = st.sidebar.slider("Rating minimo", 0, 85, 60)
show_debug = st.sidebar.checkbox("Mostra Debug", value=True)

# ============================
# 6) MAIN
# ============================
if st.button("🚀 AVVIA ARAB SNIPER V13.1"):
    oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")

    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})

        all_resp = data.get("response", []) or []

        # Filtri base
        fixtures = [
            m for m in all_resp
            if m.get("fixture", {}).get("status", {}).get("short") == "NS"
            and not any(x in m.get("league", {}).get("name", "") for x in EXCLUDE_NAME_TOKENS)
            and (m.get("league", {}).get("id") in IDS or m.get("league", {}).get("country") == "Italy")
        ]

        if not fixtures:
            st.info("Nessun match trovato con i filtri attuali.")
            if show_debug:
                st.write({"oggi": oggi, "fixtures_api_totali": len(all_resp), "fixtures_filtrate": 0})
            st.stop()

        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        # DEBUG counters
        cnt_trap = 0
        cnt_odds_nd = 0
        cnt_scartati_rating = 0
        cnt_pressure_na = 0

        for i, m in enumerate(fixtures):
            h_id = m["teams"]["home"]["id"]
            a_id = m["teams"]["away"]["id"]
            f_id = m["fixture"]["id"]
            h_n = m["teams"]["home"]["name"]
            a_n = m["teams"]["away"]["name"]

            status_text.text(f"Analisi {i+1}/{len(fixtures)}: {h_n} - {a_n}")
            progress_bar.progress((i + 1) / len(fixtures))

            # Odds
            q1 = qx = q2 = q_o25 = 0.0
            odds_ok = False
            try:
                odds_json = get_odds_fixture(f_id)
                q1, qx, q2, q_o25, odds_ok = safe_extract_odds(odds_json)
            except Exception:
                odds_ok = False

            if not odds_ok:
                cnt_odds_nd += 1

            # TRAP
            if 0 < q_o25 < 1.50:
                cnt_trap += 1
                continue

            sc = 40
            details: List[str] = []

            # 1) QUOTA O2.5 (come tuo)
            if 1.80 <= q_o25 <= 2.10:
                sc += 25
                details.append("🎯 +25 Sweet Spot")
            elif 2.11 <= q_o25 <= 2.50:
                sc += 15
                details.append("🎯 +15 Value Zone")
            elif 1.50 <= q_o25 <= 1.79:
                sc += 5
                details.append("🎯 +5 Low Odd")
            elif q_o25 == 0:
                details.append("🧩 O2.5 N.D.")

            # 2) S.I. & Fame
            h_si = get_spectacle_index(h_id)
            a_si = get_spectacle_index(a_id)
            h_fame = check_last_match_no_goal(h_id)
            a_fame = check_last_match_no_goal(a_id)

            if 2.2 <= (h_si + a_si) / 2 < 3.8:
                sc += 10
                details.append("🔥 +10 SI Medio")

            if h_fame or a_fame:
                sc += 15
                details.append("⚽ +15 Sblocco Goal")

            if h_si >= 3.8 or a_si >= 3.8:
                sc -= 20
                details.append("⚠️ -20 Saturazione")

            # 3) PRESSIONE OFFENSIVA (C) -> entrambe le squadre e media
            # Applica solo se base >=55 (come tua idea)
            if sc >= 55 and q_o25 >= 1.50:
                h_sh, h_co, h_nsample = get_pressure_avg(h_id, n=5)
                a_sh, a_co, a_nsample = get_pressure_avg(a_id, n=5)

                # richiedi almeno 3 sample per affidabilità
                if h_nsample < 3 or a_nsample < 3:
                    cnt_pressure_na += 1
                    details.append("📉 Pressure N/A (sample <3)")
                else:
                    avg_shots = round((h_sh + a_sh) / 2, 1)
                    avg_corners = round((h_co + a_co) / 2, 1)

                    # soglie come le tue (ma applicate alla media)
                    if avg_shots > 12.5:
                        sc += 10
                        details.append(f"🏹 +10 Tiri AVG ({avg_shots})")
                    if avg_corners > 5.5:
                        sc += 10
                        details.append(f"🚩 +10 Corner AVG ({avg_corners})")

            sc = int(max(0, min(100, sc)))

            if sc < min_rating:
                cnt_scartati_rating += 1
                continue

            results.append({
                "Ora": m["fixture"]["date"][11:16],
                "Lega": m["league"]["name"],
                "Match": f"{h_n} - {a_n}",
                "S.I.": f"{h_si} | {a_si}",
                "O2.5": f"{q_o25:.2f}" if q_o25 > 0 else "",
                "Rating": make_rating_cell(sc, details),
                "R_Num": sc
            })

        status_text.empty()
        progress_bar.empty()

        if show_debug:
            st.write({
                "oggi": oggi,
                "fixtures_api_totali": len(all_resp),
                "fixtures_filtrate": len(fixtures),
                "risultati_finali": len(results),
                "scartati_trappola": cnt_trap,
                "odds_non_disponibili": cnt_odds_nd,
                "scartati_per_min_rating": cnt_scartati_rating,
                "pressure_na_sample": cnt_pressure_na,
                "min_rating": min_rating,
            })

        if results:
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
        else:
            st.info("Nessun match Elite trovato (prova ad abbassare il Rating minimo o controlla Debug).")

    except Exception as e:
        st.error(f"Errore: {e}")

import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import base64
from typing import Any, Dict, List, Tuple

# ============================
# TIMEZONE
# ============================
try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = None

# ============================
# 1) CONFIG PAGINA E STILI
# ============================
st.set_page_config(page_title="ARAB SNIPER V15 - Clean Scanner", layout="wide")
st.title("🎯 ARAB SNIPER V15 - Clean Scanner (No Rating)")
st.caption("Over 2.5 FT + Over 1.5 HT con filtri, TRAP, inversione e snapshot quote (drop reale).")

def apply_custom_css():
    st.markdown("""
        <style>
            .main { background-color: #0e1117; }
            table { width: 100%; border-collapse: collapse; color: #ffffff !important; margin-bottom: 20px; font-family: 'Segoe UI', sans-serif; }
            th { background-color: #1a1c23; color: #00e5ff; padding: 15px; text-align: center; border: 1px solid #444; font-size: 0.9em; text-transform: uppercase; }
            td { padding: 12px; border: 1px solid #333; vertical-align: middle; text-align: center; color: #ffffff !important; }
            .match-cell { text-align: left !important; min-width: 320px; color: #ffffff !important; }
            .badge { padding: 8px 10px; border-radius: 8px; font-weight: 900; display: inline-block; color: #ffffff !important; }
            .details-list { font-size: 0.78em; margin-top: 8px; line-height: 1.35; opacity: 0.92; text-align: left; color: #ffffff !important; }
            .drop-tag { color: #ffcc00; font-size: 0.85em; font-weight: 900; margin-top: 4px; display: block; }
            .stats-tag { color: #00ffcc; font-size: 0.82em; opacity: 0.92; display:block; margin-top: 4px; }
            .mini { font-size: 0.88em; opacity: 0.95; }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# ============================
# 2) CONFIG API
# ============================
API_KEY = st.secrets.get("API_SPORTS_KEY")
if not API_KEY:
    st.error("Manca API_SPORTS_KEY nei Secrets.")
    st.stop()

HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_get(session: requests.Session, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://{HOST}/{path}"
    r = session.get(url, headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def _norm(s: str) -> str:
    return (s or "").strip().lower()

# ============================
# 3) FILTRI CAMPIONATI
# ============================
EXCLUDE_NAME_TOKENS = [
    "Women", "Womens", "Femminile", "Fem.", "Femenina",
    "U19", "U-19", "U20", "U-20", "U21", "U-21", "U23", "U-23",
    "Primavera", "Youth", "Reserve", "Reserves", "B Team", "B-team", "II", "II."
]

BANNED_COUNTRIES = set([
    # Africa (ampio)
    "Algeria","Angola","Benin","Botswana","Burkina Faso","Burundi","Cameroon","Cape Verde","Central African Republic",
    "Chad","Comoros","Congo","DR Congo","Democratic Republic of the Congo","Djibouti","Egypt","Equatorial Guinea","Eritrea",
    "Eswatini","Ethiopia","Gabon","Gambia","Ghana","Guinea","Guinea-Bissau","Ivory Coast","Côte d'Ivoire","Kenya","Lesotho",
    "Liberia","Libya","Madagascar","Malawi","Mali","Mauritania","Mauritius","Morocco","Mozambique","Namibia","Niger","Nigeria",
    "Rwanda","São Tomé and Príncipe","Sao Tome and Principe","Senegal","Seychelles","Sierra Leone","Somalia","South Africa",
    "Sudan","Tanzania","Togo","Tunisia","Uganda","Zambia","Zimbabwe",
    # Medio Oriente / arabi
    "Saudi Arabia","Qatar","United Arab Emirates","UAE","Kuwait","Oman","Bahrain","Yemen",
    "Jordan","Lebanon","Syria","Iraq","Palestine","Iran",
    # Sud Asia
    "India","Pakistan","Bangladesh","Sri Lanka","Nepal","Bhutan","Afghanistan",
])

ALWAYS_ALLOW_COUNTRIES = set([
    "Australia","Japan","New Zealand","South Korea",
    "Argentina","Brazil","Uruguay","Paraguay","Chile","Colombia","Peru","Ecuador","Bolivia","Venezuela",
    "USA","United States","Mexico","Canada","Costa Rica",
])

BANNED_LEAGUE_TOKENS = [
    "Arab", "Gulf", "Emirates", "CAF", "Africa", "African", "India", "Pakistan",
    "Women", "Femminile", "Primavera", "Youth", "U19", "U20", "U21", "U23"
]

def is_allowed_league(league_name: str, league_country: str) -> bool:
    name = _norm(league_name)
    country = (league_country or "").strip()

    for t in EXCLUDE_NAME_TOKENS:
        if _norm(t) in name:
            return False
    for t in BANNED_LEAGUE_TOKENS:
        if _norm(t) in name:
            return False
    if country in BANNED_COUNTRIES:
        return False
    if country in ALWAYS_ALLOW_COUNTRIES:
        return True
    return True

# ============================
# 4) ODDS: ESTRAZIONE MERCATI
# ============================
@st.cache_data(ttl=900)
def fetch_odds(fixture_id: int) -> Dict[str, Any]:
    with requests.Session() as s:
        return api_get(s, "odds", {"fixture": fixture_id})

def pick_best_bets_block(odds_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    resp = odds_json.get("response", []) or []
    if not resp:
        return []
    bms = resp[0].get("bookmakers", []) or []
    for bm in bms:
        bets = bm.get("bets", []) or []
        if bets:
            return bets
    return []

def find_odd_by_market_and_value(bets: List[Dict[str, Any]], market_contains: List[str], value_equals: str) -> float:
    ve = _norm(value_equals)
    for b in bets:
        name = _norm(b.get("name", ""))
        if not any(_norm(x) in name for x in market_contains):
            continue
        for v in (b.get("values", []) or []):
            if _norm(v.get("value", "")) == ve:
                try:
                    return float(v.get("odd"))
                except Exception:
                    return 0.0
    return 0.0

def find_1x2(bets: List[Dict[str, Any]]) -> Tuple[float, float, float]:
    target_tokens = ["match winner", "1x2", "full time result", "winner"]
    for b in bets:
        name = _norm(b.get("name", ""))
        if not any(t in name for t in target_tokens):
            continue
        vals = b.get("values", []) or []
        mapping = {"home": 0.0, "draw": 0.0, "away": 0.0, "1": 0.0, "x": 0.0, "2": 0.0}
        for v in vals:
            k = _norm(v.get("value", ""))
            try:
                o = float(v.get("odd"))
            except Exception:
                continue
            mapping[k] = o
        q1 = mapping.get("home") or mapping.get("1") or 0.0
        qx = mapping.get("draw") or mapping.get("x") or 0.0
        q2 = mapping.get("away") or mapping.get("2") or 0.0
        if q1 > 0 or q2 > 0:
            return q1, qx, q2

    b1 = next((b for b in bets if b.get("id") == 1), None)
    if b1 and (b1.get("values") or []):
        vals = b1["values"]
        if len(vals) >= 3:
            try:
                return float(vals[0]["odd"]), float(vals[1]["odd"]), float(vals[2]["odd"])
            except Exception:
                return 0.0, 0.0, 0.0
    return 0.0, 0.0, 0.0

def extract_markets(odds_json: Dict[str, Any]) -> Dict[str, float]:
    bets = pick_best_bets_block(odds_json)
    q1, qx, q2 = find_1x2(bets)

    o25 = find_odd_by_market_and_value(
        bets, ["over/under", "goals over/under", "total goals"], "Over 2.5"
    )
    o15_ht = find_odd_by_market_and_value(
        bets, ["first half", "1st half", "over/under - first half", "over/under 1st half", "goals over/under - first half"], "Over 1.5"
    )
    return {"q1": q1, "qx": qx, "q2": q2, "o25": o25, "o15_ht": o15_ht}

# ============================
# 5) RECENTI TEAM (HT GOAL RATE)
# ============================
@st.cache_data(ttl=3600)
def get_team_recent_profile(team_id: int) -> Dict[str, float]:
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"team": team_id, "last": 5, "status": "FT"})
    fx = data.get("response", []) or []
    if not fx:
        return {"ht_goal_rate": 0.0}

    ht_goal = 0
    valid = 0
    for f in fx:
        score = f.get("score", {}) or {}
        ht = (score.get("halftime", {}) or {})
        hth = ht.get("home")
        hta = ht.get("away")
        if hth is None or hta is None:
            continue
        valid += 1
        if int(hth) + int(hta) >= 1:
            ht_goal += 1

    denom = valid if valid > 0 else 5
    return {"ht_goal_rate": ht_goal / denom}

# ============================
# 6) UI UTILS
# ============================
def badge(text: str, kind: str) -> str:
    if kind == "good":
        bg = "#1b4332"
    elif kind == "warn":
        bg = "#ffcc00"
    elif kind == "bad":
        bg = "#ff4b4b"
    else:
        bg = "#2d6a4f"
    return f"<span class='badge' style='background:{bg};'>{text}</span>"

def checklist_cell(title: str, ok: bool, items: List[str]) -> str:
    head = badge(f"{title}: PASS" if ok else f"{title}: FAIL", "good" if ok else "bad")
    det = "".join([f"<div>• {x}</div>" for x in items]) if items else "<div>—</div>"
    return f"{head}<div class='details-list'>{det}</div>"

def get_download_link(html: str, filename: str) -> str:
    b64 = base64.b64encode(html.encode()).decode()
    return (
        f'<a href="data:text/html;base64,{b64}" download="{filename}" style="text-decoration:none;">'
        f'<button style="padding:10px 20px; background-color:#1b4332; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:900;">'
        f'💾 SCARICA ANALISI</button></a>'
    )

# ============================
# 7) SNAPSHOT LOGIC (in memoria)
# ============================
def fav_side(q1: float, q2: float) -> str:
    if q1 <= 0 or q2 <= 0:
        return "ND"
    return "1" if q1 < q2 else "2"

def inversion_reale(prev: Dict[str, float], cur: Dict[str, float]) -> Tuple[bool, str]:
    p = fav_side(prev.get("q1", 0), prev.get("q2", 0))
    c = fav_side(cur.get("q1", 0), cur.get("q2", 0))
    if p == "ND" or c == "ND":
        return False, "N.D."
    if p != c:
        return True, f"Fav {p}→{c}"
    return False, f"Fav stabile ({c})"

def drop_favorita_reale(prev: Dict[str, float], cur: Dict[str, float], drop_min_delta: float, drop_need_cur_le: float) -> Tuple[bool, str]:
    p_side = fav_side(prev.get("q1", 0), prev.get("q2", 0))
    c_side = fav_side(cur.get("q1", 0), cur.get("q2", 0))
    if p_side == "ND" or c_side == "ND":
        return False, "N.D."
    if p_side != c_side:
        return False, "Favorito cambiato"

    if c_side == "1":
        p_odd = prev.get("q1", 0.0); c_odd = cur.get("q1", 0.0)
    else:
        p_odd = prev.get("q2", 0.0); c_odd = cur.get("q2", 0.0)

    if p_odd <= 0 or c_odd <= 0:
        return False, "N.D."

    delta = p_odd - c_odd
    ok = (delta >= drop_min_delta) and (c_odd <= drop_need_cur_le)
    return ok, f"Δ={delta:.2f} (prev {p_odd:.2f} → now {c_odd:.2f})"

def fmt_delta(x: Optional[float]) -> str:
    return "N.D." if x is None else f"{x:+.2f}"

# ============================
# 8) SIDEBAR FILTRI
# ============================
st.sidebar.header("⚙️ Filtri Mercati")

use_over25 = st.sidebar.checkbox("Usa filtro Over 2.5 FT", value=True)
use_o15ht = st.sidebar.checkbox("Usa filtro Over 1.5 1°T", value=True)

min_o25 = st.sidebar.slider("Min O2.5 (FT)", 1.01, 3.50, 1.70, 0.01)
max_o25 = st.sidebar.slider("Max O2.5 (FT)", 1.01, 5.00, 2.35, 0.01)

min_o15ht = st.sidebar.slider("Min O1.5 (HT)", 1.01, 6.00, 2.10, 0.01)
max_o15ht = st.sidebar.slider("Max O1.5 (HT)", 1.01, 10.00, 3.60, 0.01)

# Struttura 1X2
max_fav_allowed = st.sidebar.slider("Anti-favorito: escludi se favorita <= ", 1.20, 2.20, 1.60, 0.01)
min_draw_allowed = st.sidebar.slider("Anti-draw: escludi se pareggio <= ", 2.50, 4.50, 3.10, 0.01)

# Gate inversione "quasi pari" su odds correnti
use_inversion_gap_gate = st.sidebar.checkbox("Gate: inversione 1↔2 (quasi pari, odds correnti)", value=False)
inv_gap_thr = st.sidebar.slider("Soglia |1-2| <= ", 0.05, 1.50, 0.35, 0.01)

# Trap
trap_fav_max = st.sidebar.slider("TRAP: favorita <= ", 1.30, 1.80, 1.55, 0.01)
trap_o25_max = st.sidebar.slider("TRAP: O2.5 <= ", 1.30, 1.80, 1.55, 0.01)
hide_traps = st.sidebar.checkbox("Nascondi TRAP", value=True)

# Recenti HT
min_ht_goal_rate = st.sidebar.slider("HT goal rate min (ultime 5) per team", 0.0, 1.0, 0.60, 0.05)

# Snapshot gates
st.sidebar.markdown("---")
st.sidebar.subheader("🧷 Snapshot / Drop reale (da snapshot)")
require_snapshot_features = st.sidebar.checkbox("Mostra colonne INV/DROP reali", value=True)

drop_min_delta = st.sidebar.slider("DROP reale: minimo crollo Δ", 0.01, 0.80, 0.15, 0.01)
drop_need_cur_le = st.sidebar.slider("DROP reale: quota attuale favorita <= ", 1.20, 2.50, 1.85, 0.01)

gate_real_inversion = st.sidebar.checkbox("Gate: SOLO match con INV REALE (snapshot)", value=False)
gate_real_drop = st.sidebar.checkbox("Gate: SOLO match con DROP REALE (snapshot)", value=False)

mode = st.sidebar.selectbox(
    "Mostra match che passano:",
    ["Almeno uno (O2.5 o O1.5HT)", "Entrambi", "Solo O2.5", "Solo O1.5HT"],
    index=0
)

search = st.sidebar.text_input("Filtro testo (lega/squadre)", value="").strip().lower()

# ============================
# 9) SNAPSHOT UI
# ============================
oggi = datetime.now(ROME_TZ).strftime("%Y-%m-%d") if ROME_TZ else datetime.now().strftime("%Y-%m-%d")

if "odds_snapshot" not in st.session_state:
    st.session_state["odds_snapshot"] = {}
if "snapshot_time" not in st.session_state:
    st.session_state["snapshot_time"] = None
if "snapshot_date" not in st.session_state:
    st.session_state["snapshot_date"] = None

colA, colB = st.columns([1, 2])
with colA:
    save_snap = st.button("📌 SALVA SNAPSHOT QUOTE")
with colB:
    snap_info = "Nessuno snapshot salvato."
    if st.session_state["snapshot_time"]:
        snap_info = f"Snapshot: {st.session_state['snapshot_date']} • {st.session_state['snapshot_time']} • fixtures: {len(st.session_state['odds_snapshot'])}"
    st.markdown(f"<div class='mini'>{snap_info}</div>", unsafe_allow_html=True)

if save_snap:
    with requests.Session() as s:
        data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
    all_fx = data.get("response", []) or []

    candidates = []
    for f in all_fx:
        try:
            if f.get("fixture", {}).get("status", {}).get("short") != "NS":
                continue
            league = f.get("league", {}) or {}
            if not is_allowed_league(league.get("name", ""), league.get("country", "")):
                continue
            candidates.append(f)
        except Exception:
            continue

    if not candidates:
        st.warning("Nessun match per salvare snapshot oggi.")
    else:
        pb = st.progress(0)
        stx = st.empty()
        snap: Dict[int, Dict[str, float]] = {}
        for i, m in enumerate(candidates):
            pb.progress((i + 1) / len(candidates))
            stx.text(f"Snapshot {i+1}/{len(candidates)}: {m['teams']['home']['name']} - {m['teams']['away']['name']}")
            fid = int(m["fixture"]["id"])

            q1 = qx = q2 = o25 = o15 = 0.0
            try:
                odds_json = fetch_odds(fid)
                mk = extract_markets(odds_json)
                q1, qx, q2 = mk["q1"], mk["qx"], mk["q2"]
                o25, o15 = mk["o25"], mk["o15_ht"]
            except Exception:
                pass

            snap[fid] = {"q1": q1, "qx": qx, "q2": q2, "o25": o25, "o15_ht": o15}

        pb.empty()
        stx.empty()

        st.session_state["odds_snapshot"] = snap
        st.session_state["snapshot_time"] = datetime.now(ROME_TZ).strftime("%H:%M:%S") if ROME_TZ else datetime.now().strftime("%H:%M:%S")
        st.session_state["snapshot_date"] = oggi
        st.success(f"Snapshot salvato: {len(snap)} fixtures.")

# ============================
# 10) MAIN SCANSIONE
# ============================
if st.button("🚀 AVVIA SCANSIONE"):
    try:
        with requests.Session() as s:
            data = api_get(s, "fixtures", {"date": oggi, "timezone": "Europe/Rome"})
    except Exception as e:
        st.error(f"Errore fixtures: {e}")
        st.stop()

    all_fx = data.get("response", []) or []

    candidates = []
    for f in all_fx:
        try:
            if f.get("fixture", {}).get("status", {}).get("short") != "NS":
                continue
            league = f.get("league", {}) or {}
            if not is_allowed_league(league.get("name", ""), league.get("country", "")):
                continue
            candidates.append(f)
        except Exception:
            continue

    if not candidates:
        st.warning("Nessun match trovato.")
        st.stop()

    snap = st.session_state.get("odds_snapshot", {}) or {}
    snap_ok = bool(snap) and (st.session_state.get("snapshot_date") == oggi)

    if (gate_real_inversion or gate_real_drop) and (not snap_ok):
        st.warning("Per usare i gate INV/DROP reali devi prima cliccare 📌 SALVA SNAPSHOT QUOTE (oggi).")
        st.stop()

    progress = st.progress(0)
    status = st.empty()

    results: List[Dict[str, Any]] = []
    cnt_hidden_traps = 0
    cnt_gate_filtered = 0
    cnt_search_filtered = 0
    cnt_odds_nd = 0
    cnt_no_snapshot = 0

    for i, m in enumerate(candidates):
        progress.progress((i + 1) / len(candidates))
        h = m["teams"]["home"]["name"]
        a = m["teams"]["away"]["name"]
        status.text(f"Scansione {i+1}/{len(candidates)}: {h} - {a}")

        league_name = m.get("league", {}).get("name", "")
        country = m.get("league", {}).get("country", "")

        text_blob = f"{league_name} {country} {h} {a}".lower()
        if search and search not in text_blob:
            cnt_search_filtered += 1
            continue

        fid = int(m["fixture"]["id"])

        # odds correnti
        q1 = qx = q2 = o25 = o15_ht = 0.0
        try:
            odds_json = fetch_odds(fid)
            mk = extract_markets(odds_json)
            q1, qx, q2 = mk["q1"], mk["qx"], mk["q2"]
            o25, o15_ht = mk["o25"], mk["o15_ht"]
        except Exception:
            cnt_odds_nd += 1

        # TRAP
        trap_reasons: List[str] = []
        if (q1 > 0 and q1 <= trap_fav_max) or (q2 > 0 and q2 <= trap_fav_max):
            trap_reasons.append(f"Favoritissima (<= {trap_fav_max:.2f})")
        if o25 > 0 and o25 <= trap_o25_max:
            trap_reasons.append(f"Over2.5 troppo basso (<= {trap_o25_max:.2f})")
        is_trap = len(trap_reasons) > 0
        if hide_traps and is_trap:
            cnt_hidden_traps += 1
            continue

        # inversione gap (corrente)
        inv_gap_ok = True
        inv_gap_text = "N.D."
        if q1 > 0 and q2 > 0:
            gap = abs(q1 - q2)
            inv_gap_text = f"|1-2|={gap:.2f}"
            inv_gap_ok = gap <= inv_gap_thr
        else:
            inv_gap_ok = False

        if use_inversion_gap_gate and not inv_gap_ok:
            cnt_gate_filtered += 1
            continue

        # struttura 1X2
        structure_ok = True
        struct_notes: List[str] = []
        if q1 > 0 and q2 > 0:
            fav = min(q1, q2)
            if fav <= max_fav_allowed:
                structure_ok = False
                struct_notes.append(f"Favorito troppo forte (fav={fav:.2f} <= {max_fav_allowed:.2f})")
            if qx > 0 and qx <= min_draw_allowed:
                structure_ok = False
                struct_notes.append(f"Draw basso (qx={qx:.2f} <= {min_draw_allowed:.2f})")
        else:
            structure_ok = False
            struct_notes.append("1X2 N.D.")

        # HT rate
        h_prof = get_team_recent_profile(int(m["teams"]["home"]["id"]))
        a_prof = get_team_recent_profile(int(m["teams"]["away"]["id"]))
        ht_gate_ok = (h_prof["ht_goal_rate"] >= min_ht_goal_rate and a_prof["ht_goal_rate"] >= min_ht_goal_rate)

        # snapshot compare + delta
        inv_real_ok = False
        inv_real_msg = "N/A"
        drop_real_ok = False
        drop_real_msg = "N/A"

        d_q1 = d_q2 = d_o25 = d_o15 = None

        if require_snapshot_features:
            if snap_ok and fid in snap:
                prev = snap[fid]
                cur = {"q1": q1, "qx": qx, "q2": q2, "o25": o25, "o15_ht": o15_ht}

                inv_real_ok, inv_real_msg = inversion_reale(prev, cur)
                drop_real_ok, drop_real_msg = drop_favorita_reale(prev, cur, drop_min_delta, drop_need_cur_le)

                if prev.get("q1", 0) > 0 and q1 > 0:
                    d_q1 = q1 - prev["q1"]
                if prev.get("q2", 0) > 0 and q2 > 0:
                    d_q2 = q2 - prev["q2"]
                if prev.get("o25", 0) > 0 and o25 > 0:
                    d_o25 = o25 - prev["o25"]
                if prev.get("o15_ht", 0) > 0 and o15_ht > 0:
                    d_o15 = o15_ht - prev["o15_ht"]
            else:
                cnt_no_snapshot += 1

        # gate reali
        if require_snapshot_features and gate_real_inversion and not inv_real_ok:
            cnt_gate_filtered += 1
            continue
        if require_snapshot_features and gate_real_drop and not drop_real_ok:
            cnt_gate_filtered += 1
            continue

        # CHECKLIST O2.5
        over25_ok = False
        over25_notes: List[str] = []
        if use_over25:
            if o25 <= 0:
                over25_notes.append("O2.5 N.D.")
            else:
                over25_notes.append(f"O2.5={o25:.2f} (range {min_o25:.2f}-{max_o25:.2f})")
                if not (min_o25 <= o25 <= max_o25):
                    over25_notes.append("❌ Fuori range O2.5")
                over25_notes.append("✅ Struttura 1X2 ok" if structure_ok else "❌ Struttura 1X2 KO")
                if require_snapshot_features:
                    over25_notes.append(f"INV reale: {'SÌ' if inv_real_ok else 'NO'} ({inv_real_msg})")
                    over25_notes.append(f"DROP reale: {'SÌ' if drop_real_ok else 'NO'} ({drop_real_msg})")
                else:
                    over25_notes.append(f"INV gap: {'OK' if inv_gap_ok else 'NO'} ({inv_gap_text})")
                if not structure_ok:
                    over25_notes.extend(struct_notes)

            over25_ok = (o25 > 0 and (min_o25 <= o25 <= max_o25) and structure_ok)

        # CHECKLIST O1.5 HT
        o15ht_ok = False
        o15ht_notes: List[str] = []
        if use_o15ht:
            if o15_ht <= 0:
                o15ht_notes.append("O1.5 HT N.D.")
            else:
                o15ht_notes.append(f"O1.5HT={o15_ht:.2f} (range {min_o15ht:.2f}-{max_o15ht:.2f})")
                if not (min_o15ht <= o15_ht <= max_o15ht):
                    o15ht_notes.append("❌ Fuori range O1.5 HT")
                o15ht_notes.append(f"HT goal rate H={h_prof['ht_goal_rate']:.0%} • A={a_prof['ht_goal_rate']:.0%}")
                o15ht_notes.append("✅ HT rate ok" if ht_gate_ok else f"❌ HT rate < {min_ht_goal_rate:.0%}")
                o15ht_notes.append("✅ Struttura 1X2 ok" if structure_ok else "❌ Struttura 1X2 KO")
                if require_snapshot_features:
                    o15ht_notes.append(f"INV reale: {'SÌ' if inv_real_ok else 'NO'} ({inv_real_msg})")
                    o15ht_notes.append(f"DROP reale: {'SÌ' if drop_real_ok else 'NO'} ({drop_real_msg})")
                else:
                    o15ht_notes.append(f"INV gap: {'OK' if inv_gap_ok else 'NO'} ({inv_gap_text})")
                if not structure_ok:
                    o15ht_notes.extend(struct_notes)

            o15ht_ok = (o15_ht > 0 and (min_o15ht <= o15_ht <= max_o15ht) and ht_gate_ok and structure_ok)

        # inclusione
        if mode == "Solo O2.5":
            show = over25_ok
        elif mode == "Solo O1.5HT":
            show = o15ht_ok
        elif mode == "Entrambi":
            show = over25_ok and o15ht_ok
        else:
            show = over25_ok or o15ht_ok

        if not show:
            cnt_gate_filtered += 1
            continue

        trap_html = (
            badge("TRAP: SÌ", "bad") +
            "<div class='details-list'>" + "".join([f"<div>• {r}</div>" for r in trap_reasons]) + "</div>"
            if is_trap else badge("TRAP: NO", "good")
        )

        inv_gap_cell = (badge("INV gap: SÌ", "good") if inv_gap_ok else badge("INV gap: NO", "warn")) + f"<div class='details-list'><div>• {inv_gap_text}</div></div>"

        inv_real_cell = badge("INV reale: SÌ", "good") + f"<div class='details-list'><div>• {inv_real_msg}</div></div>" if inv_real_ok else badge("INV reale: NO", "warn") + f"<div class='details-list'><div>• {inv_real_msg}</div></div>"
        drop_real_cell = badge("DROP reale: SÌ", "good") + f"<div class='details-list'><div>• {drop_real_msg}</div></div>" if drop_real_ok else badge("DROP reale: NO", "warn") + f"<div class='details-list'><div>• {drop_real_msg}</div></div>"

        b_o25 = badge(f"O2.5: {o25:.2f}" if o25 > 0 else "O2.5: N.D.", "neutral")
        b_o15 = badge(f"O1.5 HT: {o15_ht:.2f}" if o15_ht > 0 else "O1.5 HT: N.D.", "neutral")

        results.append({
            "Ora": m["fixture"]["date"][11:16],
            "Match": (
                f"<div class='match-cell'>"
                f"{h} - {a}"
                f"<br><span class='drop-tag'>{'🏠📉 Fav Casa range' if (q1>0 and 1.60<=q1<=1.80) else ('🚀📉 Fav Trasf range' if (q2>0 and 1.60<=q2<=1.85) else '↔️ STABILE')}</span>"
                f"<span class='stats-tag'>{country} • {league_name}</span>"
                f"<span class='stats-tag'>HT goal rate H={h_prof['ht_goal_rate']:.0%} • A={a_prof['ht_goal_rate']:.0%}</span>"
                f"</div>"
            ),
            "1X2": (f"<div class='mini'>{q1:.2f} | {qx:.2f} | {q2:.2f}</div>" if q1 > 0 else "N.D."),
            "Mercati": f"{b_o25}<br>{b_o15}",
            "INV gap": inv_gap_cell,
            "TRAP": trap_html,
            "INV reale": inv_real_cell if require_snapshot_features else badge("OFF", "neutral"),
            "DROP reale": drop_real_cell if require_snapshot_features else badge("OFF", "neutral"),
            "Δ 1": fmt_delta(d_q1) if require_snapshot_features else "OFF",
            "Δ 2": fmt_delta(d_q2) if require_snapshot_features else "OFF",
            "Δ O2.5": fmt_delta(d_o25) if require_snapshot_features else "OFF",
            "Δ O1.5HT": fmt_delta(d_o15) if require_snapshot_features else "OFF",
            "Checklist O2.5": checklist_cell("O2.5", over25_ok, over25_notes) if use_over25 else badge("O2.5: OFF", "neutral"),
            "Checklist O1.5 HT": checklist_cell("O1.5 HT", o15ht_ok, o15ht_notes) if use_o15ht else badge("O1.5 HT: OFF", "neutral"),
        })

    status.empty()
    progress.empty()

    if not results:
        st.info("Nessun match dopo filtri. Prova: disattiva gate reali o allarga range quote.")
        st.stop()

    df = pd.DataFrame(results).sort_values("Ora")
    html = df.to_html(escape=False, index=False)

    st.markdown(get_download_link(html, f"Arab_Scanner_{oggi}.html"), unsafe_allow_html=True)
    st.markdown(html, unsafe_allow_html=True)

    st.sidebar.markdown("---")
    st.sidebar.write({
        "data": oggi,
        "fixtures_totali_api": len(all_fx),
        "post_filtro_leghe": len(candidates),
        "risultati": len(results),
        "odds_nd": cnt_odds_nd,
        "trap_nascoste": cnt_hidden_traps,
        "filtrati_search": cnt_search_filtered,
        "filtrati_gate": cnt_gate_filtered,
        "snapshot_ok_oggi": snap_ok,
        "match_senza_snapshot": cnt_no_snapshot,
        "gate_INV_reale": gate_real_inversion,
        "gate_DROP_reale": gate_real_drop,
        "Δ_drop": drop_min_delta,
        "cur_fav_max": drop_need_cur_le,
        "mode": mode,
    })

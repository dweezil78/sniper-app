import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import requests

# =========================
# CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_GLOB = "free_signals_*.json"
OUT_FILE = BASE_DIR / "casse_recenti.json"

SPORTSDB_SEARCH_URL = "https://www.thesportsdb.com/api/v1/json/123/searchevents.php"
REQUEST_TIMEOUT = 12
MAX_OUTPUT = 8

session = requests.Session()
session.headers.update({"User-Agent": "ArabSniperBet/1.2"})


# =========================
# HELPERS
# =========================
def strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def clean_text(value: str) -> str:
    value = strip_accents(str(value or "").lower())
    value = re.sub(r"\bu\d{2}\b", " ", value)
    value = re.sub(r"\breserves?\b", " ", value)
    value = re.sub(r"\bii\b|\biii\b|\biv\b", " ", value)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def split_match(match_name: str):
    raw = str(match_name or "").strip()
    if " - " in raw:
        parts = [p.strip() for p in raw.split(" - ") if p.strip()]
    elif "-" in raw:
        parts = [p.strip() for p in raw.split("-") if p.strip()]
    else:
        parts = []

    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def build_queries(match_name: str):
    home, away = split_match(match_name)
    if not home or not away:
        return []

    queries = [
        f"{home} vs {away}",
        f"{away} vs {home}",
        f"{home} v {away}",
        f"{home} {away}",
    ]

    out = []
    seen = set()
    for q in queries:
        key = clean_text(q)
        if key and key not in seen:
            seen.add(key)
            out.append(q)
    return out


def get_tokens(text: str):
    return [t for t in clean_text(text).split() if len(t) >= 3]


def overlap_score(match_name: str, event_name: str) -> int:
    a = set(get_tokens(match_name))
    b = set(get_tokens(event_name))
    return len(a & b)


def parse_snapshot_date_from_filename(path: Path):
    m = re.search(r"free_signals_(\d{4}-\d{2}-\d{2})\.json$", path.name)
    if not m:
        return None
    return m.group(1)


def load_snapshots():
    files = sorted(BASE_DIR.glob(SNAPSHOT_GLOB))
    rows = []

    for fp in files:
        snapshot_date = parse_snapshot_date_from_filename(fp)
        if not snapshot_date:
            continue

        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Impossibile leggere {fp.name}: {e}")
            continue

        if not isinstance(data, list):
            print(f"[WARN] {fp.name} non contiene una lista JSON valida.")
            continue

        for item in data:
            try:
                match_name = str(item.get("match", "")).strip()
                signal = str(item.get("signal", "")).strip()
                quote = str(item.get("quote", "")).strip()
                league = str(item.get("league", "")).strip()
                time_str = str(item.get("time", "")).strip()
                fixture_id = str(item.get("fixture_id", "")).strip()
            except Exception as e:
                print(f"[WARN] Riga malformata in {fp.name}: {e}")
                continue

            if not match_name or not signal:
                continue

            rows.append(
                {
                    "data": snapshot_date,
                    "snapshot_date": snapshot_date,
                    "match": match_name,
                    "signal": signal,
                    "quote": quote,
                    "league": league,
                    "time": time_str,
                    "fixture_id": fixture_id,
                }
            )

    return rows


def parse_event_date(ev: dict):
    date_str = ev.get("dateEvent")
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def extract_score(ev: dict):
    hs = ev.get("intHomeScore")
    aw = ev.get("intAwayScore")
    if hs in (None, "") or aw in (None, ""):
        return None
    try:
        hs_i = int(hs)
        aw_i = int(aw)
        return hs_i, aw_i
    except Exception:
        return None


def choose_best_event(match_name: str, snapshot_date: str, events: list):
    try:
        target_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
    except Exception:
        return None

    ranked = []

    for ev in events:
        ev_name = ev.get("strEvent") or ""
        score = extract_score(ev)
        if not score:
            continue

        ev_date = parse_event_date(ev)
        if ev_date != target_date:
            continue

        name_score = overlap_score(match_name, ev_name)
        if name_score < 2:
            continue

        ranked.append((name_score, ev))

    if not ranked:
        return None

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def search_finished_result(match_name: str, snapshot_date: str):
    queries = build_queries(match_name)

    for q in queries:
        try:
            r = session.get(
                SPORTSDB_SEARCH_URL,
                params={"e": q},
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"[WARN] Errore ricerca '{q}': {e}")
            continue

        events = payload.get("event") or []
        if not events:
            continue

        best = choose_best_event(match_name, snapshot_date, events)
        if not best:
            continue

        score = extract_score(best)
        if not score:
            continue

        hs_i, aw_i = score
        total_goals = hs_i + aw_i

        return {
            "result": f"{hs_i}-{aw_i}",
            "total_goals": total_goals,
        }

    return None


def evaluate_signal_result(signal: str, total_goals: int):
    signal_norm = str(signal or "").upper()

    if total_goals >= 3:
        return "✅ CASSA"
    if total_goals >= 2:
        if "OVER" in signal_norm or "GOLD" in signal_norm or "BOOST" in signal_norm or "PT" in signal_norm:
            return "✅ CASSA SOFT"
    return None


def save_output(rows):
    OUT_FILE.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# =========================
# MAIN
# =========================
def main():
    rows = load_snapshots()
    print(f"DEBUG rows caricati = {len(rows)}")

    if not rows:
        save_output([])
        print("Nessuno snapshot trovato. Creato casse_recenti.json vuoto.")
        return 0

    output = []
    seen = set()

    for row in rows:
        try:
            unique_key = row.get("fixture_id") or f'{row.get("snapshot_date","")}|{row.get("match","")}'
            if unique_key in seen:
                continue
            seen.add(unique_key)

            result = search_finished_result(row["match"], row["snapshot_date"])
            if not result:
                continue

            status = evaluate_signal_result(row["signal"], result["total_goals"])
            if not status:
                continue

            output.append(
                {
                    "data": row["snapshot_date"],
                    "match": row["match"],
                    "signal": row["signal"],
                    "quote": row["quote"],
                    "result": f'{result["result"]} {status}',
                    "league": row["league"],
                    "time": row["time"],
                    "fixture_id": row["fixture_id"],
                }
            )
        except Exception as e:
            print(f"[WARN] Errore su match '{row.get('match', 'N/D')}': {e}")
            continue

    output.sort(key=lambda x: (x.get("data", ""), x.get("time", "")), reverse=True)

    final_output = [
        {
            "data": x["data"],
            "match": x["match"],
            "signal": x["signal"],
            "quote": x["quote"],
            "result": x["result"],
            "league": x["league"],
            "time": x["time"],
            "fixture_id": x["fixture_id"],
        }
        for x in output[:MAX_OUTPUT]
    ]

    save_output(final_output)
    print(f"Creato {OUT_FILE.name} con {len(final_output)} record.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("❌ ERRORE DETTAGLIATO BUILD CASSE:")
        print(str(e))
        save_output([])
        raise SystemExit(0)

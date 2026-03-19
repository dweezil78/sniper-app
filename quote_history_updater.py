import json
import argparse
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
QUOTE_HISTORY_FILE = BASE_DIR / "quote_history.json"


# =========================
# IO HELPERS
# =========================
def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def parse_float(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def fmt_num(v):
    if v is None:
        return ""
    try:
        return f"{float(v):.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(v)


def round_or_zero(v, nd=4):
    try:
        return round(float(v), nd)
    except Exception:
        return 0.0


def normalize_fixture_id(v):
    try:
        return str(int(v))
    except Exception:
        return str(v).strip()


def dedupe_preserve_order(items):
    seen = set()
    out = []
    for item in items:
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


# =========================
# SOGLIE
# =========================
DROP_1X2_LIGHT = 0.06
DROP_1X2_MEDIUM = 0.12
DROP_1X2_STRONG = 0.20

DROP_O25_INFO = 0.08


def strength_1x2(value):
    if value >= DROP_1X2_STRONG:
        return "strong"
    if value >= DROP_1X2_MEDIUM:
        return "medium"
    if value >= DROP_1X2_LIGHT:
        return "light"
    return "none"


def market_drop(old_val, new_val):
    """
    Drop positivo = quota scesa.
    Esempio: 2.10 -> 1.85 = +0.25
    """
    if old_val is None or new_val is None:
        return 0.0
    return round_or_zero(old_val - new_val, 4)


def best_1x2_side(markets):
    cands = {
        "1": markets.get("q1"),
        "X": markets.get("qx"),
        "2": markets.get("q2"),
    }
    valid = {k: v for k, v in cands.items() if v is not None}
    if not valid:
        return "", None
    side = min(valid.items(), key=lambda x: x[1])[0]
    return side, valid[side]


# =========================
# SNAPSHOT MERCATI
# =========================
def build_market_snapshot(detail_item):
    markets = detail_item.get("markets", {}) or {}
    return {
        "q1": parse_float(markets.get("q1")),
        "qx": parse_float(markets.get("qx")),
        "q2": parse_float(markets.get("q2")),
        "o25": parse_float(markets.get("o25")),
        "o05ht": parse_float(markets.get("o05ht")),
        "o15ht": parse_float(markets.get("o15ht")),
    }


def build_market_snapshot_from_row(row):
    parts = str(row.get("1X2", "")).split("|")
    while len(parts) < 3:
        parts.append("")

    return {
        "q1": parse_float(parts[0]),
        "qx": parse_float(parts[1]),
        "q2": parse_float(parts[2]),
        "o25": parse_float(row.get("O2.5")),
        "o05ht": parse_float(row.get("O0.5H")),
        "o15ht": parse_float(row.get("O1.5H")),
    }


def extract_country_from_lega(lega_value):
    lega = str(lega_value or "")
    if "(" in lega and ")" in lega:
        try:
            return lega.rsplit("(", 1)[1].replace(")", "").strip()
        except Exception:
            return ""
    return ""


def append_history_point(history_db, fixture_id, match_name, country, league, day_date, day_num, label, markets, ts):
    rec = history_db.get(fixture_id, {
        "fixture_id": fixture_id,
        "match": match_name,
        "country": country,
        "league": league,
        "first_date": day_date,
        "history": []
    })

    rec["match"] = match_name or rec.get("match", "")
    rec["country"] = country or rec.get("country", "")
    rec["league"] = league or rec.get("league", "")
    rec["first_date"] = rec.get("first_date") or day_date

    point = {
        "ts": ts,
        "label": label,
        "day": day_num,
        "date": day_date,
        "markets": markets
    }

    hist = rec.get("history", [])
    if hist:
        last_point = hist[-1]
        last_markets = last_point.get("markets", {})
        if last_markets == markets:
            history_db[fixture_id] = rec
            return history_db, False  # invariato

    hist.append(point)
    rec["history"] = hist[-40:]
    history_db[fixture_id] = rec
    return history_db, True  # aggiornato


def compute_drop_maps(history_points):
    """
    open_map = dal primo snapshot all'ultimo
    last_map = dal penultimo snapshot all'ultimo
    """
    empty_map = {"q1": 0.0, "qx": 0.0, "q2": 0.0, "o25": 0.0}

    if not history_points:
        return empty_map.copy(), empty_map.copy()

    first = history_points[0].get("markets", {})
    last = history_points[-1].get("markets", {})

    open_map = {}
    for key in empty_map.keys():
        open_map[key] = market_drop(first.get(key), last.get(key))

    if len(history_points) < 2:
        return open_map, empty_map.copy()

    prev = history_points[-2].get("markets", {})
    last_map = {}
    for key in empty_map.keys():
        last_map[key] = market_drop(prev.get(key), last.get(key))

    return open_map, last_map


def detect_inversion(history_points):
    """
    INVERSION = la favorita iniziale non è più la favorita attuale.
    """
    if not history_points:
        return False, "", "", None, None

    first = history_points[0].get("markets", {})
    last = history_points[-1].get("markets", {})

    first_side, first_quote = best_1x2_side(first)
    last_side, last_quote = best_1x2_side(last)

    if not first_side or not last_side:
        return False, first_side, last_side, first_quote, last_quote

    inverted = first_side != last_side
    return inverted, first_side, last_side, first_quote, last_quote


# =========================
# TAGS PROFESSIONALI
# =========================
def build_signal_tags(open_map, inversion_flag, inversion_from, inversion_to):
    tags = []

    # 1X2 forti
    if open_map.get("q1", 0.0) >= DROP_1X2_LIGHT:
        tags.append("DROP_1")
    if open_map.get("qx", 0.0) >= DROP_1X2_LIGHT:
        tags.append("DROP_X")
    if open_map.get("q2", 0.0) >= DROP_1X2_LIGHT:
        tags.append("DROP_2")

    # O25 solo informativo
    if open_map.get("o25", 0.0) >= DROP_O25_INFO:
        tags.append("O25_DROP")

    # Inversione
    if inversion_flag:
        tags.append("INVERSION")
        if inversion_from and inversion_to:
            tags.append(f"INV_{inversion_from}_TO_{inversion_to}")

    return dedupe_preserve_order(tags)


def build_strength_tags(open_map):
    tags = []
    for key, label in [("q1", "1"), ("qx", "X"), ("q2", "2")]:
        val = open_map.get(key, 0.0)
        lvl = strength_1x2(val)
        if lvl == "strong":
            tags.append(f"DROP_{label}_STRONG")
        elif lvl == "medium":
            tags.append(f"DROP_{label}_MED")
    return dedupe_preserve_order(tags)


def build_info_suffix(open_map, inversion_flag, inversion_from, inversion_to):
    parts = []

    if open_map.get("q1", 0.0) >= DROP_1X2_LIGHT:
        parts.append("DROP_1")
    if open_map.get("qx", 0.0) >= DROP_1X2_LIGHT:
        parts.append("DROP_X")
    if open_map.get("q2", 0.0) >= DROP_1X2_LIGHT:
        parts.append("DROP_2")

    if inversion_flag:
        if inversion_from and inversion_to:
            parts.append(f"INV {inversion_from}>{inversion_to}")
        else:
            parts.append("INVERSION")

    if open_map.get("o25", 0.0) >= DROP_O25_INFO:
        parts.append("O25_DROP")

    return " ".join(parts).strip()


# =========================
# HISTORY UPDATE
# =========================
def append_history_from_day(day_num, label, history_db):
    details_path = BASE_DIR / f"details_day{day_num}.json"
    data_path = BASE_DIR / f"data_day{day_num}.json"

    details_payload = load_json(details_path, {})
    ts = datetime.now().isoformat(timespec="seconds")
    updated = 0
    skipped = 0

    # =========================
    # PRIORITÀ 1: details_dayX.json
    # =========================
    if isinstance(details_payload, dict) and isinstance(details_payload.get("details"), dict):
        details = details_payload.get("details", {})

        for fixture_id, item in details.items():
            fixture_id = normalize_fixture_id(item.get("fixture_id", fixture_id))
            markets = build_market_snapshot(item)
            match_name = item.get("match", "")
            country = item.get("country", "")
            league = item.get("league", "")
            day_date = item.get("date", details_payload.get("date", ""))

            history_db, was_updated = append_history_point(
                history_db=history_db,
                fixture_id=fixture_id,
                match_name=match_name,
                country=country,
                league=league,
                day_date=day_date,
                day_num=day_num,
                label=label,
                markets=markets,
                ts=ts
            )

            if was_updated:
                updated += 1
            else:
                skipped += 1

        print(f"🧠 DAY{day_num}: history aggiornata per {updated} fixture, {skipped} invariati.")
        return history_db

    # =========================
    # FALLBACK: data_dayX.json
    # =========================
    rows = load_json(data_path, [])
    if not isinstance(rows, list):
        print(f"⚠️ details_day{day_num}.json non valido o mancante, e data_day{day_num}.json non valido.")
        return history_db

    print(f"⚠️ details_day{day_num}.json non valido o mancante. Uso fallback da data_day{day_num}.json")

    for row in rows:
        fixture_id = normalize_fixture_id(row.get("Fixture_ID"))
        if not fixture_id:
            continue

        markets = build_market_snapshot_from_row(row)
        match_name = row.get("Match", "")
        lega = row.get("Lega", "")
        country = extract_country_from_lega(lega)
        day_date = row.get("Data", "")
        league = lega

        history_db, was_updated = append_history_point(
            history_db=history_db,
            fixture_id=fixture_id,
            match_name=match_name,
            country=country,
            league=league,
            day_date=day_date,
            day_num=day_num,
            label=label,
            markets=markets,
            ts=ts
        )

        if was_updated:
            updated += 1
        else:
            skipped += 1

    print(f"🧠 DAY{day_num}: history aggiornata per {updated} fixture, {skipped} invariati. (fallback data_day)")
    return history_db


# =========================
# DETAILS ENRICHMENT
# =========================
def enrich_details_file(day_num, history_db):
    path = BASE_DIR / f"details_day{day_num}.json"
    payload = load_json(path, {})

    if not isinstance(payload, dict) or "details" not in payload:
        print(f"⚠️ details_day{day_num}.json non valido per enrich.")
        return

    details = payload.get("details", {})
    touched = 0

    for fixture_key, item in list(details.items()):
        fixture_id = normalize_fixture_id(item.get("fixture_id", fixture_key))
        rec = history_db.get(fixture_id)

        if not rec:
            continue

        hist = rec.get("history", [])
        if not hist:
            continue

        open_map, last_map = compute_drop_maps(hist)
        inversion_flag, inversion_from, inversion_to, open_fav_q, curr_fav_q = detect_inversion(hist)

        flags = item.get("flags", {})
        if not isinstance(flags, dict):
            flags = {}

        first_markets = hist[0].get("markets", {})
        last_markets = hist[-1].get("markets", {})

        # quote di apertura e quote attuali
        flags["open_q1"] = first_markets.get("q1")
        flags["open_qx"] = first_markets.get("qx")
        flags["open_q2"] = first_markets.get("q2")
        flags["open_o25"] = first_markets.get("o25")

        flags["curr_q1"] = last_markets.get("q1")
        flags["curr_qx"] = last_markets.get("qx")
        flags["curr_q2"] = last_markets.get("q2")
        flags["curr_o25"] = last_markets.get("o25")

        # drop 1X2
        flags["drop_q1"] = round_or_zero(open_map["q1"], 4)
        flags["drop_qx"] = round_or_zero(open_map["qx"], 4)
        flags["drop_q2"] = round_or_zero(open_map["q2"], 4)
        flags["drop_o25"] = round_or_zero(open_map["o25"], 4)

        flags["drop_last_q1"] = round_or_zero(last_map["q1"], 4)
        flags["drop_last_qx"] = round_or_zero(last_map["qx"], 4)
        flags["drop_last_q2"] = round_or_zero(last_map["q2"], 4)
        flags["drop_last_o25"] = round_or_zero(last_map["o25"], 4)

        # dominante 1X2
        drop_candidates = {
            "1": open_map["q1"],
            "X": open_map["qx"],
            "2": open_map["q2"],
        }
        best_side = max(drop_candidates.items(), key=lambda x: x[1])[0]
        best_val = max(drop_candidates.values())

        flags["drop_diff"] = round_or_zero(best_val, 4)
        flags["drop_side"] = best_side if best_val >= DROP_1X2_LIGHT else ""
        flags["drop_strength"] = strength_1x2(best_val)

        # inversione
        flags["inversion"] = bool(inversion_flag)
        flags["inversion_from"] = inversion_from
        flags["inversion_to"] = inversion_to
        flags["open_fav_side"] = inversion_from
        flags["curr_fav_side"] = inversion_to
        flags["open_fav_quote"] = open_fav_q
        flags["curr_fav_quote"] = curr_fav_q

        flags["history_points"] = len(hist)
        flags["first_seen_at"] = hist[0].get("ts")
        flags["last_seen_at"] = hist[-1].get("ts")

        item["flags"] = flags

        original_tags = item.get("tags", [])
        if not isinstance(original_tags, list):
            original_tags = []

        signal_tags = build_signal_tags(open_map, inversion_flag, inversion_from, inversion_to)
        strength_tags = build_strength_tags(open_map)

        item["tags"] = dedupe_preserve_order(original_tags + signal_tags + strength_tags)

        details[str(fixture_id)] = item
        touched += 1

    payload["details"] = details
    save_json(path, payload)
    print(f"✅ details_day{day_num}.json arricchito per {touched} fixture.")


# =========================
# DATA TABLE ENRICHMENT
# =========================
def enrich_data_file(day_num, history_db):
    path = BASE_DIR / f"data_day{day_num}.json"
    rows = load_json(path, [])

    if not isinstance(rows, list):
        print(f"⚠️ data_day{day_num}.json non valido per enrich.")
        return

    touched = 0

    for row in rows:
        fixture_id = normalize_fixture_id(row.get("Fixture_ID"))
        rec = history_db.get(fixture_id)
        if not rec:
            continue

        hist = rec.get("history", [])
        if not hist:
            continue

        open_map, _ = compute_drop_maps(hist)
        inversion_flag, inversion_from, inversion_to, _, _ = detect_inversion(hist)

        first_markets = hist[0].get("markets", {})
        last_markets = hist[-1].get("markets", {})

        # Info: aggiungiamo solo tag professionali nuovi
        info_suffix = build_info_suffix(open_map, inversion_flag, inversion_from, inversion_to)
        current_info = str(row.get("Info", "")).strip()
        if info_suffix and info_suffix not in current_info:
            row["Info"] = (current_info + " " + info_suffix).strip()
            touched += 1

        # Campi extra per futura visualizzazione professionale in web/streamlit
        row["Q1_OPEN"] = fmt_num(first_markets.get("q1"))
        row["QX_OPEN"] = fmt_num(first_markets.get("qx"))
        row["Q2_OPEN"] = fmt_num(first_markets.get("q2"))
        row["O25_OPEN"] = fmt_num(first_markets.get("o25"))

        row["Q1_CURR"] = fmt_num(last_markets.get("q1"))
        row["QX_CURR"] = fmt_num(last_markets.get("qx"))
        row["Q2_CURR"] = fmt_num(last_markets.get("q2"))
        row["O25_CURR"] = fmt_num(last_markets.get("o25"))

        # Stringhe compatte già pronte per essere mostrate in cella
        row["Q1_MOVE"] = f"{fmt_num(last_markets.get('q1'))}\n↓ {fmt_num(first_markets.get('q1'))}" if first_markets.get("q1") and last_markets.get("q1") and open_map.get("q1", 0.0) >= DROP_1X2_LIGHT else ""
        row["QX_MOVE"] = f"{fmt_num(last_markets.get('qx'))}\n↓ {fmt_num(first_markets.get('qx'))}" if first_markets.get("qx") and last_markets.get("qx") and open_map.get("qx", 0.0) >= DROP_1X2_LIGHT else ""
        row["Q2_MOVE"] = f"{fmt_num(last_markets.get('q2'))}\n↓ {fmt_num(first_markets.get('q2'))}" if first_markets.get("q2") and last_markets.get("q2") and open_map.get("q2", 0.0) >= DROP_1X2_LIGHT else ""
        row["O25_MOVE"] = f"{fmt_num(last_markets.get('o25'))}\n↓ {fmt_num(first_markets.get('o25'))}" if first_markets.get("o25") and last_markets.get("o25") and open_map.get("o25", 0.0) >= DROP_O25_INFO else ""

        row["INVERSION"] = "YES" if inversion_flag else ""
        row["INV_FROM"] = inversion_from or ""
        row["INV_TO"] = inversion_to or ""

    save_json(path, rows)
    print(f"✅ data_day{day_num}.json aggiornato per {len(rows)} righe.")

    if day_num == 1:
        live_path = BASE_DIR / "data.json"
        live_rows = load_json(live_path, [])
        if isinstance(live_rows, list):
            for row in live_rows:
                fixture_id = normalize_fixture_id(row.get("Fixture_ID"))
                rec = history_db.get(fixture_id)
                if not rec:
                    continue

                hist = rec.get("history", [])
                if not hist:
                    continue

                open_map, _ = compute_drop_maps(hist)
                inversion_flag, inversion_from, inversion_to, _, _ = detect_inversion(hist)

                first_markets = hist[0].get("markets", {})
                last_markets = hist[-1].get("markets", {})

                info_suffix = build_info_suffix(open_map, inversion_flag, inversion_from, inversion_to)
                current_info = str(row.get("Info", "")).strip()
                if info_suffix and info_suffix not in current_info:
                    row["Info"] = (current_info + " " + info_suffix).strip()

                row["Q1_OPEN"] = fmt_num(first_markets.get("q1"))
                row["QX_OPEN"] = fmt_num(first_markets.get("qx"))
                row["Q2_OPEN"] = fmt_num(first_markets.get("q2"))
                row["O25_OPEN"] = fmt_num(first_markets.get("o25"))

                row["Q1_CURR"] = fmt_num(last_markets.get("q1"))
                row["QX_CURR"] = fmt_num(last_markets.get("qx"))
                row["Q2_CURR"] = fmt_num(last_markets.get("q2"))
                row["O25_CURR"] = fmt_num(last_markets.get("o25"))

                row["Q1_MOVE"] = f"{fmt_num(last_markets.get('q1'))}\n↓ {fmt_num(first_markets.get('q1'))}" if first_markets.get("q1") and last_markets.get("q1") and open_map.get("q1", 0.0) >= DROP_1X2_LIGHT else ""
                row["QX_MOVE"] = f"{fmt_num(last_markets.get('qx'))}\n↓ {fmt_num(first_markets.get('qx'))}" if first_markets.get("qx") and last_markets.get("qx") and open_map.get("qx", 0.0) >= DROP_1X2_LIGHT else ""
                row["Q2_MOVE"] = f"{fmt_num(last_markets.get('q2'))}\n↓ {fmt_num(first_markets.get('q2'))}" if first_markets.get("q2") and last_markets.get("q2") and open_map.get("q2", 0.0) >= DROP_1X2_LIGHT else ""
                row["O25_MOVE"] = f"{fmt_num(last_markets.get('o25'))}\n↓ {fmt_num(first_markets.get('o25'))}" if first_markets.get("o25") and last_markets.get("o25") and open_map.get("o25", 0.0) >= DROP_O25_INFO else ""

                row["INVERSION"] = "YES" if inversion_flag else ""
                row["INV_FROM"] = inversion_from or ""
                row["INV_TO"] = inversion_to or ""

            save_json(live_path, live_rows)
            print(f"✅ data.json aggiorn

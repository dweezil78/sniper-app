import re
import unicodedata


def normalize_text(value: str) -> str:
    value = str(value or "").strip().lower()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


HARD_EXCLUDE_PATTERNS = [
    "women",
    "femmin",
    "friendly",
    "friendlies",
    "club friendlies",
    "amichev",
    "youth",
    "juniores",
    "u17",
    "u18",
    "u19",
    "u20",
    "u21",
    "reserve",
    "reserves",
]

MINOR_RISK_PATTERNS = [
    "serie d",
    "eccellenza",
    "promozione",
    "prima categoria",
    "seconda categoria",
    "terza categoria",
    "regional",
    "state league",
    "county",
    "amateur",
]


def match_any_pattern(text: str, patterns: list[str]) -> bool:
    t = normalize_text(text)
    return any(p in t for p in patterns)


def is_hard_excluded_league(league_name: str) -> bool:
    return match_any_pattern(league_name, HARD_EXCLUDE_PATTERNS)


def is_minor_risk_league(league_name: str) -> bool:
    return match_any_pattern(league_name, MINOR_RISK_PATTERNS)

import sys
import types
import importlib.util
import subprocess
import shutil
import requests
import os
import json
import base64
import time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
APP_PATH = BASE_DIR / "3appDays.py"
ARCHIVE_DIR = BASE_DIR / "archives"

GITHUB_OWNER = "arabsnipertech-bet"
GITHUB_REPO = "arabsniper"
GITHUB_BRANCH = "main"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents"

MIN_VALID_DAY1_ROWS = 1


# =========================
# FAKE STREAMLIT
# =========================
class SessionState(dict):
    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value


class DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def progress(self, *args, **kwargs):
        return self

    def empty(self):
        return None

    def write(self, *args, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def dataframe(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def button(self, *args, **kwargs):
        return False

    def download_button(self, *args, **kwargs):
        return False

    def subheader(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def header(self, *args, **kwargs):
        return None

    def selectbox(self, label, options=None, index=0, **kwargs):
        if options is None:
            return None
        if len(options) == 0:
            return None
        return options[index] if len(options) > index else options[0]

    def multiselect(self, label, options=None, default=None, **kwargs):
        return default or []


class FakeSidebar(DummyContext):
    pass


class FakeSecrets(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeStreamlitModule(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = SessionState()
        self.sidebar = FakeSidebar()
        self.secrets = FakeSecrets()

    def set_page_config(self, *args, **kwargs):
        return None

    def spinner(self, *args, **kwargs):
        return DummyContext()

    def progress(self, *args, **kwargs):
        return DummyContext()

    def columns(self, spec, **kwargs):
        if isinstance(spec, int):
            n = spec
        else:
            n = len(spec)
        return [DummyContext() for _ in range(n)]

    def button(self, *args, **kwargs):
        return False

    def markdown(self, *args, **kwargs):
        return None

    def dataframe(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def subheader(self, *args, **kwargs):
        return None

    def write(self, *args, **kwargs):
        return None

    def rerun(self):
        return None

    def download_button(self, *args, **kwargs):
        return False

    def dialog(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator


fake_st = FakeStreamlitModule()
sys.modules["streamlit"] = fake_st


# =========================
# IMPORT DINAMICO DI 3appDays.py
# =========================
spec = importlib.util.spec_from_file_location("app3days_module", APP_PATH)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


# =========================
# FILES
# =========================
LIVE_FILES = [
    "data.json",
    "data_day1.json",
    "data_day2.json",
    "data_day3.json",
    "data_day4.json",
    "data_day5.json",
    "details_day1.json",
    "details_day2.json",
    "details_day3.json",
    "details_day4.json",
    "details_day5.json",
    "quote_history.json",
]

SYNC_FILES = [
    "data.json",
    "data_day1.json",
    "data_day2.json",
    "data_day3.json",
    "data_day4.json",
    "data_day5.json",
    "details_day1.json",
    "details_day2.json",
    "details_day3.json",
    "details_day4.json",
    "details_day5.json",
]


# =========================
# HELPERS GENERALI
# =========================
def archive_live_files():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = ARCHIVE_DIR / ts
    target.mkdir(parents=True, exist_ok=True)

    copied = 0
    for name in LIVE_FILES:
        src = BASE_DIR / name
        if src.exists():
            shutil.copy2(src, target / name)
            copied += 1

    print(f"📦 Backup creato in: {target}", flush=True)
    print(f"📦 File copiati: {copied}", flush=True)


def github_headers():
    token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "arabsniper-runner",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_github_file(path: str) -> str:
    url = f"{GITHUB_API}/{path}"
    params = {"ref": GITHUB_BRANCH}
    response = requests.get(url, headers=github_headers(), params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()

    if "content" not in payload:
        raise RuntimeError(f"Contenuto mancante per {path}")

    content = payload["content"].replace("\n", "")
    return base64.b64decode(content).decode("utf-8")


def read_json_safe(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def expected_day1_date() -> str:
    return app.get_target_dates()[0]


def normalize_fixture_id(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text


def extract_fixture_ids_from_rows(rows):
    fixture_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        fid = normalize_fixture_id(row.get("Fixture_ID"))
        if fid:
            fixture_ids.add(fid)
    return fixture_ids


def extract_fixture_ids_from_details(details_payload):
    if not isinstance(details_payload, dict):
        return set()

    details = details_payload.get("details", {})
    if not isinstance(details, dict):
        return set()

    fixture_ids = set()
    for key, payload in details.items():
        key_norm = normalize_fixture_id(key)
        if key_norm:
            fixture_ids.add(key_norm)

        if isinstance(payload, dict):
            inner_fid = normalize_fixture_id(payload.get("fixture_id"))
            if inner_fid:
                fixture_ids.add(inner_fid)

    return fixture_ids


def validate_day1_pair(verbose=True):
    """
    Valida la coppia data_day1.json + details_day1.json in modo robusto.
    Regole:
    - data_day1.json deve esistere ed essere una lista non vuota
    - tutte le righe devono avere Data coerente con la data attesa
    - deve esserci almeno 1 fixture valido
    - details_day1.json deve esistere
    - details_day1.json deve avere date coerenti
    - i fixture id devono combaciare tra day1 e details_day1
    """
    expected = expected_day1_date()

    day1_path = BASE_DIR / "data_day1.json"
    details_path = BASE_DIR / "details_day1.json"

    day1 = read_json_safe(day1_path)
    details_payload = read_json_safe(details_path)

    if not isinstance(day1, list):
        if verbose:
            print("❌ data_day1.json non è una lista valida.", flush=True)
        return False

    if len(day1) < MIN_VALID_DAY1_ROWS:
        if verbose:
            print(f"❌ data_day1.json troppo corto: {len(day1)} righe.", flush=True)
        return False

    day1_dates = {str(row.get("Data", "")).strip() for row in day1 if isinstance(row, dict)}
    day1_dates.discard("")
    if not day1_dates:
        if verbose:
            print("❌ Nessuna data valida trovata in data_day1.json.", flush=True)
        return False

    if day1_dates != {expected}:
        if verbose:
            print(f"❌ data_day1.json ha date incoerenti. Attesa: {expected} | Trovate: {sorted(day1_dates)}", flush=True)
        return False

    day1_fixture_ids = extract_fixture_ids_from_rows(day1)
    if not day1_fixture_ids:
        if verbose:
            print("❌ data_day1.json non contiene fixture_id validi.", flush=True)
        return False

    if not isinstance(details_payload, dict):
        if verbose:
            print("❌ details_day1.json non è un oggetto JSON valido.", flush=True)
        return False

    details_date = str(details_payload.get("date", "")).strip()
    if details_date != expected:
        if verbose:
            print(f"❌ details_day1.json ha data incoerente. Attesa: {expected} | Trovata: {details_date or 'N/D'}", flush=True)
        return False

    details_map = details_payload.get("details", {})
    if not isinstance(details_map, dict) or not details_map:
        if verbose:
            print("❌ details_day1.json non contiene dettagli validi.", flush=True)
        return False

    details_fixture_ids = extract_fixture_ids_from_details(details_payload)
    if not details_fixture_ids:
        if verbose:
            print("❌ details_day1.json non contiene fixture_id validi.", flush=True)
        return False

    common_fixture_ids = day1_fixture_ids & details_fixture_ids
    if not common_fixture_ids:
        if verbose:
            print("❌ Nessun fixture_id in comune tra data_day1.json e details_day1.json.", flush=True)
            print(f"   data_day1 fixture: {len(day1_fixture_ids)} | details_day1 fixture: {len(details_fixture_ids)}", flush=True)
        return False

    if len(common_fixture_ids) < min(len(day1_fixture_ids), MIN_VALID_DAY1_ROWS):
        if verbose:
            print("❌ Match parziale insufficiente tra data_day1.json e details_day1.json.", flush=True)
            print(
                f"   Comuni: {len(common_fixture_ids)} | "
                f"data_day1: {len(day1_fixture_ids)} | "
                f"details_day1: {len(details_fixture_ids)}",
                flush=True,
            )
        return False

    if verbose:
        print(
            f"✅ Validazione day1 ok | data attesa: {expected} | "
            f"righe day1: {len(day1)} | fixture comuni: {len(common_fixture_ids)}",
            flush=True,
        )
    return True


def sync_remote_outputs_to_local(max_attempts=6, wait_seconds=10):
    """
    Dopo che 3appDays.py ha scritto i file su GitHub via API,
    li riscarichiamo tramite GitHub Contents API.
    La sync è considerata valida solo se:
    - tutti i file richiesti vengono scaricati
    - data_day1.json e details_day1.json risultano coerenti tra loro
    """
    print("🔄 Sincronizzo i file remoti GitHub nel workspace locale...", flush=True)
    expected = expected_day1_date()
    print(f"📅 Attendo day1 coerente con data: {expected}", flush=True)

    for attempt in range(1, max_attempts + 1):
        print(f"🔁 Tentativo sync {attempt}/{max_attempts}", flush=True)
        all_ok = True

        for name in SYNC_FILES:
            dest = BASE_DIR / name
            try:
                text = fetch_github_file(name)
                dest.write_text(text, encoding="utf-8")
                print(f"✅ Sync locale: {name}", flush=True)
            except Exception as exc:
                all_ok = False
                print(f"⚠️ Sync fallita per {name}: {exc}", flush=True)

        if all_ok and validate_day1_pair(verbose=True):
            print("✅ Sync completata: data_day1.json e details_day1.json sono coerenti.", flush=True)
            return True

        if attempt < max_attempts:
            print(f"⏳ Attendo {wait_seconds} secondi prima del nuovo tentativo...", flush=True)
            time.sleep(wait_seconds)

    print("❌ Sync remota fallita o day1 ancora incoerente dopo tutti i tentativi.", flush=True)
    return False


def run_quote_history(days, label):
    args = [
        sys.executable,
        "-u",
        str(BASE_DIR / "quote_history_updater.py"),
        "--days",
        ",".join(str(d) for d in days),
        "--label",
        label,
    ]
    print("🧠 Aggiorno quote_history:", " ".join(args), flush=True)
    result = subprocess.run(args, cwd=str(BASE_DIR))
    if result.returncode != 0:
        print("⚠️ Aggiornamento quote_history terminato con errore.", flush=True)
    return result.returncode


# =========================
# RUN MODES
# =========================
def run_night():
    print("🌙 RUNNER: backup file live prima del night scan...", flush=True)
    archive_live_files()

    print("🌙 RUNNER: avvio build multi-day notturna...", flush=True)
    app.HORIZON = 1
    app.run_nightly_multiday_build()
    print("✅ RUNNER: build multi-day completata.", flush=True)

    synced = sync_remote_outputs_to_local()
    if not synced:
        print("❌ Interrompo: i file remoti non sono coerenti, evito di sporcare quote_history.", flush=True)
        return 1

    result = run_quote_history([1, 2, 3, 4, 5], "night")
    return result


def run_mid_day1():
    print("☀️ RUNNER: avvio refresh centrale Day1...", flush=True)
    app.HORIZON = 1
    app.run_full_scan(horizon=1, snap=False, update_main_site=True, show_success=False)
    print("✅ RUNNER: refresh centrale Day1 completato.", flush=True)

    synced = sync_remote_outputs_to_local()
    if not synced:
        print("❌ Interrompo: i file remoti non sono coerenti dopo mid-day1.", flush=True)
        return 1

    result = run_quote_history([1], "mid_day1")
    return result


def run_evening_multi():
    print("🌆 RUNNER: avvio refresh serale multi-day (Day1..Day4)...", flush=True)
    app.HORIZON = 4
    app.run_full_scan(horizon=4, snap=False, update_main_site=True, show_success=False)
    print("✅ RUNNER: refresh serale multi-day completato.", flush=True)

    synced = sync_remote_outputs_to_local()
    if not synced:
        print("❌ Interrompo: i file remoti non sono coerenti dopo evening-multi.", flush=True)
        return 1

    result = run_quote_history([1, 2, 3, 4], "evening_multi")
    return result


def main():
    args = sys.argv[1:]

    if "--night" in args:
        return run_night()

    if "--mid-day1" in args:
        return run_mid_day1()

    if "--evening-multi" in args:
        return run_evening_multi()

    print("❌ Argomento non valido. Usa: --night | --mid-day1 | --evening-multi", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())

import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAX_RETRY = 2


def run_night():
    cmd = [sys.executable, "-u", str(BASE_DIR / "3appDays_runner.py"), "--night"]
    print("🚀 Night Scan Guard")
    print("▶ Eseguo:", " ".join(cmd), flush=True)

    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    return result.returncode


def main():
    for attempt in range(MAX_RETRY + 1):
        code = run_night()

        if code == 0:
            print("✅ Night scan completato con successo.", flush=True)
            sys.exit(0)

        if attempt < MAX_RETRY:
            print(f"⚠️ Tentativo {attempt + 1} fallito. Riprovo tra 30 secondi...", flush=True)
            time.sleep(30)

    print("❌ Night scan fallito definitivamente.", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()

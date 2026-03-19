from pathlib import Path
import shutil

BASE_DIR = Path(__file__).resolve().parent
ARCHIVES_DIR = BASE_DIR / "archives"
KEEP_LAST = 7


def main():
    if not ARCHIVES_DIR.exists():
        print("📁 Nessuna cartella archives presente.")
        return

    folders = [p for p in ARCHIVES_DIR.iterdir() if p.is_dir()]
    folders = sorted(folders, key=lambda p: p.name)

    total = len(folders)
    print(f"📦 Snapshot archives trovati: {total}")

    if total <= KEEP_LAST:
        print(f"✅ Nessuna pulizia necessaria. Tengo gli ultimi {KEEP_LAST}.")
        return

    to_delete = folders[:-KEEP_LAST]

    for folder in to_delete:
        print(f"🗑️ Elimino: {folder.name}")
        shutil.rmtree(folder, ignore_errors=True)

    print(f"✅ Pulizia completata. Rimangono gli ultimi {KEEP_LAST} snapshot.")


if __name__ == "__main__":
    main()

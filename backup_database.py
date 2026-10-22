
from pathlib import Path
from datetime import datetime
import sqlite3

PROJECT_DIR = Path(__file__).resolve().parent
DATABASE = PROJECT_DIR / "tasks.db"
BACKUP_DIR = PROJECT_DIR / "backups"
MAX_BACKUPS = 10


def main():
    if not DATABASE.exists():
        raise FileNotFoundError(f"Database not found: {DATABASE}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"tasks-backup-{timestamp}.db"

    with sqlite3.connect(DATABASE) as source:
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)

    # Verify that the backup opens and passes SQLite integrity checks.
    with sqlite3.connect(backup_path) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            backup_path.unlink(missing_ok=True)
            raise RuntimeError(f"Backup integrity check failed: {result}")

    backups = sorted(
        BACKUP_DIR.glob("tasks-backup-*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for old_backup in backups[MAX_BACKUPS:]:
        old_backup.unlink()

    print(f"Backup created: {backup_path}")
    print("Integrity check: OK")
    print(f"Backups retained: {min(len(backups), MAX_BACKUPS)}")


if __name__ == "__main__":
    main()

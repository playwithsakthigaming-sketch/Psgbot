import shutil
import time
import os

DB_FILE = "bot.db"
BACKUP_DIR = "db_backups"

# ===============================
# CONFIG
# ===============================
MAX_BACKUPS = 50   # keep latest 50 backups only

# ===============================
# CREATE BACKUP
# ===============================
def backup_db():
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError("bot.db not found")

    os.makedirs(BACKUP_DIR, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"bot_{ts}.db")

    shutil.copyfile(DB_FILE, backup_path)

    cleanup_old_backups()
    return backup_path

# ===============================
# RESTORE BACKUP
# ===============================
def restore_backup(filename: str):
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError("Backup file not found")

    shutil.copyfile(path, DB_FILE)

# ===============================
# LIST BACKUPS WITH SIZE
# ===============================
def list_backups_with_size():
    if not os.path.exists(BACKUP_DIR):
        return []

    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.endswith(".db"):
            path = os.path.join(BACKUP_DIR, f)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            backups.append((f, round(size_mb, 2)))

    # newest first
    backups.sort(reverse=True)
    return backups

# ===============================
# AUTO CLEANUP OLD BACKUPS
# ===============================
def cleanup_old_backups():
    files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
        reverse=True
    )

    if len(files) <= MAX_BACKUPS:
        return

    for old in files[MAX_BACKUPS:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except:
            pass

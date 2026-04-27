import logging
import logging.handlers
import os
import sys

# --- Logging-Setup --------------------------------------------------------
# Debug-File: max. 50 MB total (25 MB pro Datei × 2 Backups).
# In die Datei landet alles ab DEBUG, in die Konsole nur INFO+.
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_PATH = os.path.join(_LOG_DIR, "stszza.log")

_fmt = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_root = logging.getLogger()
_root.setLevel(logging.DEBUG)
# Vorhandene Handler entfernen (idempotent bei Reload)
for _h in list(_root.handlers):
    _root.removeHandler(_h)

_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(_fmt)
_root.addHandler(_console)

_file = logging.handlers.RotatingFileHandler(
    _LOG_PATH,
    maxBytes=25 * 1024 * 1024,   # 25 MB
    backupCount=1,                # + .1-Backup → max ~50 MB total
    encoding="utf-8",
)
_file.setLevel(logging.DEBUG)
_file.setFormatter(_fmt)
_root.addHandler(_file)

logging.getLogger(__name__).info("Logging initialized → %s", _LOG_PATH)

from sts_zza.gui.app import run_app

if __name__ == "__main__":
    sys.exit(run_app())

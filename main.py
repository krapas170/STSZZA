import logging
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from sts_zza.gui.app import run_app

if __name__ == "__main__":
    sys.exit(run_app())

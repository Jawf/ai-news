"""
run_once.py - Headless single job runner (no GUI)
Use this with Windows Task Scheduler as an alternative to the GUI scheduler.

Usage:
    python run_once.py
"""

import sys
import logging
import datetime
import os

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(LOG_DIR, f"job_{datetime.date.today().strftime('%Y%m%d')}.log"),
            encoding="utf-8",
        ),
    ],
)

from job_runner import load_config, run_job
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")


def main():
    config = load_config(CONFIG_PATH)
    result = run_job(config)

    # Update state
    state = {}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            pass

    state["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["last_result"] = "success" if result["success"] else "failed"
    state["run_count"] = state.get("run_count", 0) + 1

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()

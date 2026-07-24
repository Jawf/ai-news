"""run_once.py - 无 GUI 单次抓取入口（配 Windows 任务计划用）。

Usage: uv run python run_once.py
"""
import sys

from ainews.cli import main

if __name__ == "__main__":
    sys.exit(main(["fetch-once"]))

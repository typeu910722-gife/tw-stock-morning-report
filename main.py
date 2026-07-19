from __future__ import annotations
import json
import logging
import sys
import webbrowser
from pathlib import Path
from src.pipeline import run_pipeline

BASE = Path(__file__).resolve().parent
(BASE / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(BASE / "logs" / "report.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

def load_config() -> dict:
    return json.loads((BASE / "config.json").read_text(encoding="utf-8"))

if __name__ == "__main__":
    cfg = load_config()
    try:
        output = run_pipeline(BASE, cfg)
        print(f"\n[完成] {output}")
        if cfg.get("open_report_after_run", True):
            webbrowser.open(output.as_uri())
    except Exception:
        logging.exception("執行失敗")
        print("\n[失敗] 請查看 logs\\report.log")
        raise

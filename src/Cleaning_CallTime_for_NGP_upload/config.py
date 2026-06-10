import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("CALLTIME_NGP_DATA_ROOT", REPO_ROOT / "data"))

RAW_DATA_DIR = DATA_ROOT / "Raw Data"
OUTPUT_DIR = DATA_ROOT / "Data"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

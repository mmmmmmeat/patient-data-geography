from __future__ import annotations

import csv
import sys
import tempfile
import zipfile
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
STATS_DIR = BASE_DIR / "stats"
RAW_CSDDA_DIR = STATS_DIR / "statcan" / "raw" / "csdda"
RAW_FSA_DIR = STATS_DIR / "statcan" / "raw" / "fsa"
STATS_LINKS_FILE = STATS_DIR / "stats links.csv"


def load_links() -> dict[str, str]:
    if not STATS_LINKS_FILE.exists():
        raise FileNotFoundError(f"Missing stats links file: {STATS_LINKS_FILE}")
    mapping: dict[str, str] = {}
    with STATS_LINKS_FILE.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                mapping[row[0].strip().upper()] = row[1].strip()
    return mapping


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}) as response:
        response.raise_for_status()
        with destination.open("wb") as target:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    target.write(chunk)


def unzip_into(zip_path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination_dir)


def download_raw_bundle(key: str, url: str, destination_dir: Path) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / f"{key.lower()}.download"
        print(f"Downloading {key} raw census data...")
        download_file(url, tmp_path)
        if zipfile.is_zipfile(tmp_path):
            print(f"Extracting {key} raw census data...")
            unzip_into(tmp_path, destination_dir)
        else:
            print(f"Saving {key} raw census data...")
            destination_dir.mkdir(parents=True, exist_ok=True)
            target = destination_dir / f"{key.lower()}.csv"
            target.write_bytes(tmp_path.read_bytes())


def main() -> None:
    links = load_links()
    if "CSD_DA" in links:
        download_raw_bundle("CSD_DA", links["CSD_DA"], RAW_CSDDA_DIR)
    if "FSA" in links:
        download_raw_bundle("FSA", links["FSA"], RAW_FSA_DIR)

    if not any(RAW_CSDDA_DIR.rglob("*.csv")) and not any(RAW_FSA_DIR.rglob("*.csv")):
        raise RuntimeError("Raw census download finished but no raw CSV files were detected.")

    print("Raw census download complete.")


if __name__ == "__main__":
    raise SystemExit(main())

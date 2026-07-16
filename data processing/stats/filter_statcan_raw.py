from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
STATS_DIR = BASE_DIR / "stats"
RAW_CSDDA_DIR = STATS_DIR / "statcan" / "raw" / "csdda"
RAW_FSA_DIR = STATS_DIR / "statcan" / "raw" / "fsa"
FILTERED_DIR = STATS_DIR / "statcan" / "filtered"
CHAR_IDS_PATH = STATS_DIR / "characteristic_ids.csv"

CHUNK_SIZE = 100_000
OUTPUT_DA = FILTERED_DIR / "DA_filtered.csv"
OUTPUT_CSD = FILTERED_DIR / "CSD_filtered.csv"
OUTPUT_FSA = FILTERED_DIR / "FSA_filtered.csv"

SOURCE_KEYWORDS = [
    "atlantic",
    "britishcolumbia",
    "ontario",
    "prairies",
    "quebec",
    "territories",
]

GEO_LEVEL_DA = "Dissemination area"
GEO_LEVEL_CSD = "Census subdivision"
GEO_LEVEL_FSA = "Forward sortation area"


def load_characteristic_ids() -> set[str]:
    if not CHAR_IDS_PATH.exists():
        raise FileNotFoundError(f"Missing characteristic ID list: {CHAR_IDS_PATH}")
    with CHAR_IDS_PATH.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        return {row[0].strip() for row in reader if row and row[0].strip()}


def list_matching_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    matches: list[Path] = []
    for path in folder.rglob("*.csv"):
        name = path.name.lower()
        if any(keyword in name for keyword in SOURCE_KEYWORDS):
            matches.append(path)
    return sorted(matches)


def list_fsa_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    matches: list[Path] = []
    for path in folder.rglob("*.csv"):
        name = path.name.lower()
        if "readme" in name or "meta" in name:
            continue
        matches.append(path)
    return sorted(matches)


def count_rows(path: Path) -> int:
    with path.open("r", encoding="ISO-8859-1", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def print_progress(current: int, total: int, label: str) -> None:
    if total <= 0:
        return
    width = 30
    filled = int(width * current / total)
    bar = "=" * filled + "-" * (width - filled)
    percent = (current / total) * 100
    sys.stdout.write(f"\r{label} [{bar}] {percent:6.2f}% ({current}/{total})")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


def append_filtered(chunk: pd.DataFrame, output_path: Path, first_write: bool) -> bool:
    chunk.to_csv(output_path, mode="w" if first_write else "a", index=False, header=first_write)
    return False


def filter_csdda_files(char_ids: set[str]) -> None:
    files = list_matching_files(RAW_CSDDA_DIR)
    if not files:
        return

    first_da = True
    first_csd = True
    for path in files:
        total = count_rows(path)
        processed = 0
        for chunk in pd.read_csv(path, chunksize=CHUNK_SIZE, dtype=str, encoding="ISO-8859-1"):
            if "CHARACTERISTIC_ID" not in chunk.columns or "GEO_LEVEL" not in chunk.columns:
                processed += len(chunk)
                print_progress(processed, total, path.name)
                continue

            chunk["CHARACTERISTIC_ID"] = chunk["CHARACTERISTIC_ID"].astype(str).str.strip()
            chunk["GEO_LEVEL"] = chunk["GEO_LEVEL"].astype(str).str.strip()
            filtered = chunk[chunk["CHARACTERISTIC_ID"].isin(char_ids)]

            da_chunk = filtered[filtered["GEO_LEVEL"].str.contains(GEO_LEVEL_DA, case=False, na=False)]
            csd_chunk = filtered[filtered["GEO_LEVEL"].str.contains(GEO_LEVEL_CSD, case=False, na=False)]

            if not da_chunk.empty:
                first_da = append_filtered(da_chunk, OUTPUT_DA, first_da)
            if not csd_chunk.empty:
                first_csd = append_filtered(csd_chunk, OUTPUT_CSD, first_csd)

            processed += len(chunk)
            print_progress(processed, total, path.name)


def filter_fsa_files(char_ids: set[str]) -> None:
    files = list_fsa_files(RAW_FSA_DIR)
    if not files:
        return

    first_fsa = True
    for path in files:
        total = count_rows(path)
        processed = 0
        for chunk in pd.read_csv(path, chunksize=CHUNK_SIZE, dtype=str, encoding="ISO-8859-1"):
            if "CHARACTERISTIC_ID" not in chunk.columns:
                processed += len(chunk)
                print_progress(processed, total, path.name)
                continue

            chunk["CHARACTERISTIC_ID"] = chunk["CHARACTERISTIC_ID"].astype(str).str.strip()
            filtered = chunk[chunk["CHARACTERISTIC_ID"].isin(char_ids)]
            if not filtered.empty:
                first_fsa = append_filtered(filtered, OUTPUT_FSA, first_fsa)

            processed += len(chunk)
            print_progress(processed, total, path.name)


def main() -> None:
    FILTERED_DIR.mkdir(parents=True, exist_ok=True)
    for path in [OUTPUT_DA, OUTPUT_CSD, OUTPUT_FSA]:
        if path.exists():
            path.unlink()

    char_ids = load_characteristic_ids()
    filter_csdda_files(char_ids)
    filter_fsa_files(char_ids)


if __name__ == "__main__":
    main()

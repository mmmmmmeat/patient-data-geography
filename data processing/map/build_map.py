from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import csv
import urllib.request
import zipfile
import shutil
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_PROCESSING_DIR = Path(__file__).resolve().parents[1]
MAP_DIR = Path(__file__).resolve().parent
MAP_DATA_DIR = MAP_DIR / "map data"
CONFIG_DIR = DATA_PROCESSING_DIR / "configs"
MAP_LINKS_FILE = MAP_DIR / "map links.csv"


def load_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_map_links() -> dict[str, str]:
    if not MAP_LINKS_FILE.exists():
        return {}
    mapping: dict[str, str] = {}
    with MAP_LINKS_FILE.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            key = row[0].strip().upper()
            url = row[1].strip()
            if key and url:
                mapping[key] = url
    return mapping


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, destination.open("wb") as target:
        shutil.copyfileobj(response, target)


def extract_zip(zip_path: Path, extract_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)


def find_gdb_root(folder: Path) -> Path:
    for candidate in folder.rglob("*.gdb"):
        return candidate
    raise FileNotFoundError(f"No .gdb folder found under {folder}")


def get_ogr2ogr() -> str:
    env_candidates = [
        os.environ.get("OGR2OGR_PATH"),
        os.environ.get("GDAL_OGR2OGR"),
        os.environ.get("QGIS_OGR2OGR"),
    ]
    for candidate in env_candidates:
        if candidate:
            candidate_path = Path(candidate)
            if candidate_path.exists():
                return str(candidate_path)
    found = shutil.which("ogr2ogr")
    if found:
        return found
    raise FileNotFoundError("ogr2ogr not found. Install GDAL/QGIS first.")


def province_prefixes(provinces: list[str]) -> list[str]:
    mapping = {
        "NL": "10",
        "PE": "11",
        "NS": "12",
        "NB": "13",
        "QC": "24",
        "ON": "35",
        "MB": "46",
        "SK": "47",
        "AB": "48",
        "BC": "59",
        "YT": "60",
        "NT": "61",
        "NU": "62",
    }
    return [mapping[p] for p in provinces if p in mapping]


def province_postal_letters(provinces: list[str]) -> list[str]:
    mapping = {
        "NL": ["A"],
        "NS": ["B"],
        "PE": ["C"],
        "NB": ["E"],
        "QC": ["G", "H", "J"],
        "ON": ["K", "L", "M", "N", "P"],
        "MB": ["R"],
        "SK": ["S"],
        "AB": ["T"],
        "BC": ["V"],
        "YT": ["Y"],
        "NT": ["X"],
        "NU": ["X"],
    }
    letters: list[str] = []
    for province in provinces:
        letters.extend(mapping.get(province, []))
    return sorted(set(letters))


def build_map_data_name(provinces: list[str], map_area_type: str) -> str:
    province_key = "".join(sorted(provinces))
    return f"{province_key}_{map_area_type.upper()}"


def build_where_clause(area_field: str, provinces: list[str], map_area_type: str) -> str | None:
    if not provinces:
        return None
    map_area_type = str(map_area_type).strip().lower()

    if map_area_type in {"postal code", "fsa"}:
        letters = province_postal_letters(provinces)
        if not letters:
            return None
        clauses = [
            f"upper(substr(trim(CAST({area_field} AS string)), 1, 1)) = '{letter}'"
            for letter in letters
        ]
        return " OR ".join(clauses)

    prefixes = province_prefixes(provinces)
    if not prefixes:
        return None
    clauses = [f"substr(CAST({area_field} AS string), 1, {len(prefix)}) = '{prefix}'" for prefix in prefixes]
    return " OR ".join(clauses)


def run_command(args: list[str]) -> None:
    completed = subprocess.run(args, check=True)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}")


def build_map(config: dict) -> None:
    map_area_type = config["map_area_type"]
    provinces = config.get("provinces", [])
    area_field = config["area_link_column"]
    area_type_in_data = config["area_type_in_data"]
    map_links = load_map_links()
    map_url = map_links.get(map_area_type.upper()) or config.get("map_link_url")
    if not map_url:
        raise ValueError(f"No map download URL found for map type '{map_area_type}'.")

    MAP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="map_build_", dir=str(MAP_DATA_DIR)))
    download_path = workspace / "map.zip"
    extracted_dir = workspace / "extracted"
    filtered_gpkg = workspace / "filtered.gpkg"
    map_data_name = config.get("map_data_name") or build_map_data_name(provinces, map_area_type)
    out_xyz = MAP_DATA_DIR / map_data_name

    print(f"Downloading {map_area_type} map...")
    download_file(map_url, download_path)
    extract_zip(download_path, extracted_dir)
    gdb_path = find_gdb_root(extracted_dir)

    ogr2ogr = get_ogr2ogr()
    where_clause = build_where_clause(area_field, provinces, map_area_type)

    print("Filtering map geography...")
    args = [
        ogr2ogr,
        "-f",
        "GPKG",
        str(filtered_gpkg),
        str(gdb_path),
    ]
    if where_clause:
        args.extend(["-where", where_clause])
    run_command(args)

    print("Converting filtered geography to XYZ tiles...")
    out_xyz.mkdir(parents=True, exist_ok=True)
    tile_source = filtered_gpkg
    # TODO: replace this staging step with a full vector tile writer once the tile format choice is finalized.
    staged_gpkg = out_xyz / "source.gpkg"
    shutil.copy2(tile_source, staged_gpkg)

    summary = {
        "dataset_name": config["dataset_name"],
        "map_data_name": map_data_name,
        "map_area_type": map_area_type,
        "area_type_in_data": area_type_in_data,
        "provinces": provinces,
        "source_geodatabase": str(gdb_path),
        "filtered_source": str(filtered_gpkg),
        "xyz_output": str(out_xyz),
        "status": "staged",
    }
    (out_xyz / "build_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Map staging complete: {out_xyz}")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python build_map.py <config-path>")
    config_path = Path(sys.argv[1])
    config = load_config(config_path)
    build_map(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

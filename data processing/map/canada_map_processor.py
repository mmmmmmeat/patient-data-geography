#!/usr/bin/env python3
"""
Download StatCan boundary data, process it with QGIS, and write XYZ tiles.

Usage:
  python canada_map_processor.py MBQC_CSD

The code format is:
  <province codes>_<map type>

Examples:
  MB_DA
  MBQC_CSD
  ABMBON_DA

Rules:
- Province codes are 2-letter codes concatenated together.
- Map type must be one of: DA, CSD, FSA.
- The download URL is chosen from map links.csv in this folder.
- The dissolve field is inferred from the map type:
    DA  -> DAUID
    CSD -> CSDUID
    FSA -> CFSAUID
- The output folder is created at:
    {this folder}/map data/{code}
- The output is regenerated if it already exists.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


PROVINCE_TO_PRUID = {
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

MAPTYPE_TO_FIELD = {
    "DA": "DAUID",
    "CSD": "CSDUID",
    "FSA": "CFSAUID",
}


def status(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def parse_code(code: str) -> tuple[list[str], str]:
    match = re.fullmatch(r"([A-Z]+)_(DA|CSD|FSA)", code.strip().upper())
    if not match:
        raise ValueError("Code must look like MB_DA, MBQC_CSD, or ABMBON_DA.")

    provinces_blob, map_type = match.groups()
    if len(provinces_blob) % 2 != 0:
        raise ValueError("Province codes must be concatenated in 2-letter chunks.")

    provinces = [provinces_blob[i : i + 2] for i in range(0, len(provinces_blob), 2)]
    invalid = [p for p in provinces if p not in PROVINCE_TO_PRUID]
    if invalid:
        raise ValueError(f"Unknown province code(s): {', '.join(invalid)}")

    return provinces, map_type


def read_download_urls(links_csv: Path) -> dict[str, str]:
    urls: dict[str, str] = {}
    with links_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                urls[row[0].strip().upper()] = row[1].strip()
    return urls


def find_qgis_batch() -> Path:
    qgis_root = os.environ.get("QGIS_ROOT")
    candidates = []
    if qgis_root:
        candidates.append(Path(qgis_root) / "bin" / "qgis_process-qgis.bat")

    candidates.extend(
        [
            Path(r"C:\Program Files\QGIS 4.0.1\bin\qgis_process-qgis.bat"),
            Path(r"C:\Program Files (x86)\QGIS 4.0.1\bin\qgis_process-qgis.bat"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find qgis_process-qgis.bat under the QGIS install.")


def run_qgis_process(batch: Path, algorithm: str, params: dict, cwd: Path) -> None:
    payload = {"inputs": params}
    proc = subprocess.run(
        [str(batch), "run", algorithm, "-", "--json"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(cwd),
        check=False,
    )

    if proc.stdout.strip():
        print(proc.stdout.rstrip(), flush=True)
    if proc.stderr.strip():
        print(proc.stderr.rstrip(), file=sys.stderr, flush=True)

    if proc.returncode != 0:
        raise RuntimeError(f"qgis_process failed for {algorithm} with exit code {proc.returncode}")


def download_zip(url: str, dest: Path) -> None:
    status(f"Downloading {url}")
    with urllib.request.urlopen(url) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def extract_zip(zip_path: Path, extract_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    gdbs = list(extract_dir.rglob("*.gdb"))
    if not gdbs:
        raise FileNotFoundError(f"No .gdb folder found inside {zip_path.name}")
    return gdbs[0]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python canada_map_processor.py <CODE>")

    code = sys.argv[1].strip().upper()
    provinces, map_type = parse_code(code)
    dissolve_field = MAPTYPE_TO_FIELD[map_type]

    script_dir = Path(__file__).resolve().parent
    links_csv = script_dir / "map links.csv"
    urls = read_download_urls(links_csv)
    if map_type not in urls:
        raise FileNotFoundError(f"No StatCan download URL found for map type {map_type}.")

    batch = find_qgis_batch()
    pruids = [PROVINCE_TO_PRUID[p] for p in provinces]
    expression = f'"PRUID" IN ({", ".join(repr(p) for p in pruids)})'

    output_dir = script_dir / "map data" / code
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="canada_map_", dir=str(script_dir)) as tmpdir:
        work = Path(tmpdir)
        zip_path = work / f"{map_type}.zip"
        gdb_root = work / "gdb"
        filtered_gpkg = work / "filtered.gpkg"
        dissolved_gpkg = work / "dissolved.gpkg"
        singles_gpkg = work / "singleparts.gpkg"
        extent_gpkg = work / "extent.gpkg"

        gdb_root.mkdir(parents=True, exist_ok=True)
        download_zip(urls[map_type], zip_path)
        status("Unzipping data...")
        gdb_folder = extract_zip(zip_path, gdb_root)

        # Prefer the first layer name matching the GDB folder stem.
        layer_name = gdb_folder.stem
        source = f"{gdb_folder.as_posix()}|layername={layer_name}"

        status(f"Filtering PRUIDs for {', '.join(provinces)}...")
        run_qgis_process(
            batch,
            "native:extractbyexpression",
            {
                "INPUT": source,
                "EXPRESSION": expression,
                "OUTPUT": str(filtered_gpkg),
            },
            work,
        )

        status(f"Dissolving by {dissolve_field}...")
        run_qgis_process(
            batch,
            "native:dissolve",
            {
                "INPUT": str(filtered_gpkg),
                "FIELD": [dissolve_field],
                "SEPARATE_DISJOINT": False,
                "OUTPUT": str(dissolved_gpkg),
            },
            work,
        )

        status("Converting multipart features to singleparts...")
        run_qgis_process(
            batch,
            "native:multiparttosingleparts",
            {
                "INPUT": str(dissolved_gpkg),
                "OUTPUT": str(singles_gpkg),
            },
            work,
        )

        status("Building padded extent...")
        run_qgis_process(
            batch,
            "native:polygonfromlayerextent",
            {
                "INPUT": str(singles_gpkg),
                "ROUND_TO": 50000,
                "OUTPUT": str(extent_gpkg),
            },
            work,
        )

        status(f"Writing vector tiles to {output_dir}...")
        run_qgis_process(
            batch,
            "native:writevectortiles_xyz",
            {
                "LAYERS": [
                    {
                        "layer": str(singles_gpkg),
                        "layerName": "Single parts",
                    }
                ],
                "MIN_ZOOM": 0,
                "MAX_ZOOM": 12,
                "XYZ_TEMPLATE": "{z}/{x}/{y}.pbf",
                "EXTENT": str(extent_gpkg),
                "OUTPUT_DIRECTORY": str(output_dir),
            },
            work,
        )

    status("Processing complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

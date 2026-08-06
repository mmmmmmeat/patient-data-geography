"""Add population weights to a PCCF extract.

For each postal code, this script:
- finds all linked DA and CSD areas in the PCCF file
- looks up characteristic 1 (population) for each area in the filtered census file
- computes separate weights for DA and CSD as area population / total population for that postal code
- writes a new PCCF file with `weight_da` and `weight_csd` columns
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


DATA_PROCESSING_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = DATA_PROCESSING_DIR / "configs"
CURRENT_CONFIG_FILE = CONFIG_DIR / "current_config.json"
FILTERED_DA_CENSUS_PATH = DATA_PROCESSING_DIR / "stats" / "statcan" / "filtered" / "DA_filtered.csv"
FILTERED_CSD_CENSUS_PATH = DATA_PROCESSING_DIR / "stats" / "statcan" / "filtered" / "CSD_filtered.csv"

PCCF_POSTAL_COL = "POSTAL"
PCCF_DAUID_COL = "DAUID"
PCCF_CSDUID_COL = "CSDuid"
PCCF_CITY_COL = "CSDname"

PRAIRIES_GEO_COL = "ALT_GEO_CODE"
PRAIRIES_CHARACTERISTIC_ID_COL = "CHARACTERISTIC_ID"
PRAIRIES_VALUE_COL = "C1_COUNT_TOTAL"

POPULATION_CHARACTERISTIC_ID = "1"


def from_repo_path(value: str | Path | None) -> Path:
    if not value:
        return Path("")
    path = Path(value)
    if path.is_absolute():
        return path
    return (DATA_PROCESSING_DIR.parent / path).resolve()


def load_current_config() -> dict:
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
    else:
        if not CURRENT_CONFIG_FILE.exists():
            raise FileNotFoundError(
                f"Missing current config pointer: {CURRENT_CONFIG_FILE}. "
                "Run the dataset setup script first."
            )
        pointer = json.loads(CURRENT_CONFIG_FILE.read_text(encoding="utf-8"))
        config_path = from_repo_path(pointer["current_config"])
    if not config_path.exists():
        raise FileNotFoundError(f"Missing dataset config: {config_path}")
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_pccf(pccf_path: Path) -> pd.DataFrame:
    if not pccf_path.exists():
        raise FileNotFoundError(f"Missing PCCF file: {pccf_path}")
    return pd.read_excel(pccf_path, dtype=str, engine="openpyxl")


def load_prairies_data(prairies_path: Path) -> pd.DataFrame:
    if not prairies_path.exists():
        raise FileNotFoundError(f"Missing census file: {prairies_path}")

    population_by_geo: dict[str, float] = {}
    required_cols = {
        PRAIRIES_GEO_COL,
        PRAIRIES_CHARACTERISTIC_ID_COL,
        PRAIRIES_VALUE_COL,
    }

    for chunk in pd.read_csv(
        prairies_path,
        dtype=str,
        encoding="utf-8-sig",
        usecols=lambda col: col in required_cols,
        chunksize=500_000,
    ):
        missing = required_cols - set(chunk.columns)
        if missing:
            raise ValueError(
                "Census file is missing required columns: "
                + ", ".join(sorted(missing))
            )

        filtered = chunk[
            chunk[PRAIRIES_CHARACTERISTIC_ID_COL].astype(str) == POPULATION_CHARACTERISTIC_ID
        ][[PRAIRIES_GEO_COL, PRAIRIES_VALUE_COL]].copy()

        filtered[PRAIRIES_GEO_COL] = filtered[PRAIRIES_GEO_COL].astype(str).str.strip()
        filtered[PRAIRIES_VALUE_COL] = pd.to_numeric(filtered[PRAIRIES_VALUE_COL], errors="coerce")

        grouped = filtered.groupby(PRAIRIES_GEO_COL, dropna=False)[PRAIRIES_VALUE_COL].sum()
        for geo_id, population in grouped.items():
            if pd.isna(geo_id):
                continue
            population_by_geo[str(geo_id)] = population_by_geo.get(str(geo_id), 0.0) + float(
                population or 0
            )

    return pd.DataFrame(
        [(geo_id, population) for geo_id, population in population_by_geo.items()],
        columns=[PRAIRIES_GEO_COL, PRAIRIES_VALUE_COL],
    )


def attach_weight(pccf: pd.DataFrame, prairies: pd.DataFrame, geo_col: str, weight_col: str) -> pd.DataFrame:
    if geo_col not in pccf.columns:
        pccf[weight_col] = 0.0
        return pccf

    working = pccf.copy()
    working[geo_col] = working[geo_col].astype(str).str.strip()
    merged = working.merge(prairies, how="left", left_on=geo_col, right_on=PRAIRIES_GEO_COL)
    merged = merged.rename(columns={PRAIRIES_VALUE_COL: f"population_{weight_col}"})
    merged[f"population_{weight_col}"] = pd.to_numeric(merged[f"population_{weight_col}"], errors="coerce")
    totals = merged.groupby(PCCF_POSTAL_COL)[f"population_{weight_col}"].transform("sum")
    merged[weight_col] = merged[f"population_{weight_col}"] / totals
    merged[weight_col] = merged[weight_col].fillna(0)
    merged = merged.drop(columns=[PRAIRIES_GEO_COL, f"population_{weight_col}"], errors="ignore")
    return merged


def merge_weight_columns(base: pd.DataFrame, weighted: pd.DataFrame, weight_col: str) -> pd.DataFrame:
    if weight_col not in weighted.columns:
        base[weight_col] = 0.0
        return base
    keep = [PCCF_POSTAL_COL, weight_col]
    if PCCF_DAUID_COL in weighted.columns:
        keep.append(PCCF_DAUID_COL)
    if PCCF_CSDUID_COL in weighted.columns:
        keep.append(PCCF_CSDUID_COL)
    if PCCF_CITY_COL in weighted.columns:
        keep.append(PCCF_CITY_COL)
    tmp = weighted[keep].copy()
    if weight_col in base.columns:
        base = base.drop(columns=[weight_col], errors="ignore")
    return base.merge(tmp[[c for c in keep if c in tmp.columns]], on=[c for c in [PCCF_POSTAL_COL, PCCF_DAUID_COL if PCCF_DAUID_COL in tmp.columns and PCCF_DAUID_COL in base.columns else None, PCCF_CSDUID_COL if PCCF_CSDUID_COL in tmp.columns and PCCF_CSDUID_COL in base.columns else None] if c], how="left")


def main() -> None:
    config = load_current_config()
    if len(sys.argv) > 2:
        pccf_name = sys.argv[2]
        pccf_path = DATA_PROCESSING_DIR / "PCCF" / pccf_name
    else:
        pccf_path = from_repo_path(config["pccf_file"])
    if pccf_path.with_name(f"{pccf_path.stem} weighted{pccf_path.suffix}").exists():
        print(f"Weighted PCCF already exists for {pccf_path.name}. Skipping weighting.")
        return

    pccf = load_pccf(pccf_path)
    merged = pccf.copy()
    if FILTERED_DA_CENSUS_PATH.exists() and PCCF_DAUID_COL in merged.columns:
        da_prairies = load_prairies_data(FILTERED_DA_CENSUS_PATH)
        merged = attach_weight(merged, da_prairies, PCCF_DAUID_COL, "weight_da")
    else:
        merged["weight_da"] = 0.0
    if FILTERED_CSD_CENSUS_PATH.exists() and PCCF_CSDUID_COL in merged.columns:
        csd_prairies = load_prairies_data(FILTERED_CSD_CENSUS_PATH)
        merged = attach_weight(merged, csd_prairies, PCCF_CSDUID_COL, "weight_csd")
    else:
        merged["weight_csd"] = 0.0

    weighted_path = pccf_path.with_name(f"{pccf_path.stem} weighted{pccf_path.suffix}")
    merged.to_excel(weighted_path, index=False)
    print(f"Wrote weighted PCCF file to {weighted_path}")


if __name__ == "__main__":
    main()

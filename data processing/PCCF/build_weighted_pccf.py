"""Add DA population weights to a PCCF extract.

For each postal code, this script:
- finds all linked DAs in the PCCF file
- looks up characteristic 1 (population) for each DA in the filtered census file
- computes a weight as DA population / total population for that postal code
- writes a new PCCF file with a `weight` column
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


DATA_PROCESSING_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = DATA_PROCESSING_DIR / "configs"
CURRENT_CONFIG_FILE = CONFIG_DIR / "current_config.json"
FILTERED_CENSUS_PATH = DATA_PROCESSING_DIR / "stats" / "statcan" / "filtered" / "DA_filtered.csv"

PCCF_POSTAL_COL = "POSTAL"
PCCF_DAUID_COL = "DAUID"
PCCF_CITY_COL = "CSDname"

PRAIRIES_DAUID_COL = "ALT_GEO_CODE"
PRAIRIES_CHARACTERISTIC_ID_COL = "CHARACTERISTIC_ID"
PRAIRIES_VALUE_COL = "C1_COUNT_TOTAL"

POPULATION_CHARACTERISTIC_ID = "1"


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
        config_path = Path(pointer["current_config"])
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

    population_by_dauid: dict[str, float] = {}
    required_cols = {
        PRAIRIES_DAUID_COL,
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
        ][[PRAIRIES_DAUID_COL, PRAIRIES_VALUE_COL]].copy()

        filtered[PRAIRIES_DAUID_COL] = filtered[PRAIRIES_DAUID_COL].astype(str).str.strip()
        filtered[PRAIRIES_VALUE_COL] = pd.to_numeric(filtered[PRAIRIES_VALUE_COL], errors="coerce")

        grouped = filtered.groupby(PRAIRIES_DAUID_COL, dropna=False)[PRAIRIES_VALUE_COL].sum()
        for dauid, population in grouped.items():
            if pd.isna(dauid):
                continue
            population_by_dauid[str(dauid)] = population_by_dauid.get(str(dauid), 0.0) + float(
                population or 0
            )

    return pd.DataFrame(
        [(dauid, population) for dauid, population in population_by_dauid.items()],
        columns=[PRAIRIES_DAUID_COL, PRAIRIES_VALUE_COL],
    )


def main() -> None:
    config = load_current_config()
    if len(sys.argv) > 2:
        pccf_name = sys.argv[2]
        pccf_path = DATA_PROCESSING_DIR / "PCCF" / pccf_name
    else:
        pccf_path = Path(config["pccf_file"])
    if pccf_path.with_name(f"{pccf_path.stem} weighted{pccf_path.suffix}").exists():
        print(f"Weighted PCCF already exists for {pccf_path.name}. Skipping weighting.")
        return

    pccf = load_pccf(pccf_path)
    prairies = load_prairies_data(FILTERED_CENSUS_PATH)

    pccf[PCCF_DAUID_COL] = pccf[PCCF_DAUID_COL].astype(str).str.strip()

    merged = pccf.merge(
        prairies,
        how="left",
        left_on=PCCF_DAUID_COL,
        right_on=PRAIRIES_DAUID_COL,
    )

    merged = merged.rename(columns={PRAIRIES_VALUE_COL: "population"})
    merged["population"] = pd.to_numeric(merged["population"], errors="coerce")

    postal_totals = merged.groupby(PCCF_POSTAL_COL)["population"].transform("sum")
    merged["weight"] = merged["population"] / postal_totals

    merged["weight"] = merged["weight"].fillna(0)
    merged = merged.drop(columns=[PRAIRIES_DAUID_COL], errors="ignore")

    weighted_path = pccf_path.with_name(f"{pccf_path.stem} weighted{pccf_path.suffix}")
    merged.to_excel(weighted_path, index=False)
    print(f"Wrote weighted PCCF file to {weighted_path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PROCESSING_DIR = Path(__file__).resolve().parent
CONFIG_DIR = DATA_PROCESSING_DIR / "configs"
CURRENT_CONFIG_FILE = CONFIG_DIR / "current_config.json"
MERGED_DATA_DIR = DATA_PROCESSING_DIR / "map" / "merged data"
FILTERED_CENSUS_PATH = DATA_PROCESSING_DIR / "stats" / "statcan" / "filtered" / "DA_filtered.csv"

PCCF_POSTAL_COL = "POSTAL"
PCCF_DAUID_COL = "DAUID"
PCCF_FSA_COL = "FSA"
PCCF_CSDUID_COL = "CSDuid"
PCCF_CITY_COL = "CSDname"
PCCF_WEIGHT_COL = "weight"

PRAIRIE_DA_COL = "ALT_GEO_CODE"
PRAIRIE_ID_COL = "CHARACTERISTIC_ID"
PRAIRIE_COUNT_COL = "C1_COUNT_TOTAL"
PRAIRIE_RATE_COL = "C10_RATE_TOTAL"

RAW_POSTAL_COL = "patient_link"
RAW_SEX_COL = "sex"
RAW_AGE_COL = "age"
RAW_TBSA_COL = "tbsa"
RAW_ICU_COL = "icu_days"

SDOH_IDS = [
    "113", "1451", "1441", "1442", "1443", "1444", "1445", "1446", "1447", "1448",
    "1976", "1997", "2229", "76", "77", "86", "1666", "1667", "1668", "2604",
    "2612", "2613", "2614", "2615", "2616",
]


def load_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_current_config_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    if not CURRENT_CONFIG_FILE.exists():
        raise FileNotFoundError(f"Missing current config pointer: {CURRENT_CONFIG_FILE}")
    payload = json.loads(CURRENT_CONFIG_FILE.read_text(encoding="utf-8"))
    return Path(payload["current_config"])


def normalize_postal_code(value: object) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def normalize_geo_id(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def map_geo_key(value: object, map_area_type: str) -> str:
    postal = normalize_postal_code(value)
    if map_area_type == "fsa":
        return postal[:3]
    return postal


def group_key_from_row(row: pd.Series, map_area_type: str) -> str | None:
    if map_area_type == "da":
        return normalize_geo_id(row.get(PCCF_DAUID_COL))
    if map_area_type == "csd":
        return normalize_geo_id(row.get(PCCF_CSDUID_COL))
    if map_area_type == "fsa":
        return normalize_postal_code(row.get(PCCF_FSA_COL))[:3]
    return None


def to_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_to_100(series: pd.Series, invert: bool = False) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    min_value = numeric.min()
    max_value = numeric.max()
    value_range = max_value - min_value
    if pd.isna(min_value) or pd.isna(max_value) or value_range == 0:
        return pd.Series([np.nan] * len(series), index=series.index)
    normalized = (numeric - min_value) * (100.0 / value_range)
    return 100.0 - normalized if invert else normalized


def load_raw_records(
    path: Path,
    patient_link: str,
    age_col: str | None,
    sex_col: str | None,
    length_of_stay_col: str | None,
    binary_outcomes: list[dict],
    numeric_outcomes: list[dict],
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing patient file: {path}")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")

    keep_cols = [patient_link]
    for col in [age_col, sex_col, length_of_stay_col]:
        if col:
            keep_cols.append(col)
    for item in binary_outcomes + numeric_outcomes:
        keep_cols.append(item["raw_column"])
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].copy()
    df[patient_link] = df[patient_link].map(normalize_postal_code)
    if age_col and age_col in df.columns:
        df[age_col] = pd.to_numeric(df[age_col], errors="coerce")
    if sex_col and sex_col in df.columns:
        df[sex_col] = df[sex_col].astype(str).str.strip().str.upper()
    if length_of_stay_col and length_of_stay_col in df.columns:
        df[length_of_stay_col] = pd.to_numeric(df[length_of_stay_col], errors="coerce")
    return df


def load_weighted_pccf(pccf_path: Path) -> pd.DataFrame:
    if not pccf_path.exists():
        raise FileNotFoundError(f"Missing weighted PCCF file: {pccf_path}")
    df = pd.read_excel(pccf_path, dtype=str, engine="openpyxl")
    df[PCCF_POSTAL_COL] = df[PCCF_POSTAL_COL].map(normalize_postal_code)
    df[PCCF_DAUID_COL] = df[PCCF_DAUID_COL].astype(str).str.strip()
    if PCCF_CSDUID_COL in df.columns:
        df[PCCF_CSDUID_COL] = df[PCCF_CSDUID_COL].astype(str).str.strip()
    if PCCF_FSA_COL in df.columns:
        df[PCCF_FSA_COL] = df[PCCF_FSA_COL].astype(str).str.strip().str.upper().str[:3]
    if PCCF_CITY_COL in df.columns:
        df[PCCF_CITY_COL] = df[PCCF_CITY_COL].astype(str).str.strip()
        df = df.rename(columns={PCCF_CITY_COL: "csd_name"})
    df[PCCF_WEIGHT_COL] = pd.to_numeric(df[PCCF_WEIGHT_COL], errors="coerce")
    df = df.dropna(subset=[PCCF_DAUID_COL, PCCF_WEIGHT_COL])
    df = df[df[PCCF_WEIGHT_COL] > 0].copy()
    df[PCCF_WEIGHT_COL] = df.groupby(PCCF_POSTAL_COL)[PCCF_WEIGHT_COL].transform(lambda s: s / s.sum())
    return df


def pccf_has_weight_column(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        header = pd.read_excel(path, nrows=0, dtype=str)
    except Exception:
        return False
    return PCCF_WEIGHT_COL.lower() in {str(col).strip().lower() for col in header.columns}


def describe_pccf_candidate(path: Path) -> str:
    if not path.exists():
        return f"{path} [missing]"
    return f"{path} [weight column: {'yes' if pccf_has_weight_column(path) else 'no'}]"


def assign_records_to_geos(raw_df: pd.DataFrame, pccf: pd.DataFrame, patient_link: str, map_area_type: str) -> pd.DataFrame:
    rng = np.random.default_rng(20260508)
    raw_df = raw_df.copy()
    if map_area_type == "fsa":
        raw_df[PCCF_FSA_COL] = raw_df[patient_link].map(lambda value: map_geo_key(value, "fsa"))
        return raw_df[raw_df[PCCF_FSA_COL].astype(str).str.len() == 3].copy()

    group_col = PCCF_DAUID_COL if map_area_type == "da" else PCCF_CSDUID_COL
    pccf_groups = {
        postal: grp[[group_col, PCCF_WEIGHT_COL]].reset_index(drop=True)
        for postal, grp in pccf.groupby(PCCF_POSTAL_COL, sort=False)
    }

    parts: list[pd.DataFrame] = []
    for postal, group in raw_df.groupby(patient_link, sort=False):
        candidates = pccf_groups.get(postal)
        if candidates is None or candidates.empty:
            continue
        choices = rng.choice(
            candidates[group_col].to_numpy(),
            size=len(group),
            replace=True,
            p=candidates[PCCF_WEIGHT_COL].to_numpy(),
        )
        temp = group.copy()
        temp[group_col] = choices
        parts.append(temp)
    return pd.concat(parts, ignore_index=True) if parts else raw_df.iloc[0:0].copy()


def safe_mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.mean())


def safe_pct(series: pd.Series, denom: int) -> float | None:
    if denom <= 0:
        return None
    numeric = pd.to_numeric(series, errors="coerce").fillna(0)
    return float(numeric.sum() / denom * 100.0)


def build_patient_aggregation(assigned: pd.DataFrame, cfg: dict, map_area_type: str) -> pd.DataFrame:
    age_col = cfg.get("age_column")
    sex_col = cfg.get("sex_column")
    length_of_stay_col = cfg.get("length_of_stay_column")
    numeric_outcomes = cfg.get("numeric_outcomes", [])
    binary_outcomes = cfg.get("binary_outcomes", [])
    group_col = PCCF_DAUID_COL if map_area_type == "da" else PCCF_CSDUID_COL if map_area_type == "csd" else PCCF_FSA_COL

    if assigned.empty or group_col not in assigned.columns:
        return pd.DataFrame(columns=[group_col])

    rows = []
    for geo_id, g in assigned.groupby(group_col, sort=False):
        row: dict[str, object] = {group_col: geo_id}
        row["incidents_total"] = int(len(g))
        if sex_col and sex_col in g.columns:
            sex_values = g[sex_col].astype(str).str.upper()
            row["incidents_m"] = int((sex_values == "M").sum())
            row["incidents_f"] = int((sex_values == "F").sum())
        else:
            row["incidents_m"] = None
            row["incidents_f"] = None
        row["avg_age"] = safe_mean(g[age_col]) if age_col and age_col in g.columns else None
        if length_of_stay_col and length_of_stay_col in g.columns:
            row["avg_length_of_stay"] = safe_mean(g[length_of_stay_col])

        for outcome in binary_outcomes:
            raw_col = outcome["raw_column"]
            if raw_col not in g.columns:
                continue
            aff = outcome["affirmative_value"]
            mask = g[raw_col].astype(str).str.strip()
            base_name = outcome["name"]
            row[f"{base_name}_total"] = float((mask == aff).sum() / len(g) * 100.0) if len(g) else None
            if sex_col and sex_col in g.columns:
                sex_values = g[sex_col].astype(str).str.upper()
                male_mask = sex_values == "M"
                female_mask = sex_values == "F"
                row[f"{base_name}_m"] = float((mask[male_mask] == aff).sum() / max(male_mask.sum(), 1) * 100.0) if male_mask.any() else None
                row[f"{base_name}_f"] = float((mask[female_mask] == aff).sum() / max(female_mask.sum(), 1) * 100.0) if female_mask.any() else None

        for outcome in numeric_outcomes:
            raw_col = outcome["raw_column"]
            if raw_col in g.columns:
                base_name = outcome["name"]
                row[f"{base_name}_total"] = safe_mean(g[raw_col])
                if sex_col and sex_col in g.columns:
                    sex_values = g[sex_col].astype(str).str.upper()
                    row[f"{base_name}_m"] = safe_mean(g.loc[sex_values == "M", raw_col])
                    row[f"{base_name}_f"] = safe_mean(g.loc[sex_values == "F", raw_col])

        rows.append(row)
    return pd.DataFrame(rows)


def load_prairies_characteristics(dauids: set[str]) -> pd.DataFrame:
    if not FILTERED_CENSUS_PATH.exists():
        raise FileNotFoundError(f"Missing filtered census file: {FILTERED_CENSUS_PATH}")
    wide: dict[str, dict[str, float]] = defaultdict(dict)
    for chunk in pd.read_csv(FILTERED_CENSUS_PATH, dtype=str, encoding="utf-8-sig", chunksize=500_000):
        if PRAIRIE_DA_COL not in chunk.columns or PRAIRIE_ID_COL not in chunk.columns:
            continue
        chunk[PRAIRIE_DA_COL] = chunk[PRAIRIE_DA_COL].astype(str).str.strip()
        chunk[PRAIRIE_ID_COL] = chunk[PRAIRIE_ID_COL].astype(str).str.strip()
        sub = chunk[chunk[PRAIRIE_DA_COL].isin(dauids) & chunk[PRAIRIE_ID_COL].isin(SDOH_IDS)]
        for _, row in sub.iterrows():
            dauid = row[PRAIRIE_DA_COL]
            cid = row[PRAIRIE_ID_COL]
            if cid == "113":
                wide[dauid]["income_median"] = to_float(row.get(PRAIRIE_COUNT_COL))
            elif cid == "1451":
                wide[dauid]["major_repairs_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid in {"1441", "1442", "1443", "1444", "1445", "1446", "1447", "1448"}:
                wide[dauid][f"house_{cid}_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid == "1976":
                wide[dauid]["moved_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid == "1997":
                wide[dauid]["hs_complete_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid == "2229":
                wide[dauid]["employment_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid == "76":
                wide[dauid]["avg_family_size"] = to_float(row.get(PRAIRIE_COUNT_COL))
            elif cid == "77":
                wide[dauid]["avg_children"] = to_float(row.get(PRAIRIE_COUNT_COL))
            elif cid == "86":
                wide[dauid]["one_parent_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid in {"1666", "1667", "1668"}:
                wide[dauid][f"gen_{cid}_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid == "2604":
                wide[dauid]["car_commute_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
            elif cid in {"2612", "2613", "2614", "2615", "2616"}:
                wide[dauid][f"commute_{cid}_rate"] = to_float(row.get(PRAIRIE_RATE_COL))
    return pd.DataFrame.from_dict(wide, orient="index").reset_index().rename(columns={"index": PCCF_DAUID_COL})


def load_equivalence_scores() -> pd.DataFrame:
    equiv_path = DATA_PROCESSING_DIR / "stats" / "MSDI" / "1. EquivalenceTableCanada2021_en.xlsx"
    if not equiv_path.exists():
        raise FileNotFoundError(f"Missing equivalence table: {equiv_path}")
    df = pd.read_excel(equiv_path, sheet_name="Data", usecols=["DA", "SCOREMAT", "SCORESOC"], dtype={"DA": str})
    df = df.rename(columns={"DA": PCCF_DAUID_COL, "SCOREMAT": "dep_mat", "SCORESOC": "dep_soc"})
    df[PCCF_DAUID_COL] = df[PCCF_DAUID_COL].astype(str).str.strip()
    df["dep_mat"] = normalize_to_100(df["dep_mat"])
    df["dep_soc"] = normalize_to_100(df["dep_soc"])
    return df


def load_prairies_quintiles() -> pd.DataFrame:
    quint_path = DATA_PROCESSING_DIR / "stats" / "CIMD" / "can_scores_quintiles_EN.csv"
    if not quint_path.exists():
        raise FileNotFoundError(f"Missing quintiles file: {quint_path}")
    df = pd.read_csv(quint_path, dtype=str, encoding="utf-8-sig")
    df = df.rename(
        columns={
            "Dissemination Area (DA)": PCCF_DAUID_COL,
            "Residential instability Scores": "res_score",
            "Economic dependency Scores": "eco_score",
        }
    )
    df[PCCF_DAUID_COL] = df[PCCF_DAUID_COL].astype(str).str.strip()
    df["res_score"] = normalize_to_100(pd.to_numeric(df["res_score"], errors="coerce"))
    df["eco_score"] = normalize_to_100(pd.to_numeric(df["eco_score"], errors="coerce"))
    return df[[PCCF_DAUID_COL, "res_score", "eco_score"]]


def weighted_index(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    cols = list(weights.keys())
    existing_cols = [col for col in cols if col in df.columns]
    if not existing_cols:
        return pd.Series([np.nan] * len(df), index=df.index)
    vals = df[existing_cols].apply(pd.to_numeric, errors="coerce")
    weight_arr = np.array([weights[c] for c in existing_cols], dtype=float)
    denom = vals.notna().mul(weight_arr, axis=1).sum(axis=1)
    return vals.fillna(0).mul(weight_arr, axis=1).sum(axis=1) / denom.replace(0, np.nan)


def compute_sdoh_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    house_weights = {f"house_{cid}_rate": weight for cid, weight in zip(["1441","1442","1443","1444","1445","1446","1447","1448"], [8,7,6,5,4,3,2,1])}
    commute_weights = {"commute_2612_rate": 1, "commute_2613_rate": 2, "commute_2614_rate": 3, "commute_2615_rate": 4, "commute_2616_rate": 5}
    gen_weights = {"gen_1666_rate": 3, "gen_1667_rate": 2, "gen_1668_rate": 1}
    out["income_score"] = normalize_to_100(out["income_median"], invert=True) if "income_median" in out.columns else np.nan
    out["major_repairs_score"] = normalize_to_100(out["major_repairs_rate"]) if "major_repairs_rate" in out.columns else np.nan
    out["house_age_index"] = weighted_index(out, house_weights)
    out["house_age_score"] = normalize_to_100(out["house_age_index"])
    out["moved_score"] = normalize_to_100(out["moved_rate"]) if "moved_rate" in out.columns else np.nan
    housing_parts = [col for col in ["major_repairs_score", "house_age_score", "moved_score"] if col in out.columns]
    out["housing_score"] = out[housing_parts].mean(axis=1) if housing_parts else np.nan
    out["education_score"] = normalize_to_100(out["hs_complete_rate"], invert=True) if "hs_complete_rate" in out.columns else np.nan
    out["employment_score"] = normalize_to_100(out["employment_rate"]) if "employment_rate" in out.columns else np.nan
    out["family_size_score"] = normalize_to_100(out["avg_family_size"]) if "avg_family_size" in out.columns else np.nan
    out["children_score"] = normalize_to_100(out["avg_children"]) if "avg_children" in out.columns else np.nan
    out["one_parent_score"] = normalize_to_100(out["one_parent_rate"]) if "one_parent_rate" in out.columns else np.nan
    family_parts = [col for col in ["family_size_score", "children_score", "one_parent_score"] if col in out.columns]
    out["family_score"] = out[family_parts].mean(axis=1) if family_parts else np.nan
    out["generation_index"] = weighted_index(out, gen_weights)
    out["generation_score"] = normalize_to_100(out["generation_index"])
    out["car_commute_score"] = normalize_to_100(out["car_commute_rate"], invert=True) if "car_commute_rate" in out.columns else np.nan
    out["commute_time_index"] = weighted_index(out, commute_weights)
    out["commute_time_score"] = normalize_to_100(out["commute_time_index"])
    commute_parts = [col for col in ["car_commute_score", "commute_time_score"] if col in out.columns]
    out["commute_score"] = out[commute_parts].mean(axis=1) if commute_parts else np.nan
    score_cols = [col for col in ["income_score", "housing_score", "education_score", "employment_score", "family_score", "generation_score", "commute_score", "dep_mat", "dep_soc", "res_score", "eco_score"] if col in out.columns]
    out["sdoh_total_score"] = out[score_cols].mean(axis=1) if score_cols else np.nan
    return out


def build_base_table(pccf: pd.DataFrame) -> pd.DataFrame:
    base = pccf.copy()
    base = base.drop_duplicates()
    return base


def main() -> None:
    config_path = load_current_config_path()
    config = load_config(config_path)
    raw_path = Path(config["patient_data_file"])
    pccf_raw_path = Path(config["pccf_file"])
    pccf_weighted_path = pccf_raw_path.with_name(f"{pccf_raw_path.stem} weighted{pccf_raw_path.suffix}")
    map_area_type = str(config.get("map_area_type", "map")).strip().lower() or "map"
    patient_link = config["area_link_column"]
    age_col = config.get("age_column")
    sex_col = config.get("sex_column")
    length_of_stay_col = config.get("length_of_stay_column")

    print("Checking PCCF candidates:")
    print(f"  weighted: {describe_pccf_candidate(pccf_weighted_path)}")
    print(f"  raw:      {describe_pccf_candidate(pccf_raw_path)}")

    raw_df = load_raw_records(
        raw_path,
        patient_link,
        age_col,
        sex_col,
        length_of_stay_col,
        config.get("binary_outcomes", []),
        config.get("numeric_outcomes", []),
    )
    if pccf_weighted_path.exists():
        pccf = load_weighted_pccf(pccf_weighted_path)
    elif pccf_has_weight_column(pccf_raw_path):
        pccf = load_weighted_pccf(pccf_raw_path)
    else:
        raise FileNotFoundError(
            f"No weighted PCCF found at {pccf_weighted_path} and raw PCCF does not contain a weight column: {pccf_raw_path}"
        )
    base = build_base_table(pccf)
    assigned = assign_records_to_geos(raw_df, pccf, patient_link, map_area_type)
    patient_agg = build_patient_aggregation(assigned, config, map_area_type)

    if map_area_type == "da":
        geo_col = PCCF_DAUID_COL
    elif map_area_type == "csd":
        geo_col = PCCF_CSDUID_COL
    elif map_area_type == "fsa":
        geo_col = PCCF_FSA_COL
    else:
        raise ValueError(f"Unsupported map area type: {map_area_type}")

    if map_area_type == "fsa":
        base[geo_col] = base[geo_col].astype(str).str[:3]

    base = base.drop_duplicates(subset=[geo_col]).copy()

    base = base.merge(patient_agg, on=geo_col, how="left")

    if map_area_type == "da":
        sdoh_raw = load_prairies_characteristics(set(base[geo_col].astype(str)))
        equiv = load_equivalence_scores()
        quint = load_prairies_quintiles()
        base = base.merge(sdoh_raw, on=geo_col, how="left")
        base = base.merge(equiv, on=geo_col, how="left", suffixes=("", "_equiv"))
        base = base.merge(quint, on=geo_col, how="left", suffixes=("", "_quint"))
    else:
        base["dep_mat"] = np.nan
        base["dep_soc"] = np.nan
        base["res_score"] = np.nan
        base["eco_score"] = np.nan

    base = compute_sdoh_scores(base)

    out_cols = [geo_col]
    if "csd_name" in base.columns:
        out_cols.append("csd_name")
    out_cols += ["incidents_total", "incidents_m", "incidents_f", "avg_age"]
    if "avg_length_of_stay" in base.columns:
        out_cols.append("avg_length_of_stay")
    for outcome in config.get("binary_outcomes", []):
        out_cols += [f"{outcome['name']}_total", f"{outcome['name']}_m", f"{outcome['name']}_f"]
    for outcome in config.get("numeric_outcomes", []):
        out_cols += [f"{outcome['name']}_total", f"{outcome['name']}_m", f"{outcome['name']}_f"]
    out_cols += [
        "income_score",
        "housing_score",
        "education_score",
        "employment_score",
        "family_score",
        "generation_score",
        "commute_score",
        "dep_mat",
        "dep_soc",
        "res_score",
        "eco_score",
        "sdoh_total_score",
    ]
    for col in out_cols:
        if col not in base.columns:
            base[col] = np.nan
    output = base[out_cols].copy()
    MERGED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_name = f"{config_path.stem}.csv"
    output_path = MERGED_DATA_DIR / output_name
    output.to_csv(output_path, index=False)
    manifest = {
        "output_csv": str(output_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "map_area_type": map_area_type,
        "config_name": config_path.stem,
        "binary_outcomes": config.get("binary_outcomes", []),
        "numeric_outcomes": config.get("numeric_outcomes", []),
        "base_columns": {
            "geo": geo_col,
            "csd_name": "csd_name" if "csd_name" in output.columns else None,
            "incidents_total": "incidents_total",
            "incidents_m": "incidents_m",
            "incidents_f": "incidents_f",
            "avg_age": "avg_age",
            "avg_length_of_stay": "avg_length_of_stay" if "avg_length_of_stay" in output.columns else None,
        },
    }
    (MERGED_DATA_DIR / "current_output.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {len(output)} rows to {output_path}")


if __name__ == "__main__":
    main()

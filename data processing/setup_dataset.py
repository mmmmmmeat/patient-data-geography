from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PROCESSING_DIR = Path(__file__).resolve().parent
CONFIG_DIR = DATA_PROCESSING_DIR / "configs"
CURRENT_CONFIG_FILE = CONFIG_DIR / "current_config.json"
MAP_LINKS_FILE = DATA_PROCESSING_DIR / "map" / "map links.csv"
STATS_LINKS_FILE = DATA_PROCESSING_DIR / "stats" / "stats links.csv"
CENSUS_FILTERED_PATH = DATA_PROCESSING_DIR / "stats" / "statcan" / "filtered" / "DA_filtered.csv"
FILTERED_CENSUS_ARCHIVE = DATA_PROCESSING_DIR / "stats" / "statcan" / "filtered" / "filtered_census.zip"

PROVINCES = ["NL", "PE", "NS", "NB", "QC", "ON", "MB", "SK", "AB", "BC", "YT", "NT", "NU"]
AREA_TYPES = {"1": "da", "2": "csd", "3": "fsa"}


def to_repo_path(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(BASE_DIR)).replace("\\", "/")
    except Exception:
        return str(path)


def from_repo_path(value: str | Path | None) -> Path:
    if not value:
        return Path("")
    path = Path(value)
    if path.is_absolute():
        return path
    return (BASE_DIR / path).resolve()


@dataclass
class BinaryOutcome:
    name: str
    raw_column: str
    affirmative_value: str
    negative_value: str


@dataclass
class NumericOutcome:
    name: str
    raw_column: str


@dataclass
class DatasetConfig:
    dataset_name: str
    map_data_name: str
    patient_data_file: str
    pccf_file: str
    provinces: list[str]
    map_area_type: str
    area_link_column: str
    age_column: str | None
    sex_column: str | None
    sex_male_value: str | None
    sex_female_value: str | None
    length_of_stay_column: str | None
    binary_outcomes: list[BinaryOutcome]
    numeric_outcomes: list[NumericOutcome]


def prompt(text: str) -> str:
    return input(text).strip()


def prompt_yes_no(text: str) -> bool:
    while True:
        value = prompt(f"{text} (y/n): ").lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def prompt_required(text: str) -> str:
    while True:
        value = prompt(text)
        if value:
            return value
        print("This value is required.")


def prompt_optional(text: str) -> str | None:
    value = prompt(text)
    return value or None


def read_headers_from_patient_file(path: Path) -> list[str]:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return list(pd.read_excel(path, nrows=0).columns)
    return list(pd.read_csv(path, nrows=0).columns)


def read_column_values(path: Path, column: str) -> pd.Series:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    return df[column] if column in df.columns else pd.Series(dtype=str)


def normalize_token(value: object) -> str:
    return str(value).strip().lower()


def titleish(value: str) -> str:
    value = str(value).strip()
    if not value:
        return value
    if len(value) == 1:
        return value.upper()
    return value[0].upper() + value[1:].lower()


def detect_pair(series: pd.Series, candidates: list[str], pairing: dict[str, str]) -> tuple[str, str]:
    values = [normalize_token(v) for v in series.dropna().astype(str).tolist()]
    for cand in candidates:
        if cand in values:
            return titleish(cand), titleish(pairing[cand])
    return "?", "?"


def detect_binary_pair(series: pd.Series) -> tuple[str, str]:
    return detect_pair(series, ["yes", "y", "1", "no", "n", "0"], {"yes": "no", "y": "n", "1": "0", "no": "yes", "n": "y", "0": "1"})


def detect_sex_pair(series: pd.Series) -> tuple[str, str]:
    return detect_pair(series, ["male", "m", "female", "f"], {"male": "female", "m": "f", "female": "male", "f": "m"})


def prompt_existing_file(folder: Path, prompt_text: str) -> str:
    while True:
        name = prompt_required(prompt_text)
        if (folder / name).exists():
            return name
        print(f"File not found: {folder / name}")


def prompt_provinces() -> list[str]:
    print("Select one or more provinces/territories.")
    print("Enter values separated by commas or spaces. Example: MB, SK, AB")
    print("Available: " + ", ".join(PROVINCES))
    while True:
        raw = prompt("Province codes: ")
        if not raw:
            print("Please select at least one province or territory.")
            continue
        tokens = [part.strip().upper() for part in raw.replace(",", " ").split()]
        invalid = [token for token in tokens if token not in PROVINCES]
        if invalid:
            print(f"Invalid province codes: {', '.join(sorted(set(invalid)))}")
            continue
        return sorted(set(tokens))


def build_map_data_name(provinces: list[str], map_area_type: str) -> str:
    province_key = "".join(sorted(provinces))
    return f"{province_key}_{map_area_type.upper()}"


def prompt_map_area_type() -> str:
    print("Map area display type:")
    for key, value in AREA_TYPES.items():
        print(f"  {key}. {value}")
    while True:
        choice = prompt("Select an option: ")
        if choice in AREA_TYPES:
            return AREA_TYPES[choice]
        print("Please choose 1, 2, or 3.")


def prompt_binary_outcomes() -> list[BinaryOutcome]:
    outcomes: list[BinaryOutcome] = []
    print("Enter binary outcomes one at a time.")
    print("Press Enter on the name prompt to finish.")
    while True:
        name = prompt("Binary outcome name: ")
        if not name:
            break
        raw_column = prompt_required("Column name as it appears in your data: ")
        affirmative_value = prompt_required("Affirmative binary value as it appears in your data: ")
        negative_value = prompt_required("Negative binary value as it appears in your data: ")
        outcomes.append(BinaryOutcome(name, raw_column, affirmative_value, negative_value))
    return outcomes


def prompt_numeric_outcomes() -> list[NumericOutcome]:
    outcomes: list[NumericOutcome] = []
    print("Enter float/integer outcomes one at a time.")
    print("Press Enter on the name prompt to finish.")
    while True:
        name = prompt("Numeric outcome name: ")
        if not name:
            break
        raw_column = prompt_required("Column name as it appears in your data: ")
        outcomes.append(NumericOutcome(name, raw_column))
    return outcomes


def prompt_column_choice(prompt_text: str, headers: list[str]) -> str:
    if not headers:
        raise ValueError("No columns found in the patient file.")
    print(prompt_text)
    for i, header in enumerate(headers, start=1):
        print(f"  {i}. {header}")
    while True:
        choice = prompt_required("Select a column by number: ")
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(headers):
                return headers[idx]
        print("Invalid selection.")


def load_keyed_links(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                mapping[row[0].strip().upper()] = row[1].strip()
    return mapping


def excel_has_column(path: Path, column_name: str) -> bool:
    if not path.exists():
        return False
    try:
        header = pd.read_excel(path, nrows=0)
    except Exception:
        return False
    return column_name.strip().lower() in {str(col).strip().lower() for col in header.columns}


def describe_excel_candidate(path: Path, column_name: str = "weight") -> str:
    if not path.exists():
        return f"{path} [missing]"
    has_column = excel_has_column(path, column_name)
    return f"{path} [{column_name} column: {'yes' if has_column else 'no'}]"


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(
        url.strip(),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
        stream=True,
        timeout=120,
        allow_redirects=True,
    ) as response:
        response.raise_for_status()
        with destination.open("wb") as target:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    target.write(chunk)


def unzip_archive(archive_path: Path, destination_dir: Path) -> None:
    with archive_path.open("rb") as handle:
        signature = handle.read(4)
    if signature != b"PK\x03\x04":
        preview = archive_path.read_text(encoding="utf-8", errors="ignore")[:500]
        raise ValueError(
            "Downloaded file is not a ZIP archive. "
            "The link likely returned an HTML page instead of the file. "
            f"Preview: {preview!r}"
        )
    destination_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_extract_dir = Path(tmpdir) / "extract"
        temp_extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp_extract_dir)

        entries = [item for item in temp_extract_dir.iterdir()]
        if len(entries) == 1 and entries[0].is_dir():
            source_dir = entries[0]
        else:
            source_dir = temp_extract_dir

        for item in source_dir.iterdir():
            target = destination_dir / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(item), str(target))
            else:
                shutil.move(str(item), str(target))


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def set_current_config(config_path: Path) -> None:
    CURRENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURRENT_CONFIG_FILE.write_text(json.dumps({"current_config": to_repo_path(config_path)}, indent=2), encoding="utf-8")


def list_configs() -> list[Path]:
    if not CONFIG_DIR.exists():
        return []
    return sorted(p for p in CONFIG_DIR.glob("*.json") if p.name != CURRENT_CONFIG_FILE.name)


def load_selected_config_path() -> Path | None:
    if not CURRENT_CONFIG_FILE.exists():
        return None
    try:
        payload = json.loads(CURRENT_CONFIG_FILE.read_text(encoding="utf-8"))
        candidate = from_repo_path(payload["current_config"])
        return candidate if candidate.exists() else None
    except Exception:
        return None


def choose_existing_config() -> Path:
    configs = list_configs()
    if not configs:
        print("You have no configs yet. Please make a new config first.")
        return None
    print("Saved configs:")
    for i, path in enumerate(configs, start=1):
        print(f"  {i}. {path.stem}")
    while True:
        choice = prompt_required("Select a config by number: ")
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(configs):
                return configs[idx]
        print("Invalid selection.")


def select_config_flow() -> tuple[Path, bool]:
    current = load_selected_config_path()
    if current is None:
        configs = list_configs()
        if len(configs) == 1:
            set_current_config(configs[0])
            current = configs[0]
    current_label = current.name if current is not None else "none"
    print("Startup options:")
    print(f"  1. Continue with current config ({current_label})")
    print("  2. Change current config")
    print("  3. Make a new config")
    while True:
        choice = prompt("Select an option: ")
        if choice == "1":
            if current is None:
                print("No current config detected.")
                continue
            return current, False
        if choice == "2":
            selected = choose_existing_config()
            if selected is None:
                continue
            set_current_config(selected)
            return selected, False
        if choice == "3":
            return create_new_config(), True
        print("Please choose 1, 2, or 3.")


def create_new_config() -> Path:
    print("Creating a new config")
    dataset_name = prompt_required("Name for this config: ")
    patient_data_file = prompt_existing_file(DATA_PROCESSING_DIR / "patient data", "Name of patient data file: ")
    pccf_file = prompt_existing_file(DATA_PROCESSING_DIR / "PCCF", "Name of pccf: ")
    provinces = prompt_provinces()
    map_area_type = prompt_map_area_type()
    map_data_name = build_map_data_name(provinces, map_area_type)
    patient_path = DATA_PROCESSING_DIR / "patient data" / patient_data_file
    patient_headers = read_headers_from_patient_file(patient_path)

    print()
    print("Base patient columns")
    area_link_column = prompt_column_choice("Postal Code column:", patient_headers)
    age_column = prompt_optional("Age column name (blank for none): ")
    sex_column = prompt_optional("Sex column name (blank for none): ")
    length_of_stay_column = prompt_optional("Length of stay column name (blank for none): ")
    binary_outcomes = prompt_binary_outcomes()
    numeric_outcomes = prompt_numeric_outcomes()
    sex_male_value = None
    sex_female_value = None
    if sex_column:
        sex_series = read_column_values(patient_path, sex_column)
        sex_male_value, sex_female_value = detect_sex_pair(sex_series)
        print(f"Detected sex values: {sex_male_value} / {sex_female_value}")
        override = prompt_yes_no("Do you want to change the detected sex values?")
        if override:
            sex_male_value = prompt_required("Male value: ")
            sex_female_value = prompt_required("Female value: ")

    for outcome in binary_outcomes:
        if outcome.raw_column in patient_headers:
            values = read_column_values(patient_path, outcome.raw_column)
            aff, neg = detect_binary_pair(values)
            print(f"Detected binary values for {outcome.name}: {aff} / {neg}")
            override = prompt_yes_no("Do you want to change the detected binary values?")
            if override:
                outcome.affirmative_value = prompt_required("Affirmative value: ")
                outcome.negative_value = prompt_required("Negative value: ")
            else:
                outcome.affirmative_value = aff
                outcome.negative_value = neg

    patient_folder = DATA_PROCESSING_DIR / "patient data" / dataset_name
    pccf_folder = DATA_PROCESSING_DIR / "PCCF" / dataset_name
    patient_folder.mkdir(parents=True, exist_ok=True)
    pccf_folder.mkdir(parents=True, exist_ok=True)
    patient_source = DATA_PROCESSING_DIR / "patient data" / patient_data_file
    pccf_source = DATA_PROCESSING_DIR / "PCCF" / pccf_file
    patient_dest = patient_folder / patient_data_file
    pccf_dest = pccf_folder / pccf_file
    if patient_source.exists():
        shutil.copy2(patient_source, patient_dest)
    if pccf_source.exists():
        shutil.copy2(pccf_source, pccf_dest)

    config = DatasetConfig(
        dataset_name=dataset_name,
        map_data_name=map_data_name,
        patient_data_file=to_repo_path(patient_dest),
        pccf_file=to_repo_path(pccf_dest),
        provinces=provinces,
        map_area_type=map_area_type,
        area_link_column=area_link_column,
        age_column=age_column,
        sex_column=sex_column,
        sex_male_value=sex_male_value,
        sex_female_value=sex_female_value,
        length_of_stay_column=length_of_stay_column,
        binary_outcomes=binary_outcomes,
        numeric_outcomes=numeric_outcomes,
    )

    ensure_config_dir()
    config_path = CONFIG_DIR / f"{dataset_name}.json"
    write_json(config_path, asdict(config))
    set_current_config(config_path)
    print(f"Saved config to: {config_path}")
    print(f"Map data folder key: {map_data_name}")
    return config_path


def run_script(script_path: Path, config_path: Path, *extra_args: str) -> None:
    if not script_path.exists():
        raise FileNotFoundError(f"Missing script: {script_path}")
    subprocess.run([sys.executable, str(script_path), str(config_path), *extra_args], check=True)


def census_filter_script() -> Path:
    return DATA_PROCESSING_DIR / "stats" / "filter_statcan_raw.py"


def run_selected_config(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    pccf_path = from_repo_path(config["pccf_file"])
    pccf_file = pccf_path.name
    pccf_weighted_path = pccf_path.with_name(f"{pccf_path.stem} weighted{pccf_path.suffix}")
    stats_links = load_keyed_links(STATS_LINKS_FILE)

    if CENSUS_FILTERED_PATH.exists():
        print(f"Census filtered file detected at: {CENSUS_FILTERED_PATH}")
    else:
        stats_link_url = stats_links.get("FILTERED")
        use_pre_filtered = False
        if stats_link_url:
            use_pre_filtered = prompt_yes_no("Use the pre-filtered census download?")
        if use_pre_filtered and stats_link_url:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_archive = Path(tmpdir) / "filtered_census.zip"
                print("Downloading pre-filtered census data...")
                download_file(stats_link_url, tmp_archive)
                print("Unzipping pre-filtered census data...")
                unzip_archive(tmp_archive, CENSUS_FILTERED_PATH.parent)
        else:
            if prompt_yes_no("Use raw census download instead?"):
                if prompt_yes_no("Do you want to run the census cleaning script?"):
                    run_script(census_filter_script(), config_path)

    print("Checking PCCF candidates:")
    print(f"  weighted: {describe_excel_candidate(pccf_weighted_path)}")
    print(f"  raw:      {describe_excel_candidate(pccf_path)}")

    if excel_has_column(pccf_weighted_path, "weight"):
        print(f"Using weighted PCCF: {pccf_weighted_path}")
    elif excel_has_column(pccf_path, "weight"):
        print(f"Using raw PCCF with existing weight column: {pccf_path}")
    else:
        apply_weights = prompt_yes_no("PCCF file does not have a weight column yet. Would you like to apply the weights?")
        if apply_weights:
            run_script(DATA_PROCESSING_DIR / "PCCF" / "build_weighted_pccf.py", config_path, pccf_file)

    merge_patient_census = prompt_yes_no("Confirm merging patient data with census data and PCCF conversion?")
    if merge_patient_census:
        run_script(DATA_PROCESSING_DIR / "build_profile.py", config_path)

    create_map = prompt_yes_no("Confirm map creation?")
    if create_map:
        run_script(DATA_PROCESSING_DIR / "map" / "build_map.py", config_path)


def main() -> None:
    print("Dataset setup")
    print(f"Project root: {BASE_DIR}")
    print()
    config_path, created_new = select_config_flow()
    run_selected_config(config_path)


if __name__ == "__main__":
    main()

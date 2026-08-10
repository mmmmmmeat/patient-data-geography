from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
APP_VERSION = "1.4"
APP_BUILD_DATE = "2026-07-29"
DATA_PROCESSING_DIR = ROOT / "data processing"
CONFIG_DIR = DATA_PROCESSING_DIR / "configs"
CURRENT_CONFIG_FILE = CONFIG_DIR / "current_config.json"
PATIENT_DIR = DATA_PROCESSING_DIR / "patient data"
PCCF_DIR = DATA_PROCESSING_DIR / "PCCF"
GLOBAL_PCCF_DIR = PCCF_DIR / "global"
STATS_LINKS_FILE = DATA_PROCESSING_DIR / "stats" / "stats links.csv"
FILTERED_CENSUS_PATH = DATA_PROCESSING_DIR / "stats" / "statcan" / "filtered" / "DA_filtered.csv"
RAW_CSDDA_DIR = DATA_PROCESSING_DIR / "stats" / "statcan" / "raw" / "csdda"
RAW_FSA_DIR = DATA_PROCESSING_DIR / "stats" / "statcan" / "raw" / "fsa"
MAP_APP_URL = "http://localhost:8000/index.html"

PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
AREA_TYPES = ["da", "csd", "fsa"]


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


def load_configs() -> list[Path]:
    if not CONFIG_DIR.exists():
        return []
    return sorted(p for p in CONFIG_DIR.glob("*.json") if p.name != CURRENT_CONFIG_FILE.name)


def load_current_config() -> Path | None:
    if not CURRENT_CONFIG_FILE.exists():
        return None
    try:
        payload = json.loads(CURRENT_CONFIG_FILE.read_text(encoding="utf-8"))
        candidate = from_repo_path(payload["current_config"])
        return candidate if candidate.exists() else None
    except Exception:
        return None


def save_current_config(path: Path) -> None:
    CURRENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURRENT_CONFIG_FILE.write_text(json.dumps({"current_config": to_repo_path(path)}, indent=2), encoding="utf-8")


def load_config_payload(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ("patient_data_file", "pccf_file"):
        if key in payload and payload[key]:
            payload[key] = from_repo_path(payload[key])
    if payload.get("pccf_file"):
        payload["pccf_file"] = raw_pccf_path(payload["pccf_file"])
    return payload


def config_storage_paths(config_name: str) -> tuple[Path, Path]:
    safe_name = config_name.strip()
    return PATIENT_DIR / safe_name, PCCF_DIR / safe_name


def save_uploaded_file(uploaded, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(uploaded.getvalue())


def to_repo_path(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except Exception:
        return str(path)


def from_repo_path(value: str | Path | None) -> Path:
    if not value:
        return Path("")
    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def raw_pccf_path(path: Path | None) -> Path:
    if not path:
        return Path("")
    candidate = Path(path)
    if candidate.name.lower().endswith(" weighted.xlsx"):
        return candidate.with_name(candidate.name[:-len(" weighted.xlsx")] + ".xlsx")
    if candidate.stem.lower().endswith(" weighted"):
        return candidate.with_name(f"{candidate.stem[:-9]}{candidate.suffix}")
    return candidate


def weighted_pccf_path(path: Path | None) -> Path:
    raw_path = raw_pccf_path(path)
    if not raw_path:
        return Path("")
    return raw_path.with_name(f"{raw_path.stem} weighted{raw_path.suffix}")


def normalize_token(value: object) -> str:
    return str(value).strip().lower()


def titleish(value: str) -> str:
    value = str(value).strip()
    if not value:
        return value
    if len(value) == 1:
        return value.upper()
    return value[0].upper() + value[1:].lower()


def detect_value_pair(series: pd.Series, first_candidates: list[str], second_candidates: dict[str, str]) -> tuple[str, str]:
    values = [normalize_token(v) for v in series.dropna().astype(str).tolist()]
    for first in first_candidates:
        if first in values:
            second = second_candidates[first]
            return titleish(first), titleish(second)
    return "?", "?"


def detect_binary_pair(series: pd.Series) -> tuple[str, str]:
    mapping = {
        "yes": "no",
        "no": "yes",
        "y": "n",
        "n": "y",
        "1": "0",
        "0": "1",
    }
    return detect_value_pair(series, ["yes", "y", "1", "no", "n", "0"], mapping)


def detect_sex_pair(series: pd.Series) -> tuple[str, str]:
    values = [normalize_token(v) for v in series.dropna().astype(str).tolist()]
    sex_candidates = {
        "male": "female",
        "m": "f",
        "female": "male",
        "f": "m",
    }
    for first in ["male", "m", "female", "f"]:
        if first in values:
            second = sex_candidates[first]
            return titleish(first), titleish(second)
    return "?", "?"


def get_series_from_uploaded(uploaded, column: str) -> pd.Series:
    if uploaded is None or not column:
        return pd.Series(dtype=str)
    data = uploaded.getvalue()
    if uploaded.name.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(BytesIO(data), dtype=str)
    else:
        df = pd.read_csv(BytesIO(data), dtype=str)
    return df[column] if column in df.columns else pd.Series(dtype=str)


def get_series_from_path(path: Path, column: str) -> pd.Series:
    if not path.exists() or not column:
        return pd.Series(dtype=str)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str)
    return df[column] if column in df.columns else pd.Series(dtype=str)


def move_config_storage(old_name: str, new_name: str) -> None:
    old_patient, old_pccf = config_storage_paths(old_name)
    new_patient, new_pccf = config_storage_paths(new_name)
    if old_patient.exists() and old_patient != new_patient:
        new_patient.parent.mkdir(parents=True, exist_ok=True)
        if new_patient.exists():
            shutil.rmtree(new_patient)
        shutil.move(str(old_patient), str(new_patient))
    if old_pccf.exists() and old_pccf != new_pccf:
        new_pccf.parent.mkdir(parents=True, exist_ok=True)
        if new_pccf.exists():
            shutil.rmtree(new_pccf)
        shutil.move(str(old_pccf), str(new_pccf))


def global_pccf_files() -> list[Path]:
    if not GLOBAL_PCCF_DIR.exists():
        return []
    return sorted(p for p in GLOBAL_PCCF_DIR.iterdir() if p.is_file())


def other_config_options(current: Path | None) -> list[Path]:
    return [path for path in load_configs() if path != current]


def build_map_data_name(provinces: list[str], map_area_type: str) -> str:
    return f"{''.join(sorted(provinces))}_{map_area_type.upper()}"


def read_headers(path: Path) -> list[str]:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return list(pd.read_excel(path, nrows=0).columns)
    return list(pd.read_csv(path, nrows=0).columns)


def read_uploaded_headers(uploaded) -> list[str]:
    if uploaded is None:
        return []
    data = uploaded.getvalue()
    if uploaded.name.lower().endswith((".xlsx", ".xls")):
        return list(pd.read_excel(BytesIO(data), nrows=0).columns)
    return list(pd.read_csv(BytesIO(data), nrows=0).columns)


def run_script(script: Path, *args: str) -> None:
    subprocess.run([sys.executable, str(script), *args], cwd=str(ROOT), check=True)


def load_keyed_links(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    mapping: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = [part.strip() for part in line.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            mapping[parts[0].upper()] = parts[1]
    return mapping


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(
        url.strip(),
        stream=True,
        timeout=120,
        allow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def unzip_archive(archive_path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)

        entries = list(extract_dir.iterdir())
        source_dir = entries[0] if len(entries) == 1 and entries[0].is_dir() else extract_dir
        for item in source_dir.iterdir():
            target = destination_dir / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(item), str(target))
            else:
                shutil.move(str(item), str(target))


def raw_census_files_present() -> bool:
    return any(RAW_CSDDA_DIR.glob("*.csv")) or any(RAW_FSA_DIR.glob("*.csv"))


def count_raw_census_files() -> int:
    return sum(1 for _ in RAW_CSDDA_DIR.glob("*.csv")) + sum(1 for _ in RAW_FSA_DIR.glob("*.csv"))


def init_outcome_state() -> None:
    st.session_state.setdefault("binary_outcomes", [])
    st.session_state.setdefault("numeric_outcomes", [])
    st.session_state.setdefault("binary_count", 0)
    st.session_state.setdefault("numeric_count", 0)
    st.session_state.setdefault("binary_selected", 0)
    st.session_state.setdefault("numeric_selected", 0)


def ensure_outcome_lengths(kind: str, count: int) -> None:
    key = "binary_outcomes" if kind == "binary" else "numeric_outcomes"
    items = st.session_state[key]
    while len(items) < count:
        if kind == "binary":
            items.append({"name": "", "raw_column": "", "affirmative_value": "", "negative_value": ""})
        else:
            items.append({"name": "", "raw_column": ""})
    while len(items) > count:
        items.pop()
    st.session_state[key] = items


def sync_outcomes_from_payload(payload: dict) -> None:
    binary = payload.get("binary_outcomes", []) or []
    numeric = payload.get("numeric_outcomes", []) or []
    st.session_state.binary_outcomes = [dict(item) for item in binary]
    st.session_state.numeric_outcomes = [dict(item) for item in numeric]
    st.session_state.binary_count = len(st.session_state.binary_outcomes)
    st.session_state.numeric_count = len(st.session_state.numeric_outcomes)
    st.session_state.binary_count_input = st.session_state.binary_count
    st.session_state.numeric_count_input = st.session_state.numeric_count
    st.session_state.binary_selected = 0
    st.session_state.numeric_selected = 0


def reset_input_state() -> None:
    st.session_state.binary_outcomes = []
    st.session_state.numeric_outcomes = []
    st.session_state.binary_count = 0
    st.session_state.numeric_count = 0
    st.session_state.binary_count_input = 0
    st.session_state.numeric_count_input = 0
    st.session_state.binary_selected = 0
    st.session_state.numeric_selected = 0
    st.session_state.patient_source_mode = "Upload data"
    st.session_state.pccf_source_mode = "Upload PCCF"
    st.session_state.binary_override = {}
    st.session_state.sex_override = {}
    st.session_state.save_mode = "Overwrite current config"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and (key.startswith("bin_yes_") or key.startswith("bin_no_") or key.startswith("bin_marker_") or key.startswith("num_name_") or key.startswith("num_raw_")):
            del st.session_state[key]


def outcome_label(item: dict, default_name: str, is_binary: bool) -> str:
    name = str(item.get("name", "")).strip() or default_name
    raw = str(item.get("raw_column", "")).strip()
    warning = " ⚠" if not name or not raw or (is_binary and (not str(item.get("affirmative_value", "")).strip() or not str(item.get("negative_value", "")).strip())) else ""
    return f"{name}{warning}"


st.set_page_config(page_title="Dataset Setup", layout="wide")
st.title("Dataset Setup")
st.caption("Create a config, inspect columns, and run the processing steps from a guided UI.")
st.markdown(f"**Version:** {APP_VERSION}  \n**Build date:** {APP_BUILD_DATE}")

init_outcome_state()

configs = load_configs()
current = load_current_config()
current_payload = load_config_payload(current)

if "config_mode" not in st.session_state:
    st.session_state.config_mode = "Create new config"
if "editing_current_config" not in st.session_state:
    st.session_state.editing_current_config = False
if "selected_existing_config" not in st.session_state:
    st.session_state.selected_existing_config = current
if "patient_source_mode" not in st.session_state:
    st.session_state.patient_source_mode = "Upload data"
if "pccf_source_mode" not in st.session_state:
    st.session_state.pccf_source_mode = "Upload PCCF"
if "binary_override" not in st.session_state:
    st.session_state.binary_override = {}
if "sex_override" not in st.session_state:
    st.session_state.sex_override = {}
if "save_mode" not in st.session_state:
    st.session_state.save_mode = "Overwrite current config"
if "last_config_mode" not in st.session_state:
    st.session_state.last_config_mode = st.session_state.config_mode
if "loaded_config_path" not in st.session_state:
    st.session_state.loaded_config_path = None
if "pending_config_mode" not in st.session_state:
    st.session_state.pending_config_mode = None
if "pending_selected_existing_config" not in st.session_state:
    st.session_state.pending_selected_existing_config = None
if "dataset_name_input" not in st.session_state:
    st.session_state.dataset_name_input = ""
if "pending_dataset_name_input" not in st.session_state:
    st.session_state.pending_dataset_name_input = None

if st.session_state.pending_config_mode:
    st.session_state.config_mode = st.session_state.pending_config_mode
    st.session_state.pending_config_mode = None
if st.session_state.pending_selected_existing_config is not None:
    st.session_state.selected_existing_config = st.session_state.pending_selected_existing_config
    st.session_state.pending_selected_existing_config = None
if st.session_state.pending_dataset_name_input is not None:
    st.session_state.dataset_name_input = st.session_state.pending_dataset_name_input
    st.session_state.pending_dataset_name_input = None

with st.sidebar:
    st.subheader("Startup")
    mode = st.radio("What do you want to do?", ["Use current config", "Create new config"], key="config_mode")
    if configs:
        current_index = configs.index(current) if current in configs else 0
        current = st.selectbox("Current config", configs, format_func=lambda p: p.name, index=current_index, key="selected_existing_config")
        save_current_config(current)
    else:
        current = None
        st.selectbox("Current config", [Path("none found")], disabled=True)
        st.info("No configs found.")

    selected_config = current
    if st.session_state.last_config_mode != mode:
        if mode == "Create new config":
            reset_input_state()
            selected_config = None
            st.session_state.save_mode = "Save as new config"
            st.session_state.loaded_config_path = None
            st.session_state.pending_dataset_name_input = ""
        elif mode == "Use current config":
            reset_input_state()
            st.session_state.save_mode = "Overwrite current config"
            st.session_state.loaded_config_path = None
            if selected_config:
                st.session_state.pending_dataset_name_input = selected_config.stem
        st.session_state.last_config_mode = mode

if mode == "Use current config" and selected_config and selected_config.exists() and st.session_state.loaded_config_path != selected_config:
    reset_input_state()
    sync_outcomes_from_payload(load_config_payload(selected_config))
    st.session_state.loaded_config_path = selected_config
elif mode == "Create new config":
    st.session_state.loaded_config_path = None

editable = True if mode == "Use current config" else True
active_payload = load_config_payload(selected_config) if (selected_config and mode == "Use current config") else {}
widget_scope = f"{mode}_{selected_config.stem if selected_config else 'none'}"

st.header("1. Inputs")
provinces_default = active_payload.get("provinces", ["MB"])
map_area_default = active_payload.get("map_area_type", "da")
dataset_name_default = active_payload.get("dataset_name", "")
privacy_default = int(active_payload.get("privacy_min_incidents", 6) or 0)
provinces = st.multiselect("Province(s)", PROVINCES, default=provinces_default, disabled=not editable)
map_area_type = st.selectbox("Map area type", AREA_TYPES, index=AREA_TYPES.index(map_area_default) if map_area_default in AREA_TYPES else 0, disabled=not editable)
if mode == "Use current config" and selected_config:
    if not st.session_state.dataset_name_input:
        st.session_state.pending_dataset_name_input = selected_config.stem
dataset_name = st.text_input("Config name", value=st.session_state.dataset_name_input if st.session_state.dataset_name_input else dataset_name_default, key="dataset_name_input", disabled=not editable)
privacy_min_incidents = st.number_input(
    "Exclude outcomes in areas with less than this many incidents",
    min_value=0,
    max_value=1000,
    value=privacy_default,
    step=1,
    disabled=not editable,
)

patient_source_mode = st.radio(
    "Patient data source",
    ["Upload data", "Use data from another config"],
    horizontal=True,
    disabled=not editable,
    key="patient_source_mode",
)
patient_file = None
if patient_source_mode == "Upload data":
    patient_file = st.file_uploader("Drop patient file here", type=["csv", "xlsx"], disabled=not editable)

st.subheader("Patient columns")
patient_headers: list[str] = []
patient_source_path: Path | None = None
patient_source_label = "none"
if patient_source_mode == "Upload data":
    headers = read_uploaded_headers(patient_file)
    if not headers and mode == "Use current config" and active_payload.get("patient_data_file"):
        try:
            headers = read_headers(from_repo_path(active_payload["patient_data_file"]))
        except Exception:
            headers = []
    if patient_file:
        st.write("Detected columns:")
        st.write(headers)
    patient_source_path = Path(patient_file.name) if patient_file else None
    patient_source_label = patient_file.name if patient_file else "none"
    patient_headers = headers
else:
    other_configs = other_config_options(selected_config)
    if other_configs:
        source_config = st.selectbox("Select source config", other_configs, format_func=lambda p: p.name, disabled=not editable, key="patient_source_config")
        source_payload = load_config_payload(source_config)
        patient_source_path = source_payload.get("patient_data_file") if source_payload.get("patient_data_file") else None
        patient_source_label = source_config.name
        if patient_source_path and patient_source_path.exists():
            patient_headers = read_headers(patient_source_path)
            st.info(f"Using patient data from `{source_config.name}`")
        else:
            st.warning("Selected config does not have a usable patient data file.")
    else:
        st.info("No other configs were found.")
        patient_source_mode = "Upload data"
        patient_file = st.file_uploader("Drop patient file here", type=["csv", "xlsx"], disabled=not editable, key="patient_file_fallback")
        headers = read_uploaded_headers(patient_file)
        patient_headers = headers
        if patient_file:
            st.write("Detected columns:")
            st.write(headers)
    if not patient_headers and mode == "Use current config" and active_payload.get("patient_data_file"):
        try:
            patient_headers = read_headers(from_repo_path(active_payload["patient_data_file"]))
        except Exception:
            patient_headers = []
default_area = active_payload.get("area_link_column", "") if mode == "Use current config" else ""
default_age = (active_payload.get("age_column") or "") if mode == "Use current config" else ""
default_sex = (active_payload.get("sex_column") or "") if mode == "Use current config" else ""
default_los = (active_payload.get("length_of_stay_column") or "") if mode == "Use current config" else ""
area_link = st.selectbox("Postal Code column", [""] + patient_headers, index=(patient_headers.index(default_area) + 1) if default_area in patient_headers else 0, disabled=not editable, key=f"{widget_scope}_area_link")
age_col = st.selectbox("Age column", [""] + patient_headers, index=(patient_headers.index(default_age) + 1) if default_age in patient_headers else 0, disabled=not editable, key=f"{widget_scope}_age")
sex_col = st.selectbox("Sex column", [""] + patient_headers, index=(patient_headers.index(default_sex) + 1) if default_sex in patient_headers else 0, disabled=not editable, key=f"{widget_scope}_sex")
los_col = st.selectbox("Length of stay column", [""] + patient_headers, index=(patient_headers.index(default_los) + 1) if default_los in patient_headers else 0, disabled=not editable, key=f"{widget_scope}_los")
sex_series = pd.Series(dtype=str)
if sex_col:
    if patient_source_mode == "Upload data" and patient_file:
        sex_series = get_series_from_uploaded(patient_file, sex_col)
    elif patient_source_mode == "Use data from another config" and patient_source_path:
        sex_series = get_series_from_path(patient_source_path, sex_col)
    elif mode == "Use current config" and active_payload.get("patient_data_file"):
        sex_series = get_series_from_path(from_repo_path(active_payload["patient_data_file"]), sex_col)
auto_sex_male, auto_sex_female = detect_sex_pair(sex_series)
sex_male = active_payload.get("sex_male_value", auto_sex_male)
sex_female = active_payload.get("sex_female_value", auto_sex_female)

st.subheader("Outcomes")
default_binary = active_payload.get("binary_outcomes", [])
default_numeric = active_payload.get("numeric_outcomes", [])
if mode == "Use current config" and selected_config and st.session_state.loaded_config_path == selected_config:
    if not st.session_state.binary_outcomes and default_binary:
        st.session_state.binary_outcomes = [dict(item) for item in default_binary]
        st.session_state.binary_count = len(default_binary)
    if not st.session_state.numeric_outcomes and default_numeric:
        st.session_state.numeric_outcomes = [dict(item) for item in default_numeric]
        st.session_state.numeric_count = len(default_numeric)
binary_count = st.number_input("How many binary outcomes?", min_value=0, max_value=20, value=st.session_state.binary_count, key=f"{widget_scope}_binary_count_input", disabled=not editable)
numeric_count = st.number_input("How many numeric outcomes?", min_value=0, max_value=20, value=st.session_state.numeric_count, key=f"{widget_scope}_numeric_count_input", disabled=not editable)
st.session_state.binary_count = int(binary_count)
st.session_state.numeric_count = int(numeric_count)
ensure_outcome_lengths("binary", st.session_state.binary_count)
ensure_outcome_lengths("numeric", st.session_state.numeric_count)

st.markdown("**Binary outcomes**")
binary_labels = [outcome_label(item, f"Outcome {i + 1}", True) for i, item in enumerate(st.session_state.binary_outcomes)]
if binary_labels:
    st.session_state.binary_selected = st.selectbox("Select a binary outcome", range(len(binary_labels)), format_func=lambda i: binary_labels[i], key=f"{widget_scope}_binary_selected_picker", disabled=not editable)
    b_idx = int(st.session_state.binary_selected)
    b_item = st.session_state.binary_outcomes[b_idx]
    c1, c2, c3, c4 = st.columns([2, 3, 2, 2])
    b_item["name"] = c1.text_input("Outcome name", value=b_item.get("name", ""), key=f"{widget_scope}_bin_name_{b_idx}", disabled=not editable)
    b_item["raw_column"] = c2.selectbox("Raw column", [""] + headers, index=(headers.index(b_item.get("raw_column", "")) + 1) if b_item.get("raw_column", "") in headers else 0, key=f"{widget_scope}_bin_raw_{b_idx}", disabled=not editable)
    binary_series = pd.Series(dtype=str)
    if b_item.get("raw_column"):
        if patient_source_mode == "Upload data" and patient_file:
            binary_series = get_series_from_uploaded(patient_file, b_item["raw_column"])
        elif patient_source_mode == "Use data from another config" and patient_source_path:
            binary_series = get_series_from_path(patient_source_path, b_item["raw_column"])
        elif mode == "Use current config" and active_payload.get("patient_data_file"):
            binary_series = get_series_from_path(from_repo_path(active_payload["patient_data_file"]), b_item["raw_column"])
    auto_affirm, auto_negative = detect_binary_pair(binary_series)
    current_affirm = b_item.get("affirmative_value", "")
    current_negative = b_item.get("negative_value", "")
    init_marker = f"{b_item.get('raw_column', '')}"
    yes_key = f"bin_yes_{b_idx}"
    no_key = f"bin_no_{b_idx}"
    marker_key = f"bin_marker_{b_idx}"
    if st.session_state.get(marker_key) != init_marker:
        st.session_state[marker_key] = init_marker
        st.session_state[yes_key] = auto_affirm
        st.session_state[no_key] = auto_negative
    if yes_key not in st.session_state or st.session_state.get(yes_key) in {"", "?"}:
        st.session_state[yes_key] = auto_affirm
    if no_key not in st.session_state or st.session_state.get(no_key) in {"", "?"}:
        st.session_state[no_key] = auto_negative
    b_item["affirmative_value"] = c3.text_input(
        "Affirmative (Yes, 1, etc)",
        value=st.session_state[yes_key],
        key=f"bin_yes_{b_idx}",
        disabled=not editable,
    )
    b_item["negative_value"] = c4.text_input(
        "Negative (No, 0, etc)",
        value=st.session_state[no_key],
        key=f"bin_no_{b_idx}",
        disabled=not editable,
    )
else:
    st.caption("No binary outcomes yet.")

st.divider()
st.markdown("**Numeric outcomes**")
numeric_labels = [outcome_label(item, f"Outcome {i + 1}", False) for i, item in enumerate(st.session_state.numeric_outcomes)]
if numeric_labels:
    st.session_state.numeric_selected = st.selectbox("Select a numeric outcome", range(len(numeric_labels)), format_func=lambda i: numeric_labels[i], key="numeric_selected_picker", disabled=not editable)
    n_idx = int(st.session_state.numeric_selected)
    n_item = st.session_state.numeric_outcomes[n_idx]
    n1, n2 = st.columns([2, 4])
    n_item["name"] = n1.text_input("Outcome name", value=n_item.get("name", ""), key=f"{widget_scope}_num_name_{n_idx}", disabled=not editable)
    n_item["raw_column"] = n2.selectbox("Raw column", [""] + headers, index=(headers.index(n_item.get("raw_column", "")) + 1) if n_item.get("raw_column", "") in headers else 0, key=f"{widget_scope}_num_raw_{n_idx}", disabled=not editable)
else:
    st.caption("No numeric outcomes yet.")

st.subheader("PCCF source")
pccf_source_mode = st.radio(
    "PCCF source",
    ["Upload PCCF", "Use global PCCF"],
    horizontal=True,
    disabled=not editable,
    key="pccf_source_mode",
)
pccf_file = None
pccf_source_path: Path | None = None
if pccf_source_mode == "Upload PCCF":
    pccf_file = st.file_uploader("Drop PCCF file here", type=["xlsx"], disabled=not editable)
    if pccf_file:
        pccf_source_path = Path(pccf_file.name)
        st.write(f"Selected PCCF upload: `{pccf_file.name}`")
else:
    GLOBAL_PCCF_DIR.mkdir(parents=True, exist_ok=True)
    globals_found = global_pccf_files()
    if globals_found:
        pccf_source_path = st.selectbox("Global PCCF", globals_found, format_func=lambda p: p.name, disabled=not editable, key="global_pccf_pick")
        st.info(f"Using global PCCF: `{pccf_source_path.name}`")
    else:
        st.warning("No global PCCF found.")
        global_upload = st.file_uploader("Upload a global PCCF", type=["xlsx"], disabled=not editable, key="global_pccf_upload")
        if global_upload:
            pccf_dest = GLOBAL_PCCF_DIR / global_upload.name
            save_uploaded_file(global_upload, pccf_dest)
            pccf_source_path = pccf_dest
            st.success(f"Saved global PCCF to `{pccf_dest}`")

def next_available_config_path(base_name: str) -> Path:
    base_name = base_name.strip() or "config"
    candidate = CONFIG_DIR / f"{base_name}.json"
    if not candidate.exists():
        return candidate
    suffix = 1
    while True:
        candidate = CONFIG_DIR / f"{base_name} {suffix}.json"
        if not candidate.exists():
            return candidate
        suffix += 1

if mode == "Use current config" and selected_config:
    st.radio(
        "Save mode",
        ["Overwrite current config", "Save as new config"],
        key="save_mode",
        horizontal=True,
    )
    if st.session_state.save_mode == "Overwrite current config":
        preview_path = selected_config
    else:
        preview_path = next_available_config_path(dataset_name or selected_config.stem)
    st.caption(f"Will be saved as `{preview_path.name}`")
else:
    preview_path = next_available_config_path(dataset_name)
    st.caption(f"Will be saved as `{preview_path.name}`")

binary_outcomes = [BinaryOutcome(**item) for item in st.session_state.binary_outcomes if item.get("name") and item.get("raw_column")]
numeric_outcomes = [NumericOutcome(**item) for item in st.session_state.numeric_outcomes if item.get("name") and item.get("raw_column")]

map_data_name = build_map_data_name(provinces, map_area_type)
st.info(f"Map data folder key will be: `{map_data_name}`")

st.subheader("Save config")
save_clicked = st.button("Save config", disabled=not editable)
if editable and save_clicked and dataset_name and area_link:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if mode == "Use current config" and selected_config and st.session_state.save_mode == "Overwrite current config":
        config_path = selected_config
        if config_path.stem != dataset_name:
            new_config_path = CONFIG_DIR / f"{dataset_name}.json"
            if new_config_path.exists():
                new_config_path.unlink()
            shutil.move(str(config_path), str(new_config_path))
            move_config_storage(config_path.stem, dataset_name)
            config_path = new_config_path
    elif mode == "Use current config" and selected_config and st.session_state.save_mode == "Save as new config":
        config_path = next_available_config_path(dataset_name or selected_config.stem)
    else:
        config_path = next_available_config_path(dataset_name)

    if patient_source_mode == "Upload data" and patient_file:
        patient_folder, _ = config_storage_paths(config_path.stem)
        patient_dest = patient_folder / patient_file.name
        save_uploaded_file(patient_file, patient_dest)
        patient_path = patient_dest
    elif patient_source_mode == "Use data from another config" and patient_source_path:
        patient_path = patient_source_path
    else:
        patient_path = Path(active_payload.get("patient_data_file", ""))

    if pccf_source_mode == "Upload PCCF" and pccf_file:
        _, pccf_folder = config_storage_paths(config_path.stem)
        pccf_dest = pccf_folder / pccf_file.name
        save_uploaded_file(pccf_file, pccf_dest)
        pccf_path = raw_pccf_path(pccf_dest)
    elif pccf_source_mode == "Use global PCCF" and pccf_source_path:
        pccf_path = raw_pccf_path(pccf_source_path)
    else:
        pccf_path = raw_pccf_path(from_repo_path(active_payload.get("pccf_file", "")))

    payload = {
        "dataset_name": dataset_name,
        "map_data_name": map_data_name,
        "patient_data_file": to_repo_path(patient_path),
        "pccf_file": to_repo_path(pccf_path),
        "provinces": sorted(set(provinces)),
        "map_area_type": map_area_type,
        "area_link_column": area_link,
        "age_column": age_col or None,
        "sex_column": sex_col or None,
        "sex_male_value": sex_male or None,
        "sex_female_value": sex_female or None,
        "length_of_stay_column": los_col or None,
        "privacy_min_incidents": int(privacy_min_incidents),
        "binary_outcomes": [asdict(item) for item in binary_outcomes],
        "numeric_outcomes": [asdict(item) for item in numeric_outcomes],
    }
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    save_current_config(config_path)
    if mode == "Create new config":
        st.session_state.pending_config_mode = "Use current config"
        st.session_state.editing_current_config = False
        st.session_state.save_mode = "Overwrite current config"
        st.session_state.pending_selected_existing_config = config_path
        st.session_state.pending_dataset_name_input = config_path.stem
    st.success(f"Saved config to {config_path}")
    st.success("Patient data was saved into the config-specific folder.")
    st.success(f"Patient data added for `{config_path.stem}`.")
    st.session_state.editing_current_config = False
    st.rerun()

st.header("2. Process")
if mode == "Use current config" and selected_config:
    st.write(f"Selected config: `{selected_config.name}`")
    census_links = load_keyed_links(STATS_LINKS_FILE)
    prefiltered_url = census_links.get("FILTERED")

    st.subheader("Census data")
    if prefiltered_url:
        if st.button("Download pre-filtered census data"):
            with st.spinner("Downloading and extracting pre-filtered census data..."):
                tmp_archive = FILTERED_CENSUS_PATH.parent / "filtered_census.zip"
                download_file(prefiltered_url, tmp_archive)
                unzip_archive(tmp_archive, FILTERED_CENSUS_PATH.parent)
                if tmp_archive.exists():
                    tmp_archive.unlink()
            st.success(f"Pre-filtered census data is ready at {FILTERED_CENSUS_PATH.parent}")
    else:
        st.warning("No pre-filtered census link was found in `stats links.csv`.")

    st.write("Raw census download is very large and is intended for reproducibility.")
    raw_clicked = st.button("I want to download the raw census data")
    if raw_clicked:
        with st.spinner("Downloading raw census data..."):
            run_script(DATA_PROCESSING_DIR / "stats" / "download_statcan_raw.py", str(selected_config))
        if raw_census_files_present():
            st.success(f"Raw census data downloaded successfully. Files detected: {count_raw_census_files()}")
        else:
            st.error("The raw download step finished, but no raw census files were detected.")

    if raw_census_files_present():
        st.info("Raw census files are present. You can run the cleaning step separately when ready.")
        if st.button("Run raw census cleaning workflow"):
            with st.spinner("Running raw census cleaning workflow..."):
                run_script(DATA_PROCESSING_DIR / "stats" / "filter_statcan_raw.py", str(selected_config))
            st.success("Raw census cleaning completed")

    st.subheader("Processing")
    pccf_target = raw_pccf_path(from_repo_path(active_payload.get("pccf_file", "")))
    if pccf_target and pccf_target.name:
        pccf_weighted_target = weighted_pccf_path(pccf_target)
        st.info(f"PCCF for selected config: `{pccf_target}`")
        if pccf_weighted_target.exists():
            st.success(f"Weighted PCCF detected: `{pccf_weighted_target.name}`")
        else:
            st.warning(f"Weighted PCCF not found yet: `{pccf_weighted_target.name}`")
    else:
        st.info("PCCF for selected config: not set yet")
    col1, col2 = st.columns(2)
    if col1.button("Build weighted PCCF"):
        try:
            with st.spinner("Building weighted PCCF..."):
                run_script(DATA_PROCESSING_DIR / "PCCF" / "build_weighted_pccf.py", str(selected_config))
            st.success("PCCF weighting done")
        except subprocess.CalledProcessError as exc:
            st.error(f"PCCF weighting failed: {exc}")
    if col2.button("Build profile"):
        try:
            with st.spinner("Building merged profile..."):
                run_script(DATA_PROCESSING_DIR / "build_profile.py", str(selected_config))
            st.success("Profile build done")
        except subprocess.CalledProcessError as exc:
            st.error(f"Profile build failed: {exc}")
else:
    st.warning("Create or select a config to enable processing.")

st.header("3. Map")
st.caption("This embeds the existing MapLibre web map in the Streamlit app.")
components.iframe(MAP_APP_URL, height=900, scrolling=True)
st.caption("If the map does not load, start the local static server from the project root with `python -m http.server 8000`.")

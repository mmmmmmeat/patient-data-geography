from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SETUP_SCRIPT = ROOT / "data processing" / "setup_dataset.py"


WINDOWS_CANDIDATES = [
    r"C:\Program Files\QGIS 4.0.1\apps\Python312\python.exe",
    r"C:\Program Files\QGIS 4.0.1\bin\python-qgis.bat",
    r"C:\OSGeo4W\bin\python.exe",
    r"C:\OSGeo4W64\bin\python.exe",
]


UNIX_CANDIDATES = [
    "python3",
    "python",
]


def candidate_exists(candidate: str) -> bool:
    path = Path(candidate)
    if path.exists():
        return True
    return shutil.which(candidate) is not None


def choose_python() -> str:
    if candidate_exists(sys.executable):
        return sys.executable

    system = platform.system().lower()
    candidates = WINDOWS_CANDIDATES if system == "windows" else UNIX_CANDIDATES
    for candidate in candidates:
        if candidate_exists(candidate):
            return candidate

    raise RuntimeError(
        "Could not find a usable Python interpreter. "
        "Install Python with GDAL support or QGIS/OSGeo4W, then try again."
    )


def main() -> int:
    if not SETUP_SCRIPT.exists():
        raise FileNotFoundError(f"Setup script not found: {SETUP_SCRIPT}")

    python_exe = choose_python()
    print(f"Using Python: {python_exe}")
    completed = subprocess.run([python_exe, str(SETUP_SCRIPT)], cwd=str(ROOT))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

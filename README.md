# New Profile Builder

Prototype workspace for the geography-aware burn profile pipeline.

## Current structure

- `app.js`, `index.html`, `styles.css`, `config.js` - current web app
- `data processing/` - data setup and future cleaning scripts
- `data processing/setup_dataset.py` - interactive dataset setup script
- `data processing/configs/` - saved config files, one per dataset

## Setup flow

Run the setup script to create a dataset-specific config:

```bash
python "data processing/setup_dataset.py"
```

Or use the launcher from the repo root:

```bash
python run_setup.py
```

The script will ask for:

- dataset name
- raw patient data file
- area type in the data
- area type to display on the map
- province or provinces
- whether PCCF conversion is available
- area link column
- age column
- sex column
- length of stay column
- outcome columns

It then writes a JSON config into `data processing/configs/` for that dataset.

## Notes

- This setup step is only responsible for collecting metadata and saving config.
- Later scripts will read that config and do the map cleaning, patient cleaning, PCCF conversion, and profile building.
- The province list is based on Canadian provinces and territories, since the workflow is intended to stay Canada-only.
- The current setup script also looks at `C:\Users\sawye\Downloads\map links.csv` for province/area-type map download links.

## Dependencies

- Python is required to run the setup and data processing scripts.
- Node.js is required only if you want the optional `npx onedrive-link` helper to resolve SharePoint/OneDrive download links automatically.
- If you are not using the OneDrive helper, Node.js is optional.

## Installing GDAL

### Windows

- Easiest path: install QGIS or OSGeo4W, which includes a native GDAL build and matching Python bindings.
- If QGIS is installed, the repo can usually use the bundled Python automatically.
- The launcher checks common Windows locations such as `C:\Program Files\QGIS 4.0.1\apps\Python312\python.exe` and OSGeo4W Python paths.
- If you prefer the command line, keep GDAL available through the QGIS/OSGeo4W Python instead of trying to build it into the system Python.

### macOS and other Unix-like systems

- Install Python 3 plus GDAL with your package manager or your preferred Python distribution.
- Common options:
  - Homebrew on macOS
  - `apt`/`dnf`/`pacman` on Linux
  - `python3 -m pip install gdal` only if the native GDAL libraries are already installed
- The launcher falls back to `python3` or `python` on Unix-like systems.
- After install, verify imports with:

```bash
python3 -c "from osgeo import gdal; print(gdal.VersionInfo())"
```

## Launcher behavior

- The launcher does not install dependencies.
- It only finds an existing Python that can run the setup script.
- On Windows, it prefers QGIS/OSGeo4W-style Python installs.
- On Unix-like systems, it prefers `python3` and then `python`.

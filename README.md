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

## SDOH score weights

The score logic is implemented in `data processing/build_profile.py`. Most scores are normalized directly from a single census measure, and a few are built from weighted subcomponents.

### Directly normalized scores

- `income_score`
  - source: `income_median`
  - normalized to 0 to 100
  - inverted so higher income becomes lower deprivation
- `major_repairs_score`
  - source: `major_repairs_rate`
  - normalized to 0 to 100
- `education_score`
  - source: `hs_complete_rate`
  - normalized to 0 to 100
  - inverted
- `employment_score`
  - source: `employment_rate`
  - normalized to 0 to 100
- `moved_score`
  - source: `moved_rate`
  - normalized to 0 to 100
- `car_commute_score`
  - source: `car_commute_rate`
  - normalized to 0 to 100
  - inverted
- `dep_mat`
  - source: `SCOREMAT`
  - normalized to 0 to 100
- `dep_soc`
  - source: `SCORESOC`
  - normalized to 0 to 100
- `res_score`
  - source: provincial/Canada census reference file, `Residential instability Scores`
  - normalized to 0 to 100
- `eco_score`
  - source: provincial/Canada census reference file, `Economic dependency Scores`
  - normalized to 0 to 100

### Weighted subcomponents

#### Housing

`housing_score` is the mean of:

- `major_repairs_score`
- `house_age_score`
- `moved_score`

`house_age_score` comes from a weighted index of the housing build-year categories:

- `1441_rate` = weight `8`
- `1442_rate` = weight `7`
- `1443_rate` = weight `6`
- `1444_rate` = weight `5`
- `1445_rate` = weight `4`
- `1446_rate` = weight `3`
- `1447_rate` = weight `2`
- `1448_rate` = weight `1`

That ordering is descending from oldest to newest category.

#### Family

`family_score` is the mean of:

- `family_size_score`
- `children_score`
- `one_parent_score`

There are no additional custom weights inside this group.

#### Generation

`generation_score` comes from a weighted index of the generation-status categories:

- `1666_rate` = weight `3`
- `1667_rate` = weight `2`
- `1668_rate` = weight `1`

#### Commuting / transport

`commute_score` is the mean of:

- `car_commute_score`
- `commute_time_score`

`commute_time_score` comes from a weighted index of commute-time categories:

- `2612_rate` = weight `1`
- `2613_rate` = weight `2`
- `2614_rate` = weight `3`
- `2615_rate` = weight `4`
- `2616_rate` = weight `5`

#### Final combined SDOH score

`sdoh_total_score` is the simple mean of the component scores:

- `income_score`
- `housing_score`
- `education_score`
- `employment_score`
- `family_score`
- `generation_score`
- `commute_score`
- `dep_mat`
- `dep_soc`
- `res_score`
- `eco_score`

It is not a weighted average.

### Notes on the attached weights document

The attached `Score weights.docx` matched the current code for the following items:

- housing build-year weights
- generation weights
- commute-time weights
- the fact that `sdoh_total_score` is a simple mean

One thing that could be confusing in the document is that it refers to some source fields by their derived score names rather than the exact intermediate column names in the code. The underlying weights themselves match the script.

## Dependencies

- Python is required to run the setup and data processing scripts.
- Third-party dependency and data-source notes are documented in [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md).

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

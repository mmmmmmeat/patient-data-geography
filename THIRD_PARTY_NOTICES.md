# Third-Party Notices

This repository bundles or depends on third-party software and data sources. Their licenses and terms remain with their respective authors and publishers.

## Bundled browser libraries

- MapLibre GL JS
  - File: [`maplibre-gl.js`](./maplibre-gl.js)
  - License: BSD 3-Clause
  - Source: https://github.com/maplibre/maplibre-gl-js
- MapLibre GL CSS
  - File: [`maplibre-gl.css`](./maplibre-gl.css)
  - Distributed with MapLibre GL JS
- Papa Parse
  - File: [`papaparse.min.js`](./papaparse.min.js)
  - License: MIT
  - Source: https://github.com/mholt/PapaParse

## Python dependencies

Installed through `requirements.txt`:

- `streamlit`
- `pandas`
- `openpyxl`
- `requests`
- `numpy`

These are third-party packages with their own upstream licenses. Refer to each package's project page or installed wheel metadata for the exact license text.

## Data sources and reference files

The project also reads and transforms external statistical and geographic reference files, including but not limited to:

- CIMD
- MSDI
- PCCF / PCCF+ reference data
- Statistics Canada census profile tables

These sources are used for research and processing within the app. Any redistribution, publication, or derivative use must follow the relevant provider terms, citation requirements, and access restrictions.

## Retained notices

Where a bundled file includes its own license header, that notice should remain intact.

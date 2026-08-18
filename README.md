# Patient Data Geographical Representation Tool

## Necessary files

- patient data
- PCCF

PCCF should be obtained through your institution through your DLI access.

## Setup Instructions

1. Ensure you have Python installed with `pip`. If you don't, or aren't sure, see the Python setup section.
2. If you want to create maps, you need to install QGIS. It is free: [https://qgis.org/download/](https://qgis.org/download/)
3. Download a ZIP file of this repository. Go to the `Code` tab at the top of the page, then click the green `Code` button. Then click `Download ZIP`.
4. Put the downloaded ZIP file somewhere on your computer, then unzip it.
5. Open a PowerShell window on Windows or a terminal on macOS, then change directory to the unzipped repository.
6. Run `pip install -r requirements.txt`.
7. Once that is complete, run the app:

```bash
python "test2/launch_app.py"
```

On macOS or Linux, this may need to be:

```bash
python3 "test2/launch_app.py"
```

This starts the local map server on port `8000`, launches Streamlit, and opens the browser automatically.

8. The app window should open automatically. If it does not, paste `http://localhost:8501` into a browser address bar.
9. Enter the prompted fields in the app. The province selector will only work for provinces you have a PCCF for.
10. There are 2 upload sections: one for your patient data and one for your PCCF. Drop each into their respective upload boxes. Use the `Use global PCCF` option if you want to avoid uploading the PCCF multiple times.
11. Enter a name for your configuration. It can be saved and selected later if you create different maps.
12. Save your config.
13. In the processing section, there are 2 buttons you only need to click once: `Download pre-filtered census data` and `Build weighted PCCF`. Click them in that order.
14. For each new config you will need to build a profile. Click the `Build profile` button.
15. For each new map type you will need to build the map. Click the `Build map` button. This may take a while. If you build the map for Ontario DA-level data, for example, you do not need to build it again for another Ontario DA-level map.
16. The map will now be displayed at the bottom of the page. You may need to reload the page for it to show. Hover over areas to show statistics, and use the metrics section to switch the data displayed.

## Stopping the app

- Press `Ctrl+C` in the terminal that started the launcher.
- If you opened the app in a browser, you can close the tab or window, but that only closes the browser view.
- To fully stop the local servers, you still need to stop the launcher process in the terminal.

## Python setup

### Windows

1. Open PowerShell and run:

```powershell
python -V
```

2. If that does not work, try:

```powershell
py -V
```

3. If one of those commands shows a version, Python is installed.
4. If neither works, install Python from [https://www.python.org/downloads/](https://www.python.org/downloads/)
5. After installation, check `pip` with:

```powershell
pip -V
```

6. If `pip` is not available, try:

```powershell
python -m pip -V
```

7. If `pip` still is not available, run:

```powershell
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python -m get-pip.py
```

### Mac

1. Open Terminal and run:

```bash
python3 -V
```

2. If that shows a version, Python is installed.
3. If not, install Python from [https://www.python.org/downloads/](https://www.python.org/downloads/)
4. Check `pip` with:

```bash
pip -V
```

5. If that does not work, try:

```bash
python3 -m pip -V
```

6. If `pip` still is not available, run:

```bash
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python3 -m get-pip.py
```

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
  - source: census reference file, `Residential instability Scores`
  - normalized to 0 to 100
- `eco_score`
  - source: census reference file, `Economic dependency Scores`
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

`commute_time_score` comes from a weighted index of commute-time categories and is inverted so longer commute times map to higher risk:

- `2612_rate` = weight `1`
- `2613_rate` = weight `2`
- `2614_rate` = weight `3`
- `2615_rate` = weight `4`
- `2616_rate` = weight `5`

#### Final combined SDOH score

`sdoh_total_score` is a weighted average of the component scores:

- `income_score`
- `housing_score`
- `education_score`
- `employment_score`
- `family_score`
- `generation_score`
- `commute_score` with reduced weight
- `dep_mat`
- `dep_soc`
- `res_score`
- `eco_score`

The commuting component is intentionally given less influence than the other major score groups.

## Dependencies

- Python (and pip) is required to run the setup and data processing scripts.
- QGIS is required for creating maps.
- Third-party dependency and data-source notes are documented in [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md).

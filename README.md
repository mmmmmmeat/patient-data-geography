# New Profile Builder

Prototype workspace for the geography-aware profile pipeline.

## Current structure

- `app.js`, `index.html`, `styles.css`, `config.js` - current web app
- `data processing/` - data setup and future cleaning scripts
- `data processing/setup_dataset.py` - interactive dataset setup script
- `data processing/configs/` - saved config files, one per dataset
- `test2/launch_app.py` - cross-platform launcher that starts the local map server and Streamlit

## Necessary files

To use the app, the following inputs need to be available somewhere in the project workflow:

- patient data
- PCCF
- map data

PCCF should be obtained through your institution through your DLI access.

## Starting the app

1. Install Python 3.
2. Make sure `pip` is available.
3. Install the dependencies from `requirements.txt`.
4. Run the launcher:

```bash
python "test2/launch_app.py"
```

On macOS or Linux, this may need to be:

```bash
python3 "test2/launch_app.py"
```

This starts the local map server on port `8000`, launches Streamlit, and opens the browser automatically.

## Stopping the app

- Press `Ctrl+C` in the terminal that started the launcher.
- If you opened the app in a browser, you can close the tab or window, but that only closes the browser view.
- To fully stop the local servers, you still need to stop the launcher process in the terminal.

## Streamlit setup flow

The current Streamlit interface asks for the following in roughly this order:

1. Choose whether to use the current config or create a new config.
2. Select the current config if one exists.
3. Enter the name for the configuration when creating a new one.
4. Enter the map display area or areas.
5. Choose the map area display type:
   - dissemination area
   - census subdivision
   - forward sortation area
6. Select or upload the patient data file.
7. Select the patient data link column.
8. Select the age column.
9. Select the sex column and detect male/female values.
10. Select binary outcome columns and let the app detect affirmative/negative values where possible.
11. Select numeric outcome columns.
12. Set the privacy threshold for suppressing outcomes in low-count areas.
13. Select or upload the PCCF source, or use the global PCCF if one is already available.
14. Save the config, either overwriting the current config or saving as a new one.

## Notes

- This setup step is responsible for collecting metadata and saving config.
- Later scripts read that config and do map handling, patient handling, PCCF conversion, and profile building.
- The province list is based on Canadian provinces and territories, since the workflow is Canada-only.
- The current setup script also looks at `C:\Users\sawye\Downloads\map links.csv` for province and map download links.

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

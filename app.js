const CONFIG = window.BURN_APP_CONFIG;
const CURRENT_CONFIG_POINTER_URL = new URL(CONFIG.currentConfigPointer, window.location.href).href;

const STATE = {
  mode: "sdoh",
  sex: "total",
  metric: "sdoh_total_score",
  selected: null,
  dataByDauid: new Map(),
  loadedTiles: false,
  mapAreaType: "da",
  privacyMinIncidents: 0,
  geoColumn: "DAUID",
  tileGeoColumn: "DAUID",
};

const BASE_SDoh_METRICS = [
  { key: "income_score", label: "Income" },
  { key: "housing_score", label: "Housing" },
  { key: "education_score", label: "Education" },
  { key: "employment_score", label: "Employment" },
  { key: "family_score", label: "Family structure" },
  { key: "generation_score", label: "Generation status" },
  { key: "commute_score", label: "Commuting / transport" },
  { key: "dep_mat", label: "Material deprivation" },
  { key: "dep_soc", label: "Social deprivation" },
  { key: "res_score", label: "Residential instability" },
  { key: "eco_score", label: "Economic dependency" },
  { key: "sdoh_total_score", label: "Combined SDOH" },
];

const COLOR_RANGES = {
  sdoh: ["#f4f8fb", "#b9d2df", "#6c99b7", "#2e5c87", "#102f4d"],
  outcome: ["#fff4e5", "#f6c27a", "#ef8d4f", "#c7552f", "#7d1f13"],
};

const NO_DATA_COLOR = "#b4b8bc";

let TILE_URL = "";
let CSV_URL = "";
let METRICS = {
  sdoh: [...BASE_SDoh_METRICS],
  outcome: [],
};

let map = null;

function resolveGeoColumn(headers) {
  const normalized = new Map((headers || []).map((header) => [String(header).trim().toLowerCase(), String(header)]));
  const candidates = ["DAUID", "LINK", "ID", "CSDuid", "FSA"];
  for (const candidate of candidates) {
    const match = normalized.get(candidate.toLowerCase());
    if (match) return match;
  }
  return STATE.geoColumn || "";
}

function resolveTileGeoColumn(mapAreaType) {
  const normalized = String(mapAreaType || "").trim().toLowerCase();
  if (normalized === "csd") return "CSDUID";
  if (normalized === "fsa") return "CFSAUID";
  return "DAUID";
}

function sexSuffix() {
  if (STATE.sex === "m") return "_m";
  if (STATE.sex === "f") return "_f";
  return "_total";
}

function metricColumn(metric) {
  const suffix = sexSuffix();
  const sexAwareMetrics = new Set([
    "incidents_total",
    "avg_tbsa_total",
    "avg_icu_days_total",
    "avg_length_of_stay_total",
  ]);
  if (!sexAwareMetrics.has(metric)) return metric;
  return metric.replace("_total", suffix);
}

function getOutcomeMetricsFromConfig(config) {
  const metrics = [];
  for (const entry of config.binary_outcomes ?? []) {
    const label = String(entry.name ?? "").trim();
    if (!label) continue;
    metrics.push({ key: label, label });
  }
  for (const entry of config.numeric_outcomes ?? []) {
    const label = String(entry.name ?? "").trim();
    if (!label) continue;
    metrics.push({ key: label, label });
  }
  return metrics;
}

function outcomeMetricKey(baseMetric) {
  if (!baseMetric) return baseMetric;
  if (baseMetric.endsWith("_total") || baseMetric.endsWith("_m") || baseMetric.endsWith("_f")) {
    return baseMetric;
  }
  return `${baseMetric}${sexSuffix()}`;
}

function buildMapDataName(provinces, mapAreaType) {
  const provinceKey = [...(provinces || [])].map((p) => String(p).trim().toUpperCase()).filter(Boolean).sort().join("");
  return `${provinceKey}_${String(mapAreaType || "").trim().toUpperCase()}`;
}

function getAllMetricKeys() {
  const keys = new Set([
    ...METRICS.sdoh.map((m) => m.key),
    ...METRICS.outcome.map((m) => m.key),
    "incidents_total",
    "avg_age",
  ]);
  for (const outcome of METRICS.outcome) {
    keys.add(`${outcome.key}_total`);
    keys.add(`${outcome.key}_m`);
    keys.add(`${outcome.key}_f`);
  }
  return keys;
}

function isOutcomeMetric(metric) {
  return metric === "incidents_total" || metric.endsWith("_total") || metric.endsWith("_m") || metric.endsWith("_f");
}

function logMap(msg, extra) {
  if (extra !== undefined) console.log(`[map] ${msg}`, extra);
  else console.log(`[map] ${msg}`);
}

function buildMap() {
  map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        tiles: {
          type: "vector",
          promoteId: STATE.tileGeoColumn || "DAUID",
          tiles: [TILE_URL],
          minzoom: 0,
          maxzoom: 14,
        },
      },
      layers: [
        {
          id: "burn-fill",
          type: "fill",
          source: "tiles",
          "source-layer": CONFIG.tileSourceLayer,
          paint: { "fill-color": "#666", "fill-opacity": 0.65 },
        },
        {
          id: "burn-line",
          type: "line",
          source: "tiles",
          "source-layer": CONFIG.tileSourceLayer,
          paint: { "line-color": "rgba(255,255,255,0.5)", "line-width": 0.6 },
        },
      ],
      glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      sprite: "",
    },
    center: [-97.1384, 49.8951],
    zoom: 6.2,
  });

  map.addControl(new maplibregl.NavigationControl(), "top-right");
}

async function loadData() {
  const csv = await fetch(CSV_URL).then((r) => r.text());
  const parsed = Papa.parse(csv, { header: true, skipEmptyLines: true });
  logMap("CSV headers", parsed.meta?.fields || []);
  const csvHeaders = parsed.meta?.fields || [];
  STATE.geoColumn = resolveGeoColumn(csvHeaders);
  parsed.data.forEach((row) => {
    const geoValue = String(row[STATE.geoColumn] ?? row[STATE.geoColumn.toUpperCase()] ?? row[STATE.geoColumn.toLowerCase()] ?? "").trim();
    if (!geoValue) return;
    STATE.dataByDauid.set(geoValue, row);
  });
  logMap("Loaded geography keys", Array.from(STATE.dataByDauid.keys()).slice(0, 5));
}

function pickMetric() {
  const list = METRICS[STATE.mode];
  if (!list.some((m) => m.key === STATE.metric)) {
    STATE.metric = list[0]?.key || "sdoh_total_score";
  }
  if (STATE.mode === "outcome") {
    STATE.metric = outcomeMetricKey(STATE.metric);
  }
  const select = document.getElementById("metricSelect");
  select.innerHTML = list.map((m) => `<option value="${m.key}">${m.label}</option>`).join("");
  select.value = STATE.mode === "outcome" ? (STATE.metric.replace(/_(?:total|m|f)$/, "") || STATE.metric) : STATE.metric;
}

function colorExpression(metric) {
  const palette = COLOR_RANGES[STATE.mode];
  const resolvedMetric = STATE.mode === "outcome" ? outcomeMetricKey(metric) : metric;
  if (STATE.mode === "outcome" && STATE.privacyMinIncidents > 0) {
    const valuesWhenAllowed = [];
    for (const row of STATE.dataByDauid.values()) {
      if (Number(row.incidents_total) < STATE.privacyMinIncidents) continue;
      const metricValue = Number(row[metricColumn(resolvedMetric)]);
      if (Number.isFinite(metricValue)) valuesWhenAllowed.push(metricValue);
    }
    if (valuesWhenAllowed.length === 0) return NO_DATA_COLOR;
    const min = Math.min(...valuesWhenAllowed);
    const max = Math.max(...valuesWhenAllowed);
    const range = max - min || 1;
    const stops = palette.map((color, index) => [min + (range * index) / (palette.length - 1), color]);
    return [
      "case",
      ["<", ["to-number", ["feature-state", "incidents_total"]], STATE.privacyMinIncidents],
      NO_DATA_COLOR,
      ["!", ["boolean", ["feature-state", "has_value"], false]],
      NO_DATA_COLOR,
      ["interpolate", ["linear"], ["coalesce", ["to-number", ["feature-state", resolvedMetric]], min], ...stops.flat()],
    ];
  }
  const values = [];
  for (const row of STATE.dataByDauid.values()) {
    const metricValue = Number(row[metricColumn(resolvedMetric)]);
    if (Number.isFinite(metricValue)) values.push(metricValue);
  }
  if (values.length === 0) return NO_DATA_COLOR;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stops = palette.map((color, index) => [min + (range * index) / (palette.length - 1), color]);
  return [
    "case",
    ["!", ["boolean", ["feature-state", "has_value"], false]],
    NO_DATA_COLOR,
    ["interpolate", ["linear"], ["coalesce", ["to-number", ["feature-state", metric]], min], ...stops.flat()],
  ];
}

function updateFeatureState() {
  if (!map || !STATE.loadedTiles) return;
  for (const [dauid, row] of STATE.dataByDauid.entries()) {
    const state = {};
    for (const metric of getAllMetricKeys()) {
      const value = Number(row[metricColumn(metric)]);
      if (Number.isFinite(value)) state[metric] = value;
    }
    for (const outcome of METRICS.outcome) {
      const totalKey = `${outcome.key}_total`;
      const maleKey = `${outcome.key}_m`;
      const femaleKey = `${outcome.key}_f`;
      const totalValue = Number(row[metricColumn(totalKey)]);
      const maleValue = Number(row[metricColumn(maleKey)]);
      const femaleValue = Number(row[metricColumn(femaleKey)]);
      if (Number.isFinite(totalValue)) state[totalKey] = totalValue;
      if (Number.isFinite(maleValue)) state[maleKey] = maleValue;
      if (Number.isFinite(femaleValue)) state[femaleKey] = femaleValue;
    }
    state.incidents_total = Number.isFinite(Number(row.incidents_total)) ? Number(row.incidents_total) : state.incidents_total;
    if (STATE.mode === "outcome" && STATE.privacyMinIncidents > 0 && Number(row.incidents_total) < STATE.privacyMinIncidents) {
      for (const metric of Object.keys(state)) {
        if (metric !== "incidents_total" && metric !== "avg_age" && !metric.endsWith("_score")) {
          delete state[metric];
        }
      }
    }
    state.has_value = Object.keys(state).length > 0;
    map.setFeatureState({ source: "tiles", sourceLayer: CONFIG.tileSourceLayer, id: dauid }, state);
  }
}

function updateMapPaint() {
  if (!map) return;
  map.setPaintProperty("burn-fill", "fill-color", colorExpression(STATE.metric));
  map.setPaintProperty("burn-fill", "fill-opacity", STATE.mode === "outcome" ? 0.78 : 0.72);
}

function updateLegend() {
  const metric = STATE.metric;
  const title = METRICS[STATE.mode].find((m) => m.key === metric)?.label ?? metric;
  document.getElementById("legend").innerHTML = `<strong>${title}</strong><br/>Low <span style="opacity:.7">-&gt;</span> High`;
}

function formatValue(value) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  return Number.isInteger(num) ? String(num) : num.toFixed(1);
}

function setSelected(dauid) {
  STATE.selected = dauid;
  const row = STATE.dataByDauid.get(String(dauid)) || {};
  document.getElementById("daid").textContent = dauid ?? "-";
  const csdWrap = document.getElementById("csdNameWrap");
  const csdValue = document.getElementById("csdName");
  if (STATE.mapAreaType === "fsa") {
    csdWrap.style.display = "none";
    csdValue.textContent = "-";
  } else {
    const csdName = String(row.csd_name || row.CSDname || row.CSD_NAME || "").trim();
    if (csdName) {
      csdWrap.style.display = "";
      csdValue.textContent = csdName;
    } else {
      csdWrap.style.display = "none";
      csdValue.textContent = "-";
    }
  }
  const incidentsValue = formatValue(row[metricColumn("incidents_total")]);
  const suppressed = STATE.privacyMinIncidents > 0 && Number(row.incidents_total) < STATE.privacyMinIncidents;
  document.getElementById("incidents").textContent = suppressed
    ? `${incidentsValue} (suppressed)`
    : incidentsValue;
  document.getElementById("avgAge").textContent = formatValue(row.avg_age);
  document.getElementById("featureId").textContent = dauid ?? "-";

  const items = [
    ["SDOH", formatValue(row.sdoh_total_score)],
    ["Income", formatValue(row.income_score)],
    ["Housing", formatValue(row.housing_score)],
    ["Employment", formatValue(row.employment_score)],
    ["Education", formatValue(row.education_score)],
    ["Material dep.", formatValue(row.dep_mat)],
    ["Social dep.", formatValue(row.dep_soc)],
    ["Residential instability", formatValue(row.res_score)],
    ["Economic dependency", formatValue(row.eco_score)],
  ];
  document.getElementById("summaryList").innerHTML = items
    .map(([label, value]) => `<div class="summary-item"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function wireUI() {
  document.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });
  document.querySelectorAll("[data-sex]").forEach((btn) => {
    btn.addEventListener("click", () => setSex(btn.dataset.sex));
  });
  document.getElementById("metricSelect").addEventListener("change", (e) => {
    STATE.metric = e.target.value;
    updateMapPaint();
    updateLegend();
  });
}

function setMode(mode) {
  STATE.mode = mode;
  pickMetric();
  updateFeatureState();
  updateMapPaint();
  updateLegend();
  document.querySelectorAll("[data-mode]").forEach((btn) => btn.classList.toggle("active", btn.dataset.mode === mode));
}

function setSex(sex) {
  STATE.sex = sex;
  document.querySelectorAll("[data-sex]").forEach((btn) => btn.classList.toggle("active", btn.dataset.sex === sex));
  updateFeatureState();
  updateMapPaint();
  updateLegend();
  if (STATE.mode === "outcome" && STATE.metric) {
    STATE.metric = outcomeMetricKey(STATE.metric);
  }
  if (STATE.selected) setSelected(STATE.selected);
}

async function loadCurrentConfig() {
  const currentConfig = await fetch(CURRENT_CONFIG_POINTER_URL).then((r) => r.json());
  const configPath = String(currentConfig.current_config || "");
  const configStem = configPath.split(/[/\\]/).pop().replace(/\.json$/i, "");
  const selectedConfigUrl = new URL(`./data processing/configs/${configStem}.json`, window.location.href).href;
  const selectedConfig = await fetch(selectedConfigUrl).then((r) => r.json());
  logMap("Current config pointer", currentConfig);
  logMap("Selected config stem", configStem);
  STATE.mapAreaType = String(selectedConfig.map_area_type || "da").trim().toLowerCase();
  STATE.privacyMinIncidents = Number(selectedConfig.privacy_min_incidents || 0) || 0;
  STATE.tileGeoColumn = resolveTileGeoColumn(STATE.mapAreaType);
  STATE.geoColumn = "DAUID";
  const mapDataName = selectedConfig.map_data_name || buildMapDataName(selectedConfig.provinces, selectedConfig.map_area_type);
  TILE_URL = `${new URL(`./data processing/map/map data/${mapDataName}/`, window.location.href).href}{z}/{x}/{y}.pbf`;
  CSV_URL = new URL(`./data processing/map/merged data/${selectedConfig.dataset_name || configStem}.csv`, window.location.href).href;
  logMap("Resolved map inputs", {
    mapAreaType: STATE.mapAreaType,
    geoColumn: STATE.geoColumn,
    tileGeoColumn: STATE.tileGeoColumn,
    mapDataName,
    tileSourceLayer: CONFIG.tileSourceLayer,
    tileUrl: TILE_URL,
    csvUrl: CSV_URL,
  });
  METRICS = {
    sdoh: [...BASE_SDoh_METRICS],
    outcome: getOutcomeMetricsFromConfig(selectedConfig),
  };
  if (METRICS.outcome.length === 0) {
    METRICS.outcome = [{ key: "sdoh_total_score", label: "Combined SDOH" }];
  }
}

function initMapListeners() {
  map.on("mousemove", "burn-fill", (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const dauid = getFeatureGeoId(f.properties);
    map.getCanvas().style.cursor = "pointer";
    setSelected(dauid);
  });

  map.on("mouseleave", "burn-fill", () => {
    map.getCanvas().style.cursor = "";
  });

  map.on("click", "burn-fill", (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const dauid = getFeatureGeoId(f.properties);
    setSelected(dauid);
  });

  map.on("sourcedata", (e) => {
    if (e.sourceId === "tiles") {
      STATE.loadedTiles = e.isSourceLoaded || STATE.loadedTiles;
      if (STATE.loadedTiles) {
        updateFeatureState();
        updateMapPaint();
      }
    }
  });

  map.on("error", (e) => {
    logMap("error", e?.error ?? e);
  });
}

function getFeatureGeoId(properties) {
  if (!properties) return "";
  const candidates = [
    "DAUID",
    "dauid",
    "CSDUID",
    "csduid",
    "CFSAUID",
    "cfsauid",
    "LINK",
    "link",
    "ID",
    "id",
    "FSA",
    "fsa",
    STATE.geoColumn,
    STATE.geoColumn.toUpperCase(),
    STATE.geoColumn.toLowerCase(),
  ];
  for (const key of candidates) {
    if (Object.prototype.hasOwnProperty.call(properties, key)) {
      const value = String(properties[key] ?? "").trim();
      if (value) return value;
    }
  }
  return "";
}

async function main() {
  await loadCurrentConfig();
  buildMap();

  map.on("load", async () => {
    logMap("loaded");
    await loadData();
    logMap("CSV loaded", { rows: STATE.dataByDauid.size });
    wireUI();
    setMode("sdoh");
    setSex("total");
    updateFeatureState();
    updateLegend();
    initMapListeners();
  });
}

main().catch((err) => {
  console.error(err);
  const legend = document.getElementById("legend");
  if (legend) legend.textContent = `Failed to initialize map: ${err?.message || err}`;
});

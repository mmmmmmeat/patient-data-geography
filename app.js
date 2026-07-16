const CONFIG = window.BURN_APP_CONFIG;
const TILE_URL = `${new URL("./xyz/", window.location.href).href}{z}/{x}/{y}.pbf`;
const CURRENT_CONFIG_POINTER_URL = new URL(CONFIG.currentConfigPointer, window.location.href).href;

const SDOH_METRICS = [
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

const STATE = {
  mode: "sdoh",
  sex: "total",
  metric: "sdoh_total_score",
  selected: null,
  dataByDauid: new Map(),
  loadedTiles: false,
  manifest: null,
  outcomeMetrics: [],
  currentConfigPath: null,
};

const COLOR_RANGES = {
  sdoh: ["#f4f8fb", "#b9d2df", "#6c99b7", "#2e5c87", "#102f4d"],
  outcome: ["#fff4e5", "#f6c27a", "#ef8d4f", "#c7552f", "#7d1f13"],
  combined: ["#f2f0ff", "#c7b8ff", "#9777ff", "#6a4bd8", "#381f82"],
};

const NO_DATA_COLOR = "#b4b8bc";

function sanitizeOutcomeKey(name) {
  return String(name || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function buildOutcomeMetrics(manifest) {
  const metrics = [];
  const seen = new Set();
  for (const outcome of [...(manifest?.binary_outcomes ?? []), ...(manifest?.numeric_outcomes ?? [])]) {
    const base = sanitizeOutcomeKey(outcome.name);
    if (!base || seen.has(base)) continue;
    seen.add(base);
    metrics.push({ key: `${base}_total`, label: outcome.name, base });
  }
  return metrics;
}

function getMetricsForMode(mode) {
  if (mode === "sdoh") return SDOH_METRICS;
  if (mode === "combined") {
    return [
      { key: "sdoh_total_score", label: "Combined SDOH" },
      ...STATE.outcomeMetrics,
    ];
  }
  return STATE.outcomeMetrics;
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
    ...STATE.outcomeMetrics.map((metricDef) => metricDef.key),
  ]);
  if (!sexAwareMetrics.has(metric)) return metric;
  return metric.replace("_total", suffix);
}

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      tiles: {
        type: "vector",
        promoteId: "DAUID",
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
        paint: {
          "fill-color": "#666",
          "fill-opacity": 0.65,
        },
      },
      {
        id: "burn-line",
        type: "line",
        source: "tiles",
        "source-layer": CONFIG.tileSourceLayer,
        paint: {
          "line-color": "rgba(255,255,255,0.5)",
          "line-width": 0.6,
        },
      },
    ],
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sprite: "",
  },
  center: [-97.1384, 49.8951],
  zoom: 6.2,
});

map.addControl(new maplibregl.NavigationControl(), "top-right");

function logMap(msg, extra) {
  if (extra !== undefined) {
    console.log(`[map] ${msg}`, extra);
  } else {
    console.log(`[map] ${msg}`);
  }
}

function formatValue(value) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  return Number.isInteger(num) ? String(num) : num.toFixed(1);
}

async function loadData() {
  const pointer = await fetch(CURRENT_CONFIG_POINTER_URL).then((r) => r.json());
  const configUrl = new URL(pointer.current_config, window.location.href).href;
  const config = await fetch(configUrl).then((r) => r.json());
  STATE.currentConfigPath = pointer.current_config;
  const configStem = String(pointer.current_config).split("/").pop().replace(/\.json$/i, "");
  const csvUrl = new URL(`./data processing/map/merged data/${configStem}.csv`, window.location.href).href;
  const manifestUrl = new URL(`./data processing/map/merged data/current_output.json`, window.location.href).href;
  const manifest = await fetch(manifestUrl).then((r) => r.json());
  STATE.manifest = manifest;
  STATE.outcomeMetrics = buildOutcomeMetrics(config);
  const csv = await fetch(csvUrl).then((r) => r.text());
  const parsed = Papa.parse(csv, { header: true, skipEmptyLines: true });
  parsed.data.forEach((row) => {
    const dauid = String(row.DAUID || row.dauid || "").trim();
    if (!dauid) return;
    STATE.dataByDauid.set(dauid, row);
  });
}

function updateMetricSelect() {
  const list = getMetricsForMode(STATE.mode);
  if (!list.some((m) => m.key === STATE.metric)) {
    STATE.metric = list[0]?.key || "sdoh_total_score";
  }
  const select = document.getElementById("metricSelect");
  select.innerHTML = list.map((m) => `<option value="${m.key}">${m.label}</option>`).join("");
  select.value = STATE.metric;
}

function colorExpression(metric) {
  const palette = COLOR_RANGES[STATE.mode];
  const values = [];
  for (const row of STATE.dataByDauid.values()) {
    const metricValue = Number(row[metricColumn(metric)]);
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
    [
      "interpolate",
      ["linear"],
      ["coalesce", ["to-number", ["feature-state", metric]], min],
      ...stops.flat(),
    ],
  ];
}

function updateFeatureState() {
  if (!STATE.loadedTiles) return;
  const allMetrics = new Set([
    ...SDOH_METRICS.map((m) => m.key),
    ...STATE.outcomeMetrics.map((m) => m.key),
    "incidents_total",
    "avg_age",
    "avg_tbsa_total",
    "avg_icu_days_total",
    "avg_length_of_stay_total",
  ]);

  for (const [dauid, row] of STATE.dataByDauid.entries()) {
    const state = {};
    for (const metric of allMetrics) {
      const value = Number(row[metricColumn(metric)]);
      if (Number.isFinite(value)) state[metric] = value;
    }
    state.has_value = Object.keys(state).length > 0;
    map.setFeatureState({ source: "tiles", sourceLayer: CONFIG.tileSourceLayer, id: dauid }, state);
  }
}

function updateMapPaint() {
  map.setPaintProperty("burn-fill", "fill-color", colorExpression(STATE.metric));
  map.setPaintProperty("burn-fill", "fill-opacity", STATE.mode === "outcome" ? 0.78 : 0.72);
}

function updateLegend() {
  const metric = STATE.metric;
  const title = getMetricsForMode(STATE.mode).find((m) => m.key === metric)?.label ?? metric;
  document.getElementById("legend").innerHTML = `<strong>${title}</strong><br/>Low -> High`;
}

function buildSummaryItems(row) {
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

  for (const outcome of STATE.manifest?.binary_outcomes ?? []) {
    const base = sanitizeOutcomeKey(outcome.name);
    items.push([`${outcome.name} (total)`, formatValue(row[`${base}_total`])]);
    items.push([`${outcome.name} (male)`, formatValue(row[`${base}_m`])]);
    items.push([`${outcome.name} (female)`, formatValue(row[`${base}_f`])]);
  }

  for (const outcome of STATE.manifest?.numeric_outcomes ?? []) {
    const base = sanitizeOutcomeKey(outcome.name);
    items.push([`${outcome.name} (total)`, formatValue(row[`${base}_total`])]);
    items.push([`${outcome.name} (male)`, formatValue(row[`${base}_m`])]);
    items.push([`${outcome.name} (female)`, formatValue(row[`${base}_f`])]);
  }

  return items;
}

function setSelected(dauid) {
  STATE.selected = dauid;
  const row = STATE.dataByDauid.get(String(dauid)) || {};
  document.getElementById("daid").textContent = dauid ?? "-";
  document.getElementById("csdName").textContent = row.csd_name ?? "-";
  document.getElementById("incidents").textContent = formatValue(row[metricColumn("incidents_total")]);
  document.getElementById("avgAge").textContent = formatValue(row.avg_age);
  document.getElementById("summaryList").innerHTML = buildSummaryItems(row)
    .map(([label, value]) => `<div class="summary-item"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function setMode(mode) {
  STATE.mode = mode;
  updateMetricSelect();
  updateFeatureState();
  updateMapPaint();
  updateLegend();
  document.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
}

function setSex(sex) {
  STATE.sex = sex;
  document.querySelectorAll("[data-sex]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.sex === sex);
  });
  updateFeatureState();
  updateMapPaint();
  updateLegend();
  if (STATE.selected) setSelected(STATE.selected);
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

map.on("load", async () => {
  logMap("loaded");
  await loadData();
  logMap("CSV loaded", {
    rows: STATE.dataByDauid.size,
    config: STATE.currentConfigPath,
    manifest: STATE.manifest?.output_csv,
  });
  wireUI();
  setMode("sdoh");
  setSex("total");
  updateFeatureState();
  updateLegend();

  map.on("mousemove", "burn-fill", (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const dauid = String(f.properties.DAUID || f.properties.dauid || "");
    map.getCanvas().style.cursor = "pointer";
    setSelected(dauid);
  });

  map.on("mouseleave", "burn-fill", () => {
    map.getCanvas().style.cursor = "";
  });

  map.on("click", "burn-fill", (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const dauid = String(f.properties.DAUID || f.properties.dauid || "");
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
});

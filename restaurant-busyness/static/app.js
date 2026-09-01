/* Busy or Not — frontend for the Restaurant & Cafe Busyness API.
   One search box: venue names, cities, and categories all go to
   /v1/search, which works out what was meant. No build step, no deps. */

const $ = (sel) => document.querySelector(sel);

const state = {
  venues: [],
  filter: "all",
  sort: "relevance",
  view: "list",
  origin: null,        // {lat, lng} of the resolved place, when there is one
  lastQuery: "",
  drawerVenue: null,
  forecastDay: null,
};

const LEVEL_CLASS = { not_busy: "q", moderate: "m", busy: "b", very_busy: "v" };
const LEVEL_TEXT = {
  not_busy: "Not busy", moderate: "Moderate",
  busy: "Busy", very_busy: "Very busy",
};
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/* ---------- helpers ---------- */

async function api(path, options) {
  const res = await fetch(path, options);
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    throw new Error((body && (body.error || body.detail)) || `Request failed (${res.status})`);
  }
  return body;
}

function setStatus(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg || "";
  el.classList.toggle("error", Boolean(isError));
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function levelClass(b) {
  return b && b.level ? LEVEL_CLASS[b.level] || "none" : "none";
}

function levelText(b) {
  if (!b || b.busyness_score === null || b.busyness_score === undefined) return "No data";
  return LEVEL_TEXT[b.level] || "Unknown";
}

/* Circular busyness gauge. */
function ring(score, cls, size = 54) {
  const r = size / 2 - 5, circ = 2 * Math.PI * r;
  const pct = score === null || score === undefined ? 0 : score / 100;
  const label = score === null || score === undefined ? "–" : score;
  return `
    <div class="ring" style="width:${size}px;height:${size}px">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
        <circle class="track" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="5"/>
        <circle class="value stroke-${cls}" cx="${size / 2}" cy="${size / 2}" r="${r}"
                fill="none" stroke-width="5"
                stroke-dasharray="${(circ * pct).toFixed(1)} ${circ.toFixed(1)}"/>
      </svg>
      <div class="num ${cls}">${label}</div>
    </div>`;
}

/* ---------- rendering ---------- */

function visibleVenues() {
  let list = state.venues.slice();

  if (state.filter === "quiet") {
    list = list.filter((v) => ["not_busy", "moderate"].includes(v.busyness?.level));
  } else if (state.filter === "busy") {
    list = list.filter((v) => ["busy", "very_busy"].includes(v.busyness?.level));
  }

  const score = (v) => v.busyness?.busyness_score ?? -1;
  const sorters = {
    // The API already returns best-match order; keep it as received.
    relevance: null,
    busyness: (a, b) => score(b) - score(a),
    quietest: (a, b) => {
      const [x, y] = [score(a), score(b)];
      if (x < 0) return 1;
      if (y < 0) return -1;
      return x - y;
    },
    distance: (a, b) => (a.distance_km ?? 1e9) - (b.distance_km ?? 1e9),
    name: (a, b) => String(a.name || "").localeCompare(String(b.name || "")),
  };
  const sorter = sorters[state.sort];
  return sorter ? list.sort(sorter) : list;
}

function renderResults() {
  const list = visibleVenues();
  const grid = $("#results");
  $("#controls").hidden = state.venues.length === 0;

  if (!list.length) {
    grid.innerHTML = state.venues.length
      ? `<p class="empty">Nothing matches this filter.</p>`
      : `<p class="empty">No venues found. Try a different name or city.</p>`;
    return;
  }

  grid.innerHTML = list.map((v, i) => {
    const b = v.busyness || {};
    const cls = levelClass(b);
    const live = b.source && b.source.includes("live");
    const checkins = b.recent_checkins || 0;
    return `
      <article class="card" tabindex="0" role="button" data-index="${i}"
               aria-label="${escapeHtml(v.name || "Venue")}, ${levelText(b)}">
        <div class="card-head">
          <div style="min-width:0">
            <h3>${escapeHtml(v.name || "Unnamed venue")}</h3>
            <p class="addr">${escapeHtml(v.address || v.timezone || "")}</p>
          </div>
          ${ring(b.busyness_score, cls)}
        </div>
        <div class="meta">
          <span class="level ${cls}">${levelText(b)}</span>
          ${live ? '<span class="tag live">● live</span>' : ""}
          ${checkins ? `<span class="tag">${checkins} check-in${checkins > 1 ? "s" : ""}</span>` : ""}
          ${v.distance_km != null ? `<span class="tag">${v.distance_km} km</span>` : ""}
        </div>
      </article>`;
  }).join("");

  if (state.view === "map") renderMap();

  grid.querySelectorAll(".card").forEach((card) => {
    const open = () => openDrawer(list[Number(card.dataset.index)]);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
}

function showSkeletons(n = 6) {
  $("#controls").hidden = true;
  $("#results").innerHTML = Array.from({ length: n }, () => `
    <article class="card skeleton">
      <div class="card-head">
        <div style="flex:1">
          <div class="bar" style="width:65%;height:15px;margin-bottom:8px"></div>
          <div class="bar" style="width:85%"></div>
        </div>
        <div class="bar" style="width:54px;height:54px;border-radius:50%"></div>
      </div>
      <div class="bar" style="width:40%"></div>
    </article>`).join("");
}

/* ---------- search ---------- */

async function runSearch(query, extra = {}) {
  const q = (query ?? $("#q").value).trim();
  if (!q) { setStatus("Type a venue name or a place to search."); return; }

  $("#q").value = q;
  state.lastQuery = q;
  $("#search-btn").disabled = true;
  setStatus("Searching…");
  showSkeletons();

  const params = new URLSearchParams({ q, radius: "5000", limit: "24", ...extra });

  try {
    const data = await api(`/v1/search?${params}`);
    state.venues = data.results || [];
    state.origin = data.interpretation?.place ? true : null;
    // Best-match order only means something for a name search.
    state.sort = data.interpretation?.mode === "venue" ? "relevance" : "busyness";
    $("#sort").value = state.sort;
    renderResults();
    setStatus(describeResults(data));
  } catch (err) {
    state.venues = [];
    renderResults();
    setStatus(err.message, true);
  } finally {
    $("#search-btn").disabled = false;
  }
}

function describeResults(data) {
  const n = data.count ?? 0;
  const where = data.interpretation?.place;
  const bits = [`${n} ${n === 1 ? "venue" : "venues"}${where ? ` in ${where}` : ""}`];
  if (data.source === "simulated") bits.push("demo data");
  if (data.source === "simulated_fallback") bits.push("BestTime unavailable — showing demo data");
  if (data.cached) bits.push("cached");
  if (!n && data.job_id) {
    return "BestTime is still collecting venues for this area — search again in a moment.";
  }
  return bits.join(" · ");
}

async function refreshBusyness() {
  if (!state.venues.length) return;
  setStatus("Refreshing…");
  await Promise.all(state.venues.map(async (v) => {
    if (!v.venue_id) return;
    try {
      const data = await api(`/v1/venues/${encodeURIComponent(v.venue_id)}/live`);
      v.busyness = data.busyness;
    } catch { /* keep the previous value for this venue */ }
  }));
  renderResults();
  setStatus(`Updated ${new Date().toLocaleTimeString()}`);
}

/* ---------- drawer ---------- */

async function openDrawer(venue) {
  if (!venue) return;
  state.drawerVenue = venue;
  const today = new Date().getDay();
  state.forecastDay = today === 0 ? 6 : today - 1;

  $("#drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;
  document.body.style.overflow = "hidden";

  const b = venue.busyness || {};
  const cls = levelClass(b);
  $("#drawer-body").innerHTML = `
    <h2>${escapeHtml(venue.name || "Venue")}</h2>
    <p class="addr">${escapeHtml(venue.address || "")}</p>
    <div class="now">
      ${ring(b.busyness_score, cls, 64)}
      <div>
        <div class="big ${cls}">${levelText(b)}</div>
        <div class="sub">${escapeHtml(describeSource(b))}</div>
      </div>
    </div>
    <h4>How busy through the day</h4>
    <div class="days" id="days"></div>
    <div id="chart-area"><p class="hint">Loading forecast…</p></div>
    <h4>How busy is it right now?</h4>
    <div class="checkin" id="checkin">
      ${["quiet", "moderate", "busy", "packed"].map((lv) =>
        `<button class="lv-${lv}" data-level="${lv}">${lv[0].toUpperCase() + lv.slice(1)}</button>`
      ).join("")}
    </div>
    <p class="hint">Your report is blended into this venue's score for the next 2 hours.</p>`;

  $("#checkin").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-level]");
    if (btn) submitCheckin(venue, btn.dataset.level);
  });

  renderDayButtons();
  loadForecast(venue);
}

function describeSource(b) {
  if (!b || b.busyness_score == null) return "No busyness data available";
  const parts = [];
  if (b.source?.includes("live")) parts.push("live foot traffic");
  else if (b.source?.includes("forecast") || b.source?.includes("predicted")) parts.push("forecast");
  if (b.source?.includes("checkins")) parts.push(`${b.recent_checkins} recent check-in(s)`);
  return parts.length ? `Based on ${parts.join(" + ")}` : `Score ${b.busyness_score}/100`;
}

function renderDayButtons() {
  $("#days").innerHTML = DAYS.map((d, i) =>
    `<button class="day-btn ${i === state.forecastDay ? "active" : ""}" data-day="${i}">${d}</button>`
  ).join("");
  $("#days").querySelectorAll(".day-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.forecastDay = Number(btn.dataset.day);
      renderDayButtons();
      loadForecast(state.drawerVenue);
    });
  });
}

async function loadForecast(venue) {
  const area = $("#chart-area");
  if (!venue?.venue_id) { area.innerHTML = `<p class="hint">No forecast available.</p>`; return; }

  try {
    const data = await api(
      `/v1/venues/${encodeURIComponent(venue.venue_id)}/forecast?day=${state.forecastDay}`);
    const day = (data.days || [])[0];
    const hours = day?.hours || [];
    if (!hours.length) { area.innerHTML = `<p class="hint">No forecast for this day.</p>`; return; }

    const today = new Date().getDay();
    const isToday = state.forecastDay === (today === 0 ? 6 : today - 1);
    const currentHour = new Date().getHours();

    area.innerHTML = `
      <div class="chart">
        ${hours.map((h) => `
          <div class="hour ${isToday && h.hour === currentHour ? "current" : ""}"
               title="${h.hour}:00 — ${h.busyness_score}/100">
            <div class="fill bg-${LEVEL_CLASS[h.level] || "none"}"
                 style="height:${Math.max(h.busyness_score, 2)}%"></div>
          </div>`).join("")}
      </div>
      <div class="axis"><span>12am</span><span>6am</span><span>12pm</span><span>6pm</span><span>11pm</span></div>`;
  } catch (err) {
    area.innerHTML = `<p class="hint">Could not load forecast: ${escapeHtml(err.message)}</p>`;
  }
}

async function submitCheckin(venue, level) {
  const buttons = $("#checkin").querySelectorAll("button");
  buttons.forEach((b) => (b.disabled = true));
  try {
    const data = await api(`/v1/venues/${encodeURIComponent(venue.venue_id)}/checkin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level }),
    });
    venue.busyness = data.busyness;

    const b = data.busyness, cls = levelClass(b);
    const now = $(".now");
    if (now) {
      now.innerHTML = `${ring(b.busyness_score, cls, 64)}
        <div><div class="big ${cls}">${levelText(b)}</div>
        <div class="sub">${escapeHtml(describeSource(b))}</div></div>`;
    }
    renderResults();
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

/* ---------- map ----------
   Leaflet + OpenStreetMap tiles: free, no API key, no billing account.
   BestTime supplies each venue's coordinates; this only draws them. */

let map = null;
let markerLayer = null;

function mapAvailable() {
  return typeof window.L !== "undefined";
}

function initMap() {
  if (map || !mapAvailable()) return;
  map = L.map("map", { scrollWheelZoom: false }).setView([51.5074, -0.1278], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);
}

// Colour each pin by how busy the venue is, so the map reads at a glance.
function pinIcon(cls) {
  return L.divIcon({
    className: "pin-wrap",
    html: `<span class="pin pin-${cls}"></span>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function renderMap() {
  const holder = $("#mapview");
  if (!mapAvailable()) {
    holder.innerHTML =
      `<p class="empty">The map library could not load, so the map is unavailable.
        The list view has the same venues.</p>`;
    return;
  }

  initMap();
  markerLayer.clearLayers();

  const located = visibleVenues().filter(
    (v) => typeof v.lat === "number" && typeof v.lng === "number");

  if (!located.length) {
    setStatus("These results have no coordinates, so nothing can be mapped.");
    return;
  }

  located.forEach((v) => {
    const b = v.busyness || {};
    const marker = L.marker([v.lat, v.lng], { icon: pinIcon(levelClass(b)) })
      .addTo(markerLayer)
      .bindPopup(`
        <strong>${escapeHtml(v.name || "Venue")}</strong><br>
        <span class="pop-level ${levelClass(b)}">${levelText(b)}${
          b.busyness_score != null ? ` · ${b.busyness_score}/100` : ""
        }</span><br>
        <button class="pop-btn" data-venue="${escapeHtml(v.venue_id || "")}">Details</button>
      `);
    marker.on("popupopen", (e) => {
      const btn = e.popup.getElement().querySelector(".pop-btn");
      if (btn) btn.addEventListener("click", () => openDrawer(v));
    });
  });

  map.fitBounds(L.latLngBounds(located.map((v) => [v.lat, v.lng])), {
    padding: [40, 40], maxZoom: 15,
  });
  // The container was hidden while sizing, so Leaflet needs a nudge.
  setTimeout(() => map.invalidateSize(), 60);
}

function setView(view) {
  state.view = view;
  $("#results").hidden = view !== "list";
  $("#mapview").hidden = view !== "map";
  document.querySelectorAll("#viewtoggle button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  if (view === "map") renderMap();
}

function closeDrawer() {
  $("#drawer").hidden = true;
  $("#drawer-backdrop").hidden = true;
  document.body.style.overflow = "";
  state.drawerVenue = null;
}

/* ---------- wiring ---------- */

$("#search-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
$("#refresh-btn").addEventListener("click", refreshBusyness);
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

$("#examples").addEventListener("click", (e) => {
  const btn = e.target.closest(".example");
  if (btn) runSearch(btn.dataset.q);
});

$("#filters").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.filter = btn.dataset.filter;
  $("#filters").querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c === btn));
  renderResults();
});

$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; renderResults(); });

$("#viewtoggle").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (btn) setView(btn.dataset.view);
});

$("#geo-btn").addEventListener("click", () => {
  if (!navigator.geolocation) { setStatus("Geolocation is not supported here.", true); return; }
  setStatus("Getting your location…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const coords = `${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;
      const term = $("#q").value.trim();
      // Keep what they typed and search it around here.
      runSearch(term && !term.includes(",") ? term : "restaurant", { near: coords });
    },
    (err) => setStatus(`Could not get location: ${err.message}`, true),
    { timeout: 10000 }
  );
});

/* Show which data source is live. */
(async function init() {
  try {
    const health = await api("/health");
    const badge = $("#source-badge");
    badge.textContent = health.data_source === "besttime"
      ? "live data · BestTime" : "demo data · simulated";
    if (health.besttime && health.besttime.reachable === false) {
      badge.textContent = "BestTime unreachable · demo data";
    }
  } catch { $("#source-badge").textContent = ""; }
})();

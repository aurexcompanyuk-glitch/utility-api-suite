/* Busy or Not — frontend for the Restaurant & Cafe Busyness API.
   No build step, no dependencies. Talks to the same origin. */

const $ = (sel) => document.querySelector(sel);

const state = {
  venues: [],
  filter: "all",
  sort: "busyness",
  radius: 5000,      // metres
  origin: null,      // {lat, lng} used for the last search
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

function levelClass(b) {
  return b && b.level ? LEVEL_CLASS[b.level] || "none" : "none";
}

function levelText(b) {
  if (!b || b.busyness_score === null || b.busyness_score === undefined) return "No data";
  return LEVEL_TEXT[b.level] || "Unknown";
}

function parseLatLng(text) {
  const m = String(text).split(",").map((p) => parseFloat(p.trim()));
  if (m.length !== 2 || m.some(Number.isNaN)) return null;
  if (m[0] < -90 || m[0] > 90 || m[1] < -180 || m[1] > 180) return null;
  return { lat: m[0], lng: m[1] };
}

/* Circular busyness gauge. */
function ring(score, cls) {
  const r = 22, circ = 2 * Math.PI * r;
  const pct = score === null || score === undefined ? 0 : score / 100;
  const label = score === null || score === undefined ? "–" : score;
  return `
    <div class="ring">
      <svg width="54" height="54" viewBox="0 0 54 54" aria-hidden="true">
        <circle class="track" cx="27" cy="27" r="${r}" fill="none" stroke-width="5"/>
        <circle class="value stroke-${cls}" cx="27" cy="27" r="${r}" fill="none" stroke-width="5"
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
  return list.sort(sorters[state.sort] || sorters.busyness);
}

function renderResults() {
  const list = visibleVenues();
  const grid = $("#results");

  if (!list.length) {
    grid.innerHTML = `<p class="empty">No venues match. Try a different search or filter.</p>`;
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
            <p class="addr">${escapeHtml(v.address || "")}</p>
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

  // Index into the same sorted list the markup was built from.
  grid.querySelectorAll(".card").forEach((card) => {
    const open = () => openDrawer(list[Number(card.dataset.index)]);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function showSkeletons(n = 6) {
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

async function runSearch() {
  const q = $("#q").value.trim() || "restaurant";
  const coords = parseLatLng($("#loc").value);
  if (!coords) {
    setStatus("Enter a location as 'latitude, longitude', e.g. 51.5074, -0.1278", true);
    return;
  }

  state.origin = coords;
  $("#search-btn").disabled = true;
  setStatus("Searching…");
  showSkeletons();

  const params = new URLSearchParams({
    q, lat: coords.lat, lng: coords.lng,
    radius: String(state.radius), limit: "24",
  });

  try {
    const data = await api(`/v1/venues/search?${params}`);
    state.venues = data.results || [];
    renderResults();

    const bits = [`${state.venues.length} venue${state.venues.length === 1 ? "" : "s"}`];
    if (data.source) bits.push(`source: ${data.source}`);
    if (data.cached) bits.push("cached");
    setStatus(bits.join(" · "));

    if (data.source === "simulated_fallback") {
      setStatus(`${bits.join(" · ")} — BestTime unavailable, showing simulated data`, true);
    }
    // A radar search can still be running when it returns nothing yet.
    if (!state.venues.length && data.job_id) {
      setStatus("BestTime is still collecting venues for this area — try again shortly.");
    }
  } catch (err) {
    setStatus(err.message, true);
    $("#results").innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
  } finally {
    $("#search-btn").disabled = false;
  }
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
  state.forecastDay = new Date().getDay() === 0 ? 6 : new Date().getDay() - 1;

  $("#drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;
  document.body.style.overflow = "hidden";

  const b = venue.busyness || {};
  const cls = levelClass(b);
  $("#drawer-body").innerHTML = `
    <h2>${escapeHtml(venue.name || "Venue")}</h2>
    <p class="addr">${escapeHtml(venue.address || "")}</p>
    <div class="now">
      ${ring(b.busyness_score, cls)}
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

    const isToday = state.forecastDay === (new Date().getDay() === 0 ? 6 : new Date().getDay() - 1);
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
      now.innerHTML = `${ring(b.busyness_score, cls)}
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

$("#filters").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.filter = btn.dataset.filter;
  $("#filters").querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c === btn));
  renderResults();
});

$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; renderResults(); });

$("#radius").addEventListener("change", (e) => {
  state.radius = Number(e.target.value);
  runSearch();
});

$("#geo-btn").addEventListener("click", () => {
  if (!navigator.geolocation) { setStatus("Geolocation is not supported here.", true); return; }
  setStatus("Getting your location…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      $("#loc").value = `${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;
      setStatus("Location set.");
      runSearch();
    },
    (err) => setStatus(`Could not get location: ${err.message}`, true),
    { timeout: 10000 }
  );
});

/* Show which data source is live, then run an initial search. */
(async function init() {
  try {
    const health = await api("/health");
    const badge = $("#source-badge");
    badge.textContent = health.data_source === "besttime"
      ? "live data · BestTime" : "demo data · simulated";
    if (health.besttime && health.besttime.reachable === false) {
      badge.textContent = "BestTime unreachable · simulated";
    }
  } catch { $("#source-badge").textContent = ""; }
  runSearch();
})();

/**
 * Shared helpers for the ICTD course static site.
 */

const DATA_PREFIX = "data/";
const SITE_ASSET_VERSION = window.SITE_ASSET_VERSION || "dev";

function versionedDataUrl(url) {
  const join = url.includes("?") ? "&" : "?";
  return `${url}${join}v=${SITE_ASSET_VERSION}`;
}

function showLoadError(message) {
  const banner = document.getElementById("load-error");
  if (banner) {
    banner.hidden = false;
    banner.textContent = message;
  } else {
    console.error(message);
  }
}

async function fetchText(url) {
  const response = await fetch(versionedDataUrl(url), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${url} (${response.status})`);
  }
  return response.text();
}

async function fetchJson(url) {
  const response = await fetch(versionedDataUrl(url), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${url} (${response.status})`);
  }
  return response.json();
}

function isFileProtocol() {
  return window.location.protocol === "file:";
}

function guardFileProtocol() {
  if (isFileProtocol()) {
    showLoadError(
      "This site loads content via fetch(), which browsers block on file:// URLs. " +
      "Run a local server from the site/ directory, e.g. python -m http.server 8000, " +
      "then open http://localhost:8000/index.html"
    );
    return true;
  }
  return false;
}

function getReadingUrl(reading) {
  const doi = reading.doi;
  if (doi) {
    if (/^https?:\/\//i.test(doi)) {
      return doi;
    }
    return `https://doi.org/${doi.replace(/^doi:/i, "").trim()}`;
  }
  const link = reading.link;
  if (link && link !== "null" && link !== "undefined") {
    return link;
  }
  return null;
}

function formatAuthors(authors) {
  if (!authors || typeof authors !== "string") {
    return null;
  }
  const trimmed = authors.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.length <= 60) {
    return trimmed;
  }
  const firstSegment = trimmed.split(/[;,]/)[0].trim();
  if (!firstSegment) {
    return trimmed.slice(0, 57) + "...";
  }
  return `${firstSegment} et al.`;
}

function isBookReading(reading) {
  return reading.notes && reading.notes.toLowerCase().includes("this is a book");
}

function isSensitiveReading(reading) {
  return reading.notes && reading.notes.toUpperCase().includes("SENSITIVE");
}

function buildMetaLine(reading) {
  const parts = [];
  const authors = formatAuthors(reading.authors);
  if (authors) {
    parts.push(authors);
  }
  if (reading.year) {
    parts.push(String(reading.year));
  }
  if (reading.venue) {
    parts.push(reading.venue);
  }
  return parts.join(" — ");
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function sortTopicsByFramework(topicIds, framework) {
  const order = new Map(
    framework.topics.map((topic) => [topic.id, topic.sequence])
  );
  return [...new Set(topicIds)].sort(
    (a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99)
  );
}

/** When a reading spans multiple topics, show it in one column only (highest precedence wins). */
const TOPIC_COLUMN_PRECEDENCE = [
  "problem_discovery",
  "impact_evaluation",
  "operations_scale",
  "sociotechnical_dynamics",
  "ethnographic_design",
  "cs_fundamentals",
];

/** Pseudo-column for area-agnostic / primer material on the examples page. */
const BACKGROUND_COLUMN_ID = "background_readings";

function isBackgroundDomainReading(reading) {
  return Boolean(reading && reading.area_agnostic);
}

function assignReadingToTopicColumn(readingTopics, topicsCovered) {
  const covered = new Set(topicsCovered || []);
  const eligible = (readingTopics || []).filter((topicId) => covered.has(topicId));
  if (!eligible.length) {
    return null;
  }
  for (const topicId of TOPIC_COLUMN_PRECEDENCE) {
    if (eligible.includes(topicId)) {
      return topicId;
    }
  }
  return eligible[0];
}

function createReadingCard(reading, axisIdsForCaseStudy, axisNameById) {
  const card = document.createElement("article");
  card.className = "reading-card";
  card.id = reading.id;
  card.tabIndex = 0;

  const url = getReadingUrl(reading);
  const titleHtml = url
    ? `<a class="reading-card__title" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(reading.title)}</a>`
    : `<span class="reading-card__title">${escapeHtml(reading.title)}</span>`;

  let badges = "";
  if (isBookReading(reading)) {
    badges += '<span class="badge badge--book">book</span>';
  }
  if (isSensitiveReading(reading)) {
    badges += '<span class="badge badge--sensitive">sensitive</span>';
  }

  const meta = buildMetaLine(reading);
  const metaHtml = meta
    ? `<div class="reading-card__meta">${escapeHtml(meta)}</div>`
    : "";

  const readingAxes = new Set(reading.cross_cutting_axes || []);
  const relevantAxes = (axisIdsForCaseStudy || []).filter((axisId) =>
    readingAxes.has(axisId)
  );
  let axisHtml = "";
  if (relevantAxes.length) {
    axisHtml =
      '<div class="axis-tags">' +
      relevantAxes
        .map((axisId) => {
          const label = axisNameById[axisId] || axisId;
          return `<span class="axis-tag axis-tag--${escapeHtml(axisId)}">${escapeHtml(label)}</span>`;
        })
        .join("") +
      "</div>";
  }

  let tooltipHtml = "";
  if (reading.abstract && reading.abstract.trim()) {
    card.classList.add("has-tooltip");
    tooltipHtml = `<div class="tooltip" role="tooltip">${escapeHtml(reading.abstract)}</div>`;
  }

  card.innerHTML = titleHtml + badges + metaHtml + axisHtml + tooltipHtml;
  return card;
}

function setActiveNav(page) {
  document.querySelectorAll(".site-nav a").forEach((link) => {
    if (link.dataset.page === page) {
      link.setAttribute("aria-current", "page");
    }
  });
}

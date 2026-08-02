/**
 * Renders schedule.html from schedule.json + readings.json.
 */

function buildLinkMetaLine(link) {
  const parts = [];
  if (link.authors) {
    parts.push(link.authors);
  } else if (link.author) {
    parts.push(link.author);
  }
  if (link.date) {
    parts.push(link.date);
  }
  if (link.venue) {
    parts.push(link.venue);
  }
  return parts.length ? parts.join(" — ") : null;
}

function resolveLinkMeta(link, readingsById) {
  if (link.type === "reading") {
    const reading = readingsById[link.reading_id];
    if (!reading) {
      return {
        title: link.reading_id,
        url: null,
        meta: null,
        missing: true,
      };
    }
    return {
      title: reading.title,
      url: getReadingUrl(reading),
      meta: buildMetaLine(reading),
      missing: false,
    };
  }

  if (link.type === "external") {
    return {
      title: link.title || link.url,
      url: link.url,
      meta: buildLinkMetaLine(link),
      missing: false,
    };
  }

  if (link.type === "content") {
    const path = (link.path || "").replace(/^\//, "");
    return {
      title: link.title || path.split("/").pop(),
      url: path,
      meta: buildLinkMetaLine(link),
      missing: false,
    };
  }

  return {
    title: link.title || "Link",
    url: link.url || null,
    meta: link.date || null,
    missing: false,
  };
}

function renderSessionLinks(links, readingsById) {
  const list = document.createElement("ul");
  list.className = "schedule-session__links";

  for (const link of links) {
    const resolved = resolveLinkMeta(link, readingsById);
    const item = document.createElement("li");
    item.className = "schedule-link";

    let titleHtml;
    if (resolved.url) {
      const external = link.type === "external";
      titleHtml = `<a href="${escapeHtml(resolved.url)}"${
        external ? ' target="_blank" rel="noopener noreferrer"' : ""
      }>${escapeHtml(resolved.title)}</a>`;
    } else {
      titleHtml = `<span>${escapeHtml(resolved.title)}</span>`;
    }

    const typeLabel =
      link.type === "reading" ? "Paper" : link.type === "content" ? "File" : "Link";
    let html =
      `<span class="schedule-link__type">${escapeHtml(typeLabel)}</span> ` + titleHtml;

    if (resolved.meta) {
      html += `<span class="schedule-link__meta">${escapeHtml(resolved.meta)}</span>`;
    }
    if (resolved.missing) {
      html += `<span class="schedule-link__missing">reading not found</span>`;
    }

    item.innerHTML = html;
    list.appendChild(item);
  }

  return list;
}

function renderSessions(schedule, readingsById, container) {
  container.innerHTML = "";
  const sessions = schedule.sessions || [];

  if (!sessions.length) {
    container.innerHTML = "<p>No sessions scheduled yet.</p>";
    return;
  }

  for (const [index, session] of sessions.entries()) {
    const article = document.createElement("article");
    article.className = "schedule-session";
    article.id = `session-${index + 1}`;

    const header = document.createElement("header");
    header.className = "schedule-session__header";

    const date = document.createElement("p");
    date.className = "schedule-session__date";
    date.textContent = session.date;
    header.appendChild(date);

    const title = document.createElement("h2");
    title.className = "schedule-session__title";
    title.textContent = session.title;
    header.appendChild(title);

    article.appendChild(header);

    if (session.description) {
      const description = document.createElement("p");
      description.className = "schedule-session__description";
      description.textContent = session.description;
      article.appendChild(description);
    }

    if (session.links && session.links.length) {
      const linksHeading = document.createElement("h3");
      linksHeading.className = "schedule-session__links-heading";
      linksHeading.textContent = "Reference material";
      article.appendChild(linksHeading);
      article.appendChild(renderSessionLinks(session.links, readingsById));
    }

    container.appendChild(article);
  }
}

async function initSchedulePage() {
  setActiveNav("schedule");
  if (guardFileProtocol()) {
    return;
  }

  try {
    const [schedule, readingsData] = await Promise.all([
      fetchJson(`${DATA_PREFIX}schedule.json`),
      fetchJson(`${DATA_PREFIX}readings.json`),
    ]);

    const readingsById = Object.fromEntries(
      readingsData.readings.map((reading) => [reading.id, reading])
    );

    renderSessions(schedule, readingsById, document.getElementById("schedule-content"));
  } catch (error) {
    console.error(error);
    showLoadError(
      `Could not load schedule data: ${error.message}. ` +
      "Serve the site over HTTP (see site/README.md)."
    );
  }
}

document.addEventListener("DOMContentLoaded", initSchedulePage);

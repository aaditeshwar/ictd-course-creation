/**
 * Renders key-readings.html from framework.json topic vector + readings.json.
 */

function renderTopicVector(framework, readingsById, container) {
  container.innerHTML = "";
  const vector = framework.area_agnostic_topic_vector || [];
  if (!vector.length) {
    container.innerHTML = "<p>No topic vector entries found.</p>";
    return;
  }

  for (const entry of vector) {
    const section = document.createElement("article");
    section.className = "topic-vector-block";
    section.id = `topic-${entry.id}`;

    const heading = document.createElement("h2");
    heading.textContent = entry.name;
    section.appendChild(heading);

    if (entry.methodology_description) {
      const desc = document.createElement("p");
      desc.className = "topic-vector-block__description";
      desc.textContent = entry.methodology_description;
      section.appendChild(desc);
    }

    const list = document.createElement("ul");
    list.className = "topic-vector-block__readings";

    const ids = entry.example_readings || [];
    for (const readingId of ids) {
      const reading = readingsById[readingId];
      const item = document.createElement("li");
      if (!reading) {
        item.innerHTML = `<span class="reading-missing">${escapeHtml(readingId)}</span>`;
        list.appendChild(item);
        continue;
      }

      const url = getReadingUrl(reading);
      const titleHtml = url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(reading.title)}</a>`
        : escapeHtml(reading.title);
      item.innerHTML =
        `${titleHtml} <span class="reading-id">${escapeHtml(reading.id)}</span>`;
      list.appendChild(item);
    }

    section.appendChild(list);
    container.appendChild(section);
  }
}

async function initKeyReadingsPage() {
  setActiveNav("key-readings");
  if (guardFileProtocol()) {
    return;
  }

  try {
    const [framework, readingsData] = await Promise.all([
      fetchJson(`${DATA_PREFIX}framework.json`),
      fetchJson(`${DATA_PREFIX}readings.json`),
    ]);

    const readingsById = Object.fromEntries(
      readingsData.readings.map((reading) => [reading.id, reading])
    );

    renderTopicVector(
      framework,
      readingsById,
      document.getElementById("topic-vector-content")
    );
  } catch (error) {
    console.error(error);
    showLoadError(
      `Could not load key readings data: ${error.message}. ` +
      "Serve the site over HTTP (see site/README.md)."
    );
  }
}

document.addEventListener("DOMContentLoaded", initKeyReadingsPage);

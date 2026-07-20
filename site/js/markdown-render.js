/**
 * Renders main_page_content.md and inserts the live framework summary.
 */

const DUPLICATE_SECTION_PATTERN =
  /### The topics:[\s\S]*?### The cross-cutting axes:[\s\S]*?(?=\nBrowse the|\n## |$)/;

function stripDuplicateFrameworkSections(markdown) {
  return markdown.replace(DUPLICATE_SECTION_PATTERN, "").trim();
}

function renderFrameworkSummary(framework, container) {
  const topics = [...framework.topics].sort((a, b) => a.sequence - b.sequence);
  const areas = framework.areas;
  const axes = framework.cross_cutting_axes;

  const topicItems = topics
    .map(
      (topic) =>
        `<li><span class="topic-name">${escapeHtml(topic.name)}</span> — ${escapeHtml(topic.description)}</li>`
    )
    .join("");

  const areaItems = areas
    .map(
      (area) =>
        `<li><a href="examples.html#area-${escapeHtml(area.id)}">${escapeHtml(area.name)}</a></li>`
    )
    .join("");

  const axisItems = axes
    .map((axis) => `<li>${escapeHtml(axis.name)}</li>`)
    .join("");

  container.innerHTML = `
    <section class="framework-summary" id="framework-summary" aria-label="Course framework summary">
      <h3>Topics (pedagogical sequence)</h3>
      <ol>${topicItems}</ol>
      <h3>Areas</h3>
      <ul class="areas-grid">${areaItems}</ul>
      <h3>Cross-cutting axes</h3>
      <ul>${axisItems}</ul>
    </section>
  `;
}

function insertSummaryAfterHeading(mainContent, summaryContainer) {
  const headings = mainContent.querySelectorAll("h2");
  for (const heading of headings) {
    if (heading.textContent.toLowerCase().includes("areas and topics")) {
      heading.insertAdjacentElement("afterend", summaryContainer);
      return;
    }
  }
  mainContent.appendChild(summaryContainer);
}

async function initMainPage() {
  setActiveNav("home");
  if (guardFileProtocol()) {
    return;
  }

  const mainContent = document.getElementById("main-content");
  const summaryHost = document.createElement("div");

  try {
    const [markdown, framework] = await Promise.all([
      fetchText("content/main_page_content.md"),
      fetchJson(`${DATA_PREFIX}framework.json`),
    ]);

    const cleaned = stripDuplicateFrameworkSections(markdown);
    mainContent.innerHTML = marked.parse(cleaned);
    mainContent.classList.add("prose");

    renderFrameworkSummary(framework, summaryHost);
    insertSummaryAfterHeading(mainContent, summaryHost.firstElementChild || summaryHost);
  } catch (error) {
    console.error(error);
    showLoadError(
      `Could not load page content: ${error.message}. ` +
      "Serve the site over HTTP (see site/README.md)."
    );
  }
}

document.addEventListener("DOMContentLoaded", initMainPage);

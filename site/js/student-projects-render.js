/**
 * Renders student-projects.html from data/student-projects.csv.
 */

const STUDENT_PROJECTS_CSV = `${DATA_PREFIX}student-projects.csv`;

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (inQuotes) {
      if (char === '"') {
        if (next === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\r") {
      // skip
    } else if (char === "\n") {
      row.push(field);
      field = "";
      if (row.length > 1 || row[0] !== "") {
        rows.push(row);
      }
      row = [];
    } else {
      field += char;
    }
  }

  if (field.length || row.length) {
    row.push(field);
    rows.push(row);
  }

  return rows;
}

function isMissingStudentName(name) {
  const normalized = String(name || "").trim().toUpperCase();
  return !normalized || normalized === "NA" || normalized === "N/A";
}

function formatStudentNames(name1, name2) {
  const students = [name1, name2]
    .map((name) => String(name || "").trim())
    .filter((name) => !isMissingStudentName(name));
  return students.join(", ");
}

function normalizeAttachmentUrl(url) {
  const trimmed = String(url || "").trim();
  if (!trimmed || /^na$/i.test(trimmed)) {
    return null;
  }
  return trimmed;
}

function csvRowsToProjects(rows) {
  if (!rows.length) {
    return [];
  }

  const header = rows[0];
  const dataRows = rows.slice(1);

  return dataRows
    .map((cells, index) => ({
      timestamp: cells[0] || "",
      name1: cells[1] || "",
      email1: cells[2] || "",
      name2: cells[3] || "",
      email2: cells[4] || "",
      caseStudyId: cells[5] || "",
      title: cells[6] || "",
      description: cells[7] || "",
      attachmentUrl: normalizeAttachmentUrl(cells[8]),
      rowNumber: index + 2,
    }))
    .filter((project) => project.title.trim() && project.attachmentUrl);
}

function renderProject(project, index) {
  const article = document.createElement("article");
  article.className = "student-project";
  article.id = `project-${index + 1}`;

  const title = document.createElement("h2");
  title.className = "student-project__title";
  title.textContent = project.title;
  article.appendChild(title);

  const students = document.createElement("p");
  students.className = "student-project__students";
  const studentNames = formatStudentNames(project.name1, project.name2);
  students.textContent = studentNames || "Students not listed";
  article.appendChild(students);

  if (project.caseStudyId.trim()) {
    const caseStudy = document.createElement("p");
    caseStudy.className = "student-project__case-study";
    caseStudy.innerHTML =
      `<span class="student-project__label">Case study</span> ` +
      `<code>${escapeHtml(project.caseStudyId.trim())}</code>`;
    article.appendChild(caseStudy);
  }

  if (project.description.trim()) {
    const description = document.createElement("div");
    description.className = "student-project__description";
    description.textContent = project.description.trim();
    article.appendChild(description);
  }

  const attachmentHeading = document.createElement("h3");
  attachmentHeading.className = "student-project__attachment-heading";
  attachmentHeading.textContent = "Position paper";
  article.appendChild(attachmentHeading);

  const link = document.createElement("a");
  link.className = "student-project__attachment";
  link.href = project.attachmentUrl;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "Open Google Drive attachment";
  article.appendChild(link);

  return article;
}

function renderProjects(projects, container) {
  container.innerHTML = "";

  if (!projects.length) {
    container.innerHTML = "<p>No student projects listed yet.</p>";
    return;
  }

  for (const [index, project] of projects.entries()) {
    container.appendChild(renderProject(project, index));
  }
}

async function initStudentProjectsPage() {
  setActiveNav("student-projects");
  if (guardFileProtocol()) {
    return;
  }

  try {
    const csvText = await fetchText(STUDENT_PROJECTS_CSV);
    const rows = parseCsv(csvText);
    const projects = csvRowsToProjects(rows);
    renderProjects(projects, document.getElementById("student-projects-content"));
  } catch (error) {
    console.error(error);
    showLoadError(
      `Could not load student projects: ${error.message}. ` +
      "Serve the site over HTTP (see site/README.md)."
    );
  }
}

document.addEventListener("DOMContentLoaded", initStudentProjectsPage);

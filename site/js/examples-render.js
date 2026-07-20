/**

 * Renders examples.html from examples.json + readings.json + framework.json.

 */



/** Display order for area sections on examples.html (not framework.json list order). */

const AREA_DISPLAY_ORDER = [

  "water_security",

  "forests_restoration",

  "wildlife_conservation",

  "agriculture",

  "governance",

  "media_information",

  "labour",

  "livelihood",

  "health",

  "education",

  "infrastructure",

];



const MIN_TOPICS_DEFAULT_FILTER = 3;



/** Examples page column headers (override framework.json names where needed). */

const TOPIC_COLUMN_LABELS = {

  cs_fundamentals: "Computing elements",

};



function getOrderedAreas(framework) {

  const byId = Object.fromEntries(framework.areas.map((area) => [area.id, area]));

  const ordered = AREA_DISPLAY_ORDER.filter((id) => byId[id]).map((id) => byId[id]);

  for (const area of framework.areas) {

    if (!AREA_DISPLAY_ORDER.includes(area.id)) {

      ordered.push(area);

    }

  }

  return ordered;

}



function countBackgroundConceptResources(backgroundConcepts) {

  let count = 0;

  for (const concept of backgroundConcepts || []) {

    count += (concept.suggested_resources || []).length;

  }

  return count;

}



function hasBackgroundColumn(study, backgroundReadings) {

  return (

    backgroundReadings.length > 0 ||

    countBackgroundConceptResources(study.background_concepts) > 0

  );

}



function buildCaseStudyColumns(study, readingsById) {

  const topicColumns = new Map();

  const backgroundReadings = [];



  for (const readingId of study.readings) {

    const reading = readingsById[readingId];

    if (!reading) {

      continue;

    }

    if (isBackgroundDomainReading(reading)) {

      backgroundReadings.push(reading);

      continue;

    }

    const columnTopic = assignReadingToTopicColumn(

      reading.topics,

      study.topics_covered

    );

    if (!columnTopic) {

      continue;

    }

    if (!topicColumns.has(columnTopic)) {

      topicColumns.set(columnTopic, []);

    }

    topicColumns.get(columnTopic).push(reading);

  }



  return {

    topicColumns,

    backgroundReadings,

    backgroundConcepts: study.background_concepts || [],

  };

}



function countTopicColumns(study, readingsById) {
  const layout = buildCaseStudyColumns(study, readingsById);
  return [...layout.topicColumns.values()].filter((readings) => readings.length).length;
}

function countDisplayedColumns(study, readingsById) {
  const layout = buildCaseStudyColumns(study, readingsById);
  let count = countTopicColumns(study, readingsById);
  if (hasBackgroundColumn(study, layout.backgroundReadings)) {
    count += 1;
  }
  return count;
}

function matchesDefaultFilter(study, readingsById) {
  const layout = buildCaseStudyColumns(study, readingsById);
  return (
    countTopicColumns(study, readingsById) >= MIN_TOPICS_DEFAULT_FILTER &&
    hasBackgroundColumn(study, layout.backgroundReadings)
  );
}

function filterCaseStudies(studies, filterMode, readingsById) {
  if (filterMode === "all") {
    return studies;
  }
  return studies.filter((study) => matchesDefaultFilter(study, readingsById));
}



function buildAreaSections(framework, examples, readingsById, filterMode = "multi-topic") {

  const axisNameById = Object.fromEntries(

    framework.cross_cutting_axes.map((axis) => [axis.id, axis.name])

  );

  const areaNameById = Object.fromEntries(

    framework.areas.map((area) => [area.id, area.name])

  );



  const studiesByPrimaryArea = new Map();

  for (const area of framework.areas) {

    studiesByPrimaryArea.set(area.id, []);

  }

  const toc = document.getElementById("examples-toc-list");

  const content = document.getElementById("examples-content");

  toc.innerHTML = "";

  content.innerHTML = "";



  const filteredExamples = {

    ...examples,

    case_studies: filterCaseStudies(examples.case_studies, filterMode, readingsById),

  };



  for (const study of filteredExamples.case_studies) {

    const primary = study.areas[0];

    if (studiesByPrimaryArea.has(primary)) {

      studiesByPrimaryArea.get(primary).push(study);

    }

  }



  for (const area of getOrderedAreas(framework)) {

    const studies = studiesByPrimaryArea.get(area.id) || [];

    if (!studies.length) {

      continue;

    }



    const tocItem = document.createElement("li");

    tocItem.innerHTML = `<a href="#area-${escapeHtml(area.id)}">${escapeHtml(area.name)}</a>`;

    toc.appendChild(tocItem);



    const section = document.createElement("section");

    section.className = "area-section";

    section.id = `area-${area.id}`;



    const heading = document.createElement("h2");

    heading.textContent = area.name;

    section.appendChild(heading);



    for (const study of studies) {

      section.appendChild(renderCaseStudy(study, readingsById, framework, areaNameById, axisNameById));

    }



    content.appendChild(section);

  }



  if (!content.children.length) {

    const empty = document.createElement("p");

    empty.className = "examples-empty";

    empty.textContent =

      filterMode === "multi-topic"

        ? "No case studies span three or more topics and include background readings with the current filter."

        : "No case studies to display.";

    content.appendChild(empty);

  }

}



function getWideColumnId(layout, topicsInOrder, study) {

  const columns = [];



  for (const topicId of topicsInOrder) {

    const readings = layout.topicColumns.get(topicId);

    if (readings && readings.length) {

      columns.push({ id: topicId, count: readings.length });

    }

  }



  if (hasBackgroundColumn(study, layout.backgroundReadings)) {

    columns.push({

      id: BACKGROUND_COLUMN_ID,

      count:

        layout.backgroundReadings.length +

        countBackgroundConceptResources(layout.backgroundConcepts),

    });

  }



  if (columns.length >= 4) {

    return null;

  }



  let maxCount = 0;

  let wideColumnId = null;

  for (const column of columns) {

    if (column.count > maxCount) {

      maxCount = column.count;

      wideColumnId = column.id;

    }

  }

  return wideColumnId;

}



function createBackgroundResourceCard(resource) {

  const card = document.createElement("article");

  card.className = "reading-card reading-card--background";



  const url = resource.url;

  const titleHtml = url

    ? `<a class="reading-card__title" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(resource.title)}</a>`

    : `<span class="reading-card__title">${escapeHtml(resource.title)}</span>`;



  const typeLabel = resource.type ? `<span class="badge badge--primer">${escapeHtml(resource.type)}</span>` : "";

  card.innerHTML = titleHtml + typeLabel;

  return card;

}



function renderBackgroundColumn(study, layout, axisNameById, wideColumnId) {

  if (!hasBackgroundColumn(study, layout.backgroundReadings)) {

    return null;

  }



  const column = document.createElement("div");

  column.className = "topic-column topic-column--background";

  if (wideColumnId === BACKGROUND_COLUMN_ID) {

    column.classList.add("topic-column--wide");

  }



  const header = document.createElement("h4");

  header.className = "topic-column__header";

  header.textContent = "Background readings";

  column.appendChild(header);



  for (const reading of layout.backgroundReadings) {

    column.appendChild(

      createReadingCard(reading, study.cross_cutting_axes, axisNameById)

    );

  }



  for (const concept of layout.backgroundConcepts) {

    const resources = concept.suggested_resources || [];

    if (!resources.length) {

      continue;

    }



    const conceptBlock = document.createElement("div");

    conceptBlock.className = "background-concept";



    const conceptTitle = document.createElement("h5");

    conceptTitle.className = "background-concept__title";

    conceptTitle.textContent = concept.concept;

    conceptBlock.appendChild(conceptTitle);



    if (concept.why_needed) {

      const why = document.createElement("p");

      why.className = "background-concept__why";

      why.textContent = concept.why_needed;

      conceptBlock.appendChild(why);

    }



    for (const resource of resources) {

      conceptBlock.appendChild(createBackgroundResourceCard(resource));

    }



    column.appendChild(conceptBlock);

  }



  return column;

}



function renderCaseStudy(study, readingsById, framework, areaNameById, axisNameById) {

  const block = document.createElement("article");

  block.className = "case-study";



  const title = document.createElement("h3");

  title.className = "case-study__title";

  title.innerHTML =

    `${escapeHtml(study.name)} ` +

    `<span class="case-study__id">${escapeHtml(study.id)}</span>`;

  block.appendChild(title);



  const description = document.createElement("p");

  description.className = "case-study__description";

  description.textContent = study.description;

  block.appendChild(description);



  if (study.areas.length > 1) {

    const spans = document.createElement("p");

    spans.className = "case-study__spans";

    const otherNames = study.areas

      .slice(1)

      .map((areaId) => areaNameById[areaId] || areaId)

      .join(", ");

    spans.textContent = `Also spans: ${otherNames}`;

    block.appendChild(spans);

  }



  const layout = buildCaseStudyColumns(study, readingsById);

  const topicsInOrder = sortTopicsByFramework(study.topics_covered, framework);

  const wideColumnId = getWideColumnId(layout, topicsInOrder, study);



  const columns = document.createElement("div");

  columns.className = "topic-columns";



  for (const topicId of topicsInOrder) {

    const readingsInColumn = layout.topicColumns.get(topicId);

    if (!readingsInColumn || !readingsInColumn.length) {

      continue;

    }



    const topic = framework.topics.find((item) => item.id === topicId);

    if (!topic) {

      continue;

    }



    const column = document.createElement("div");

    column.className = "topic-column";

    if (topicId === wideColumnId) {

      column.classList.add("topic-column--wide");

    }



    const header = document.createElement("h4");

    header.className = "topic-column__header";

    header.textContent = TOPIC_COLUMN_LABELS[topicId] || topic.name;

    column.appendChild(header);



    for (const reading of readingsInColumn) {

      column.appendChild(

        createReadingCard(reading, study.cross_cutting_axes, axisNameById)

      );

    }



    columns.appendChild(column);

  }



  const backgroundColumn = renderBackgroundColumn(

    study,

    layout,

    axisNameById,

    wideColumnId

  );

  if (backgroundColumn) {

    columns.appendChild(backgroundColumn);

  }



  block.appendChild(columns);

  return block;

}



async function initExamplesPage() {

  setActiveNav("examples");

  if (guardFileProtocol()) {

    return;

  }



  try {

    const [framework, examples, readingsData] = await Promise.all([

      fetchJson(`${DATA_PREFIX}framework.json`),

      fetchJson(`${DATA_PREFIX}examples.json`),

      fetchJson(`${DATA_PREFIX}readings.json`),

    ]);



    const readingsById = Object.fromEntries(

      readingsData.readings.map((reading) => [reading.id, reading])

    );



    const render = (filterMode) => {

      buildAreaSections(framework, examples, readingsById, filterMode);

    };



    render("multi-topic");



    document.querySelectorAll('input[name="examples-filter"]').forEach((input) => {

      input.addEventListener("change", () => {

        if (input.checked) {

          render(input.value);

        }

      });

    });

  } catch (error) {

    console.error(error);

    showLoadError(

      `Could not load examples data: ${error.message}. ` +

      "Serve the site over HTTP (see site/README.md)."

    );

  }

}



document.addEventListener("DOMContentLoaded", initExamplesPage);



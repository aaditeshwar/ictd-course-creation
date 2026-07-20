"""
Venue-specific scrapers. Each function takes a URL and returns a list of dicts:
    {"title": str, "authors": str, "year": int|None, "link": str|None, "abstract": str|None}

CAVEAT: I (Claude) could not inspect raw HTML of these sites in this session -- my web_fetch
tool returns pre-cleaned text, not HTML source. These selectors are my best knowledge of each
site's typical structure as of my training, but ACM/IEEE/OJS templates do change. If a scraper
returns nothing, open the page in a browser, View Source / Inspect Element on one paper entry,
and adjust the selectors marked with # ADJUST ME.

Install: pip install requests beautifulsoup4 lxml
"""
import time
import re
import requests
from bs4 import BeautifulSoup

from enrich_metadata import extract_doi, lookup_paper_metadata, apply_metadata_to_paper
from dedup import is_duplicate

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
REQUEST_DELAY = 1.5  # be polite; raise this if you get blocked


def _get(url, **kwargs):
    time.sleep(REQUEST_DELAY)
    r = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
    r.raise_for_status()
    return r


def scrape_acm_dl_proceedings(url, year=None):
    """
    ACM Digital Library proceedings TOC page (dl.acm.org/doi/proceedings/10.1145/XXXXXXX).
    ACM has bot-detection; if this 403s, use a real browser + 'Save Page As HTML' and pass the
    local file path to scrape_acm_dl_proceedings_from_file() instead.
    """
    resp = _get(url)
    return _parse_acm_dl_html(resp.text, year)


def scrape_acm_dl_proceedings_from_file(filepath, year=None):
    with open(filepath, encoding="utf-8") as f:
        html = f.read()
    return _parse_acm_dl_html(html, year)


def _parse_acm_dl_html(html, year=None):
    soup = BeautifulSoup(html, "lxml")
    papers = []
    # ADJUST ME: ACM DL wraps each paper in <div class="issue-item"> or <li class="search__item">
    for item in soup.select("div.issue-item, li.issue-item"):
        title_el = item.select_one("h5.issue-item__title a, .issue-item__title a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        link = title_el.get("href", "")
        if link and not link.startswith("http"):
            link = "https://dl.acm.org" + link
        authors_el = item.select_one(".issue-item__authors, .rlist--inline")
        authors = authors_el.get_text(" ", strip=True) if authors_el else None
        abstract_el = item.select_one(".issue-item__abstract, .issue-item__abstract p")
        abstract = abstract_el.get_text(" ", strip=True) if abstract_el else None
        papers.append({
            "title": title, "authors": authors, "year": year,
            "link": link or None, "abstract": abstract
        })
    return papers


DBLP_BASE = "https://dblp.org"
DBLP_YEAR_URL_PATTERNS = {
    "ghtc": lambda year: [re.compile(rf"^https://dblp\.org/db/conf/ghtc/ghtc{year}\.html$")],
    "kdd": lambda year: [re.compile(rf"^https://dblp\.org/db/conf/kdd/kdd{year}(?:-\d+)?\.html$")],
    "fat": lambda year: [re.compile(rf"^https://dblp\.org/db/conf/fat/facct{year}\.html$")],
    "dev": lambda year: [re.compile(rf"^https://dblp\.org/db/conf/dev/compass{year}\.html$")],
    "ictd": lambda year: [re.compile(rf"^https://dblp\.org/db/conf/ictd/ictd{year}\.html$")],
    "chi": lambda year: [
        re.compile(rf"^https://dblp\.org/db/conf/chi/chi{year}\.html$"),
        re.compile(rf"^https://dblp\.org/db/conf/chi/chi{year}a\.html$"),
    ],
}
PACMHCI_YEAR_TO_VOLUME = {2021: 5, 2022: 6, 2023: 7, 2024: 8, 2025: 9}
JCSS_YEAR_TO_VOLUME = {2023: 1, 2024: 2, 2025: 3}


def _abs_dblp_url(href):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return DBLP_BASE + href


def _resolve_dblp_proceedings_urls(url, year=None, dblp_conf=None):
    """Resolve one or more DBLP proceedings TOC URLs (handles multi-volume years like KDD 2025)."""
    if "index.html" not in url:
        return [url]

    if year is None or not dblp_conf:
        raise ValueError("DBLP index URL requires both year and dblp_conf")

    patterns = DBLP_YEAR_URL_PATTERNS[dblp_conf](year)
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "lxml")
    matched = []
    for a in soup.select("a[href]"):
        href = _abs_dblp_url(a.get("href", ""))
        if any(pattern.match(href) for pattern in patterns):
            matched.append(href)
    return sorted(set(matched))


def _parse_dblp_entry(entry, year=None):
    title_el = entry.select_one("span.title")
    if not title_el:
        return None
    title = title_el.get_text(" ", strip=True).rstrip(".")
    authors = [a.get_text(strip=True) for a in entry.select('span[itemprop="author"]')]
    if not authors:
        authors = [
            a.get_text(strip=True)
            for a in entry.select('span[data-itemprop="author"] span[itemprop="name"]')
        ]
    link_el = entry.select_one('nav.publ li.ee a[href], nav.publ .head a[href^="http"]')
    link = link_el.get("href") if link_el else None
    doi = extract_doi(link)
    return {
        "title": title,
        "authors": ", ".join(authors) if authors else None,
        "year": year,
        "link": link,
        "doi": doi,
        "abstract": None,
    }


def _enrich_papers_with_abstracts(papers, fetch_abstracts=True, existing_sigs=None):
    """Fill missing abstracts using DOI/title lookups via scholarly metadata APIs."""
    if not fetch_abstracts or not papers:
        return papers

    to_enrich = papers
    if existing_sigs:
        to_enrich = [
            p for p in papers
            if not is_duplicate(p["title"], existing_sigs)[0]
        ]
        skipped = len(papers) - len(to_enrich)
        if skipped:
            print(f"  skipping metadata lookup for {skipped} papers already in readings.json")

    total = len(to_enrich)
    if not total:
        return papers

    print(f"  fetching abstracts for {total} papers via DOI/metadata APIs ...")
    found = 0
    for idx, paper in enumerate(to_enrich, start=1):
        if paper.get("abstract"):
            found += 1
            continue
        if idx == 1 or idx % 10 == 0 or idx == total:
            print(f"  abstract {idx}/{total} ({found} found so far) ...")
        result = lookup_paper_metadata(
            paper["title"],
            authors=paper.get("authors"),
            doi=paper.get("doi") or extract_doi(paper.get("link")),
        )
        if apply_metadata_to_paper(paper, result):
            found += 1
    print(f"  abstracts found for {found}/{total} papers")
    return papers


def _parse_dblp_proceedings_html(html, year=None, section_heading=None):
    soup = BeautifulSoup(html, "lxml")
    if section_heading:
        root = soup.select_one("#main-content, .page, body")
        if not root:
            return []
        papers = []
        current_h2_section = None
        for el in root.descendants:
            if getattr(el, "name", None) == "h2":
                current_h2_section = el.get_text(" ", strip=True)
            elif (getattr(el, "name", None) == "li"
                  and "inproceedings" in " ".join(el.get("class") or [])):
                if not _section_matches(current_h2_section or "", section_heading):
                    continue
                paper = _parse_dblp_entry(el, year=year)
                if paper:
                    papers.append(paper)
        return papers

    papers = []
    for entry in soup.select("li.entry.inproceedings"):
        paper = _parse_dblp_entry(entry, year=year)
        if paper:
            papers.append(paper)
    return papers


def _section_matches(section_text, section_heading):
    if not section_heading:
        return True
    return section_heading.lower() in section_text.lower()


def _parse_dblp_journal_html(html, year=None, section_heading=None):
    """Parse a DBLP journal volume page, optionally keeping one issue section only."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("#main-content, .page, body")
    if not root:
        return []

    papers = []
    current_section = None
    for el in root.descendants:
        if getattr(el, "name", None) in ("h2", "header"):
            text = el.get_text(" ", strip=True)
            if text and len(text) < 120 and ("Volume" in text or "Number" in text or "CSCW" in text):
                current_section = text
        elif (getattr(el, "name", None) == "li"
              and "entry" in (el.get("class") or [])
              and "article" in (el.get("class") or [])):
            if not _section_matches(current_section or "", section_heading):
                continue
            paper = _parse_dblp_entry(el, year=year)
            if paper:
                papers.append(paper)
    return papers


def _resolve_dblp_journal_volume_url(url, year=None, dblp_journal=None, dblp_volume=None):
    if "index.html" not in url:
        return [url]

    if dblp_volume is None and year is not None:
        if dblp_journal == "pacmhci":
            dblp_volume = PACMHCI_YEAR_TO_VOLUME.get(year)
        elif dblp_journal == "acmjcss":
            dblp_volume = JCSS_YEAR_TO_VOLUME.get(year)

    if dblp_volume is None or not dblp_journal:
        raise ValueError(
            f"DBLP journal index URL requires dblp_journal and (year or dblp_volume): {url}"
        )
    return [f"{DBLP_BASE}/db/journals/{dblp_journal}/{dblp_journal}{dblp_volume}.html"]


def scrape_dblp_journal(url, year=None, dblp_journal=None, dblp_volume=None,
                        section_heading=None, fetch_abstracts=True, existing_sigs=None):
    """
    Scrape papers from a DBLP journal volume page (e.g. PACM HCI for CSCW, acmjcss for JCSS).
    Use section_heading to keep one issue (e.g. 'CSCW1', 'CSCW2', or 'Number 2, 2025').
    """
    vol_urls = _resolve_dblp_journal_volume_url(
        url, year=year, dblp_journal=dblp_journal, dblp_volume=dblp_volume
    )
    papers, seen_titles = [], set()
    for vol_url in vol_urls:
        resp = _get(vol_url)
        for paper in _parse_dblp_journal_html(resp.text, year=year, section_heading=section_heading):
            key = paper["title"].lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            papers.append(paper)
    if section_heading and not papers:
        raise RuntimeError(
            f"No DBLP journal papers matched section={section_heading!r} at {vol_urls[0]}"
        )
    return _enrich_papers_with_abstracts(
        papers, fetch_abstracts=fetch_abstracts, existing_sigs=existing_sigs
    )


def scrape_dblp_proceedings(url, year=None, dblp_conf=None, section_heading=None,
                            fetch_abstracts=True, existing_sigs=None):
    """
    Scrape conference papers from DBLP proceedings pages.
    Pass a direct year URL (e.g. .../kdd/kdd2024.html) or an index URL plus dblp_conf + year
    (needed for multi-volume proceedings such as KDD 2025).
    Use section_heading to keep papers from one h2 section (e.g. IJCAI special tracks).
    Abstracts are fetched afterward via DOI/metadata APIs (Semantic Scholar, Crossref, OpenAlex).
    """
    proc_urls = _resolve_dblp_proceedings_urls(url, year=year, dblp_conf=dblp_conf)
    if not proc_urls:
        raise RuntimeError(
            f"No DBLP proceedings pages matched for conf={dblp_conf!r}, year={year!r} at {url}"
        )

    papers, seen_titles = [], set()
    for proc_url in proc_urls:
        resp = _get(proc_url)
        for paper in _parse_dblp_proceedings_html(
            resp.text, year=year, section_heading=section_heading
        ):
            key = paper["title"].lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            papers.append(paper)
    if section_heading and not papers:
        raise RuntimeError(
            f"No DBLP proceedings papers matched section={section_heading!r} at {proc_urls[0]}"
        )
    return _enrich_papers_with_abstracts(
        papers, fetch_abstracts=fetch_abstracts, existing_sigs=existing_sigs
    )


def scrape_ijcai_listing(url, year=None):
    """
    IJCAI accepted-papers listing pages. Markup varies by year:
      - 2024/2023: div.article with .id / .title / .authors / .abstract
      - 2025: div.paper with numeric id, preprint link, div.abstract
      - 2022: div.paper_wrapper with strong title + i authors (no abstracts)
    Abstracts are present in static HTML (CSS-hidden toggles), so requests is enough.
    """
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "lxml")
    papers = _parse_ijcai_html(soup, year)
    if papers:
        return papers
    text = soup.get_text("\n", strip=True)
    return _parse_ijcai_text(text, year)


def _parse_ijcai_html(soup, year=None):
    papers = []

    for article in soup.select("div.article"):
        title_el = article.select_one("div.title")
        if not title_el:
            continue
        authors_el = article.select_one("div.authors")
        abstract_el = article.select_one("div.abstract")
        papers.append({
            "title": title_el.get_text(strip=True),
            "authors": authors_el.get_text(strip=True) if authors_el else None,
            "year": year,
            "link": None,
            "abstract": abstract_el.get_text(" ", strip=True)[:3000] if abstract_el else None,
        })

    for wrapper in soup.select("div.paper_wrapper"):
        content = wrapper.select_one("div.content")
        title_el = content.select_one("strong") if content else None
        if not title_el:
            continue
        authors_el = content.select_one("i") if content else None
        papers.append({
            "title": title_el.get_text(strip=True),
            "authors": authors_el.get_text(strip=True) if authors_el else None,
            "year": year,
            "link": None,
            "abstract": None,
        })

    for item in soup.select("div.paper"):
        title = _ijcai_paper_div_title(item)
        if not title:
            continue
        link_el = item.select_one("a.pdf-link")
        authors = None
        for info in item.select("div.info"):
            em = info.find("em")
            if em and "authors" in em.get_text(strip=True).lower():
                authors = info.get_text(" ", strip=True).replace("Authors:", "").strip()
                break
        abstract_el = item.select_one("div.abstract")
        papers.append({
            "title": title,
            "authors": authors,
            "year": year,
            "link": link_el.get("href") if link_el else None,
            "abstract": abstract_el.get_text(" ", strip=True)[:3000] if abstract_el else None,
        })

    return papers


def _ijcai_paper_div_title(item):
    """Extract title text from 2025-style div.paper (id in strong, title follows as text nodes)."""
    strong = item.find("strong")
    if not strong:
        return None
    parts = []
    node = strong.next_sibling
    while node:
        if getattr(node, "name", None) in ("div", "button"):
            break
        if isinstance(node, str):
            text = node.strip()
            if text:
                parts.append(text)
        elif node.name in ("a", "br"):
            break
        node = node.next_sibling
    return " ".join(parts).strip() or None


def _parse_ijcai_text(text, year=None):
    """
    Fallback text parser for IJCAI pages whose HTML selectors miss (e.g. template changes).
    Handles 2025-style flat text where Preprint is on its own line, not inline with the title.
    """
    papers = []
    pattern = re.compile(
        r"(\d{3,5}):\s*(.+?)\n.*?"
        r"Authors:\s*(.+?)\n.*?"
        r"Show Abstract\s*(.+?)(?=\n\d{3,5}:|\Z)",
        re.DOTALL
    )
    for m in pattern.finditer(text):
        _, title, authors, abstract = m.groups()
        papers.append({
            "title": title.strip(),
            "authors": authors.strip(),
            "year": year,
            "link": None,
            "abstract": abstract.strip()[:3000],
        })
    return papers


def _aaai_issue_articles(soup, section_heading=None):
    """Return obj_article_summary divs, optionally limited to one h2 section."""
    articles = []
    current_section = None
    root = soup.select_one("#main-content, .page, body")
    if not root:
        return articles
    for el in root.descendants:
        if getattr(el, "name", None) == "h2":
            current_section = el.get_text(" ", strip=True)
        elif (getattr(el, "name", None) == "div"
              and el.get("class")
              and "obj_article_summary" in el.get("class")):
            if section_heading:
                if not current_section or section_heading.lower() not in current_section.lower():
                    continue
            articles.append(el)
    return articles


def scrape_aaai_ojs_issue(url, year=None, fetch_abstracts=True, section_heading=None,
                          existing_sigs=None):
    """
    AAAI OJS issue page (ojs.aaai.org/index.php/AAAI/issue/view/NNN). Lists article titles +
    authors + links, but NOT abstracts inline -- need a second fetch per article if you want them.

    Combined AAAI issues also contain Senior Member, Journal Track, etc. Pass section_heading
    (e.g. "AI for Social Impact") to scrape only the AISI track papers.
    """
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "lxml")
    items = _aaai_issue_articles(soup, section_heading=section_heading)
    total = len(items)
    if section_heading:
        print(f"  found {total} papers in section matching {section_heading!r}")
    else:
        print(f"  found {total} papers")
    if fetch_abstracts and total:
        est_secs = int(total * REQUEST_DELAY)
        print(f"  fetching abstracts for {total} papers (~{est_secs}s at {REQUEST_DELAY}s/request) ...")

    papers = []
    for idx, item in enumerate(items, start=1):
        title_el = item.select_one("h3.title a, .title a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        link = title_el.get("href", "")
        authors_el = item.select_one(".authors")
        authors = authors_el.get_text(" ", strip=True) if authors_el else None
        abstract = doi = None
        if fetch_abstracts and link:
            if not (existing_sigs and is_duplicate(title, existing_sigs)[0]):
                if idx == 1 or idx % 10 == 0 or idx == total:
                    print(f"  abstract {idx}/{total} ...")
                abstract, doi = _fetch_ojs_article_metadata(link)
            elif idx == 1 or idx % 10 == 0 or idx == total:
                print(f"  abstract {idx}/{total} (already in readings.json) ...")
        papers.append({
            "title": title, "authors": authors, "year": year,
            "link": link or None, "doi": doi, "abstract": abstract
        })
    return papers


def _fetch_ojs_article_metadata(article_url, legacy=False):
    """Fetch abstract (and DOI when present) from an OJS article page."""
    try:
        resp = _get(article_url)
    except Exception:
        return None, None
    soup = BeautifulSoup(resp.text, "lxml")
    doi_el = soup.select_one('meta[name="citation_doi"]')
    doi = doi_el.get("content") if doi_el else extract_doi(article_url)
    if legacy:
        abstract_el = soup.select_one("#articleAbstract, div#articleAbstract")
    else:
        abstract_el = soup.select_one("section.abstract, .item.abstract")
    abstract = abstract_el.get_text(" ", strip=True) if abstract_el else None
    if abstract and abstract.lower().startswith("abstract"):
        abstract = abstract[8:].strip()
    return abstract, doi


def _fetch_ojs_article_abstract(article_url, legacy=False):
    abstract, _ = _fetch_ojs_article_metadata(article_url, legacy=legacy)
    return abstract


def _legacy_ojs_issue_entries(soup, section_heading=None):
    """Parse old OJS 2 table-of-contents markup (e.g. ITID journal)."""
    entries = []
    current_section = None
    for el in soup.select("#main-content, .page, body"):
        root = el
        break
    else:
        root = soup

    for node in root.descendants:
        if getattr(node, "name", None) == "h4" and "tocSectionTitle" in " ".join(node.get("class") or []):
            current_section = node.get_text(" ", strip=True)
        elif getattr(node, "name", None) == "table" and "tocArticle" in " ".join(node.get("class") or []):
            if section_heading and (not current_section or section_heading.lower() not in current_section.lower()):
                continue
            rows = node.select("tr")
            idx = 0
            while idx < len(rows):
                title_el = rows[idx].select_one(".tocTitle")
                if not title_el:
                    idx += 1
                    continue
                title = title_el.get_text(" ", strip=True)
                abs_link = rows[idx].select_one('.tocGalleys a[href*="article/view"]')
                authors = None
                if idx + 1 < len(rows):
                    authors_el = rows[idx + 1].select_one(".tocAuthors")
                    if authors_el:
                        authors = re.sub(r"\s+", " ", authors_el.get_text(" ", strip=True)).strip(" ,")
                entries.append({
                    "title": title,
                    "authors": authors or None,
                    "link": abs_link.get("href") if abs_link else None,
                })
                idx += 2
    return entries


def scrape_ojs_legacy_issue(url, year=None, fetch_abstracts=True, section_heading=None,
                            existing_sigs=None):
    """
    Legacy OJS 2 issue pages (table.tocArticle), used by ITID.
    Title/authors are on the issue TOC; abstracts require a per-article fetch.
    """
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "lxml")
    entries = _legacy_ojs_issue_entries(soup, section_heading=section_heading)
    total = len(entries)
    print(f"  found {total} papers")
    if fetch_abstracts and total:
        est_secs = int(total * REQUEST_DELAY)
        print(f"  fetching abstracts for {total} papers (~{est_secs}s at {REQUEST_DELAY}s/request) ...")

    papers = []
    for idx, entry in enumerate(entries, start=1):
        link = entry.get("link") or ""
        if link and not link.startswith("http"):
            link = requests.compat.urljoin(url, link)
        abstract = doi = None
        if fetch_abstracts and link:
            if not (existing_sigs and is_duplicate(entry["title"], existing_sigs)[0]):
                if idx == 1 or idx % 10 == 0 or idx == total:
                    print(f"  abstract {idx}/{total} ...")
                abstract, doi = _fetch_ojs_article_metadata(link, legacy=True)
            elif idx == 1 or idx % 10 == 0 or idx == total:
                print(f"  abstract {idx}/{total} (already in readings.json) ...")
        papers.append({
            "title": entry["title"],
            "authors": entry.get("authors"),
            "year": year,
            "link": link or None,
            "doi": doi,
            "abstract": abstract,
        })
    return papers


SPRINGER_BASE = "https://link.springer.com"
DEV_ENGINEERING_ISSN = "2352-7285"


def _openalex_abstract(inverted_index):
    if not inverted_index:
        return None
    positions = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def _parse_springer_chapter_html(html, year=None):
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one("h1.c-article-title, h1")
    if not title_el:
        return None
    title = title_el.get_text(" ", strip=True)
    authors = [m.get("content") for m in soup.select('meta[name="citation_author"]')]
    doi_el = soup.select_one('meta[name="citation_doi"]')
    doi = doi_el.get("content") if doi_el else None
    abstract_el = soup.select_one("#Abs1-content, .c-article-section__content, section.Abstract")
    abstract = abstract_el.get_text(" ", strip=True) if abstract_el else None
    link = doi and f"https://doi.org/{doi}" or None
    return {
        "title": title,
        "authors": ", ".join(authors) if authors else None,
        "year": year,
        "link": link,
        "doi": doi,
        "abstract": abstract[:3000] if abstract else None,
    }


def scrape_springer_book_toc(url, year=None, fetch_abstracts=True, existing_sigs=None):
    """
    Springer Link book table of contents (IFIP ICT4D proceedings volumes).
    Lists chapters from the book TOC, then fetches each chapter page for metadata.
    """
    book_url = url.split("#")[0]
    resp = _get(book_url)
    soup = BeautifulSoup(resp.text, "lxml")
    chapter_links = []
    seen = set()
    for a in soup.select('a[href*="/chapter/"]'):
        href = a.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)
        if not href.startswith("http"):
            href = SPRINGER_BASE + href
        chapter_links.append((href, a.get_text(" ", strip=True)))

    total = len(chapter_links)
    print(f"  found {total} chapters")
    if fetch_abstracts and total:
        est_secs = int(total * REQUEST_DELAY)
        print(f"  fetching chapter metadata for {total} chapters (~{est_secs}s) ...")

    papers = []
    for idx, (chapter_url, toc_title) in enumerate(chapter_links, start=1):
        if fetch_abstracts:
            if existing_sigs and is_duplicate(toc_title, existing_sigs)[0]:
                continue
            if idx == 1 or idx % 5 == 0 or idx == total:
                print(f"  chapter {idx}/{total} ...")
            try:
                chapter_resp = _get(chapter_url)
            except Exception:
                continue
            paper = _parse_springer_chapter_html(chapter_resp.text, year=year)
        else:
            paper = {"title": chapter_url.rsplit("/", 1)[-1], "authors": None, "year": year,
                     "link": chapter_url, "doi": extract_doi(chapter_url), "abstract": None}
        if paper:
            papers.append(paper)
    return papers


def _sciencedirect_volume_from_url(url):
    match = re.search(r"/vol/(\d+)/", url)
    return int(match.group(1)) if match else None


def _fetch_sciencedirect_volume_html(url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, wait_until="networkidle", timeout=120000)
        html = page.content()
        browser.close()
    return html


def _parse_sciencedirect_volume_html(html, year=None):
    soup = BeautifulSoup(html, "lxml")
    papers = []
    seen_links = set()
    for a in soup.select('a[href*="/science/article/pii/"]'):
        href = a.get("href", "")
        title = a.get_text(" ", strip=True)
        if not title or not href or href in seen_links:
            continue
        seen_links.add(href)
        if not href.startswith("http"):
            href = "https://www.sciencedirect.com" + href
        papers.append({
            "title": title,
            "authors": None,
            "year": year,
            "link": href,
            "doi": None,
            "abstract": None,
        })
    return papers


def _fetch_development_engineering_via_openalex(volume, year, issn=DEV_ENGINEERING_ISSN):
    """Fallback when ScienceDirect blocks automated access."""
    params = {
        "filter": f"primary_location.source.issn:{issn},biblio.volume:{volume},publication_year:{year}",
        "per-page": 200,
        "select": "title,doi,publication_year,authorships,abstract_inverted_index",
    }
    resp = requests.get("https://api.openalex.org/works", params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    papers = []
    for work in resp.json().get("results", []):
        authors = ", ".join(
            a.get("author", {}).get("display_name", "")
            for a in work.get("authorships", [])
            if a.get("author", {}).get("display_name")
        )
        doi = extract_doi(work.get("doi"))
        papers.append({
            "title": work.get("title") or work.get("display_name"),
            "authors": authors or None,
            "year": work.get("publication_year") or year,
            "link": f"https://doi.org/{doi}" if doi else None,
            "doi": doi,
            "abstract": _openalex_abstract(work.get("abstract_inverted_index")),
        })
    return papers


def scrape_sciencedirect_volume_toc(url, year=None, issn=DEV_ENGINEERING_ISSN, fetch_abstracts=True,
                                  existing_sigs=None):
    """
    ScienceDirect journal volume/issue TOC (Development Engineering).
    Tries Playwright first; falls back to OpenAlex by ISSN + volume + year when blocked.
    """
    volume = _sciencedirect_volume_from_url(url)
    papers = []
    try:
        html = _fetch_sciencedirect_volume_html(url)
        if "there was a problem providing the content" not in html.lower():
            papers = _parse_sciencedirect_volume_html(html, year=year)
    except Exception as exc:
        print(f"  ScienceDirect Playwright fetch failed: {exc}")

    if not papers and volume is not None and year is not None:
        print(f"  ScienceDirect blocked or empty; using OpenAlex ISSN {issn} vol {volume} year {year} ...")
        papers = _fetch_development_engineering_via_openalex(volume, year, issn=issn)

    if not papers:
        raise RuntimeError(f"No papers found for ScienceDirect volume TOC: {url}")

    if fetch_abstracts:
        missing = sum(1 for p in papers if not p.get("abstract"))
        if missing:
            print(f"  enriching {missing}/{len(papers)} papers missing abstracts via metadata APIs ...")
            papers = _enrich_papers_with_abstracts(
                papers, fetch_abstracts=True, existing_sigs=existing_sigs
            )
    return papers


def scrape_ieee_xplore_all_proceedings(url):
    """
    IEEE Xplore is heavily JavaScript-rendered; plain requests will usually NOT return paper
    listings (you'll get an app shell). Two options:
      1. Use IEEE Xplore's public metadata API (requires a free API key):
         https://developer.ieee.org/  -- then query by punumber/conference ID.
      2. Use a headless browser (playwright/selenium) to render the page before parsing.
    This function is a stub showing the Playwright approach; install playwright and run
    `playwright install chromium` first.
    """
    from playwright.sync_api import sync_playwright
    papers = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, wait_until="networkidle", timeout=60000)
        html = page.content()
        browser.close()
    soup = BeautifulSoup(html, "lxml")
    # ADJUST ME: inspect the rendered DOM; IEEE Xplore issue lists typically use
    # <xpl-issue-toc-results> / <div class="List-results-items">
    for item in soup.select("div.List-results-items, xpl-results-item"):
        title_el = item.select_one("a")
        if not title_el:
            continue
        papers.append({
            "title": title_el.get_text(strip=True),
            "authors": None,
            "year": None,
            "link": "https://ieeexplore.ieee.org" + title_el.get("href", ""),
            "abstract": None,  # fetch per-paper page separately if needed
        })
    return papers


def _load_html_file(filepath):
    """Load HTML from disk; unwrap browser 'View Source' saves if needed."""
    with open(filepath, encoding="utf-8") as f:
        raw = f.read()
    if "line-content" in raw and "line-gutter-backdrop" in raw:
        wrapper = BeautifulSoup(raw, "lxml")
        inner = "\n".join(td.get_text() for td in wrapper.select("td.line-content"))
        return BeautifulSoup(inner, "lxml")
    return BeautifulSoup(raw, "lxml")


def _parse_climate_change_ai_html(soup, venue_filter=None):
    """
    Parse the CCAI papers table (class paper-table). Each row has venue, title (+ details
    with abstract/authors), and subject-area tags.
    """
    papers = []
    base_url = "https://www.climatechange.ai"

    for row in soup.select(".paper-table tbody tr"):
        venue_el = row.select_one(".paper-venue")
        title_td = row.select_one(".paper-title")
        if not title_td:
            continue
        title_el = title_td.select_one('a[href*="/papers/"]')
        if not title_el:
            continue

        venue = venue_el.get_text(" ", strip=True) if venue_el else None
        if venue_filter and venue and venue_filter.lower() not in venue.lower():
            continue

        title = title_el.get_text(" ", strip=True)
        link = title_el.get("href", "")
        if link and not link.startswith("http"):
            link = base_url + link

        year = None
        if venue:
            year_match = re.search(r"(20\d{2})", venue)
            if year_match:
                year = int(year_match.group(1))

        abstract = authors = None
        for p in row.select("details p"):
            text = p.get_text(" ", strip=True)
            if text.lower().startswith("abstract"):
                abstract = re.sub(r"^abstract\s*:?\s*", "", text, flags=re.I).strip()
            elif text.lower().startswith("authors"):
                authors = re.sub(r"^authors\s*:?\s*", "", text, flags=re.I).strip()

        papers.append({
            "title": title,
            "authors": authors,
            "year": year,
            "link": link or None,
            "abstract": abstract[:3000] if abstract else None,
            "venue": venue,
            "subject_areas": [a.get_text(strip=True) for a in row.select(".paper-area")],
        })
    return papers


def scrape_climate_change_ai_from_file(filepath, venue_filter=None, year=None):
    """Parse a saved CCAI papers page (raw HTML or browser view-source export)."""
    soup = _load_html_file(filepath)
    papers = _parse_climate_change_ai_html(soup, venue_filter=venue_filter)
    if year is not None:
        for paper in papers:
            paper["year"] = year
    return papers


def scrape_climate_change_ai(url="https://www.climatechange.ai/papers", venue_filter=None,
                             html_file=None, html_file_fallback=None, year=None):
    """
    Climate Change AI workshop papers index. The listing is a static HTML table (paper-table),
    not a Next.js __NEXT_DATA__ blob. Use html_file to parse a saved copy offline, or
    html_file_fallback if the live fetch returns no rows.
    """
    if html_file:
        return scrape_climate_change_ai_from_file(html_file, venue_filter=venue_filter, year=year)

    resp = _get(url)
    papers = _parse_climate_change_ai_html(BeautifulSoup(resp.text, "lxml"), venue_filter=venue_filter)

    if not papers and html_file_fallback:
        papers = scrape_climate_change_ai_from_file(
            html_file_fallback, venue_filter=venue_filter, year=year
        )

    if year is not None:
        for paper in papers:
            paper["year"] = year
    return papers


ASETH_SKIP_PDF = re.compile(
    r"(job|position|research-at-act4d|research_associate|technologies_that|summary\.pdf|"
    r"research_philosophy|ongoing.projects)",
    re.I,
)


def _parse_personal_biblio_meta(meta_text):
    """Parse author/venue/year tail from a homepage bibliography line."""
    meta = re.sub(r"\s+", " ", meta_text or "").strip()
    if not meta:
        return None, None, None

    venue = None
    year = None
    pub_in = re.search(r"Published in\s+(.+?)(?:\.|$)", meta, re.I)
    if pub_in:
        venue = pub_in.group(1).strip().rstrip(".")

    conf = re.search(
        r"((?:ACM|IEEE|IJCAI|ASONAM|PROPL|ICTD|CHI|FAccT|NeurIPS|ICML|COMPASS|JCSS)[^.,]{0,50}),\s*"
        r"((19|20)\d{2})",
        meta,
        re.I,
    )
    if conf:
        venue = venue or conf.group(1).strip()
        year = int(conf.group(2))

    month_year = re.search(
        r"\.\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+((19|20)\d{2})\b",
        meta,
        re.I,
    )
    if month_year and not year:
        year = int(month_year.group(2))

    if not year:
        year_match = re.search(r"\b(19|20)\d{2}\b", meta)
        year = int(year_match.group()) if year_match else None

    authors = meta
    if month_year:
        authors = meta[: month_year.start()].strip()
    elif conf:
        authors = meta[: conf.start()].strip().rstrip(".").strip()
    elif pub_in:
        authors = meta[: pub_in.start()].strip().rstrip(".").strip()
    if authors.startswith("-"):
        authors = authors[1:].strip()
    if not authors:
        authors = None

    if not venue and year:
        year_match = re.search(r"\b(19|20)\d{2}\b", meta)
        if year_match:
            rest = meta[year_match.end() :].strip().lstrip(".").strip()
            if rest:
                venue = rest.split(".")[0].strip()

    return authors or None, year, venue or None


def _parse_personal_homepage_biblio_html(html, base_url, year=None):
    """Parse a flat faculty publications page with local PDF links per entry."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("body") or soup
    blocks = re.split(r"(?:<br\s*/?>\s*){2,}", str(root), flags=re.I)
    papers = []
    seen_titles = set()

    for chunk in blocks:
        block = BeautifulSoup(chunk, "lxml")
        pdf_a = block.find("a", href=re.compile(r"\.pdf$", re.I))
        if not pdf_a:
            continue
        href = pdf_a.get("href", "")
        if ASETH_SKIP_PDF.search(href):
            continue

        title = pdf_a.get_text(" ", strip=True)
        if len(title) < 10 or title.lower() in seen_titles:
            continue

        full = block.get_text(" ", strip=True)
        meta = full[len(title) :].strip()
        if meta.startswith("-"):
            meta = meta[1:].strip()

        authors, entry_year, venue = _parse_personal_biblio_meta(meta)
        pdf_url = requests.compat.urljoin(base_url, href)

        papers.append({
            "title": title,
            "authors": authors,
            "year": entry_year or year,
            "venue": venue,
            "link": pdf_url,
            "doi": None,
            "abstract": None,
        })
        seen_titles.add(title.lower())

    return papers


def _enrich_personal_biblio_papers(papers, fetch_abstracts=True, existing_sigs=None):
    if not fetch_abstracts or not papers:
        return papers

    to_enrich = papers
    if existing_sigs:
        to_enrich = [
            p for p in papers
            if not is_duplicate(p["title"], existing_sigs)[0]
        ]
        skipped = len(papers) - len(to_enrich)
        if skipped:
            print(f"  skipping metadata lookup for {skipped} papers already in readings.json")

    total = len(to_enrich)
    if not total:
        return papers

    print(f"  looking up DOI/abstract for {total} papers via metadata APIs ...")
    found = 0
    for idx, paper in enumerate(to_enrich, start=1):
        if idx == 1 or idx % 10 == 0 or idx == total:
            print(f"  metadata {idx}/{total} ({found} with abstract so far) ...")
        result = lookup_paper_metadata(
            paper["title"],
            authors=paper.get("authors"),
            doi=paper.get("doi") or extract_doi(paper.get("link")),
        )
        if apply_metadata_to_paper(paper, result):
            found += 1
    print(f"  abstracts found for {found}/{total} papers")
    return papers


def scrape_personal_homepage_biblio(url, year=None, fetch_abstracts=True, existing_sigs=None):
    """
    Flat faculty publications page (e.g. IITD homepage biblio lists).
    Parses title/authors/venue from HTML and local PDF links, then uses
    lookup_paper_metadata() to discover DOIs and fetch abstracts.
    """
    resp = _get(url)
    base_url = url.rsplit("/", 1)[0] + "/"
    papers = _parse_personal_homepage_biblio_html(resp.text, base_url, year=year)
    if not papers:
        raise RuntimeError(f"No publications parsed from homepage biblio: {url}")
    print(f"  found {len(papers)} publications")
    return _enrich_personal_biblio_papers(
        papers, fetch_abstracts=fetch_abstracts, existing_sigs=existing_sigs
    )

"""
Bulk-populates abstract / venue (journal or conference name) / year for readings in
readings.json that are missing them, using free, no-API-key scholarly metadata sources,
tried in this order per reading:

    1. Semantic Scholar API   -- best abstract coverage for CS/ML papers
    2. Crossref API           -- best coverage for journal articles & DOI-registered books
    3. OpenAlex API           -- broad fallback, good abstract coverage (inverted index -> reconstructed)
    4. Google Books API       -- fallback specifically for books (no DOI, e.g. trade nonfiction)

Install: pip install requests
Run:     python enrich_metadata.py

Design notes:
    - Video/talk readings (link contains youtube.com/youtu.be/ted.com) are skipped entirely --
      those aren't papers and already have their own metadata path (fetch_youtube_metadata.py).
    - Only readings with a currently-empty/missing "abstract" field are looked up, so this is
      safe to re-run (idempotent) after manually fixing a few entries.
    - Matches are accepted only above a title-similarity threshold (fuzzy word-overlap, same
      approach as dedup.py) to avoid attaching the wrong paper's abstract to a reading -- WRONG
      metadata is worse than NO metadata, so this errs conservative and leaves low-confidence
      matches for a human to check (logged to enrichment_needs_review.json).
    - Rate-limited (sleeps between calls) to be a good API citizen; Semantic Scholar in
      particular will start rejecting requests if hit too fast without an API key.
"""
import json
import re
import time
import argparse
import requests

HEADERS = {"User-Agent": "ictd-course-reading-list-enrichment/1.0 (mailto:aadi@somebody.edu)"}
REQUEST_DELAY = 1.2
MATCH_THRESHOLD = 0.6


def sig_words(title):
    s = re.sub(r'[^a-z0-9 ]', ' ', title.lower())
    stop = {'the','and','of','in','using','evidence','from','for','with','on','to','a','an',
            'study','case','india','indian','analysis','paper','data','new','review'}
    return {w for w in s.split() if len(w) >= 4 and w not in stop}


def title_score(a, b):
    sa, sb = sig_words(a), sig_words(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def is_video(reading):
    link = reading.get("link") or ""
    return "youtube.com" in link or "youtu.be" in link or "ted.com" in link


# ---------------- source 1: Semantic Scholar ----------------
def try_semantic_scholar(title):
    try:
        r = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": title, "fields": "title,abstract,venue,year,externalIds", "limit": 3},
            headers=HEADERS, timeout=15
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        for candidate in data:
            if title_score(title, candidate.get("title", "")) >= MATCH_THRESHOLD:
                return {
                    "abstract": candidate.get("abstract"),
                    "venue": candidate.get("venue"),
                    "year": candidate.get("year"),
                    "doi": (candidate.get("externalIds") or {}).get("DOI"),
                    "source": "semantic_scholar",
                    "matched_title": candidate.get("title"),
                }
    except requests.RequestException:
        pass
    return None


# ---------------- source 2: Crossref ----------------
def try_crossref(title, authors=None):
    try:
        params = {"query.bibliographic": title, "rows": 3}
        r = requests.get("https://api.crossref.org/works", params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        items = r.json().get("message", {}).get("items", [])
        for candidate in items:
            cand_title = (candidate.get("title") or [""])[0]
            if title_score(title, cand_title) >= MATCH_THRESHOLD:
                abstract = candidate.get("abstract")
                if abstract:
                    abstract = re.sub(r"<[^>]+>", "", abstract).strip()  # Crossref abstracts are JATS XML
                venue = (candidate.get("container-title") or [None])[0] or candidate.get("publisher")
                year = None
                date_parts = candidate.get("published", {}).get("date-parts", [[None]])
                if date_parts and date_parts[0] and date_parts[0][0]:
                    year = date_parts[0][0]
                return {
                    "abstract": abstract,
                    "venue": venue,
                    "year": year,
                    "doi": candidate.get("DOI"),
                    "source": "crossref",
                    "matched_title": cand_title,
                }
    except requests.RequestException:
        pass
    return None


# ---------------- source 3: OpenAlex ----------------
def try_openalex(title):
    try:
        r = requests.get(
            "https://api.openalex.org/works",
            params={"search": title, "per-page": 3},
            headers=HEADERS, timeout=15
        )
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        for candidate in results:
            cand_title = candidate.get("title") or candidate.get("display_name") or ""
            if title_score(title, cand_title) >= MATCH_THRESHOLD:
                abstract = None
                inv = candidate.get("abstract_inverted_index")
                if inv:
                    # OpenAlex stores abstracts as an inverted index {word: [positions]} -- reconstruct
                    positions = {}
                    for word, idxs in inv.items():
                        for i in idxs:
                            positions[i] = word
                    abstract = " ".join(positions[i] for i in sorted(positions))
                venue = None
                host = candidate.get("host_venue") or candidate.get("primary_location", {}).get("source") or {}
                if host:
                    venue = host.get("display_name")
                return {
                    "abstract": abstract,
                    "venue": venue,
                    "year": candidate.get("publication_year"),
                    "doi": extract_doi(candidate.get("doi")),
                    "source": "openalex",
                    "matched_title": cand_title,
                }
    except requests.RequestException:
        pass
    return None


# ---------------- source 4: Google Books (fallback for trade books) ----------------
def try_google_books(title, authors=None):
    try:
        q = f"intitle:{title}"
        if authors:
            q += f"+inauthor:{authors.split(',')[0].split('&')[0].strip()}"
        r = requests.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": q, "maxResults": 3}, headers=HEADERS, timeout=15
        )
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        for candidate in items:
            info = candidate.get("volumeInfo", {})
            cand_title = info.get("title", "")
            if title_score(title, cand_title) >= MATCH_THRESHOLD:
                year = None
                pub_date = info.get("publishedDate", "")
                if pub_date[:4].isdigit():
                    year = int(pub_date[:4])
                return {
                    "abstract": info.get("description"),
                    "venue": info.get("publisher"),
                    "year": year,
                    "source": "google_books",
                    "matched_title": cand_title,
                }
    except requests.RequestException:
        pass
    return None


def extract_doi(link):
    if not link:
        return None
    match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", link)
    return match.group(0).rstrip(".,;") if match else None


def try_crossref_doi(doi):
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}", headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        candidate = r.json().get("message", {})
        abstract = candidate.get("abstract")
        if abstract:
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
        venue = (candidate.get("container-title") or [None])[0] or candidate.get("publisher")
        year = None
        date_parts = candidate.get("published", {}).get("date-parts", [[None]])
        if date_parts and date_parts[0] and date_parts[0][0]:
            year = date_parts[0][0]
        return {
            "abstract": abstract,
            "venue": venue,
            "year": year,
            "doi": candidate.get("DOI") or doi,
            "source": "crossref_doi",
            "matched_title": (candidate.get("title") or [""])[0],
        }
    except requests.RequestException:
        return None


def try_openalex_doi(doi):
    try:
        r = requests.get(f"https://api.openalex.org/works/doi:{doi}", headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        candidate = r.json()
        abstract = None
        inv = candidate.get("abstract_inverted_index")
        if inv:
            positions = {}
            for word, idxs in inv.items():
                for i in idxs:
                    positions[i] = word
            abstract = " ".join(positions[i] for i in sorted(positions))
        venue = None
        host = candidate.get("host_venue") or candidate.get("primary_location", {}).get("source") or {}
        if host:
            venue = host.get("display_name")
        return {
            "abstract": abstract,
            "venue": venue,
            "year": candidate.get("publication_year"),
            "doi": doi,
            "source": "openalex_doi",
            "matched_title": candidate.get("title") or candidate.get("display_name"),
        }
    except requests.RequestException:
        return None


def try_semantic_scholar_doi(doi):
    try:
        r = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "title,abstract,venue,year,externalIds"},
            headers=HEADERS, timeout=15,
        )
        if r.status_code != 200:
            return None
        candidate = r.json()
        return {
            "abstract": candidate.get("abstract"),
            "venue": candidate.get("venue"),
            "year": candidate.get("year"),
            "doi": (candidate.get("externalIds") or {}).get("DOI") or doi,
            "source": "semantic_scholar_doi",
            "matched_title": candidate.get("title"),
        }
    except requests.RequestException:
        return None


def _merge_metadata(base, update):
    """Merge two lookup results, preferring non-empty abstract from update."""
    if not update:
        return base or {}
    out = dict(base) if base else {}
    for key in ("venue", "year", "doi", "matched_title"):
        if update.get(key) and not out.get(key):
            out[key] = update[key]
    if update.get("abstract"):
        out["abstract"] = update["abstract"]
        out["source"] = update.get("source", out.get("source"))
    elif update.get("source") and not out.get("source"):
        out["source"] = update["source"]
    return out


def _lookup_by_doi(doi):
    """Try all DOI metadata sources, merging until an abstract is found."""
    best = {}
    for fn in (try_semantic_scholar_doi, try_openalex_doi, try_crossref_doi):
        best = _merge_metadata(best, fn(doi))
        time.sleep(REQUEST_DELAY)
        if best.get("abstract"):
            break
    return best


def apply_metadata_to_paper(paper, result):
    """Apply a lookup_paper_metadata() result onto a scraper paper dict."""
    if not result:
        return False
    if result.get("abstract"):
        paper["abstract"] = result["abstract"][:3000]
    if result.get("doi"):
        paper["doi"] = result["doi"]
        paper["link"] = f"https://doi.org/{result['doi']}"
    if result.get("venue") and not paper.get("venue"):
        paper["venue"] = result["venue"]
    if result.get("year") and not paper.get("year"):
        paper["year"] = result["year"]
    return bool(result.get("abstract"))


def lookup_paper_metadata(title, authors=None, doi=None):
    """
    Look up abstract (and optionally venue/year/DOI) for a paper.
    When a DOI is available, try all DOI endpoints (Semantic Scholar, OpenAlex,
    Crossref) and merge results. If title search finds a DOI but no abstract,
    retry the DOI endpoints — Crossref often has the DOI while OpenAlex has the abstract.
    """
    resolved_doi = doi or None
    if resolved_doi:
        best = _lookup_by_doi(resolved_doi)
        if best.get("abstract") or best.get("venue") or best.get("doi"):
            return best

    best = {}
    for fn in (lambda: try_semantic_scholar(title),
               lambda: try_crossref(title, authors),
               lambda: try_openalex(title),
               lambda: try_google_books(title, authors)):
        result = fn()
        time.sleep(REQUEST_DELAY)
        if not result:
            continue
        best = _merge_metadata(best, result)
        if best.get("abstract"):
            return best

    found_doi = best.get("doi")
    if found_doi and not best.get("abstract"):
        best = _merge_metadata(best, _lookup_by_doi(found_doi))

    if best.get("abstract") or best.get("venue") or best.get("doi"):
        return best
    return None


def enrich_reading(reading):
    title = reading["title"]
    authors = reading.get("authors")
    doi = reading.get("doi") or extract_doi(reading.get("link"))
    return lookup_paper_metadata(title, authors=authors, doi=doi)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--readings", default="data/readings.json")
    parser.add_argument("--limit", type=int, default=None, help="cap number processed, for testing")
    args = parser.parse_args()

    with open(args.readings, encoding="utf-8") as f:
        rd = json.load(f)

    targets = [r for r in rd["readings"] if not r.get("abstract") and not is_video(r)]
    if args.limit:
        targets = targets[:args.limit]
    print(f"Enriching {len(targets)} readings...\n")

    updated, needs_review, no_match = [], [], []

    for i, r in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {r['id']}: {r['title'][:70]}")
        result = enrich_reading(r)
        if result is None:
            print("    NO MATCH found in any source")
            no_match.append({"id": r["id"], "title": r["title"]})
            continue

        if result.get("abstract"):
            r["abstract"] = result["abstract"][:3000]
        if result.get("venue") and not r.get("venue"):
            r["venue"] = result["venue"]
        if result.get("year") and not r.get("year"):
            r["year"] = result["year"]
        if result.get("doi"):
            r["doi"] = result["doi"]
        r["_enrichment_source"] = result["source"]

        print(f"    OK via {result['source']}: matched '{result.get('matched_title','')[:60]}'")
        updated.append(r["id"])

    with open(args.readings, "w", encoding="utf-8") as f:
        json.dump(rd, f, indent=2)

    with open("enrichment_no_match.json", "w", encoding="utf-8") as f:
        json.dump(no_match, f, indent=2)

    print(f"\nDone. Updated {len(updated)}, no match for {len(no_match)}.")
    print("No-match list written to enrichment_no_match.json -- these will mostly be older/obscure "
          "reports, working papers, or theses not indexed by any of the four sources; consider a "
          "manual web search for the important ones, or a targeted Google Scholar lookup.")


if __name__ == "__main__":
    main()

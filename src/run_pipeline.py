"""
Usage:
    python run_pipeline.py <venue_key>          # process one venue from venue_configs.VENUE_QUEUE
    python run_pipeline.py all                  # process the whole queue in order

Outputs:
    candidates_<venue_key>.json  -- everything the LLM marked relevant, for YOUR review
    skipped_<venue_key>.json     -- everything filtered out, WITH reasons (so you can audit
                                     false negatives, not just trust the filter blindly)

Papers are filtered in batches (default 100). After each batch, both output files are rewritten
with all results accumulated so far, so partial progress survives interruptions.

Nothing is written into readings.json automatically -- review candidates_*.json yourself, then
run merge_candidates.py on the files you approve.
"""
import sys
import json
import traceback
import inspect

import scrapers
from ollama_filter import load_framework, build_taxonomy_block, classify_paper, keyword_prefilter
from dedup import build_existing_sigs, is_duplicate, partition_new_papers
from venue_configs import VENUE_QUEUE

BATCH_SIZE = 100

SCRAPER_MAP = {
    "acm_dl_proceedings": scrapers.scrape_acm_dl_proceedings,
    "dblp_proceedings": scrapers.scrape_dblp_proceedings,
    "dblp_journal": scrapers.scrape_dblp_journal,
    "ijcai_listing": scrapers.scrape_ijcai_listing,
    "aaai_ojs_issue": scrapers.scrape_aaai_ojs_issue,
    "ojs_legacy_issue": scrapers.scrape_ojs_legacy_issue,
    "springer_book_toc": scrapers.scrape_springer_book_toc,
    "sciencedirect_volume_toc": scrapers.scrape_sciencedirect_volume_toc,
    "personal_homepage_biblio": scrapers.scrape_personal_homepage_biblio,
    "ieee_xplore_all_proceedings": scrapers.scrape_ieee_xplore_all_proceedings,
    "climate_change_ai": scrapers.scrape_climate_change_ai,
}


def _write_results(venue_key, candidates, skipped):
    with open(f"data/candidates_{venue_key}.json", "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2)
    with open(f"data/skipped_{venue_key}.json", "w", encoding="utf-8") as f:
        json.dump(skipped, f, indent=2)


def _classify_one_paper(paper, venue_key, year, fw, taxonomy_block, existing_sigs):
    """Run dedup → keyword prefilter → LLM on one paper. Returns (candidate|None, skipped|None)."""
    dup, match, score = is_duplicate(paper["title"], existing_sigs)
    if dup:
        return None, {**paper, "skip_reason": f"DUPLICATE of existing '{match['id']}' (score={score:.2f})"}

    passed, matched_kw = keyword_prefilter(paper, fw, min_hits=1)
    if not passed:
        return None, {**paper, "skip_reason": "NO_KEYWORD_OVERLAP"}

    try:
        verdict = classify_paper(paper, taxonomy_block)
    except Exception as e:
        return None, {**paper, "skip_reason": f"LLM_CALL_FAILED: {e}"}

    if verdict.get("relevant"):
        return {
            "id": None,
            "title": paper["title"],
            "authors": paper.get("authors"),
            "year": paper.get("year") or year,
            "venue": venue_key,
            "areas": verdict.get("areas", []),
            "topics": verdict.get("topics", []),
            "cross_cutting_axes": verdict.get("cross_cutting_axes", []),
            "area_agnostic": verdict.get("area_agnostic", False),
            "source_course": f"{venue_key}_venue_search",
            "notes": verdict.get("reason"),
            "link": paper.get("link"),
            "abstract": paper.get("abstract"),
            "_matched_keywords": matched_kw,
        }, None

    return None, {**paper, "skip_reason": verdict.get("reason", "LLM_MARKED_IRRELEVANT")}


def process_venue(venue_key, scraper_type, url, year, extra_kwargs,
                   framework_path="data/framework.json", readings_path="data/readings.json",
                   batch_size=BATCH_SIZE):
    fw = load_framework(framework_path)
    taxonomy_block = build_taxonomy_block(fw)

    with open(readings_path, encoding="utf-8") as f:
        readings_data = json.load(f)
    existing_sigs = build_existing_sigs(readings_data["readings"])

    print(f"[{venue_key}] scraping {url} ...")
    scraper_fn = SCRAPER_MAP[scraper_type]
    kwargs = dict(extra_kwargs)
    if year is not None:
        kwargs["year"] = year
    if "existing_sigs" in inspect.signature(scraper_fn).parameters:
        kwargs["existing_sigs"] = existing_sigs
    try:
        papers = scraper_fn(url, **kwargs)
    except Exception as e:
        print(f"[{venue_key}] SCRAPE FAILED: {e}")
        traceback.print_exc()
        return
    print(f"[{venue_key}] scraped {len(papers)} papers")

    papers, already_in_readings = partition_new_papers(papers, existing_sigs)
    if already_in_readings:
        print(f"[{venue_key}] {len(already_in_readings)} already in readings.json — "
              f"skipping metadata/LLM for those")
    if not papers:
        skipped = already_in_readings
        _write_results(venue_key, [], skipped)
        print(f"[{venue_key}] DONE. 0 candidates, {len(skipped)} skipped (all already ingested).")
        return

    candidates, skipped = [], list(already_in_readings)
    _write_results(venue_key, candidates, skipped)

    total = len(papers)
    for batch_start in range(0, total, batch_size):
        batch = papers[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        batch_end = min(batch_start + batch_size, total)
        print(f"[{venue_key}] batch {batch_num}: papers {batch_start + 1}-{batch_end} of {total} ...")

        for paper in batch:
            candidate, skip = _classify_one_paper(
                paper, venue_key, year, fw, taxonomy_block, existing_sigs
            )
            if candidate:
                candidates.append(candidate)
            if skip:
                skipped.append(skip)

        _write_results(venue_key, candidates, skipped)
        print(f"[{venue_key}] batch {batch_num} saved — "
              f"{len(candidates)} candidates, {len(skipped)} skipped so far")

    print(f"[{venue_key}] DONE. {len(candidates)} candidates, {len(skipped)} skipped. "
          f"Review candidates_{venue_key}.json before merging.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    target = sys.argv[1]
    queue = VENUE_QUEUE if target == "all" else [v for v in VENUE_QUEUE if v[0] == target]
    if not queue:
        print(f"Unknown venue key: {target}. Options: {[v[0] for v in VENUE_QUEUE]}")
        sys.exit(1)

    for venue_key, scraper_type, url, year, extra_kwargs in queue:
        process_venue(venue_key, scraper_type, url, year, extra_kwargs)

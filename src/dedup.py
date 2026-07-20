"""Fuzzy title-matching dedup against the existing readings.json corpus (same logic used
throughout the project's check_dupes.py, extracted here for reuse)."""
import re

STOPWORDS = {
    'the', 'and', 'of', 'in', 'using', 'evidence', 'from', 'for', 'with', 'on', 'to', 'a', 'an',
    'study', 'case', 'india', 'indian', 'analysis', 'paper', 'data', 'proceedings', 'journal',
    'international', 'conference', 'vol', 'pp', 'new', 'review', 'via', 'into', 'how', 'what',
    'towards', 'based', 'approach', 'application', 'applications', 'understanding', 'across',
    'onward', 'total', 'optional', 'video', 'watch', 'minute', 'minutes'
}
MIN_SIG_WORDS = 4
MATCH_THRESHOLD = 0.65


def sig_words(title):
    s = title.lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return {w for w in s.split() if len(w) >= 4 and w not in STOPWORDS}


def build_existing_sigs(readings):
    return [(r, sig_words(r["title"])) for r in readings if len(sig_words(r["title"])) >= MIN_SIG_WORDS]


def find_best_match(title, existing_sigs):
    cand = sig_words(title)
    if len(cand) < MIN_SIG_WORDS:
        return None, 0.0
    best, best_score = None, 0.0
    for r, sig in existing_sigs:
        inter = len(cand & sig)
        smaller = min(len(cand), len(sig))
        score = inter / smaller if smaller else 0
        if score > best_score:
            best, best_score = r, score
    return best, best_score


def is_duplicate(title, existing_sigs, threshold=MATCH_THRESHOLD):
    match, score = find_best_match(title, existing_sigs)
    return (score >= threshold), match, score


def partition_new_papers(papers, existing_sigs, threshold=MATCH_THRESHOLD):
    """Split scraped papers into ones not yet in readings.json vs already-ingested duplicates."""
    new_papers = []
    already_in_readings = []
    for paper in papers:
        dup, match, score = is_duplicate(paper["title"], existing_sigs, threshold=threshold)
        if dup:
            already_in_readings.append({
                **paper,
                "skip_reason": (
                    f"ALREADY_IN_READINGS: duplicate of '{match['id']}' (score={score:.2f})"
                ),
            })
        else:
            new_papers.append(paper)
    return new_papers, already_in_readings

"""
Fetches exact title, upload year, and description for every YouTube link in readings.json,
using yt-dlp (does NOT download video/audio -- metadata only, --skip-download).

Install:
    pip install yt-dlp

Run (from the same folder as readings.json, or pass --readings path):
    python fetch_youtube_metadata.py

What it does:
    - Finds every reading whose "link" contains youtube.com or youtu.be
    - Runs yt-dlp --dump-json on each (one process call per video, ~1-2 sec each)
    - Updates that reading's "title" to the exact YouTube title (only if it looks like a real
      title -- won't overwrite if yt-dlp fails)
    - Sets "year" to the upload year
    - Sets "abstract" to the full video description (some are long; truncated to 3000 chars)
    - Leaves everything else untouched
    - Writes back to readings.json, and prints a summary + list of any failures (e.g. deleted
      videos, region-locked, etc. -- these need manual attention)
"""
import json
import subprocess
import argparse
import sys
import time


def fetch_metadata(url, retries=2):
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["yt-dlp", "--dump-json", "--skip-download", "--no-warnings", url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None, result.stderr.strip()[:300]
            data = json.loads(result.stdout)
            return {
                "title": data.get("title"),
                "upload_date": data.get("upload_date"),  # format YYYYMMDD
                "description": data.get("description"),
                "channel": data.get("uploader") or data.get("channel"),
            }, None
        except subprocess.TimeoutExpired:
            if attempt < retries - 1:
                continue
            return None, "TIMEOUT"
        except json.JSONDecodeError:
            return None, "JSON_PARSE_FAILED"
        except FileNotFoundError:
            print("ERROR: yt-dlp not found. Install with: pip install yt-dlp")
            sys.exit(1)
    return None, "UNKNOWN_FAILURE"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--readings", default="data/readings.json")
    args = parser.parse_args()

    with open(args.readings, encoding="utf-8") as f:
        rd = json.load(f)

    targets = [r for r in rd["readings"]
               if r.get("link") and ("youtube.com" in r["link"] or "youtu.be" in r["link"])]
    print(f"Found {len(targets)} YouTube links to process.\n")

    updated, failed = [], []
    for i, r in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {r['id']} -> {r['link']}")
        meta, err = fetch_metadata(r["link"])
        if meta is None:
            print(f"    FAILED: {err}")
            failed.append({"id": r["id"], "link": r["link"], "error": err})
            continue

        old_title = r["title"]
        if meta["title"]:
            r["title"] = meta["title"]
        if meta["upload_date"]:
            r["year"] = int(meta["upload_date"][:4])
        if meta["description"]:
            r["abstract"] = meta["description"][:3000]
        r["_youtube_channel"] = meta["channel"]  # bonus field, remove if you don't want it

        print(f"    OK: '{old_title}' -> '{meta['title']}' ({r.get('year')})")
        updated.append(r["id"])

    with open(args.readings, "w", encoding="utf-8") as f:
        json.dump(rd, f, indent=2)

    print(f"\nDone. Updated {len(updated)}, failed {len(failed)}.")
    if failed:
        print("\nFAILURES (need manual attention -- video may be deleted/private/region-locked):")
        for f_ in failed:
            print(f"  {f_['id']}: {f_['error']}  ({f_['link']})")
        with open("youtube_fetch_failures.json", "w", encoding="utf-8") as f:
            json.dump(failed, f, indent=2)
        print("\n(also written to youtube_fetch_failures.json)")


if __name__ == "__main__":
    main()

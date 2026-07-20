# ICTD course creation

This repo contains:

- **`site/`** — static course website (readings, examples, schedule)
- **`src/`**, **`skills/`**, **`data/`** — local pipelines for venue ingestion, case-study generation, and lecture prep (not served to the web)

---

## Local venue-ingestion pipeline

Runs the same three-step process we used for the IJCAI pilot (scrape → keyword prefilter →
LLM relevance+tagging → dedup against readings.json), but locally, so it can chew through
Climate Change AI / KDD / FAccT / GHTC / AAAI without burning conversation turns.

## Setup

```bash
pip install requests beautifulsoup4 lxml
# only needed for GHTC (IEEE Xplore) and possibly Climate Change AI if no embedded JSON is found:
pip install playwright && playwright install chromium

# Ollama, if not already running:
ollama pull qwen2.5
ollama serve   # usually starts automatically after pull/install
```

Copy this whole `local_pipeline/` folder so it sits *next to* your `framework.json` and
`readings.json` (or adjust the paths passed to `process_venue()` in `run_pipeline.py`).

## Run

```bash
# one venue at a time (recommended -- review each before moving on):
python src/run_pipeline.py climate_change_ai
python src/run_pipeline.py ijcai_2024
python src/run_pipeline.py kdd_2025
# ...etc, keys are in venue_configs.py

# or the whole remaining queue in the order you specified:
python src/run_pipeline.py all
```

Each run produces two files per venue:

- `candidates_<venue>.json` — papers the LLM marked relevant, with suggested area/topic/axis
tags and its one-sentence reasoning in `notes`. **Review this by hand.**
- `skipped_<venue>.json` — everything filtered out, tagged with *why* (duplicate / no keyword
overlap / LLM said irrelevant + its reason). Worth a skim to catch false negatives, especially
early on while you're calibrating trust in qwen2.5's judgment.



## Review & merge

Open `candidates_<venue>.json`, delete entries you disagree with, optionally fix the `id` field
(a short slug), then:

```bash
python src/merge_candidates.py data/candidates_kdd_2025.json data/readings.json
```

This re-checks for duplicates against the *live* readings.json (including anything merged from
other venues since the candidates file was generated) before appending.

## Tuning notes

- **Selectors will likely need adjustment.** I could not verify raw HTML against these live
sites in the conversation that produced this code (my fetch tool returns cleaned text, not
HTML source) — the CSS selectors in `scrapers.py` are my best knowledge of each platform's
typical markup, marked `# ADJUST ME`. Inspect one real page per venue type and fix as needed.
- **ACM DL bot detection**: if `scrape_acm_dl_proceedings()` gets blocked, save the page as HTML
from your browser (Ctrl+S) and use `scrape_acm_dl_proceedings_from_file()` instead.
- **qwen2.5 model size**: the default `qwen2.5` (7B) should be fine for this classification task,
but if you notice bad JSON output or weak judgment calls, try `qwen2.5:14b` and change `MODEL`
in `ollama_filter.py`.
- **min_hits in keyword_prefilter()**: currently 1 (any single keyword hit passes to the LLM).
Raise to 2-3 if too much junk is reaching the LLM step and slowing things down; lower recall
risk if you do.
- **The prompt in** `ollama_filter.py` **is a first draft** — after reviewing a batch of
`candidates_*.json` / `skipped_*.json`, you'll likely want to tighten or loosen the
developing-regions rule wording based on what you see qwen2.5 getting wrong.

---

## Course website — production (Apache 2)

The public site is **static files only** under `site/`. Apache serves HTML, JS, CSS, JSON, and Markdown; no application server or Python process is required in production.

### 1. Install Apache

On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install apache2
sudo systemctl enable --now apache2
```

Ensure JSON is served correctly (usually already enabled):

```bash
grep -i application/json /etc/mime.types
```

### 2. Deploy the site files

Clone or copy the repo on the server, then publish only the `site/` tree. Example layout:

```bash
sudo mkdir -p /var/www/ictd-course
sudo rsync -av --delete site/ /var/www/ictd-course/
sudo chown -R www-data:www-data /var/www/ictd-course
```

Before each deploy (or when data changes upstream), sync JSON from `data/` into the web tree:

```bash
cp data/framework.json data/readings.json data/examples.json site/data/
rsync -av --delete site/ /var/www/ictd-course/
```

Edit course copy in `site/content/main_page_content.md` before syncing if needed.

After changing CSS or JS, bump `SITE_ASSET_VERSION` in `site/js/site-config.js` and the matching `?v=` query strings on script/style links in the HTML pages so browsers pick up the new assets.

### 3. Apache virtual host

Create `/etc/apache2/sites-available/ictd-course.conf`:

```apache
<VirtualHost *:80>
    ServerName ictd.example.edu
    DocumentRoot /var/www/ictd-course

    <Directory /var/www/ictd-course>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    # Course data and markdown are loaded via fetch(); allow cross-origin is not needed.
    # Optional: short cache for static assets, no cache for JSON/markdown during active term.
    <FilesMatch "\.(html|css|js)$">
        Header set Cache-Control "public, max-age=3600"
    </FilesMatch>
    <FilesMatch "\.(json|md)$">
        Header set Cache-Control "no-cache"
    </FilesMatch>

    ErrorLog ${APACHE_LOG_DIR}/ictd-course-error.log
    CustomLog ${APACHE_LOG_DIR}/ictd-course-access.log combined
</VirtualHost>
```

Enable the site and reload Apache:

```bash
sudo a2enmod headers
sudo a2ensite ictd-course.conf
sudo a2dissite 000-default.conf   # optional, if this vhost should be the default
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Replace `ictd.example.edu` with your hostname and point DNS (or `/etc/hosts` for testing) at the server.

### 4. HTTPS (recommended)

```bash
sudo apt install certbot python3-certbot-apache
sudo certbot --apache -d ictd.example.edu
```

Certbot adds a `:443` vhost and renewal cron. Re-run `certbot renew --dry-run` after major Apache upgrades.

### 5. Updates

To publish content or data changes:

```bash
cd /path/to/ictd-course-creation
git pull
cp data/framework.json data/readings.json data/examples.json site/data/
sudo rsync -av --delete site/ /var/www/ictd-course/
```

No build step. Refresh the browser; JSON loads use `cache: no-store` in the client.

### 6. What stays off the server

Do **not** expose the repo root, `.env`, `data/lecture-prep/`, `data/examples-output/`, or `.venv/` via Apache. Only sync `site/` to the document root. Pipeline scripts (`src/`, `skills/`) run on a developer or batch machine, not through the web server.

Local preview: see [`site/README.md`](site/README.md).

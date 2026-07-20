# ICTD Course Website

Static HTML/CSS/JS site for the ICTD course reading list and framework.

## Local preview

Because the pages load JSON and Markdown via `fetch()`, opening `index.html` directly
(`file://`) will fail in most browsers due to CORS restrictions.

From this directory, run:

```bash
python -m http.server 8000
```

Then open [http://localhost:8000/index.html](http://localhost:8000/index.html).

## Data files

Copy updated versions of these upstream files into `site/data/` and `site/content/` as they change:

- `data/framework.json`
- `data/readings.json`
- `data/examples.json`
- `content/main_page_content.md`

No rebuild step is required — refresh the browser after updating the data files.

During local development, JSON loads use `cache: no-store` and assets carry a version
query string (`site/js/site-config.js` → `SITE_ASSET_VERSION`; bump that value and the
matching `?v=` on CSS/JS links in the HTML pages when you change scripts or styles and
the browser still shows stale content).

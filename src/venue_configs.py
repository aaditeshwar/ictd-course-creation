"""
Remaining venues to process, in the order requested: Climate Change AI, IJCAI (2022-2024;
2025 already done), KDD, FAccT, GHTC, AAAI AISI.

Each entry: (venue_key, scraper_type, url, year, extra_kwargs)
scraper_type must match a function name suffix in scrapers.py (scrape_<scraper_type>).
"""

VENUE_QUEUE = [
    # ---- Climate Change AI (special case: one page, filter by venue/subject client-side or
    #      via the embedded JSON blob -- see scrapers.scrape_climate_change_ai) ----
    ("climate_change_ai", "climate_change_ai", "https://www.climatechange.ai/papers", None, {
        "html_file_fallback": "raw/view-source_https___www.climatechange.ai_papers_.html",
    }),

    # ---- IJCAI remaining years (2025 already ingested manually) ----
    ("ijcai_2024", "ijcai_listing",
     "https://ijcai24.org/ai-for-social-good-special-track-accepted-papers/index.html", 2024, {}),
    ("ijcai_2023", "ijcai_listing",
     "https://ijcai-23.org/special-track-on-ai-for-good/index.html", 2023, {}),
    ("ijcai_2022", "dblp_proceedings", "https://dblp.org/db/conf/ijcai/ijcai2022.html", 2022,
     {"section_heading": "AI for Good"}),

    # ---- KDD main proceedings (DBLP; ACM DL blocks bots) ----
    ("kdd_2025", "dblp_proceedings", "https://dblp.org/db/conf/kdd/index.html", 2025, {"dblp_conf": "kdd"}),
    ("kdd_2024", "dblp_proceedings", "https://dblp.org/db/conf/kdd/kdd2024.html", 2024, {}),
    ("kdd_2023", "dblp_proceedings", "https://dblp.org/db/conf/kdd/kdd2023.html", 2023, {}),
    ("kdd_2022", "dblp_proceedings", "https://dblp.org/db/conf/kdd/kdd2022.html", 2022, {}),
    ("kdd_2021", "dblp_proceedings", "https://dblp.org/db/conf/kdd/kdd2021.html", 2021, {}),

    # ---- FAccT (DBLP conf key: fat; proceedings pages: facctYYYY.html) ----
    ("facct_2025", "dblp_proceedings", "https://dblp.org/db/conf/fat/facct2025.html", 2025, {}),
    ("facct_2024", "dblp_proceedings", "https://dblp.org/db/conf/fat/facct2024.html", 2024, {}),
    ("facct_2023", "dblp_proceedings", "https://dblp.org/db/conf/fat/facct2023.html", 2023, {}),
    ("facct_2022", "dblp_proceedings", "https://dblp.org/db/conf/fat/facct2022.html", 2022, {}),
    ("facct_2021", "dblp_proceedings", "https://dblp.org/db/conf/fat/facct2021.html", 2021, {}),

    # ---- GHTC (DBLP; IEEE Xplore is JS-rendered) ----
    ("ghtc_2024", "dblp_proceedings", "https://dblp.org/db/conf/ghtc/ghtc2024.html", 2024, {}),
    ("ghtc_2023", "dblp_proceedings", "https://dblp.org/db/conf/ghtc/ghtc2023.html", 2023, {}),
    ("ghtc_2022", "dblp_proceedings", "https://dblp.org/db/conf/ghtc/ghtc2022.html", 2022, {}),
    ("ghtc_2021", "dblp_proceedings", "https://dblp.org/db/conf/ghtc/ghtc2021.html", 2021, {}),

    # ---- AAAI AISI (OJS -- title/authors inline, abstracts need per-article fetch) ----
    ("aaai_25_aisi", "aaai_ojs_issue", "https://ojs.aaai.org/index.php/AAAI/issue/view/650", 2025,
     {"section_heading": "AI for Social Impact"}),
    ("aaai_24_aisi", "aaai_ojs_issue", "https://ojs.aaai.org/index.php/AAAI/issue/view/595", 2024,
     {"section_heading": "AI for Social Impact"}),
    ("aaai_23_aisi", "aaai_ojs_issue", "https://ojs.aaai.org/index.php/AAAI/issue/view/559", 2023,
     {"section_heading": "AI for Social Impact"}),

    # ---- ACM COMPASS (DBLP conf key: dev; proceedings pages: compassYYYY.html) ----
    ("compass_2025", "dblp_proceedings", "https://dblp.org/db/conf/dev/index.html", 2025, {"dblp_conf": "dev"}),
    ("compass_2024", "dblp_proceedings", "https://dblp.org/db/conf/dev/compass2024.html", 2024, {}),
    ("compass_2023", "dblp_proceedings", "https://dblp.org/db/conf/dev/compass2023.html", 2023, {}),
    ("compass_2022", "dblp_proceedings", "https://dblp.org/db/conf/dev/compass2022.html", 2022, {}),
    ("compass_2021", "dblp_proceedings", "https://dblp.org/db/conf/dev/compass2021.html", 2021, {}),

    # ---- ACM ICTD (biennial; DBLP: ictdYYYY.html) ----
    ("ictd_2024", "dblp_proceedings", "https://dblp.org/db/conf/ictd/ictd2024.html", 2024, {}),
    ("ictd_2022", "dblp_proceedings", "https://dblp.org/db/conf/ictd/ictd2022.html", 2022, {}),
    ("ictd_2020", "dblp_proceedings", "https://dblp.org/db/conf/ictd/ictd2020.html", 2020, {}),

    # ---- ACM JCSS (DBLP journal; volume N -> acmjcssN.html) ----
    ("jcss_2025", "dblp_journal", "https://dblp.org/db/journals/acmjcss/index.html", 2025,
     {"dblp_journal": "acmjcss", "dblp_volume": 3}),
    ("jcss_2024", "dblp_journal", "https://dblp.org/db/journals/acmjcss/index.html", 2024,
     {"dblp_journal": "acmjcss", "dblp_volume": 2}),
    ("jcss_2023", "dblp_journal", "https://dblp.org/db/journals/acmjcss/index.html", 2023,
     {"dblp_journal": "acmjcss", "dblp_volume": 1}),

    # ---- CHI (DBLP; main + supplemental volumes chiYYYY.html / chiYYYYa.html) ----
    ("chi_2025", "dblp_proceedings", "https://dblp.org/db/conf/chi/index.html", 2025, {"dblp_conf": "chi"}),
    ("chi_2024", "dblp_proceedings", "https://dblp.org/db/conf/chi/index.html", 2024, {"dblp_conf": "chi"}),
    ("chi_2023", "dblp_proceedings", "https://dblp.org/db/conf/chi/index.html", 2023, {"dblp_conf": "chi"}),
    ("chi_2022", "dblp_proceedings", "https://dblp.org/db/conf/chi/index.html", 2022, {"dblp_conf": "chi"}),
    ("chi_2021", "dblp_proceedings", "https://dblp.org/db/conf/chi/index.html", 2021, {"dblp_conf": "chi"}),

    # ---- CSCW (published in PACM HCI; DBLP journal volume + CSCW1/CSCW2 issue sections) ----
    ("cscw_2025_1", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2025,
     {"dblp_journal": "pacmhci", "section_heading": "Number 2, 2025"}),
    ("cscw_2025_2", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2025,
     {"dblp_journal": "pacmhci", "section_heading": "Number 7, 2025"}),
    ("cscw_2024_1", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2024,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW1"}),
    ("cscw_2024_2", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2024,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW2"}),
    ("cscw_2023_1", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2023,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW1"}),
    ("cscw_2023_2", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2023,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW2"}),
    ("cscw_2022_1", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2022,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW1"}),
    ("cscw_2022_2", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2022,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW2"}),
    ("cscw_2021_1", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2021,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW1"}),
    ("cscw_2021_2", "dblp_journal", "https://dblp.org/db/journals/pacmhci/index.html", 2021,
     {"dblp_journal": "pacmhci", "section_heading": "CSCW2"}),

    # ---- AIES (specific issue URLs supplied directly -- reuse aaai_ojs_issue, same platform
    #      as AAAI AISI. 2025 spans three parts; older years not yet supplied.) ----
    ("aies_2025_part1", "aaai_ojs_issue", "https://ojs.aaai.org/index.php/AIES/issue/view/677", 2025, {}),
    ("aies_2025_part2", "aaai_ojs_issue", "https://ojs.aaai.org/index.php/AIES/issue/view/678", 2025, {}),
    ("aies_2025_part3", "aaai_ojs_issue", "https://ojs.aaai.org/index.php/AIES/issue/view/679", 2025, {}),
    ("aies_2024", "aaai_ojs_issue", "https://ojs.aaai.org/index.php/AIES/issue/view/609", 2024, {}),
    # NOTE: AIES 2021-2023 issue URLs not yet supplied -- still need manual lookup on
    # https://ojs.aaai.org/index.php/AIES/issue/archive if those years matter for the course.
 
    # ---- ITID journal (legacy OJS 2 table TOC -- scrape_ojs_legacy_issue) ----
    ("itid_2020", "ojs_legacy_issue", "https://itidjournal.org/index.php/itid/issue/view/90.html", 2020, {}),
    ("itid_2019", "ojs_legacy_issue", "https://itidjournal.org/index.php/itid/issue/view/89.html", 2019, {}),
    ("itid_2018", "ojs_legacy_issue", "https://itidjournal.org/index.php/itid/issue/view/88.html", 2018, {}),
    ("itid_2017", "ojs_legacy_issue", "https://itidjournal.org/index.php/itid/issue/view/87.html", 2017, {}),
 
    # ---- IFIP ICT4D (Springer Link book TOC -- scrape_springer_book_toc) ----
    ("ifip_ict4d_2024_part1", "springer_book_toc",
     "https://link.springer.com/book/10.1007/978-3-031-66982-8#toc", 2024, {}),
    ("ifip_ict4d_2024_part2", "springer_book_toc",
     "https://link.springer.com/book/10.1007/978-3-031-66986-6#toc", 2024, {}),
    ("ifip_ict4d_2022", "springer_book_toc",
     "https://link.springer.com/book/10.1007/978-3-031-19429-0#toc", 2022, {}),
    ("ifip_ict4d_2020", "springer_book_toc",
     "https://link.springer.com/book/10.1007/978-3-030-65828-1#toc", 2020, {}),
 
    # ---- Development Engineering (ScienceDirect volume TOC; OpenAlex fallback when blocked) ----
    ("development_engineering_2023", "sciencedirect_volume_toc",
     "https://www.sciencedirect.com/journal/development-engineering/vol/8/suppl/C", 2023, {}),
    ("development_engineering_2022", "sciencedirect_volume_toc",
     "https://www.sciencedirect.com/journal/development-engineering/vol/7/suppl/C", 2022, {}),
    ("development_engineering_2021", "sciencedirect_volume_toc",
     "https://www.sciencedirect.com/journal/development-engineering/vol/6/suppl/C", 2021, {}),
    ("development_engineering_2020", "sciencedirect_volume_toc",
     "https://www.sciencedirect.com/journal/development-engineering/vol/5/suppl/C", 2020, {}),
      
    # ================= NEW: instructor-specific venue ================= #
 
    # ---- Aaditeshwar Seth's own publications page (not from venues.json -- added directly by
    #      the instructor). Single flat page spanning all years (2009-present); already tagged
    #      as "This is a book. " for the one book on it (seth_technology_dis_empowerment) which
    #      is already in readings.json, so expect at least one duplicate to catch on dedup. Most
    #      of this author's work is directly ICTD-relevant by construction (it's the instructor's
    #      own research group, ACT4D), but the page also includes general networks/systems papers
    #      (e.g. GPU-accelerated hydrology algorithms, STAC extensions) that may not map cleanly
    #      onto the course's areas/topics -- keep needs_filtering=true rather than assuming
    #      everything on this one page is automatically in scope.) ----
    ("aseth_publications", "personal_homepage_biblio",
     "https://www.cse.iitd.ernet.in/~aseth/publications.html", None, {}),

]

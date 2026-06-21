#!/usr/bin/env python3
"""Unit tests for web_scraper.py — offline (fetch + model injected).

    python3 scripts/orch/test_web_scraper.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import web_scraper as ws  # noqa: E402


class HtmlToText(unittest.TestCase):
    def test_strips_boilerplate_keeps_text_and_title(self):
        raw = ("<html><head><title>eCTD Module 1</title></head><body>"
               "<nav>menu menu</nav><script>evil()</script>"
               "<p>Module 1 is the regional administrative information.</p>"
               "<footer>copyright</footer></body></html>")
        title, text = ws._html_to_text(raw)
        self.assertEqual(title, "eCTD Module 1")
        self.assertIn("regional administrative information", text)
        self.assertNotIn("evil", text)
        self.assertNotIn("copyright", text)


class FetchText(unittest.TestCase):
    def test_jina_service_path(self):
        def fetch(u, timeout=20):
            self.assertTrue(u.startswith("https://r.jina.ai/"))
            return ("# Health Canada ANDS\n\n"
                    + "Abbreviated New Drug Submission guidance. " * 40)  # not thin
        page = ws.fetch_text("https://example.com/ands", {"ADF_SCRAPER": "jina"}, fetch)
        self.assertEqual(page["title"], "Health Canada ANDS")
        self.assertIn("Abbreviated New Drug Submission", page["markdown"])

    def test_thin_or_blocked_service_falls_back_to_plain_get(self):
        # Jina returned a 731-char 401 stub for FDA while a plain GET got 44KB — so a
        # thin/blocked service result must fall back to the plain fetch.
        def fetch(u, timeout=20):
            if u.startswith("https://r.jina.ai/"):
                return "401 Unauthorized"                      # thin block stub
            return "<title>Real</title><body>" + ("full eCTD content " * 200) + "</body>"
        page = ws.fetch_text("https://www.fda.gov/ectd", {"ADF_SCRAPER": "jina"}, fetch)
        self.assertEqual(page["title"], "Real")
        self.assertIn("full eCTD content", page["markdown"])   # got it via fallback

    def test_firecrawl_thin_stub_also_falls_back(self):
        # the Firecrawl branch must guard with _is_thin too (not just jina).
        def fetch(u, timeout=20):
            if "firecrawl" in u:
                return "403 Forbidden"                         # thin block stub
            return "<title>Real</title><body>" + ("full content " * 200) + "</body>"
        page = ws.fetch_text("https://x.test",
                             {"ADF_SCRAPER": "firecrawl", "FIRECRAWL_API_KEY": "k"}, fetch)
        self.assertEqual(page["title"], "Real")
        self.assertIn("full content", page["markdown"])

    def test_fallback_plain_get_when_no_service(self):
        def fetch(u, timeout=20):
            return "<title>T</title><p>plain body text</p>"
        page = ws.fetch_text("https://x.test", {"ADF_SCRAPER": "none"}, fetch)
        self.assertIn("plain body text", page["markdown"])

    def test_dead_url_is_none(self):
        page = ws.fetch_text("https://x.test", {"ADF_SCRAPER": "none"},
                             lambda u, timeout=20: None)
        self.assertIsNone(page)


class Search(unittest.TestCase):
    def test_parses_ddg_results_and_decodes_redirects(self):
        ddg = ('<a class="result__a" href="/l/?uddg=https%3A%2F%2Fcanada.ca%2Fectd">x</a>'
               '<a class="result__a" href="https://hc-sc.gc.ca/ands">y</a>')
        urls = ws.search("ands", {}, lambda u, timeout=20: ddg)
        self.assertIn("https://canada.ca/ectd", urls)
        self.assertIn("https://hc-sc.gc.ca/ands", urls)

    def test_empty_on_fetch_failure(self):
        self.assertEqual(ws.search("q", {}, lambda u, timeout=20: None), [])


class ScrapeAndGather(unittest.TestCase):
    def test_scrape_uses_model_to_extract_facts(self):
        def fetch(u, timeout=20):
            return "# Page\n\nlong raw domain text about eCTD modules and validation"

        def complete(prompt, role):
            self.assertEqual(role, "extract")
            return ("- eCTD has 5 modules\n- Module 1 is region-specific", {})
        note = ws.scrape("https://x/ectd", {"ADF_SCRAPER": "jina"}, fetch, complete)
        self.assertIn("eCTD has 5 modules", note["facts"])
        self.assertEqual(note["citations"], ["https://x/ectd"])

    def test_gather_prioritizes_user_urls_then_search(self):
        pages = {  # well over the thin-threshold so the service result is used
            "https://user.test/doc": "# User\n\n" + "user-provided requirements doc " * 80,
            "https://hit.test/a": "# Hit\n\n" + "searched page content here " * 80,
        }

        def fetch(u, timeout=20):
            if "duckduckgo" in u:
                return '<a class="result__a" href="https://hit.test/a">h</a>'
            for k, v in pages.items():
                if k in u:
                    return v
            return None
        notes = ws.gather(queries=["ands"], urls=["https://user.test/doc"],
                          env={"ADF_RESEARCH": "1", "ADF_SCRAPER": "jina"}, fetch=fetch)
        titles = [n["title"] for n in notes]
        self.assertEqual(titles[0], "User")          # user URL first (authoritative)
        self.assertIn("Hit", titles)

    def test_disabled_research_returns_empty(self):
        self.assertEqual(ws.gather(["q"], env={"ADF_RESEARCH": "0"}), [])

    # ---- G20: scrape() clips head+tail instead of blind [:12000] truncation ----
    def test_scrape_preserves_tail_content_of_long_page(self):
        head_part = "HEAD_CONTENT " * 923     # ~12000 chars
        tail_part = " TAIL_SENTINEL " * 800   # ~12000 chars
        big_body = head_part + tail_part

        captured = []

        def fetch(u, timeout=20):
            return big_body                    # Jina path: markdown used verbatim

        def complete(prompt, role):
            captured.append(prompt)
            return ("- some extracted fact", {})

        note = ws.scrape("https://x.test", {"ADF_SCRAPER": "jina"}, fetch, complete)
        self.assertIsNotNone(note)
        self.assertTrue(captured, "complete() was never called")
        self.assertIn("TAIL_SENTINEL", captured[0])   # tail survives the clip

    def test_scrape_no_model_fallback_also_clips_not_truncates(self):
        head_part = "HEAD_CONTENT " * 923
        tail_part = " TAIL_SENTINEL " * 800
        big_body = head_part + tail_part

        def fetch(u, timeout=20):
            return big_body                    # Jina path

        note = ws.scrape("https://x.test", {"ADF_SCRAPER": "jina"}, fetch, complete=None)
        self.assertIsNotNone(note)
        self.assertIn("TAIL_SENTINEL", note["facts"])

    # ---- G19: gather() warns when user URLs exceed max_pages ----
    def test_gather_warns_when_user_urls_exceed_cap(self):
        """gather() must emit a WARNING when caller supplies >max_pages user URLs."""
        user_urls = [f"https://user{i}.test/doc" for i in range(9)]

        def fetch(u, timeout=20):
            return "# Page\n\n" + f"authoritative content from {u} " * 80

        with self.assertLogs("web_scraper", level="WARNING") as cm:
            notes = ws.gather(
                queries=[], urls=user_urls,
                env={"ADF_RESEARCH": "1", "ADF_SCRAPER": "none"},
                fetch=fetch, max_pages=8)

        warning_text = " ".join(cm.output)
        self.assertIn("9", warning_text)              # supplied count
        self.assertIn("8", warning_text)              # cap
        self.assertIn("1", warning_text)              # dropped count
        self.assertLessEqual(len(notes), 8)           # 9th URL never scraped

    def test_gather_no_warn_when_duplicates_collapse_under_cap(self):
        """9 copies of 1 URL collapse to 1 unique after dedup — no WARNING fires."""
        dup_urls = ["https://same.test/doc"] * 9

        with self.assertNoLogs("web_scraper", level="WARNING"):
            ws.gather(
                queries=[], urls=dup_urls,
                env={"ADF_RESEARCH": "1", "ADF_SCRAPER": "none"},
                fetch=lambda u, timeout=20: "# Same\n\n" + "content " * 80,
                max_pages=8)

    def test_gather_does_not_warn_when_user_urls_within_cap(self):
        """3 user URLs with max_pages=8: no WARNING should fire."""
        with self.assertNoLogs("web_scraper", level="WARNING"):
            ws.gather(
                queries=[], urls=["https://a.test/", "https://b.test/", "https://c.test/"],
                env={"ADF_RESEARCH": "1", "ADF_SCRAPER": "none"},
                fetch=lambda u, timeout=20: "# T\n\n" + "x " * 80,
                max_pages=8)

    def test_gather_does_not_warn_on_search_only_truncation(self):
        """0 user URLs + 12 search hits with max_pages=8: search trimming is silent."""
        def fetch(u, timeout=20):
            if "duckduckgo" in u:
                return "".join(f'<a href="https://h{i}.test/">r</a>' for i in range(12))
            return "# H\n\n" + "y " * 80

        with self.assertNoLogs("web_scraper", level="WARNING"):
            ws.gather(
                queries=["test query"], urls=[],
                env={"ADF_RESEARCH": "1", "ADF_SCRAPER": "none"},
                fetch=fetch, max_pages=8)


class RobotsCompliance(unittest.TestCase):
    """G17 — robots.txt awareness on the urllib FALLBACK path only."""

    def test_robots_disallow_blocks_fallback_fetch(self):
        def fetch(u, timeout=20):
            if u.endswith("/robots.txt"):
                return "User-agent: *\nDisallow: /docs/"
            return "<title>T</title><p>content</p>"

        result = ws.fetch_text("https://example.com/docs/guide",
                               {"ADF_SCRAPER": "none"}, fetch)
        self.assertIsNone(result)

    def test_robots_disallow_returns_none_not_exception(self):
        called = []

        def fetch(u, timeout=20):
            called.append(u)
            # robotparser matches the agent TOKEN before "/" (per RFC), so a site
            # targeting our crawler declares the bare product token "ADF-Research".
            if u.endswith("/robots.txt"):
                return "User-agent: ADF-Research\nDisallow: /"
            return "<title>T</title><p>content</p>"

        result = ws.fetch_text("https://example.com/page",
                               {"ADF_SCRAPER": "none"}, fetch)
        self.assertIsNone(result)
        self.assertNotIn("https://example.com/page", called)  # blocked GET never issued

    def test_robots_crawl_delay_is_respected(self):
        sleep_calls = []

        def fetch(u, timeout=20):
            if u.endswith("/robots.txt"):
                return "User-agent: *\nCrawl-delay: 3"
            return "<title>T</title><p>content</p>"

        result = ws.fetch_text("https://example.com/page",
                               {"ADF_SCRAPER": "none"}, fetch,
                               _sleep=lambda s: sleep_calls.append(s))
        self.assertIsNotNone(result)
        self.assertEqual(len(sleep_calls), 1)
        self.assertTrue(3 <= sleep_calls[0] <= 10)

    def test_robots_fetch_error_is_fail_open(self):
        def fetch(u, timeout=20):
            if u.endswith("/robots.txt"):
                raise Exception("network error")
            return "<title>T</title><p>content here</p>"

        result = ws.fetch_text("https://example.com/page",
                               {"ADF_SCRAPER": "none"}, fetch)
        self.assertIsNotNone(result)
        self.assertIn("content here", result["markdown"])

    def test_robots_not_checked_on_jina_primary_path(self):
        called = []

        def fetch(u, timeout=20):
            called.append(u)
            return "# Jina Page\n\n" + "non-thin markdown content here " * 80

        ws.fetch_text("https://example.com/page", {"ADF_SCRAPER": "jina"}, fetch)
        self.assertFalse([u for u in called if u.endswith("/robots.txt")],
                         "robots.txt must NOT be fetched on the primary Jina path")


if __name__ == "__main__":
    unittest.main()

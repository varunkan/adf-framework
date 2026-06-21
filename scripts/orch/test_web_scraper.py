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


if __name__ == "__main__":
    unittest.main()

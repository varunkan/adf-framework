#!/usr/bin/env python3
"""ADF web scraper — the requirements crew's Analyst tool: turn a URL or a search query
into a focused, CITED research note. Layered for robustness (the "best-in-class scraping
agent" + a powerful fallback):

  1. PRIMARY service — Jina Reader (`r.jina.ai`, free, JS-aware) or Firecrawl — returns
     clean, LLM-ready markdown. (`ADF_SCRAPER=jina|firecrawl|none`)
  2. FALLBACK — `urllib` GET + a stdlib HTML→text extractor (de-boilerplate) when no
     service / it fails.
  3. EXTRACT — a fast model (Llama-70B via `model_router` role 'extract') pulls the
     requirement-relevant facts so the note is focused, not raw HTML.

Gated `ADF_RESEARCH`; every layer degrades gracefully (never crashes the stage).
Injection-based (`fetch` + `complete` are injectable) so it's unit-testable offline.

  fetch_text(url, env, fetch)          -> {url, title, markdown} | None
  search(query, env, fetch)            -> [url, …]
  scrape(url, env, fetch, complete)    -> {url, title, facts, citations} | None
  gather(queries, urls, env, …)        -> [note, …]   (the research corpus)
"""
import html
import os
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser


def is_enabled(env=None):
    env = env if env is not None else os.environ
    return env.get("ADF_RESEARCH", "1").strip().lower() not in ("0", "false", "off")


_SSL = None


def _ssl_ctx():
    """Reuse agent_runner's SSL context — some Python builds (e.g. 3.15 here) lack a CA
    bundle, so a plain urlopen silently fails cert verification → 0 sources. agent_runner
    already solved this for the model APIs; share it."""
    global _SSL
    if _SSL is None:
        try:
            import agent_runner
            _SSL = agent_runner.ssl_context()
        except Exception:  # noqa: BLE001
            import ssl
            _SSL = ssl.create_default_context()
    return _SSL


def _http_get(url, timeout=20):
    """Plain GET → text, or None. The default fetcher (injectable in tests)."""
    req = urllib.request.Request(url, headers={"User-Agent": "ADF-Research/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except Exception:  # noqa: BLE001 — a dead URL must not crash research
        return None


class _Textify(HTMLParser):
    """Stdlib HTML→text: drop script/style/nav/footer, keep visible text + the title."""
    _SKIP = {"script", "style", "noscript", "nav", "footer", "header", "form", "svg"}

    def __init__(self):
        super().__init__()
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if self._in_title:
            self.title = (self.title + " " + text).strip()
        elif text:
            self.parts.append(text)


def _html_to_text(raw):
    p = _Textify()
    try:
        p.feed(raw)
    except Exception:  # noqa: BLE001
        pass
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(p.parts))
    return p.title, text


_BLOCKED = re.compile(r"\b(401|403|unauthorized|access denied|forbidden|captcha|"
                      r"are you a robot|reference #\w)\b", re.I)


def _is_thin(md, minlen=1200):
    """A scraping service can return a THIN block/401/JS-gated stub (e.g. Jina got 731
    chars of a 401 page from FDA.gov while a plain GET returned the full 44KB). Treat
    that as a miss so we fall back to the plain fetch, which often gets MORE."""
    if not md or len(md.strip()) < minlen:
        return True
    return bool(_BLOCKED.search(md[:400]))


def fetch_text(url, env=None, fetch=None):
    """Return {url, title, markdown} for a URL via the configured scraper, or None.
    Tries the service first; if it returns a THIN/blocked stub, falls back to a plain GET
    + stdlib de-boilerplate (which frequently retrieves more than a throttled service)."""
    env = env if env is not None else os.environ
    fetch = fetch or _http_get
    scraper = env.get("ADF_SCRAPER", "jina").strip().lower()

    if scraper == "jina":
        md = fetch("https://r.jina.ai/" + url)
        if md and not _is_thin(md):
            title = next((ln[2:].strip() for ln in md.splitlines()
                          if ln.startswith("# ")), url)
            return {"url": url, "title": title, "markdown": md.strip()}
    elif scraper == "firecrawl" and (env.get("FIRECRAWL_API_KEY") or "").strip():
        # firecrawl is POST-based; callers can inject; default GET path used in tests
        md = fetch("https://api.firecrawl.dev/v0/scrape?url=" + urllib.parse.quote(url))
        if md and md.strip():
            return {"url": url, "title": url, "markdown": md.strip()}

    raw = fetch(url)                              # fallback: plain GET + de-boilerplate
    if not raw or not raw.strip():
        return None
    title, text = _html_to_text(raw)
    return {"url": url, "title": title or url, "markdown": text}


def search(query, env=None, fetch=None, limit=5):
    """Return result URLs for a query. Tries DuckDuckGo's LITE endpoint (the HTML one now
    serves a bot challenge) and extracts external result links generically — tolerant to
    markup drift, decoding `uddg=` redirects. Keyless; empty on failure (the crew then
    relies on the planner's seed URLs + user-provided URLs). Degrades, never crashes."""
    env = env if env is not None else os.environ
    fetch = fetch or _http_get
    q = urllib.parse.quote(query)
    raw = (fetch("https://lite.duckduckgo.com/lite/?q=" + q)
           or fetch("https://html.duckduckgo.com/html/?q=" + q))
    if not raw:
        return []
    urls = []
    for href in re.findall(r'href="([^"]+)"', raw):
        href = html.unescape(href)
        m = re.search(r"[?&]uddg=([^&]+)", href)        # DDG redirect → real URL
        if m:
            url = urllib.parse.unquote(m.group(1))
        elif href.startswith("http"):
            url = href
        else:
            continue
        if url.startswith("http") and "duckduckgo.com" not in url and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def scrape(url, env=None, fetch=None, complete=None):
    """Fetch a URL and return a focused research note {url, title, facts, citations}.
    When a model `complete(prompt, role)` is given, a fast model extracts the
    requirement-relevant facts; otherwise the cleaned text is returned (truncated)."""
    page = fetch_text(url, env, fetch)
    if not page:
        return None
    body = page["markdown"][:12000]
    facts = body
    if complete is not None:
        res = complete(
            "Extract ONLY the facts, rules, constraints, and requirements relevant to "
            "building software for this domain, as terse bullet points. Ignore "
            f"navigation/marketing. Source: {page['title']} ({url})\n\n{body}",
            "extract")
        if res and res[0] and res[0].strip():
            facts = res[0].strip()
    return {"url": url, "title": page["title"], "facts": facts, "citations": [url]}


def gather(queries=None, urls=None, env=None, fetch=None, complete=None,
           per_query=3, max_pages=8):
    """The research corpus: search each query, fetch the top hits + any user-named URLs,
    and scrape each into a cited note. Returns [] when research is disabled or offline."""
    env = env if env is not None else os.environ
    if not is_enabled(env):
        return []
    seen, targets = set(), []
    for u in (urls or []):                         # user-named URLs first (authoritative)
        if u not in seen:
            seen.add(u)
            targets.append(u)
    for q in (queries or []):
        for u in search(q, env, fetch, limit=per_query):
            if u not in seen:
                seen.add(u)
                targets.append(u)
    notes = []
    for u in targets[:max_pages]:
        note = scrape(u, env, fetch, complete)
        if note:
            notes.append(note)
    return notes

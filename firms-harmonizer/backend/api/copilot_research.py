"""Bounded source retrieval: publisher metadata and first-party incident documents.

Search snippets are leads. DOI metadata identifies a publication, not a verified
incident cause. Only an excerpt actually present in retrieved official text may be
presented as an incident-specific reported explanation.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html import unescape
from html.parser import HTMLParser
import logging
import os
import re
from time import monotonic
import unicodedata
from urllib.parse import quote, urlparse

import httpx

from backend.api.cache import LRUCache
from backend.api.schemas import CitationReference

log = logging.getLogger(__name__)
SCIENCE_CACHE = LRUCache(32)
ARTICLE_CACHE = LRUCache(64)
OFFICIAL_DOMAINS = ("nasa.gov", "copernicus.eu", "comunidad.madrid", "madrid.org", "112.es",
    "aemet.es", "miteco.gob.es", "guardiacivil.es", "policia.es", "gov.br", "inpe.br",
    "argentina.gob.ar", "gov.ar", "floridadisaster.org", "fdacs.gov")
NEWS_DOMAINS = ("reuters.com", "apnews.com", "rtve.es", "efe.com", "europapress.es", "elpais.com",
    "bbc.com", "bbc.co.uk", "theguardian.com", "elconfidencial.com", "elmundo.es", "abc.es",
    "lavanguardia.com", "telemadrid.es", "g1.globo.com", "agenciabrasil.ebc.com.br")


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def source_tier(url: str) -> int:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return 0
        if host.endswith((".gov", ".gob.es")) or any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS):
            return 2
        if any(host == d or host.endswith("." + d) for d in NEWS_DOMAINS):
            return 1
    except ValueError:
        return 0
    return 0


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "noscript"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "article", "section", "div", "li") and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def official_article(citation: CitationReference) -> CitationReference:
    """No arbitrary hosts, redirects, cookies, unbounded bodies or model-supplied URLs."""
    if os.getenv("COPILOT_OFFLINE") == "1" or source_tier(citation.url or "") != 2:
        return citation
    cached = ARTICLE_CACHE.get(citation.url)
    if cached and monotonic() - cached[0] < 1800:
        return citation.model_copy(update={"relevance_note": cached[1], "dataset_or_doi": cached[2]})
    try:
        with httpx.Client(timeout=3.0, follow_redirects=False) as client:
            with client.stream("GET", citation.url, headers={"User-Agent": "FIRMS-Harmonizer/1.0 research assistant"}) as response:
                response.raise_for_status()
                if response.is_redirect or "text/html" not in response.headers.get("content-type", ""):
                    return citation
                body = bytearray()
                deadline = monotonic() + 3
                for chunk in response.iter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 256_000 or monotonic() > deadline:
                        return citation
        html = body.decode("utf-8", errors="replace")
        # Prefer the article or main element over navigation and unrelated footers.
        main = re.search(r"<(article|main)\b[^>]*>(.*?)</\1>", html, re.I | re.S)
        parser = ArticleText()
        parser.feed(main[2] if main else html)
        article = re.sub(r"[ \t]+", " ", unescape(" ".join(parser.parts))).strip()[:7000]
        if len(article) < 120:
            return citation
        # A first-party page still needs a location/date match before any causal use.
        note = "Retrieved official article text (location/date match must still be checked):\n" + article
        identifier = "Official report; article text retrieved; incident match unconfirmed"
        ARTICLE_CACHE.put(citation.url, (monotonic(), note, identifier))
        return citation.model_copy(update={"relevance_note": note, "dataset_or_doi": identifier})
    except (httpx.HTTPError, ValueError):
        log.info("Official incident article unavailable")
        return citation


def enrich_official_reports(citations: list[CitationReference]) -> list[CitationReference]:
    targets = [c for c in citations if source_tier(c.url or "") == 2][:3]
    if not targets or os.getenv("COPILOT_OFFLINE") == "1":
        return citations
    with ThreadPoolExecutor(max_workers=3) as executor:
        enriched = {c.id: result for c, result in zip(targets, executor.map(official_article, targets))}
    return [enriched.get(c.id, c) for c in citations]


def scientific_sources(question: str) -> list[CitationReference]:
    """Crossref is a bibliographic registry, never a detector of incident truth."""
    if os.getenv("COPILOT_OFFLINE") == "1":
        return []
    q = normalize(question)
    topic = ("wildfire remote sensing fire radiative power MODIS VIIRS" if re.search(r"\b(frp|fre|modis|viirs|energy|energia)\b", q)
             else "wildfire ignition causes fire weather drought wind")
    cached = SCIENCE_CACHE.get(topic)
    if cached and monotonic() - cached[0] < 3600:
        return cached[1]
    try:
        with httpx.Client(timeout=4.0) as client:
            response = client.get("https://api.crossref.org/works", params={"query.bibliographic": topic,
                "filter": "type:journal-article", "rows": 6},
                headers={"User-Agent": "FIRMS-Harmonizer/1.0 (scientific bibliography)"})
            response.raise_for_status()
            items = response.json()["message"]["items"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        log.info("Scientific bibliography provider unavailable")
        return []
    if not isinstance(items, list):
        return []
    sources = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("DOI"), str) or not isinstance(item.get("title"), list):
            continue
        doi = item.get("DOI", "").lower()
        title = unescape(re.sub(r"<[^>]+>", "", " ".join(item.get("title", []))))
        relation = item.get("relation") or {}
        if (item.get("type") != "journal-article" or not re.fullmatch(r"10\.\d{4,9}/\S+", doi)
                or doi in seen or item.get("update-to") or relation.get("is-retracted-by")
                or re.search(r"retract|withdrawn|correction|corrigendum|erratum", normalize(title))):
            continue
        if not re.search(r"wildfire|forest fire|vegetation fire|fire weather|fire danger|fire radiative|ignition", normalize(title)):
            continue
        parts = (item.get("published") or item.get("published-print") or item.get("published-online") or {}).get("date-parts", [])
        if not parts or not parts[0] or not isinstance(parts[0][0], int) or not 1900 <= parts[0][0] <= date.today().year:
            continue
        authors = ", ".join(a["family"] for a in item.get("author", [])[:3] if a.get("family")) or item.get("publisher", "Publisher metadata")
        journal = "; ".join(item.get("container-title", []))
        abstract = unescape(re.sub(r"<[^>]+>", " ", item.get("abstract", "")))[:1000]
        sources.append(CitationReference(id=f"[{7 + len(sources)}]", source_type="PEER_REVIEWED",
            title=title[:250], authors_or_agency=authors, year=parts[0][0],
            dataset_or_doi=f"{doi}; Crossref publication metadata; full text not reviewed", url="https://doi.org/" + quote(doi, safe="/"),
            relevance_note=f"Scientific background, not an investigation of the selected incident. Publication metadata verified through Crossref. {journal}. {abstract}"))
        seen.add(doi)
        if len(sources) == 3:
            break
    if sources:
        SCIENCE_CACHE.put(topic, (monotonic(), sources))
    return sources


def supported_ignition_excerpt(citation: CitationReference, quote_text: str, scope) -> bool:
    """An incident claim needs an exact official excerpt and explicit event place/date."""
    if "article text retrieved" not in citation.dataset_or_doi or source_tier(citation.url or "") != 2:
        return False
    quote_normalized = normalize(" ".join(quote_text.split()))
    article = normalize(" ".join(citation.relevance_note.split()))
    if not 5 <= len(quote_text.split()) <= 25 or quote_normalized not in article or re.search(r"https?://|[<>\[\]]", quote_text):
        return False
    if not re.search(r"caus|origin|ignit|provoc|rayo|lightning|negligen|intencion|arson|investig|desconoc", quote_normalized):
        return False
    if not scope.start or scope.start != scope.end:
        return False
    day = date.fromisoformat(scope.start)
    # No inferred incident date from a page publication timestamp or URL alone.
    explicit_dates = [day.isoformat(), f"{day.day:02}/{day.month:02}/{day.year}",
                      f"{day.day}/{day.month}/{day.year}"]
    spanish = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    import calendar
    explicit_dates += [f"{day.day} de {spanish[day.month-1]} de {day.year}",
                       f"{day.day} {calendar.month_name[day.month].lower()} {day.year}",
                       f"{calendar.month_name[day.month].lower()} {day.day}, {day.year}"]
    locality = normalize(scope.locality or scope.label)
    terms = [t for t in re.findall(r"[a-z]{4,}", locality) if t not in {"selected", "area", "near", "study", "envelope", "spain", "brazil"}]
    offset = article.find(quote_normalized)
    before = article[:offset].rstrip()
    after = article[offset + len(quote_normalized):].lstrip()
    if before and before[-1] not in ".!?:":
        return False
    if quote_normalized[-1] not in ".!?" and after and after[0] not in ".!?":
        return False
    nearby = article[max(0, offset - 500):offset + len(quote_normalized) + 500]
    return any(d in nearby for d in explicit_dates) and bool(terms) and any(t in nearby for t in terms)

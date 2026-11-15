"""Bounded source retrieval: publisher metadata and first-party incident documents.

Search snippets are leads. DOI metadata identifies a publication, not a verified
incident cause. Only an excerpt actually present in retrieved official text may be
presented as an incident-specific reported explanation.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html import unescape
from backend.api.copilot_network import is_offline

import logging
import os
import re
from time import monotonic
import unicodedata
from urllib.parse import quote, urlparse, urljoin

import httpx
from lxml import html as html_parser

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
    "lavanguardia.com", "telemadrid.es", "cadenaser.com", "euronews.com", "g1.globo.com", "agenciabrasil.ebc.com.br")


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def source_tier(url: str) -> int:
    if not isinstance(url, str):
        return 0
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


def google_search_reports(query: str) -> list[CitationReference]:
    """Discover source URLs with Google; model prose is never an article excerpt.

    Google search redirect URLs may be resolved once, without following the target.
    Only independently approved HTTPS publishers enter the existing article reader.
    Google inference and redirect discovery share one twelve-second deadline.
    Publisher/redirect reads retain a maximum four-second timeout.
    """
    key = os.getenv('GEMINI_API_KEY')
    if is_offline() or not key:
        return []
    deadline = monotonic() + 12.0
    reports = []
    seen = set()
    try:
        with httpx.Client(timeout=12.0, follow_redirects=False) as client:
            response = client.post(
                'https://generativelanguage.googleapis.com/v1beta/models/'
                + os.getenv('GEMINI_MODEL', 'gemini-3.8-flash') + ':generateContent',
                headers={'x-goog-api-key': key},
                json={'contents': [{'parts': [{'text':
                    'Find primary official incident reports and reputable reporting for this place and period. '
                    'Return relevant source links, prioritizing official agencies. Query: '+query[:800]}]}],
                    'tools': [{'google_search': {}}], 'generationConfig': {'maxOutputTokens': 600, 'thinkingConfig': {'thinkingLevel': 'low'}}})
            response.raise_for_status()
            candidate = response.json().get('candidates', [{}])[0]
            chunks = candidate.get('groundingMetadata', {}).get('groundingChunks', [])
            for chunk in chunks[:8]:
                web = chunk.get('web', {})
                url = web.get('uri', '')
                parsed = urlparse(url)
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                if (parsed.scheme == 'https' and parsed.hostname == 'vertexaisearch.cloud.google.com'
                        and parsed.path.startswith('/grounding-api-redirect/')
                        and not parsed.username and not parsed.password and parsed.port in (None, 443)):
                    redirect = client.get(url, timeout=min(4.0, remaining))
                    url = urljoin(url, redirect.headers.get('location', '')) if redirect.is_redirect else ''
                tier = source_tier(url)
                if not tier or url in seen:
                    continue
                seen.add(url)
                reports.append(CitationReference(id=f'[W{len(reports)+1}]',
                    source_type='WEB_NEWS_REPORT',
                    title=str(web.get('title') or urlparse(url).hostname)[:240],
                    authors_or_agency=urlparse(url).hostname, year=date.today().year,
                    dataset_or_doi='Google Search source lead; article and incident match not yet verified',
                    url=url, relevance_note='Discovered through Google grounding metadata. '
                    'Search-generated prose is not a quotation or independently verified incident evidence.'))
                if len(reports) == 5:
                    break
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError, IndexError):
        log.info('Google source discovery unavailable; retained %s approved leads', len(reports))
    return reports


def official_article(citation: CitationReference) -> CitationReference:
    """No arbitrary hosts, redirects, cookies, unbounded bodies or model-supplied URLs."""
    if is_offline() or source_tier(citation.url or "") == 0:
        return citation
    cached = ARTICLE_CACHE.get(citation.url)
    if cached and monotonic() - cached[0] < 1800:
        return citation.model_copy(update={"relevance_note": cached[1], "dataset_or_doi": cached[2]})
    try:
        with httpx.Client(timeout=4.0, follow_redirects=False) as client:
            url = citation.url
            for attempt in range(3):
                with client.stream("GET", url, headers={"User-Agent": "FIRMS-Harmonizer/1.0 research assistant"}) as response:
                    if response.is_redirect:
                        target = urljoin(url, response.headers.get("location", ""))
                        if attempt == 2 or not research_host_allowed(target):
                            return citation
                        url = target
                        continue
                    response.raise_for_status()
                    if "text/html" not in response.headers.get("content-type", ""):
                        return citation
                    body = bytearray()
                    deadline = monotonic() + 4
                    for chunk in response.iter_bytes(chunk_size=8192):
                        body.extend(chunk)
                        if len(body) >= 1_000_000 or monotonic() > deadline:
                            break
                    break
            else:
                return citation
        encoding = re.search(br'charset=["\']?([a-zA-Z0-9_-]+)', bytes(body[:8192]))
        codec = encoding[1].decode('ascii') if encoding else 'utf-8'
        try:
            html = body.decode(codec, errors='replace')
        except LookupError:
            html = body.decode('utf-8', errors='replace')
        if html.count('�') > 3:
            html = body.decode('cp1252', errors='replace')
        # Prefer the article or main element over navigation and unrelated footers.
        tree = html_parser.fromstring(html, parser=html_parser.HTMLParser(no_network=True))
        for node in tree.xpath('//script|//style|//nav|//footer|//header|//aside|//form|//noscript'):
            node.drop_tree()
        bodies = tree.xpath('//*[contains(@class,"field--name-body") or @itemprop="articleBody" or contains(@class,"article__body") or contains(@class,"article-body")]')
        bodies = bodies or tree.xpath('//article') or tree.xpath('//main') or [tree]
        chosen = max(bodies, key=lambda node: len(node.text_content()))
        article = re.sub(r'[ \t]+', ' ', chosen.text_content()).strip()[:14000]
        if len(article) < 120:
            return citation
        # A first-party page still needs a location/date match before any causal use.
        note = "Retrieved article text (location/date match must still be checked):\n" + article
        identifier = ("Official report" if source_tier(citation.url or "") == 2 else "News report") + "; article text retrieved; incident match unconfirmed"
        ARTICLE_CACHE.put(citation.url, (monotonic(), note, identifier))
        return citation.model_copy(update={"relevance_note": note, "dataset_or_doi": identifier})
    except (httpx.HTTPError, ValueError, html_parser.etree.ParserError):
        log.info("Official incident article unavailable")
        return citation


def enrich_official_reports(citations: list[CitationReference]) -> list[CitationReference]:
    official = [c for c in citations if source_tier(c.url or "") == 2]
    news = [c for c in citations if source_tier(c.url or "") == 1]
    distinct_news = []
    hosts = set()
    for citation in news:
        host = urlparse(citation.url).hostname.removeprefix("www.")
        if host not in hosts:
            distinct_news.append(citation)
            hosts.add(host)
    targets = official[:2] + distinct_news[:2]
    targets += [c for c in official[2:] + news[2:] if c not in targets][:4-len(targets)]
    if not targets or is_offline():
        return citations
    with ThreadPoolExecutor(max_workers=4) as executor:
        enriched = {c.id: result for c, result in zip(targets, executor.map(official_article, targets))}
    return [enriched.get(c.id, c) for c in citations]


def scientific_sources(question: str) -> list[CitationReference]:
    """Crossref is a bibliographic registry, never a detector of incident truth."""
    if is_offline():
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
        if not isinstance(item, dict) or not isinstance(item.get("DOI"), str) or not isinstance(item.get("title"), list) or not all(isinstance(t, str) for t in item["title"]):
            continue
        doi = item.get("DOI", "").lower()
        title = unescape(re.sub(r"<[^>]+>", "", " ".join(item.get("title", []))))
        relation = item.get("relation") or {}
        if not isinstance(relation, dict):
            continue
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
        sources.append(CitationReference(id=f"[{7 + len(sources)}]", source_type="PEER_REVIEWED",
            title=title[:250], authors_or_agency=authors, year=parts[0][0],
            dataset_or_doi=f"{doi}; Crossref publication metadata; full text not reviewed", url="https://doi.org/" + quote(doi, safe="/"),
            relevance_note=f"Scientific background, not an investigation of the selected incident. Publication metadata verified through Crossref. {journal}. Full text not reviewed."))
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


def research_host_allowed(url: str) -> bool:
    return source_tier(url) > 0


def supported_report_excerpt(citation: CitationReference, excerpt: str, scope) -> bool:
    """Validate attributed regional reporting without equating it with a satellite cell."""
    if "article text retrieved" not in citation.dataset_or_doi or not source_tier(citation.url or ""):
        return False
    if not isinstance(excerpt, str) or not 5 <= len(excerpt.split()) <= 80 or re.search(r"https?://|[<>\[\]]", excerpt):
        return False
    text = normalize(" ".join(citation.relevance_note.split()))
    exact = normalize(" ".join(excerpt.split()))
    offset = text.find(exact)
    if offset < 0:
        return False
    before, after = text[:offset].rstrip(), text[offset+len(exact):].lstrip()
    paragraph_start = any(normalize(line.strip()).startswith(exact) for line in citation.relevance_note.splitlines())
    if before and before[-1] not in ".!?:" and not paragraph_start:
        return False
    if exact[-1] not in ".!?" and after and after[0] not in ".!?":
        return False
    terms = set(re.findall(r"[a-z]{4,}", normalize(scope.locality or scope.label))) - {"selected", "area", "study", "envelope", "near", "spain", "brazil"}
    if {'sierra', 'oeste'} <= terms:
        terms |= {'madrid', 'san martin de valdeiglesias', 'villa del prado', 'robledo de chavela'}
    if not terms or not any(t in text for t in terms) or not scope.start or not scope.end:
        return False
    # Explicit article dates can occur in the article header rather than beside each sentence.
    iso = re.findall(r"20\d{2}[-/]\d{2}[-/]\d{2}", text + " " + (citation.url or ""))
    if any(scope.start <= value.replace("/", "-") <= scope.end for value in iso):
        return True
    url_date = re.search(r"(20\d{2})(\d{2})(\d{2})", citation.url or "")
    if url_date and scope.start <= "-".join(url_date.groups()) <= scope.end:
        return True
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    for number, month in enumerate(months, 1):
        for match in re.finditer(rf"\b(\d{{1,2}})\s+(?:de\s+)?{month}\s+(?:de\s+)?(20\d{{2}})\b", text):
            try:
                event_date = date(int(match[2]), number, int(match[1])).isoformat()
            except ValueError:
                continue
            if scope.start <= event_date <= scope.end:
                return True
    return False


def incident_passages(citation: CitationReference, scope) -> list[str]:
    """Select verbatim regional passages before generation, excluding liveblog detours."""
    if 'article text retrieved' not in citation.dataset_or_doi:
        return []
    terms = set(re.findall(r'[a-z]{4,}', normalize(scope.locality or scope.label))) - {'selected','area','near','study','envelope','spain','brazil'}
    if 'madrid' in terms or {'sierra','oeste'} <= terms:
        terms |= {'madrid','sierra oeste','san martin de valdeiglesias','villa del prado','robledo de chavela','almorox'}
    content = citation.relevance_note.split(':\n',1)[-1]
    sentences = [sentence for paragraph in content.splitlines() if paragraph.strip() for sentence in re.split(r'(?<=[.!?])\s+', paragraph)]
    single_official = source_tier(citation.url or "") == 2 and any(t in normalize(citation.title) for t in terms) and bool(re.search(r"20\d{2}/\d{2}/\d{2}", citation.url or ""))
    passages = [part.strip() for part in sentences if 5 <= len(part.split()) <= 80
            and (single_official or any(t in normalize(part) for t in terms))
            and re.search(r'incendi|fuego|frente|viento|fire|wind|burn', normalize(part))]
    return sorted(passages, key=lambda p: -len(re.findall(r'viento|temperatur|humedad|confluencia|propag|origin|causa|investig|wind|humidity|spread', normalize(p))))[:8]


def indexed_sources(scope) -> list[CitationReference]:
    """Curated source URLs supplement discovery; answers still require fetched evidence."""
    import json
    from pathlib import Path
    if is_offline() or not scope.start or not scope.end:
        return []
    entries=json.loads((Path(__file__).resolve().parents[2]/'data/copilot_sources.json').read_text())
    locality=normalize((scope.locality or '')+' '+scope.label)
    results=[]
    for item in entries:
        if not scope.start <= item['report_date'] <= scope.end or not any(normalize(p) in locality for p in item['localities']):
            continue
        if not source_tier(item['url']):
            continue
        results.append(CitationReference(id=f'[W{100+len(results)}]',source_type='WEB_NEWS_REPORT',title=item['title'],
            authors_or_agency=item['agency'],year=int(item['report_date'][:4]),url=item['url'],
            dataset_or_doi='Official report; curated URL; content must be retrieved',
            relevance_note='Official incident report discovered and indexed for its stated place and publication date. Content is not inferred from this index.'))
    return results

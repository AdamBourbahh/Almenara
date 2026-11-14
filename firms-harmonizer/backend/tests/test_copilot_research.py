"""Trusted-source retrieval, honest causal answers and citation evidence checks."""
import json

import httpx
import pytest

from backend.api import copilot_research as research, fire_copilot as copilot
from backend.api.schemas import CitationReference, ExplainSpikeRequest
from backend.tests.test_explain_spike import real_archive


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("COPILOT_OFFLINE", "1")
    research.SCIENCE_CACHE.clear()
    research.ARTICLE_CACHE.clear()


def official(note=None):
    return CitationReference(id="[W1]", source_type="WEB_NEWS_REPORT", title="Madrid incident investigation",
        authors_or_agency="comunidad.madrid", year=2026,
        url="https://www.comunidad.madrid/noticias/madrid-incendio",
        dataset_or_doi="Official report; article text retrieved; incident match unconfirmed",
        relevance_note=note or "Retrieved official article text: Madrid. 24 de julio de 2026. La causa del incendio permanece bajo investigación.")


def test_attached_madrid_aoi_and_day_are_not_broadened(real_archive):
    coordinates = [[[-4.25,40.35],[-4.15,40.35],[-4.15,40.45],[-4.25,40.45],[-4.25,40.35]]]
    req = ExplainSpikeRequest(aoi={"coordinates": coordinates}, region_name="Selected area",
        period_start="2026-07-24", period_end="2026-07-24", user_question="por que sucedio ese incendio en madrid")
    result = copilot.answer(req)
    assert result.map_context.aoi.coordinates == coordinates
    assert result.map_context.period_start == result.map_context.period_end == "2026-07-24"
    text = result.explanation_markdown
    assert text.startswith("### Answer")
    assert "**2 satellite detections**" in text
    assert "ignition cause is **not verified" in text
    assert "Days with the most detections" not in text
    assert "MW" not in text
    assert {c.id for c in result.citations} == {"[2]", "[3]", "[5]"}


def test_annual_causal_question_asks_for_incident_day_without_guessing_peak(real_archive):
    result = copilot.answer(ExplainSpikeRequest(user_question="Why did that Madrid fire happen?",
        period_start="2026-01-01", period_end="2026-12-31"))
    assert "**365 days**" in result.explanation_markdown
    assert "Select the incident's day" in result.explanation_markdown
    assert result.map_context.period_start == "2026-01-01"
    assert result.map_context.period_end == "2026-12-31"
    assert "busiest" not in result.explanation_markdown
    assert "| Date" not in result.explanation_markdown


def test_supported_official_quote_is_preserved_with_its_uncertainty(real_archive, monkeypatch):
    monkeypatch.setattr(copilot, "search_reports", lambda scope: ([official()], "official search"))
    payload = {"claims": [{"source_id": "[W1]", "quote": "La causa del incendio permanece bajo investigación."}]}
    monkeypatch.setattr(copilot, "complete", lambda *a, **k: (json.dumps(payload), "test-extractor"))
    result = copilot.answer(ExplainSpikeRequest(user_question="Why did the Madrid fire happen on 24 July 2026?"))
    assert result.physical_classification == "OFFICIAL_INVESTIGATION_EXCERPT"
    assert "bajo investigación" in result.explanation_markdown
    assert "confirmed cause" not in result.explanation_markdown
    assert "[W1]" in result.explanation_markdown


@pytest.mark.parametrize("quote", ["The fire was caused by arson.", "el incendio fue provocado.", "https://evil.example cause of fire"])
def test_invented_or_negation_truncated_causal_quotes_are_rejected(real_archive, monkeypatch, quote):
    source = official("Retrieved official article text: Madrid. 24 de julio de 2026. Las autoridades no han confirmado que el incendio fue provocado.")
    monkeypatch.setattr(copilot, "search_reports", lambda scope: ([source], "official search"))
    monkeypatch.setattr(copilot, "complete", lambda *a, **k: (json.dumps({"claims": [{"source_id":"[W1]", "quote":quote}]}), "test"))
    result = copilot.answer(ExplainSpikeRequest(user_question="Why did the Madrid fire happen on 24 July 2026?"))
    assert result.physical_classification == "CAUSE_NOT_VERIFIED"
    assert "Official investigation\n" not in result.explanation_markdown
    assert "arson" not in result.explanation_markdown


def test_official_quote_needs_event_date_and_locality_not_just_publication_year():
    scope = copilot.resolve_scope(ExplainSpikeRequest(user_question="Madrid 24 July 2026"))
    quote = "La causa del incendio permanece bajo investigación."
    assert research.supported_ignition_excerpt(official(), quote, scope)
    assert not research.supported_ignition_excerpt(official("Madrid. 2026. " + quote), quote, scope)
    assert not research.supported_ignition_excerpt(official("Barcelona. 24 de julio de 2026. " + quote), quote, scope)
    assert not research.supported_ignition_excerpt(official().model_copy(update={"dataset_or_doi":"Official report; snippet only"}), quote, scope)


@pytest.mark.parametrize("url,tier", [
    ("https://www.comunidad.madrid/noticias/fire", 2),
    ("https://earthobservatory.nasa.gov/fire", 2),
    ("https://www.rtve.es/noticias/fire", 1),
    ("https://comunidad.madrid.evil.example/fire", 0),
    ("https://rtve.es@evil.example/fire", 0),
    ("http://127.0.0.1/fire", 0),
    ("https://random-fire-blog.example/rumor", 0),
])
def test_report_sources_require_real_trusted_hosts(url, tier):
    assert research.source_tier(url) == tier


def test_filter_prefers_official_reports_and_drops_unrecognized_blogs():
    scope = copilot.resolve_scope(ExplainSpikeRequest(user_question="Madrid 24 July 2026"))
    results = [{"title":"Madrid incendio July 2026", "body":"Madrid fire report in July 2026", "href":url}
        for url in ["https://rumor.example/fire", "https://rtve.es/fire", "https://comunidad.madrid/fire"]]
    sources = copilot.filter_reports(scope, results)
    assert [s.url for s in sources] == ["https://comunidad.madrid/fire", "https://rtve.es/fire"]
    assert sources[0].dataset_or_doi.startswith("Official report")


def test_crossref_metadata_does_not_become_incident_evidence(monkeypatch):
    monkeypatch.delenv("COPILOT_OFFLINE")
    article = {"type":"journal-article", "DOI":"10.1234/fire.2020", "title":["Wildfire ignition and fire weather"],
        "published":{"date-parts":[[2020]]}, "author":[{"family":"Researcher"}], "container-title":["Fire research"]}
    items = [article, {**article, "DOI":"invented"}, {**article, "DOI":"10.1234/retracted", "relation":{"is-retracted-by":[{}]}},
        {**article, "DOI":"10.1234/correction", "title":["Correction: wildfire study"]}, {**article, "DOI":"10.1234/restaurants", "title":["Madrid restaurants"]}]
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"message":{"items":items}})
    factory = httpx.Client
    monkeypatch.setattr(research.httpx, "Client", lambda **kw: factory(transport=httpx.MockTransport(handle), **kw))
    sources = research.scientific_sources("Why did the Madrid fire occur?")
    assert len(sources) == 1
    assert sources[0].url == "https://doi.org/10.1234/fire.2020"
    assert "not an investigation" in sources[0].relevance_note
    assert "full text not reviewed" in sources[0].dataset_or_doi
    assert requests[0].url.host == "api.crossref.org"
    assert research.scientific_sources("Cause of wildfire?") == sources
    assert len(requests) == 1


def test_offline_research_never_calls_any_provider(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("Offline research cannot make network requests")
    monkeypatch.setattr(research.httpx, "Client", forbidden)
    assert research.scientific_sources("Wildfire causes") == []
    assert research.official_article(official()) == official()


def test_article_retrieval_extracts_only_text_and_refuses_redirects(monkeypatch):
    monkeypatch.delenv("COPILOT_OFFLINE")
    factory = httpx.Client
    html = "<html><nav>Unrelated rumor</nav><main><p>Madrid. 24 de julio de 2026.</p><p>" + "La causa del incendio permanece bajo investigación. " * 4 + "</p><script>invented cause</script></main></html>"
    def handle(request):
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location":"https://evil.example"})
        return httpx.Response(200, text=html, headers={"content-type":"text/html"})
    monkeypatch.setattr(research.httpx, "Client", lambda **kw: factory(transport=httpx.MockTransport(handle), **kw))
    result = research.official_article(official())
    assert "article text retrieved" in result.dataset_or_doi
    assert "invented cause" not in result.relevance_note
    assert "Unrelated rumor" not in result.relevance_note
    redirect = official().model_copy(update={"url":"https://comunidad.madrid/redirect"})
    assert research.official_article(redirect) == redirect

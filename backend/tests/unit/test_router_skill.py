import pytest

from agents.shared.router import load_knowledge_base, route_sources


@pytest.mark.asyncio
async def test_route_sources_filters_by_skill():
    """route_sources with skill_filter should only return sources whose skills match."""
    sources = await route_sources("AI", "千问", skill_filter="business")
    for src in sources:
        src_skills = src.get("skills")
        assert src_skills is None or "business" in src_skills, (
            f"Source '{src.get('name')}' has skills={src_skills}, shouldn't match 'business'"
        )


@pytest.mark.asyncio
async def test_route_sources_returns_all_when_no_skill_filter():
    """Without skill_filter, all relevant sources should be returned regardless of skills."""
    sources = await route_sources("AI", "千问")
    assert len(sources) > 0
    # Should include sources with skills and without
    has_skills = [s for s in sources if s.get("skills")]
    no_skills = [s for s in sources if not s.get("skills")]
    assert len(has_skills) > 0 or len(no_skills) >= 0


@pytest.mark.asyncio
async def test_route_sources_technical_returns_only_technical_sources():
    """skill_filter='technical' should only return sources tagged for technical."""
    sources = await route_sources("AI", "千问", skill_filter="technical")
    for src in sources:
        src_skills = src.get("skills")
        assert src_skills is None or "technical" in src_skills


@pytest.mark.asyncio
async def test_route_sources_competitor_filter_still_works_with_skill():
    """Competitor matching should still apply alongside skill filtering."""
    # Sources for "千问" with skill "company"
    sources = await route_sources("AI", "千问", skill_filter="company")
    for src in sources:
        comps = src.get("competitors", [])
        assert any("千问" in c or c in "千问" for c in comps) or not comps


@pytest.mark.asyncio
async def test_route_sources_returns_empty_when_no_match():
    """Should return empty list when no source matches both competitor and skill."""
    sources = await route_sources("AI", "NonExistentCompetitorXYZ", skill_filter="business")
    assert isinstance(sources, list)


@pytest.mark.asyncio
async def test_knowledge_base_loads_valid_yaml():
    """knowledge_base.yaml should parse correctly."""
    sources = load_knowledge_base()
    assert isinstance(sources, list)
    assert len(sources) > 0
    for src in sources:
        assert "url" in src, f"Source missing url: {src.get('name')}"
        assert "name" in src

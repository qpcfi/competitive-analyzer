# Competitor Discovery via Web Evidence and LLM

## Context

`GET /api/v1/competitor-recommendations` currently calls
`agents.orchestrator.discover_competitors()`. The existing behavior asks the
model to invent competitor names first, then falls back to simple search-result
title/snippet matching. This is too weak for real competitor discovery because
it can confuse ranking pages, repositories, and article titles with actual
products.

## Requirements

- Discover competitors from public web evidence for a user-provided domain.
- Search the web, fetch relevant result pages, clean their page content, and
  ask the LLM to identify competitor products or companies from that evidence.
- If no LLM is configured, fail explicitly instead of returning heuristic
  guesses.
- Preserve the current frontend response shape: route items expose `name` and
  `reason`.
- Keep external calls bounded with limits, timeouts, and partial failure
  tolerance.
- Keep behavior covered by unit tests.

## Architecture

`services.web_search` will remain the low-level public-web utility module. It
will keep DuckDuckGo HTML search parsing and add page fetching helpers that
return normalized page evidence:

- search result title, URL, and snippet
- fetched page title
- cleaned text excerpt with scripts, styles, and navigation noise removed
- degraded fetch error when a page cannot be fetched

`agents.orchestrator.discover_competitors()` will become an evidence-driven
workflow:

1. Validate the domain.
2. Require `llm`; if absent, raise `CompetitorDiscoveryUnavailable`.
3. Build search queries such as `<domain> competitors products`,
   `<domain> alternatives`, and `<domain> market vendors`.
4. Search each query with small limits and deduplicate URLs.
5. Fetch a bounded number of pages and extract text snippets.
6. If no usable evidence remains, raise `CompetitorDiscoveryUnavailable`.
7. Ask the LLM to return only JSON competitor candidates with:
   `name`, `reason`, `source_urls`, and `confidence`.
8. Parse, normalize, deduplicate, and filter invalid candidate names.
9. Return the top names to existing orchestrator callers.

The route will catch `CompetitorDiscoveryUnavailable` and return HTTP 503 with
a clear detail message. Successful responses keep the existing `items` array.
Reasons should be generated from the LLM candidate reason when available, with a
generic evidence-backed reason as fallback.

## Data Flow

```text
domain
  -> search queries
  -> DuckDuckGo SearchResult[]
  -> fetched PageEvidence[]
  -> LLM prompt with bounded evidence excerpts
  -> JSON candidate list
  -> normalized route response
```

## Error Handling

- Missing or empty domain remains a 400 from the route.
- Missing LLM configuration becomes 503.
- Search failures become 503 if no other query yields evidence.
- Individual page fetch failures are retained as degraded evidence but do not
  fail the whole discovery if other pages are usable.
- Invalid model JSON becomes 503, because guessing is explicitly disallowed.

## Testing

Unit tests will cover:

- no LLM raises `CompetitorDiscoveryUnavailable`
- search results are deduplicated before page fetch
- fetched page text is included in the LLM prompt
- JSON candidate parsing filters invalid names and preserves reasons
- no usable evidence raises `CompetitorDiscoveryUnavailable`
- route maps discovery unavailability to HTTP 503

Existing tests for search-result parsing and name normalization should keep
passing, with updates where the public API changes from name-only internals to
candidate-aware internals.

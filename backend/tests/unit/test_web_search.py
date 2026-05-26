from services.web_search import parse_duckduckgo_results


def test_parse_duckduckgo_results_extracts_title_url_and_snippet():
    html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://example.com/pricing">Example Pricing</a>
          <a class="result__snippet">Official pricing and feature details.</a>
        </div>
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fvendor.com%2Fdocs">Vendor Docs</a>
          <div class="result__snippet">Technical documentation for API limits.</div>
        </div>
      </body>
    </html>
    """

    results = parse_duckduckgo_results(html, query="example pricing")

    assert [item.title for item in results] == ["Example Pricing", "Vendor Docs"]
    assert [item.url for item in results] == ["https://example.com/pricing", "https://vendor.com/docs"]
    assert results[0].snippet == "Official pricing and feature details."
    assert results[1].query == "example pricing"

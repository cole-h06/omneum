import json

from pathlib import Path

from verity import Assertion


def search_agent():

    results = json.loads(
        Path(
            "examples/multi_agent/data/search_results.json"
        ).read_text()
    )

    # In a production workflow, a search agent would
    # retrieve search results, then use an LLM to extract
    # structured assertions. They're hardcoded here to
    # keep the example deterministic and focused on
    # Verity's inference pipeline.
    #
    # `results` is intentionally unused because this
    # example is intended to demonstrate the interface between an
    # agent and Verity, not the extraction process.

    _ = results

    return [

        Assertion(
            source="search_agent",
            entity="gpt-5.6-sol",
            attribute="context_window_tokens",
            value=256000
        ),

        Assertion(
            source="search_agent",
            entity="gpt-5.6-sol",
            attribute="recommended_endpoint",
            value="/v1/responses"
        ),

        Assertion(
            source="search_agent",
            entity="gpt-5.6-sol",
            attribute="supports_web_search",
            value=True
        ),

        Assertion(
            source="search_agent",
            entity="gpt-5.6-sol",
            attribute="supports_file_search",
            value=True
        ),

        Assertion(
            source="search_agent",
            entity="gpt-5.6-sol",
            attribute="supports_mcp_tools",
            value=True
        ),

        Assertion(
            source="search_agent",
            entity="gpt-5.6-sol",
            attribute="reasoning_effort_levels",
            value="low,medium,high,xhigh,max"
        )

    ]
import json

from pathlib import Path

from verity import Assertion


def api_agent():

    response = json.loads(
        Path(
            "examples/multi_agent/data/vendor_api.json"
        ).read_text()
    )

    # In a production workflow, an API client would
    # retrieve this response and construct structured
    # assertions from it. They're hardcoded here to
    # keep the example deterministic and focused on
    # Verity's inference pipeline.
    #
    # `response` is intentionally unused because this
    # example is intended to demonstrate the interface between an
    # agent and Verity, not the extraction process.

    _ = response

    return [

        Assertion(
            source="api_agent",
            entity="gpt-5.6-sol",
            attribute="context_window_tokens",
            value=1050000
        ),

        Assertion(
            source="api_agent",
            entity="gpt-5.6-sol",
            attribute="max_output_tokens",
            value=128000
        ),

        Assertion(
            source="api_agent",
            entity="gpt-5.6-sol",
            attribute="recommended_endpoint",
            value="/v1/responses"
        ),

        Assertion(
            source="api_agent",
            entity="gpt-5.6-sol",
            attribute="supports_web_search",
            value=True
        ),

        Assertion(
            source="api_agent",
            entity="gpt-5.6-sol",
            attribute="supports_file_search",
            value=True
        ),

        Assertion(
            source="api_agent",
            entity="gpt-5.6-sol",
            attribute="supports_structured_outputs",
            value=True
        )

    ]
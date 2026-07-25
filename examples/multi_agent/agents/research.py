from pathlib import Path

from verity import Assertion


def research_agent():

    document = Path(
        "examples/multi_agent/data/openai_docs.md"
    ).read_text()

    # In a production workflow, an LLM would extract
    # structured assertions from the document. They're
    # hardcoded here to keep the example deterministic
    # and focused on Verity's inference pipeline.
    #
    # `document` is intentionally unused because this
    # example is intended to demonstrate the interface between an
    # agent and Verity, not the extraction process.

    _ = document

    return [

        Assertion(
            source="research_agent",
            entity="gpt-5.6-sol",
            attribute="context_window_tokens",
            value=1050000
        ),

        Assertion(
            source="research_agent",
            entity="gpt-5.6-sol",
            attribute="max_output_tokens",
            value=128000
        ),

        Assertion(
            source="research_agent",
            entity="gpt-5.6-sol",
            attribute="recommended_endpoint",
            value="/v1/responses"
        ),

        Assertion(
            source="research_agent",
            entity="gpt-5.6-sol",
            attribute="supports_web_search",
            value=True
        ),

        Assertion(
            source="research_agent",
            entity="gpt-5.6-sol",
            attribute="supports_file_search",
            value=True
        ),

        Assertion(
            source="research_agent",
            entity="gpt-5.6-sol",
            attribute="supports_structured_outputs",
            value=True
        )

    ]
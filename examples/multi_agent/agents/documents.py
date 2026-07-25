from pathlib import Path

from verity import Assertion


def documents_agent():

    document = Path(
        "examples/multi_agent/data/company_policy.md"
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
            source="documents_agent",
            entity="gpt-5.6-sol",
            attribute="recommended_endpoint",
            value="/v1/responses"
        ),

        Assertion(
            source="documents_agent",
            entity="gpt-5.6-sol",
            attribute="reasoning_effort",
            value="high"
        ),

        Assertion(
            source="documents_agent",
            entity="gpt-5.6-sol",
            attribute="context_window_tokens",
            value=1050000
        ),

        Assertion(
            source="documents_agent",
            entity="gpt-5.6-sol",
            attribute="supports_function_calling",
            value=True
        ),

        Assertion(
            source="documents_agent",
            entity="gpt-5.6-sol",
            attribute="supports_web_search",
            value=True
        ),

        Assertion(
            source="documents_agent",
            entity="gpt-5.6-sol",
            attribute="supports_file_search",
            value=True
        ),

        Assertion(
            source="documents_agent",
            entity="gpt-5.6-sol",
            attribute="supports_mcp_tools",
            value=True
        )

    ]
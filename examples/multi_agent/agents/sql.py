import json

from pathlib import Path

from verity import Assertion


def sql_agent():

    rows = json.loads(
        Path(
            "examples/multi_agent/data/sql_rows.json"
        ).read_text()
    )

    # In a production workflow, a database query would
    # return these rows and the agent would construct
    # structured assertions from the returned result set. They're
    # hardcoded here to keep the example deterministic
    # and focused on Verity's inference pipeline.
    #
    # `rows` is intentionally unused because this
    # example is intended to demonstrate the interface between an
    # agent and Verity, not the extraction process.

    _ = rows

    return [

        Assertion(
            source="sql_agent",
            entity="gpt-5.6-sol",
            attribute="context_window_tokens",
            value=1050000
        ),

        Assertion(
            source="sql_agent",
            entity="gpt-5.6-sol",
            attribute="max_output_tokens",
            value=128000
        ),

        Assertion(
            source="sql_agent",
            entity="gpt-5.6-sol",
            attribute="recommended_endpoint",
            value="/v1/responses"
        ),

        Assertion(
            source="sql_agent",
            entity="gpt-5.6-sol",
            attribute="reasoning_effort",
            value="high"
        ),

        Assertion(
            source="sql_agent",
            entity="gpt-5.6-sol",
            attribute="supports_structured_outputs",
            value=True
        )

    ]
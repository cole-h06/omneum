from verity import (CredibilityGraph, VerityClient,)

from agents.api import api_agent
from agents.search import search_agent
from agents.documents import documents_agent
from agents.research import research_agent
from agents.sql import sql_agent


def main():

    client = VerityClient(
        endpoint="https://verity.example.com"
    )

    graph = CredibilityGraph()

    graph.add_assertions(
        research_agent()
    )

    graph.add_assertions(
        api_agent()
    )

    graph.add_assertions(
        search_agent()
    )

    graph.add_assertions(
        documents_agent()
    )

    graph.add_assertions(
        sql_agent()
    )

    result = client.infer_credibility(graph)

    print("\nSource Credibility\n")

    for source in result.sources:

        print(
            f"{source.name}: {source.score:.3f}"
        )

    print("\nClaim Support\n")

    for claim in result.claims:

        print(
            f"{claim.entity}.{claim.attribute} = "
            f"{claim.value} "
            f"({claim.support:.3f})"
        )


if __name__ == "__main__":

    main()
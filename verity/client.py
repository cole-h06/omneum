from .graph import CredibilityGraph


class VerityClient:
    """
    Client for communicating with a Verity deployment.
    """

    def __init__(
        self,
        endpoint: str,
    ) -> None:
        self.endpoint = endpoint

    def infer_credibility(
        self,
        graph: CredibilityGraph,
    ):
        """
        Computes credibility over the submitted graph.

        The SDK validates and canonicalizes the graph, generates
        deterministic linkage IDs, makes the protocol
        request, sends it to the deployment, and returns the
        credibility results.
        """

        raise NotImplementedError
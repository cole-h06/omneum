"""Optional local MCP adapter around the existing SDK contribution pipeline."""
from contextlib import asynccontextmanager
from datetime import datetime
import os
from pathlib import Path
import sys

from mcp import StdioServerParameters
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from .client import NetworkContributionError, OmneumClientConfig, open_stdio_client
from .contribution.network import OmneumNetwork
from .information import Claim, Observation, Source
from .dependency import DependencyEstimatorConfig
from .transport.mcp import OmneumFastMCP
from .tools.evaluate_voprf import error_result


class AssertionInput(BaseModel):
    """New assertion occurrences only; never a stored-graph export request."""
    model_config = ConfigDict(extra='forbid')
    observation_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    entity_namespace: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    attribute: str = Field(min_length=1)
    value: str | int | float | bool | list | dict | None
    observed_at: datetime

    def observation(self):
        return Observation(
            observation_id=self.observation_id,
            source=Source(self.source_kind, self.source_identifier),
            claim=Claim(self.entity_namespace, self.entity, self.attribute, self.value),
            observed_at=self.observed_at,
        )


class ContributorMCP(OmneumFastMCP):
    async def call_tool(self, name, arguments):
        try:
            return await super().call_tool(name, arguments)
        except ToolError:
            # FastMCP otherwise echoes validation input and exception messages.
            return error_result("Observation evaluation failed; check the request and local service.",
                                "invalid_request")


def network_configuration(environ=None):
    """Explicit opt-in only. Invalid or incomplete configuration fails closed."""
    environ = os.environ if environ is None else environ
    enabled = environ.get('OMNEUM_NETWORK_CONTRIBUTION', 'false').lower()
    if enabled == 'false':
        return None
    if enabled != 'true':
        raise ValueError('OMNEUM_NETWORK_CONTRIBUTION must be true or false')
    credential = environ.get('OMNEUM_API_KEY')
    if not credential:
        raise ValueError('Network opt-in requires OMNEUM_API_KEY')
    return OmneumNetwork.pseudonymous(api_key=credential)


async def evaluate(client, observations, estimator, enabled):
    """Delegate evaluation, persistence, allowlisting and submission to the SDK."""
    values = tuple(item.observation() for item in observations)
    status = 'disabled'
    try:
        result = await client.evaluate_context(values, estimator=estimator)
        if enabled:
            status = 'submitted'
    except NetworkContributionError as error:
        # SDK persistence precedes submission. Return the computed local result
        # without exposing request contents, credentials or uncertain receipts.
        result = error.evaluation
        status = 'failed_or_uncertain'
    return {
        'network_contribution': status,
        'source_reliability': [dict(source_kind=item.source.kind,
            source_identifier=item.source.identifier, reliability=item.reliability)
            for item in result.source_reliability],
        'claim_support': [dict(entity_namespace=item.claim.entity_namespace,
            entity=item.claim.entity, attribute=item.claim.attribute,
            value=item.claim.value, support=item.support)
            for item in result.claim_support],
    }


def local_environment():
    # MCP subprocesses do not inherit arbitrary caller environment values.
    # Forward local deployment settings without forwarding the Network credential.
    allowed = {'HOME', 'PATH', 'XDG_CONFIG_HOME', 'APPDATA', 'LOCALAPPDATA',
               'OMNEUM_CONFIG_DIR', 'OMNEUM_DAEMON_SOCKET', 'OMNEUM_DAEMON_UID'}
    return {name: value for name, value in os.environ.items() if name in allowed}


def create_server(config=None, parameters=None):
    config = config or OmneumClientConfig.from_local_deployment()
    configuration_unavailable = False
    try:
        network = network_configuration()
        if network is not None and network.linkage.public_key == config.voprf_public_key:
            raise ValueError("Network and local keys must differ")
    except Exception:
        # Optional contribution misconfiguration must never disable local use.
        # No unvalidated configuration or exception text reaches the MCP host.
        network = None
        configuration_unavailable = True
    # The protected managed MCP session stays isolated; this caller-side
    # adapter owns local persistence and optional authenticated HTTPS calls.
    sibling = Path(sys.executable).parent / 'omneum-server'
    command = str(sibling) if sibling.is_file() else 'omneum-server'
    parameters = parameters or StdioServerParameters(command=command, env=local_environment())
    client = None

    @asynccontextmanager
    async def lifespan(_server):
        nonlocal client
        async with open_stdio_client(config, parameters, network_contribution=network) as session:
            client = session
            try:
                yield None
            finally:
                client = None

    server = ContributorMCP('Omneum contributor', lifespan=lifespan)

    @server.tool()
    async def evaluate_observations(
        observations: list[AssertionInput], estimator: DependencyEstimatorConfig,
    ) -> dict:
        """Evaluate new assertion observations locally; contribute only if explicitly enabled.

        Network failures retain the local result and are reported in
        network_contribution. Historical Context Graph contents are never uploaded.
        """
        if not 1 <= len(observations) <= 4096:
            raise ValueError('provide 1–4096 new observations')
        result = await evaluate(client, observations, estimator, network is not None)
        if configuration_unavailable:
            result['network_contribution'] = 'configuration_unavailable'
        return result

    tool = server._tool_manager.get_tool('evaluate_observations')
    tool.fn_metadata.arg_model.model_config.update(extra='forbid')
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters = tool.fn_metadata.arg_model.model_json_schema()
    return server


def main():
    from .server import _suppress_mcp_logging
    _suppress_mcp_logging()
    try:
        server = create_server()
    except Exception:
        raise SystemExit('Omneum contributor configuration failed; check local installation, explicit opt-in, API credential and Network provisioning') from None
    try:
        server.run()
    except Exception:
        raise SystemExit('Omneum contributor local service failed; check the local installation') from None


if __name__ == '__main__':
    main()

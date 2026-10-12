"""Maximum-cardinality SDK request, with synthetic fixed-width linkage tokens.

Only cryptographic round trips are substituted: graph construction, dependency
estimation, MCP ClientSession and stdio serialization are production code.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import sys

from omneum.mcp import ClientSession, StdioServerParameters, stdio_client

from omneum.client import (
    OmneumClient, OmneumClientConfig, LinkageToken, _MCPOmneumEvaluator,
    ContextEvaluationRejectedError,
)
from omneum.config import VOPRF_MODE
from omneum.dependency import DependencyEstimatorConfig
from omneum.information import Source, Claim, Observation
from omneum.linkage import LinkagePurpose, ENCODING_VERSION
from omneum.oprf import CIPHERSUITE
from omneum.tools.evaluate_context import (
    MAX_ASSERTIONS, MAX_SOURCES, MAX_ATTRIBUTES, MAX_CLAIMS, MAX_SOURCE_PAIRS, _validate_graph,
)


async def maximum_wire():
    # The receiver returns the exact bytes written by MCP's stdio transport.
    receiver = '''import sys,json
line=sys.stdin.buffer.readline()
request=json.loads(line)
print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":{
    "content":[],"isError":True,"structuredContent":{
        "message":"measurement complete","omneum_code":"server_busy"}}}),flush=True)
print(line.hex(),file=sys.stderr,flush=True)
'''
    import tempfile
    with tempfile.TemporaryFile(mode='w+') as captured:
        async with stdio_client(StdioServerParameters(
            command=sys.executable, args=['-I', '-B', '-c', receiver],
        ), errlog=captured) as (read, write):
            async with ClientSession(read, write) as session:
                config = OmneumClientConfig(
                    'urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741',
                    2**32 - 1, VOPRF_MODE, CIPHERSUITE, ENCODING_VERSION,
                    bytes.fromhex('c803e2cc6b05fc15064549b5920659ca4a77b2cca6f04f6b357009335476ad4e'),
                )
                client = OmneumClient(config, _MCPOmneumEvaluator(session))

                def linker(purpose):
                    async def link(*args):
                        return LinkageToken(
                            config.deployment_id, config.voprf_key_version,
                            config.voprf_mode, config.voprf_ciphersuite,
                            config.linkage_encoding_version, purpose,
                            hashlib.sha512(repr((purpose, args)).encode()).digest(),
                        )
                    return link

                client.link_source = linker(LinkagePurpose.SOURCE)
                client.link_attribute = linker(LinkagePurpose.ATTRIBUTE)
                client.link_claim = linker(LinkagePurpose.CLAIM)
                sources = [Source('web_document', f'https://example.test/{i}') for i in range(MAX_SOURCES)]
                observations = [Observation(
                    str(i), sources[i % MAX_SOURCES],
                    Claim('service', 'example', f'attribute-{i % MAX_ATTRIBUTES}', i),
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                ) for i in range(MAX_ASSERTIONS)]
                # Use different sources for the two claims of each attribute.
                observations = [Observation(
                    item.observation_id, sources[(i + i // MAX_ATTRIBUTES) % MAX_SOURCES],
                    item.claim, item.observed_at,
                ) for i, item in enumerate(observations)]
                try:
                    await client.evaluate_context(observations, estimator=DependencyEstimatorConfig(
                        upstream_weight=1., citation_weight=1., assertion_lineage_weight=1.,
                        ownership_weight=1., temporal_weight=1., graph_weight=1.,
                        temporal_window_seconds=3600.,
                    ))
                except ContextEvaluationRejectedError:
                    pass
        captured.seek(0)
        wire = bytes.fromhex(captured.read().strip())
    from omneum.models import EvaluateAssertionRequest
    request = EvaluateAssertionRequest.model_validate(json.loads(wire)['params']['arguments'])
    graph = _validate_graph(request)
    assert (len(graph.sources), len(graph.attributes), len(graph.claims), graph.assertion_count) == (
        MAX_SOURCES, MAX_ATTRIBUTES, MAX_CLAIMS, MAX_ASSERTIONS,
    )
    assert len(request.source_pairs) == MAX_SOURCE_PAIRS
    return wire


if __name__ == '__main__':
    wire = asyncio.run(maximum_wire())
    print(json.dumps({'sources': MAX_SOURCES, 'attributes': MAX_ATTRIBUTES,
                      'claims': MAX_CLAIMS, 'assertions': MAX_ASSERTIONS,
                      'source_pairs': MAX_SOURCE_PAIRS,
                      'wire_bytes_including_lf': len(wire), 'frame_bytes': len(wire)-1,
                      'headroom_bytes': 2**21-(len(wire)-1),
                      'headroom_percent_of_limit': 100*(2**21-(len(wire)-1))/2**21}))

"""Use an administratively provisioned local daemon; examples never hold k."""
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from mcp import StdioServerParameters
from omneum import OmneumClientConfig


@contextmanager
def example_deployment():
    root = Path(__file__).parents[2]
    config = OmneumClientConfig.from_local_deployment()
    server = StdioServerParameters(
        command=sys.executable, args=["-m", "omneum.server"], cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
    )
    yield config, server

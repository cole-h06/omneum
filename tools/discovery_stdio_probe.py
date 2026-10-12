"""Introspect the actual Docker stdio entry point without deploying or using host services."""
import argparse
import asyncio
import json
from mcp import ClientSession, StdioServerParameters, stdio_client


async def probe(image):
    server = StdioServerParameters(command='docker', args=[
        'run', '--rm', '-i', '--network', 'none', image])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resources()
            prompts = await session.list_prompts()
            result = await session.call_tool('ping')
            assert not result.isError and result.structuredContent['status'] == 'ok'
            names = sorted(t.name for t in tools.tools)
            assert names == ['evaluate_context', 'evaluate_voprf', 'ping']
            print(json.dumps({'status': 'passed', 'mode': 'Docker entrypoint stdio',
                'tools': names, 'resources': len(resources.resources), 'prompts': len(prompts.prompts)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='omneum-discovery:1.0.3')
    asyncio.run(probe(parser.parse_args().image))

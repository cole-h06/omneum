"""Generate local-client configuration links only; never launch or install a client."""
import argparse
import base64
import json
from pathlib import Path
import shlex
from urllib.parse import urlencode


def links(server_path):
    path = Path(server_path)
    if not path.is_absolute() or path.name != 'omneum-server' or '\x00' in server_path or '\n' in server_path:
        raise ValueError('provide the absolute installed omneum-server executable path')
    config = {'omneum': {'command': server_path, 'args': []}}
    encoded = base64.b64encode(json.dumps(config, separators=(',', ':')).encode()).decode()
    cursor = 'cursor://anysphere.cursor-deeplink/mcp/install?' + urlencode({'name': 'omneum', 'config': encoded})
    vscode = {'name': 'omneum', 'type': 'stdio', 'command': server_path, 'args': []}
    return cursor, 'code --add-mcp ' + shlex.quote(json.dumps(vscode, separators=(',', ':')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-path', required=True)
    for result in links(parser.parse_args().server_path):
        print(result)

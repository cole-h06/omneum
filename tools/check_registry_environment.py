"""Fail closed unless GitHub reports required independent environment reviewers."""
import json
import os
import subprocess

from registry_readiness import require


def check_environment(document):
    require(document.get('name') == 'mcp-registry', 'wrong publishing environment')
    rules = [rule for rule in document.get('protection_rules', []) if rule.get('type') == 'required_reviewers']
    require(len(rules) == 1 and rules[0].get('reviewers'), 'mcp-registry requires at least one reviewer')
    require(rules[0].get('prevent_self_review') is True, 'mcp-registry must prevent self-review')


def main():
    require(os.environ.get('GITHUB_REPOSITORY') == 'cole-h06/omneum', 'wrong repository')
    result = subprocess.run(['gh', 'api', 'repos/cole-h06/omneum/environments/mcp-registry'],
                            check=True, capture_output=True, text=True)
    check_environment(json.loads(result.stdout))
    print('Protected registry environment: independent review required')


if __name__ == '__main__':
    main()

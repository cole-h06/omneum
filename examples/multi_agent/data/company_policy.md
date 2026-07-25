# Internal AI Platform Standards

**Last Updated:** July 2026

## Approved Models

The primary reasoning model for production services is GPT-5.6 Sol.

## API Integration

All new services must integrate using the `/v1/responses` endpoint.

Streaming responses should be enabled whenever practical.

Structured outputs should be used for machine-to-machine communication.

## Reasoning Configuration

Unless otherwise specified, production services should use a reasoning effort of `high`.

## Context

GPT-5.6 Sol provides a context window of 1050000 tokens.

## Tool Usage

The capabilities that are approved for production use:

- Function calling
- Web search
- File search
- MCP tools

## Security

Applications should validate all tool outputs before executing downstream actions.

Structured assertions produced by AI agents should be verified before being used in automated workflows.
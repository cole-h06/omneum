# Verity SDK

Build applications that communicate with Verity deployments using the official Verity SDKs.

This guide covers installation, configuration, architecture, and how to integrate the Verity SDK into your application. The SDK handles canonicalization, linkage token generation, protocol communication, and interpretation of deterministic credibility telemetry so you can focus on building your application.

---

# Installation

Choose the SDK that matches your application.

## Python

```bash
pip install verity
```

## JavaScript / TypeScript

```bash
npm install @verity/sdk
```

---

# Configuration

The Verity SDK communicates with deployments implementing the Verity Protocol.

## Self-Hosted Deployment

```python
client = VerityClient(
    endpoint="https://verity.example.com"
)
```

---

# Quick Start

Create a client and construct a credibility graph using your application data. Once completed, you can submit it for inference.

Python

```python
from verity import CredibilityGraph
from verity import VerityClient

client = VerityClient(
    endpoint="https://verity.example.com"
)

graph = CredibilityGraph()

graph.add(
    source="docs.anthropic.com",
    entity="messages_api",
    attribute="supports_streaming",
    value=True
)

result = client.infer_credibility(graph)
```

JavaScript

```javascript
import {
    CredibilityGraph,
    VerityClient
} from "@verity/sdk";

const client = new VerityClient({
    endpoint: "https://verity.example.com"
});

const graph = new CredibilityGraph();

graph.add({
    source: "docs.anthropic.com",
    entity: "messages_api",
    attribute: "supports_streaming",
    value: true
});

const result =
    await client.inferCredibility(graph);
```

---

## Why the SDK?

If your application already runs inside an MCP-compatible environment, you can communicate directly with a Verity MCP server using your existing MCP client.

The Verity SDK is intended for applications that communicate directly with Verity deployments. It automates canonicalization, linkage token generation, protocol communication, and response rendering.

---

# What the SDK Does

The SDK automatically:

- Canonicalizes your application data.
- Generates deterministic linkage identifiers.
- Maintains a local metadata registry.
- Constructs Verity Protocol requests.
- Communicates with Verity deployments.
- Resolves linkage identifiers returned by the deployment.
- Optionally renders deterministic credibility explanations.

---

# Architecture

The Verity SDK performs all content-sensitive operations locally before communicating with a Verity deployment.

Your application never sends its original sources, entities, attributes, or values to the deployment. Instead, the SDK canonicalizes your data, generates deterministic linkage identifiers, maintains a local metadata registry, and exchanges only opaque identifiers with the deployment.

The deployment returns deterministic credibility telemetry, which the SDK can optionally combine with your original application data to produce explanations.

---

# Canonicalization

Provide ordinary application data to the SDK.

```python
{
    "source": "docs.anthropic.com",
    "entity": "messages_api",
    "attribute": "supports_streaming",
    "value": True
}
```

The SDK automatically canonicalizes your data according to the Verity Canonicalization Specification before generating linkage identifiers.

---

# Linkage Token Generation

After canonicalization, the SDK generates deterministic linkage identifiers.

| Canonical Representation | Linkage Identifier |
|---------------------------|--------------------|
| Canonical Source | `source_id` |
| Canonical `(Entity, Attribute)` | `attribute_id` |
| Canonical `(Entity, Attribute, Value)` | `claim_id` |

Only these linkage identifiers are transmitted to the Verity deployment.

---

# Local Metadata Registry

The SDK maintains a local registry that maps linkage identifiers back to your original application data.

For example,

```text
clm_f72d10...

        │
        ▼

messages_api.supports_streaming = true
```

The local metadata registry never leaves your application.

---

# Making Requests

Once your graph has been constructed, submit it using the SDK.

```python
result = client.infer_credibility(graph)
```

The SDK handles request construction, serialization, transmission, and response parsing automatically.

---

# Understanding Responses

Verity deployments return deterministic credibility telemetry describing the structure of the credibility graph.

Example

```json
{
  "claim_support": [
    {
      "attribute_id": "attr_93e4f7...",
      "claim_id": "clm_f72d10...",
      "support": 0.83,
      "independent_support_count": 3,
      "dependent_support_count": 0,
      "is_attribute_max_support": true,
      "conflicting_claims": [
        {
          "claim_id": "clm_51d8ab...",
          "support": 0.17
        }
      ]
    }
  ]
}
```

These signals describe graph topology only. The deployment never has access to your application's original content.

---

# Rendering Credibility Signals

Because the SDK maintains the local metadata registry, it can combine returned telemetry with your original application data to explain results.

Example

```text
Revenue: $94M

Credibility: 0.91

✓ Supported by 4 independent sources.

✓ Highest-supported competing value.
```

Or,

```text
Vendor API <-> Internal SQL

Independence: 0.24

! High assertion overlap detected.
```

These explanations are generated entirely within the SDK. Verity deployments never generate natural-language explanations and never receive the underlying application data.

---

# Agent Integrations

The SDK can be integrated into existing AI frameworks, such as:

- LangGraph
- CrewAI
- Microsoft Agent Framework
- Mastra
- LlamaIndex

Applications running inside MCP-compatible environments can integrate directly with the Verity MCP server. 

Applications outside the MCP ecosystem can use the Verity SDK to communicate directly with Verity deployments.

---

# API Reference

The following sections describe the SDK interfaces available for each supported programming language.
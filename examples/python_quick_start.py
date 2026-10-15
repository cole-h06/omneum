"""Run with: python -m examples.python_quick_start"""

import omneum
from omneum.explanations import explain_evaluation

observations = [
    {
        "url": "https://a.example",
        "value": 4200000000,
        "claim": {
            "entity_namespace": "company",
            "entity": "acme",
            "attribute": "fy2025_gross_revenue",
        },
        "upstream": ["https://sec.example"],
    },
    {
        "url": "https://b.example",
        "value": 4200000000,
        "claim": {
            "entity_namespace": "company",
            "entity": "acme",
            "attribute": "fy2025_gross_revenue",
        },
        "upstream": ["https://sec.example"],
    },
    {
        "url": "https://c.example",
        "value": 4200000000,
        "claim": {
            "entity_namespace": "company",
            "entity": "acme",
            "attribute": "fy2025_gross_revenue",
        },
        "upstream": [],
    },
]

result = omneum.evaluate(observations)
print(explain_evaluation(result))
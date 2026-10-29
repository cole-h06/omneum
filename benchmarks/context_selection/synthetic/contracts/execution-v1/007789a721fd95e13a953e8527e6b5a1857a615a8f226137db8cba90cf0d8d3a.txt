"""Run with: python -m omneum.demo"""

import omneum
from omneum.explanations import explain_evaluation


def main() -> None:
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
        {
            "url": "https://d.example",
            "value": 3900000000,
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


if __name__ == "__main__":
    main()

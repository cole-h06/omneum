"""Run with: python -m examples.python_quick_start"""

import omneum

records = [
    {"url": "https://a.example", "value": 4200000000,
     "upstream": ["https://sec.example"]},
    {"url": "https://b.example", "value": 4200000000,
     "upstream": ["https://sec.example"]},
    {"url": "https://c.example", "value": 4200000000,
     "upstream": []},
]

result = omneum.evaluate(records)
print(f"Estimated independent support: {result.estimated_independent_support:.2f}")

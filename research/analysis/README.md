# Research diagnostics

These modules preserve historical exploratory calculations. Their formulas and
interpretations are unchanged; they are not production dependency estimators.

Import from the repository root:

```python
from research.analysis.directional_inclusion import directional_inclusion

result = directional_inclusion({"claim": "value"}, {"claim": "value"})
```

`community_overlap` accepts assertion rows and requires the research-only
NetworkX dependency. Other modules accept the mappings or metadata rows specified
by their arguments. `graph_matrix` combines caller-supplied matrices. The temporal
diagnostic retains its seven-day window, distinct from the applied experiment's
two-hour setting. Database loaders and mutation scripts are retired.

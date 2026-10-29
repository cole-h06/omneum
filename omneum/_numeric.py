"""Literal quantity guards for upstream extraction/normalization, not inference."""
from decimal import Decimal
import re

# Grouped thousands, leading decimals and scientific notation are single literals.
# In particular .12 is not 12, and 1,2 is two literals rather than twelve.
_LITERAL = re.compile(r'(?<![\d.])[-+]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?')


def numeric_literals(value):
    """Return exact decimal magnitudes; never establish unit equivalence."""
    if type(value) is bool or value is None:
        return frozenset()
    if isinstance(value, dict):
        return frozenset(n for v in value.values() for n in numeric_literals(v))
    if isinstance(value, (list, tuple)):
        return frozenset(n for v in value for n in numeric_literals(v))
    text = str(value).replace('−', '-')
    # A dash immediately between digits separates range/date components. It
    # does not make the upper bound negative. Unary signs and exponents remain.
    text = re.sub(r'(?<=\d)[–—-](?=\d)', ' ', text)
    return frozenset(Decimal(n.replace(',', '')) for n in _LITERAL.findall(text))

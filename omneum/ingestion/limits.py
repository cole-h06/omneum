"""Server-owned finite budgets for accepted untrusted reports, per UTC day."""
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class IngestionLimits:
    contributions: int = 1_000
    sources: int = 10_000
    claims: int = 10_000
    observations: int = 20_000
    dependencies: int = 20_000

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= 2**31 - 1:
                raise ValueError("ingestion budgets must be finite positive integers")

    def values(self):
        return (self.contributions, self.sources, self.claims,
                self.observations, self.dependencies)

from .methods import METHODS
from .runner import run_method


async def run_case(
    case,
    truth,
    *,
    trials,
    generator_provider,
    generator_model,
    methods=METHODS,
):
    if case.case_id != truth.case_id:
        raise ValueError(
            f"case/truth mismatch: "
            f"{case.case_id} != {truth.case_id}"
        )

    records = []

    for method in methods:
        method_trials = trials if method.stochastic else 1

        for trial in range(1, method_trials + 1):
            result = await run_method(
                method.method,
                case,
                truth,
                provider=method.provider,
                model=method.model,
                generator_provider=generator_provider,
                generator_model=generator_model,
            )

            records.append(
                {
                    "case_id": case.case_id,
                    "domain": case.domain,
                    "method": method.name,
                    "trial": trial,
                    **result,
                }
            )

    return records

import logging

from .methods import METHODS
from .runner import run_method


logger = logging.getLogger(__name__)


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
            context = (
                f"case_id={case.case_id} method={method.name} trial={trial}"
            )
            logger.info("Starting %s", context)
            try:
                result = await run_method(
                    method.method,
                    case,
                    truth,
                    provider=method.provider,
                    model=method.model,
                    generator_provider=generator_provider,
                    generator_model=generator_model,
                )
            except Exception as exc:
                exc.add_note(context)
                logger.exception("Execution error %s", context)
                raise

            if result.get("failure_type") is not None:
                logger.warning(
                    "Failed %s answer_score=%s failure_type=%s error=%s",
                    context,
                    result["answer_score"],
                    result["failure_type"],
                    result["error"],
                )
            else:
                logger.info(
                    "Finished %s answer_score=%s", context, result["answer_score"]
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

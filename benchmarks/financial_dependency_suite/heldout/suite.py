import logging

from .methods import METHODS
from .additive_runner import run_method
from .diagnostics import diagnostic_record, safe_artifact


logger = logging.getLogger(__name__)


async def run_case(
    case,
    truth,
    *,
    trials,
    generator_provider,
    generator_model,
    methods=METHODS,
    on_result=None,
    completed=None,
    reused=None,
    cohere_cache=None,
):
    if case.case_id != truth.case_id:
        raise ValueError(
            f"case/truth mismatch: "
            f"{case.case_id} != {truth.case_id}"
        )

    records = []

    for method in methods:
        for trial in range(1, trials + 1):
            key = (case.case_id, method.name, trial)
            if completed is not None and key in completed:
                records.append(completed[key])
                continue
            if reused is not None and key in reused:
                record = reused[key]
                if on_result is not None:
                    on_result(record)
                records.append(record)
                continue
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
                    **({"cohere_cache": cohere_cache} if cohere_cache is not None else {}),
                )
            except Exception as exc:
                exc.add_note(context)
                logger.error("Execution error %s type=%s", context, type(exc).__name__)
                raise

            raw_record = {
                "case_id": case.case_id,
                "domain": case.domain,
                "method": method.name,
                "trial": trial,
                **result,
            }
            for field in ("category", "adversarial_category"):
                value = getattr(case, field, None)
                if value is not None:
                    raw_record[field] = value
            record = diagnostic_record(raw_record, method)
            if on_result is not None:
                on_result(record)
            records.append(record)

            if result.get("failure_type") is not None:
                logger.warning(
                    "Failed %s answer_score=%s failure_type=%s error=%s",
                    context,
                    result["answer_score"],
                    result["failure_type"],
                    safe_artifact(record).get("error", "Provider failure"),
                )
            else:
                logger.info(
                    "Finished %s answer_score=%s", context, result["answer_score"]
                )

    return records

import logging
from copy import deepcopy

from .methods import METHODS
from .additive_runner import run_method, select_cohere_safe
from .cohere_cache import valid_selection
from .diagnostics import diagnostic_record, safe_artifact
from . import runner as frozen
from .loader import application_candidates


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
    paired_bge = bool({"bge_anthropic", "bge_openai", "bge_google"} & {method.name for method in methods})
    paired_cohere = "cohere_anthropic" in {method.name for method in methods}
    relevance_by_trial = {}
    if paired_bge:
        for (case_id, method_name, trial), record in (completed or {}).items():
            if case_id == case.case_id and method_name in {"bge_anthropic", "bge_openai", "bge_google", "bge_omneum"}:
                relevance = record["selection"]["bge_relevance"]
                if trial in relevance_by_trial and relevance_by_trial[trial] != relevance:
                    raise ValueError("paired BGE shortlists differ in saved records")
                relevance_by_trial[trial] = deepcopy(relevance)
    if paired_cohere:
        for (case_id, method_name, trial), record in (completed or {}).items():
            if case_id == case.case_id and method_name in {"cohere_anthropic", "cohere_omneum"}:
                relevance = record["selection"]["cohere_relevance_result"]
                if trial in relevance_by_trial and relevance_by_trial[trial] != relevance:
                    raise ValueError("paired Cohere shortlists differ in saved records")
                relevance_by_trial[trial] = deepcopy(relevance)

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
                paired_options = {}
                if paired_bge and method.name in {"bge_anthropic", "bge_openai", "bge_google", "bge_omneum"}:
                    if trial not in relevance_by_trial:
                        candidates = application_candidates(case)
                        relevance_by_trial[trial] = frozen.select_bge(
                            case.question, candidates,
                            top_n=min(len(candidates), 2 * case.context_budget),
                        )
                    paired_options["bge_relevance"] = deepcopy(relevance_by_trial[trial])
                if paired_cohere and method.name in {"cohere_anthropic", "cohere_omneum"}:
                    candidates = application_candidates(case)
                    depth = min(len(candidates), 2 * case.context_budget)
                    if trial not in relevance_by_trial:
                        relevance_by_trial[trial] = select_cohere_safe(
                            case.question, candidates, top_n=depth,
                        )
                    relevance = relevance_by_trial[trial]
                    if relevance["failure"] is None and not valid_selection(
                        relevance["selection"], candidates, depth,
                    ):
                        raise ValueError("invalid shared Cohere shortlist")
                    paired_options["cohere_relevance"] = deepcopy(relevance)
                result = await run_method(
                    method.method,
                    case,
                    truth,
                    provider=method.provider,
                    model=method.model,
                    generator_provider=generator_provider,
                    generator_model=generator_model,
                    **({"cohere_cache": cohere_cache} if cohere_cache is not None else {}),
                    **paired_options,
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

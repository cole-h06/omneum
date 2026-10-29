from omneum import ContextEvaluation
from omneum.client import _evaluate_context

from ....adapters.observations import estimator, source_identifier, to_observations
from .dataset import DEPENDENCY_WEIGHTS, load_dataset


def run_experiment(weights=None):
    sources, observations = load_dataset()
    evaluation = _evaluate_context(
        to_observations(sources, observations),
        estimator=estimator(DEPENDENCY_WEIGHTS if weights is None else weights),
    )
    return {
        "sources": sources,
        "observations": observations,
        "evaluation": evaluation,
    }


def print_evaluation(sources, evaluation: ContextEvaluation) -> None:
    labels = {source_identifier(source.source_id): source.source_id for source in sources}
    print(f"Algorithm: {evaluation.convergence.algorithm_version}")
    print(f"Iterations: {evaluation.convergence.iterations}")
    print("Source reliability:")
    for item in evaluation.source_reliability:
        print(f"  {labels[item.source.identifier]}: {item.reliability:.12f}")
    print("Claim support:")
    for item in evaluation.claim_support:
        claim = item.claim
        print(f"  {claim.entity_namespace}/{claim.entity}/{claim.attribute}={claim.value!r}: {item.support:.12f}")


def main():
    result = run_experiment()
    print_evaluation(result["sources"], result["evaluation"])


if __name__ == "__main__":
    main()

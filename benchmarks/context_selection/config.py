from omneum.dependency import DependencyEstimatorConfig


def estimator_config():
    return DependencyEstimatorConfig(
        upstream_weight=25.0,
        citation_weight=20.0,
        assertion_lineage_weight=20.0,
        ownership_weight=10.0,
        temporal_weight=10.0,
        graph_weight=15.0,
        temporal_window_seconds=172_800.0,
        estimator_version="dependency-estimator-v4",
        dependency_cluster_threshold=0.3,
    )

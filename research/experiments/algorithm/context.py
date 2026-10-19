"""Canonical synthetic context used by direct Omneum experiments."""

from ...adapters.structural import build_graph as build_inference_graph


ASSERTIONS = [
    ("financial_report", "revenue", "100M"),
    ("market_report", "revenue", "100M"),
    ("analyst_report", "revenue", "120M"),

    ("financial_report", "employees", "1000"),
    ("market_report", "employees", "1000"),
    ("analyst_report", "employees", "1200"),

    ("market_report", "headquarters", "New York"),
    ("analyst_report", "headquarters", "New York"),
]


INDEPENDENT = {
    "financial_report": {
        "financial_report": 0.0,
        "market_report": 0.0,
        "analyst_report": 0.0,
    },
    "market_report": {
        "financial_report": 0.0,
        "market_report": 0.0,
        "analyst_report": 0.0,
    },
    "analyst_report": {
        "financial_report": 0.0,
        "market_report": 0.0,
        "analyst_report": 0.0,
    },
}


DEPENDENT = {
    "financial_report": {
        "financial_report": 0.0,
        "market_report": 0.95,
        "analyst_report": 0.0,
    },
    "market_report": {
        "financial_report": 0.95,
        "market_report": 0.0,
        "analyst_report": 0.0,
    },
    "analyst_report": {
        "financial_report": 0.0,
        "market_report": 0.0,
        "analyst_report": 0.0,
    },
}


MIXED = {
    "financial_report": {
        "financial_report": 0.0,
        "market_report": 0.9,
        "analyst_report": 0.0,
    },
    "market_report": {
        "financial_report": 0.9,
        "market_report": 0.0,
        "analyst_report": 0.0,
    },
    "analyst_report": {
        "financial_report": 0.0,
        "market_report": 0.0,
        "analyst_report": 0.0,
    },
}


def build_graph(dependency_matrix=None):
    return build_inference_graph(
        ASSERTIONS,
        dependency_matrix=dependency_matrix,
    )
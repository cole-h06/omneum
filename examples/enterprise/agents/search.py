import json
from pathlib import Path

from .common import VENDOR_SOURCE, observation


FIXTURE = Path(__file__).parents[1] / "data" / "vendor_data_controls.json"


def search_agent():
    """Retrieve the vendor enterprise data-controls page."""

    vendor = json.loads(FIXTURE.read_text(encoding="utf-8"))

    page = vendor["page"]
    controls = vendor["enterprise_controls"]

    return (
        observation(
            "vendor-retention",
            VENDOR_SOURCE,
            "Provider Retention",
            f'{controls["provider_retention_days"]} days',
            page["last_modified"],
        ),
        observation(
            "vendor-region",
            VENDOR_SOURCE,
            "Processing Region",
            controls["supported_processing_regions"][0],
            page["last_modified"],
        ),
    )

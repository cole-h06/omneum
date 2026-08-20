from datetime import datetime, timezone

from omneum import Claim, Observation, Source, SourceReference


ENTITY_NAMESPACE = "service"
ENTITY = "arm_holdings"
ATTRIBUTE = "FY2023 total revenue"
REVENUE = 2_679_000_000


ARM = Source("web_document", "https://www.sec.gov/Archives/edgar/data/1973239/000119312523216983/d393891df1.htm")
REUTERS = Source("web_document", "https://www.investing.com/news/stock-market-news/arms-fullyear-revenue-fell-1-ahead-of-ipo--source-3157525")
BLOOMBERG = Source("web_document", "https://news.bloomberglaw.com/capital-markets/arms-revenue-fell-last-year-ahead-of-ipo-draft-filing-shows")
SYNDICATION = Source(
    "web_document",
    "https://www.communicationstoday.co.in/arm-revenue-falls-1-in-year-ahead-of-ipo/",
)
TECHCRUNCH = Source(
    "web_document",
    "https://techcrunch.com/2023/08/22/the-bear-and-bull-cases-for-arms-ipo/",
)

SOURCE_IDS = {
    ARM: "arm_f1",
    REUTERS: "reuters_pre_filing",
    BLOOMBERG: "bloomberg_pre_filing",
    SYNDICATION: "communications_today_syndication",
    TECHCRUNCH: "techcrunch_analysis",
}


def reference(source):
    return SourceReference(source.kind, source.identifier)


def build_observations():
    claim = Claim(
        ENTITY_NAMESPACE,
        ENTITY,
        ATTRIBUTE,
        REVENUE,
    )

    return (
        observation(
            "arm-f1-revenue",
            ARM,
            claim,
            "2023-08-21",
        ),
        observation(
            "reuters-revenue",
            REUTERS,
            claim,
            "2023-08-18",
        ),
        observation(
            "bloomberg-revenue",
            BLOOMBERG,
            claim,
            "2023-08-18",
        ),
        observation(
            "syndication-revenue",
            SYNDICATION,
            claim,
            "2023-08-19",
            upstream_sources=(reference(REUTERS),),
            parent_assertion_ids=("reuters-revenue",),
        ),
        observation(
            "techcrunch-revenue",
            TECHCRUNCH,
            claim,
            "2023-08-22",
            cited_sources=(reference(ARM),),
        ),
    )


def observation(
    assertion_id,
    source,
    claim,
    date,
    *,
    upstream_sources=(),
    cited_sources=(),
    parent_assertion_ids=(),
):
    timestamp = datetime.fromisoformat(date).replace(
        tzinfo=timezone.utc
    )

    return Observation(
        assertion_id=assertion_id,
        source=source,
        claim=claim,
        observed_at=timestamp,
        source_modified_at=timestamp,
        upstream_sources=tuple(upstream_sources),
        cited_sources=tuple(cited_sources),
        parent_assertion_ids=tuple(parent_assertion_ids),
        retrievals=(),
    )

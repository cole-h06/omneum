from datetime import datetime, timezone

from omneum import Claim, Observation, Source, SourceReference


ENTITY_NAMESPACE = "service"


ARM = Source(
    "web_document",
    "https://www.sec.gov/Archives/edgar/data/1973239/000119312523216983/d393891df1.htm",
)
REUTERS_ARM = Source(
    "web_document",
    "https://www.investing.com/news/stock-market-news/arms-fullyear-revenue-fell-1-ahead-of-ipo--source-3157525",
)
BLOOMBERG_ARM = Source(
    "web_document",
    "https://news.bloomberglaw.com/capital-markets/arms-revenue-fell-last-year-ahead-of-ipo-draft-filing-shows",
)
SYNDICATION_ARM = Source(
    "web_document",
    "https://www.communicationstoday.co.in/arm-revenue-falls-1-in-year-ahead-of-ipo/",
)
TECHCRUNCH_ARM = Source(
    "web_document",
    "https://techcrunch.com/2023/08/22/the-bear-and-bull-cases-for-arms-ipo/",
)


SVB_8K = Source(
    "web_document",
    "https://www.sec.gov/Archives/edgar/data/719739/000119312523064680/d430920d8k.htm",
)
SVB_PRESS_RELEASE = Source(
    "web_document",
    "https://www.sec.gov/Archives/edgar/data/719739/000119312523064680/d430920dex991.htm",
)
SVB_INVESTOR_UPDATE = Source(
    "web_document",
    "https://www.sec.gov/Archives/edgar/data/719739/000119312523064680/d430920dex992.htm",
)
REUTERS_SVB = Source(
    "web_document",
    "https://www.investing.com/news/stock-market-news/silicon-valley-bank-scrambles-to-reassure-clients-after-60-stock-wipeout-3026738",
)
REUTERS_SVB_RETROSPECTIVE = Source(
    "web_document",
    "https://www.investing.com/news/stock-market-news/how-svb-financial-group-imploded-in-two-days-3030474",
)


SMCI_8K = Source(
    "web_document",
    "https://www.sec.gov/Archives/edgar/data/1375365/000137536524000036/smci-20241024.htm",
)
REUTERS_SMCI = Source(
    "web_document",
    "https://www.reuters.com/technology/super-micro-computer-says-ernst-young-resigns-its-accountant-shares-tank-2024-10-30/",
)
BLOOMBERG_SMCI = Source(
    "web_document",
    "https://news.bloomberglaw.com/ip-law/super-micro-computer-auditor-ernst-young-quits-amid-doj-probe",
)
AP_SMCI = Source(
    "web_document",
    "https://apnews.com/article/d1cc4377628b3024e659dcfec9318dcd",
)
REUTERS_SYNDICATION_SMCI = Source(
    "web_document",
    "https://theprint.in/tech/super-micro-computer-says-ernst-young-resigns-as-accountant-shares-tank/2335665/",
)


ARM_SOURCE_IDS = {
    ARM: "arm_f1",
    REUTERS_ARM: "reuters_pre_filing",
    BLOOMBERG_ARM: "bloomberg_pre_filing",
    SYNDICATION_ARM: "communications_today_syndication",
    TECHCRUNCH_ARM: "techcrunch_analysis",
}

SVB_SOURCE_IDS = {
    SVB_8K: "svb_8k",
    SVB_PRESS_RELEASE: "svb_press_release",
    SVB_INVESTOR_UPDATE: "svb_investor_update",
    REUTERS_SVB: "reuters_report",
    REUTERS_SVB_RETROSPECTIVE: "reuters_retrospective",
}


SMCI_SOURCE_IDS = {
    SMCI_8K: "smci_8k",
    REUTERS_SMCI: "reuters_report",
    BLOOMBERG_SMCI: "bloomberg_report",
    AP_SMCI: "ap_report",
    REUTERS_SYNDICATION_SMCI: "reuters_syndication",
}


def reference(source):
    return SourceReference(source.kind, source.identifier)


def build_observations(case_id="arm_ipo_2023_revenue"):
    if case_id == "arm_ipo_2023_revenue":
        return build_arm_observations()

    if case_id == "svb_collapse_2023_loss":
        return build_svb_observations()

    if case_id == "smci_auditor_resignation_2024":
        return build_smci_observations()

    raise ValueError(f"unknown benchmark case: {case_id}")


def source_ids(case_id):
    if case_id == "arm_ipo_2023_revenue":
        return ARM_SOURCE_IDS

    if case_id == "svb_collapse_2023_loss":
        return SVB_SOURCE_IDS

    if case_id == "smci_auditor_resignation_2024":
        return SMCI_SOURCE_IDS

    raise ValueError(f"unknown benchmark case: {case_id}")


def build_arm_observations():
    claim = Claim(
        ENTITY_NAMESPACE,
        "arm_holdings",
        "FY2023 total revenue",
        2_679_000_000,
    )

    return (
        observation("arm-f1-revenue", ARM, claim, "2023-08-21"),
        observation(
            "reuters-revenue",
            REUTERS_ARM,
            claim,
            "2023-08-18",
        ),
        observation(
            "bloomberg-revenue",
            BLOOMBERG_ARM,
            claim,
            "2023-08-18",
        ),
        observation(
            "syndication-revenue",
            SYNDICATION_ARM,
            claim,
            "2023-08-19",
            upstream_sources=(reference(REUTERS_ARM),),
            parent_assertion_ids=("reuters-revenue",),
        ),
        observation(
            "techcrunch-revenue",
            TECHCRUNCH_ARM,
            claim,
            "2023-08-22",
            cited_sources=(reference(ARM),),
        ),
    )


def build_svb_observations():
    claim = Claim(
        ENTITY_NAMESPACE,
        "svb_financial_group",
        "AFS securities sale after-tax loss",
        1_800_000_000,
    )

    return (
        observation(
            "svb-8k-loss",
            SVB_8K,
            claim,
            "2023-03-08",
        ),
        observation(
            "svb-press-release-loss",
            SVB_PRESS_RELEASE,
            claim,
            "2023-03-08",
            upstream_sources=(reference(SVB_8K),),
            parent_assertion_ids=("svb-8k-loss",),
        ),
        observation(
            "svb-investor-update-loss",
            SVB_INVESTOR_UPDATE,
            claim,
            "2023-03-08",
            upstream_sources=(reference(SVB_8K),),
            parent_assertion_ids=("svb-8k-loss",),
        ),
        observation(
            "reuters-svb-loss",
            REUTERS_SVB,
            claim,
            "2023-03-09",
            cited_sources=(reference(SVB_8K),),
        ),
        observation(
            "reuters-svb-retrospective-loss",
            REUTERS_SVB_RETROSPECTIVE,
            claim,
            "2023-03-10",
            cited_sources=(reference(SVB_8K),),
        ),
    )



def build_smci_observations():
    claim = Claim(
        ENTITY_NAMESPACE,
        "super_micro_computer",
        "reason for EY auditor resignation",
        (
            "EY concluded that it could no longer rely on "
            "representations from management and the Audit Committee "
            "and was unwilling to be associated with management's "
            "financial statements."
        ),
    )

    return (
        observation(
            "smci-8k-ey-resignation",
            SMCI_8K,
            claim,
            "2024-10-30",
        ),
        observation(
            "reuters-smci-ey-resignation",
            REUTERS_SMCI,
            claim,
            "2024-10-30",
            cited_sources=(reference(SMCI_8K),),
        ),
        observation(
            "bloomberg-smci-ey-resignation",
            BLOOMBERG_SMCI,
            claim,
            "2024-10-30",
            cited_sources=(reference(SMCI_8K),),
        ),
        observation(
            "ap-smci-ey-resignation",
            AP_SMCI,
            claim,
            "2024-10-30",
        ),
        observation(
            "reuters-syndication-smci-ey-resignation",
            REUTERS_SYNDICATION_SMCI,
            claim,
            "2024-10-30",
            upstream_sources=(reference(REUTERS_SMCI),),
            parent_assertion_ids=(
                "reuters-smci-ey-resignation",
            ),
        ),
    )

def observation(
    assertion_id,
    source,
    claim,
    date,
    *,
    source_modified_date=None,
    upstream_sources=(),
    cited_sources=(),
    parent_assertion_ids=(),
):
    observed_at = datetime.fromisoformat(date).replace(
        tzinfo=timezone.utc
    )
    source_modified_at = datetime.fromisoformat(
        source_modified_date or date
    ).replace(tzinfo=timezone.utc)

    return Observation(
        assertion_id=assertion_id,
        source=source,
        claim=claim,
        observed_at=observed_at,
        source_modified_at=source_modified_at,
        upstream_sources=tuple(upstream_sources),
        cited_sources=tuple(cited_sources),
        parent_assertion_ids=tuple(parent_assertion_ids),
        retrievals=(),
    )

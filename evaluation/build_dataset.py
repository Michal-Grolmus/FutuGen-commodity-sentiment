"""Build an expanded historical events dataset from structured historical data.

Loads existing `historical_events.json` (hand-curated, 144 events) and appends:
  - FOMC meetings 2018-2024 (56 dates × gold/silver pairs = ~110 events)
  - Major OPEC/OPEC+ decisions (~30 × WTI+Brent = ~60 events)
  - Major CPI prints (monthly surprises 2018-2024)
  - Major NFP prints (select months)
  - Additional supply shocks, geopolitical events, USDA reports
  - Explicit NEUTRAL cases (Fed-holds-in-consensus, OPEC-maintains-policy)

Principles:
  - news_text contains ONLY information public on the event date (no hindsight).
  - analyst_direction is the ex-ante textbook interpretation of the text.
  - Events tagged with `event_cluster_id` when multiple rows share the same
    underlying news (allows optional deduplication in analysis).
  - Each generated event carries a `generator` field for traceability.

Output overwrites evaluation/historical_events.json.
Run `python -m evaluation.fetch_prices` afterwards to enrich with prices.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = ROOT / "evaluation" / "historical_events.json"


# ============================================================================
# FOMC MEETINGS 2018-2024
# (date, decision, bp, tone, context_sentence)
# decision ∈ {"hike", "hold", "cut", "emergency_cut"}
# tone ∈ {"hawkish", "neutral", "dovish"} — relative to prior guidance
# ============================================================================
FOMC_MEETINGS: list[tuple[str, str, int, str, str]] = [
    # 2018 — tightening cycle
    ("2018-01-31", "hold", 0, "hawkish",
     "Committee maintained the 1.25-1.50% range and signaled gradual further increases "
     "with inflation approaching the 2% target."),
    ("2018-03-21", "hike", 25, "hawkish",
     "Rates raised to 1.50-1.75%. Dot plot showed 3 total hikes projected for 2018, "
     "with growth outlook upgraded."),
    ("2018-05-02", "hold", 0, "neutral",
     "Rates held at 1.50-1.75%. Statement described inflation as near the 2% objective."),
    ("2018-06-13", "hike", 25, "hawkish",
     "Rates raised to 1.75-2.00%. Dot plot upgraded to 4 total hikes in 2018 "
     "(from 3 previously projected)."),
    ("2018-08-01", "hold", 0, "hawkish",
     "Rates held at 1.75-2.00%. Statement reiterated that further gradual increases "
     "would likely be appropriate."),
    ("2018-09-26", "hike", 25, "hawkish",
     "Rates raised to 2.00-2.25%. Committee dropped 'accommodative' language from "
     "statement, signaling approach to neutral."),
    ("2018-11-08", "hold", 0, "hawkish",
     "Rates held at 2.00-2.25%. Statement maintained hawkish tone despite recent "
     "equity market turmoil."),
    ("2018-12-19", "hike", 25, "hawkish",
     "Rates raised to 2.25-2.50%. Dot plot showed 2 additional hikes for 2019 "
     "(down from 3 previously) amid volatile markets."),

    # 2019 — pivot + cuts
    ("2019-01-30", "hold", 0, "dovish",
     "Rates held at 2.25-2.50%. Statement introduced 'patient' language, removing "
     "the prior bias toward further hikes."),
    ("2019-03-20", "hold", 0, "dovish",
     "Rates held. Dot plot projected zero hikes in 2019 (down from 2). Balance sheet "
     "runoff to end in September."),
    ("2019-05-01", "hold", 0, "neutral",
     "Rates held at 2.25-2.50%. Committee described policy stance as appropriate."),
    ("2019-06-19", "hold", 0, "dovish",
     "Rates held. Statement removed 'patient' language, opening the door to cuts. "
     "Markets priced in July cut."),
    ("2019-07-31", "cut", 25, "neutral",
     "Rates cut to 2.00-2.25%, first cut since the 2008 financial crisis. Powell "
     "described the move as a 'mid-cycle adjustment', not a new easing cycle."),
    ("2019-09-18", "cut", 25, "neutral",
     "Rates cut to 1.75-2.00%. Committee was divided, with 3 dissenters."),
    ("2019-10-30", "cut", 25, "hawkish",
     "Rates cut to 1.50-1.75%. Statement dropped 'act as appropriate' language, "
     "signaling a pause."),
    ("2019-12-11", "hold", 0, "neutral",
     "Rates held at 1.50-1.75%. Dot plot showed no changes projected for 2020."),

    # 2020 — COVID emergency + ZIRP
    ("2020-01-29", "hold", 0, "neutral",
     "Rates held at 1.50-1.75%. Powell noted the coronavirus outbreak as an emerging risk."),
    ("2020-03-03", "emergency_cut", 50, "dovish",
     "Emergency inter-meeting cut of 50bp to 1.00-1.25% in response to coronavirus "
     "economic shock."),
    ("2020-03-15", "emergency_cut", 100, "dovish",
     "Sunday emergency cut of 100bp to 0.00-0.25% (ZIRP). $700B QE announced. "
     "Dollar swap lines with major central banks."),
    ("2020-04-29", "hold", 0, "dovish",
     "Rates held at zero. Statement committed to maintain rate range 'until confident "
     "economy has weathered recent events'."),
    ("2020-06-10", "hold", 0, "dovish",
     "Rates held at zero. Dot plot showed no hikes through 2022. Asset purchases "
     "continued at current pace."),
    ("2020-07-29", "hold", 0, "dovish",
     "Rates held at zero. Commitment to use all tools to support economy."),
    ("2020-09-16", "hold", 0, "dovish",
     "Rates held at zero. New forward guidance: no hikes until inflation is on track "
     "to moderately exceed 2% for some time (AIT framework)."),
    ("2020-11-05", "hold", 0, "dovish",
     "Rates held at zero. Statement acknowledged rising COVID case counts as a risk."),
    ("2020-12-16", "hold", 0, "dovish",
     "Rates held at zero. Asset purchase guidance linked to 'substantial further "
     "progress' toward inflation and employment goals."),

    # 2021 — easy policy with taper signals
    ("2021-01-27", "hold", 0, "dovish",
     "Rates held at zero. Committee noted pace of recovery had moderated."),
    ("2021-03-17", "hold", 0, "dovish",
     "Rates held at zero. Dot plot still showed no hikes through 2023 despite upgraded "
     "growth forecasts. Yields surged on reflation outlook."),
    ("2021-04-28", "hold", 0, "dovish",
     "Rates held at zero. Powell described recent inflation as 'transitory'."),
    ("2021-06-16", "hold", 0, "hawkish",
     "Rates held. Dot plot shifted to 2 hikes in 2023, up from no hikes projected "
     "in March. Discussion of tapering has begun."),
    ("2021-07-28", "hold", 0, "neutral",
     "Rates held at zero. Powell acknowledged progress toward taper criteria but said "
     "'substantial further progress' still needed."),
    ("2021-09-22", "hold", 0, "hawkish",
     "Rates held. Dot plot: half of members project a 2022 hike. Powell signaled "
     "tapering could be announced as soon as November."),
    ("2021-11-03", "hold", 0, "neutral",
     "Rates held at zero. $15B/month tapering of asset purchases officially announced, "
     "ending in mid-2022."),
    ("2021-12-15", "hold", 0, "hawkish",
     "Rates held. Taper accelerated to $30B/month, ending in March. Dot plot: 3 hikes "
     "projected for 2022 (up from 0-1)."),

    # 2022 — aggressive hiking
    ("2022-01-26", "hold", 0, "hawkish",
     "Rates held at zero. Powell signaled first hike 'soon' in March."),
    ("2022-03-16", "hike", 25, "hawkish",
     "Rates raised to 0.25-0.50%, first hike since 2018. Balance sheet reduction "
     "planning begun. Dot plot: 6 more hikes in 2022."),
    ("2022-05-04", "hike", 50, "hawkish",
     "Rates raised to 0.75-1.00%, largest hike since 2000. QT confirmed to start June 1 "
     "at $47.5B/month."),
    ("2022-06-15", "hike", 75, "hawkish",
     "Rates raised to 1.50-1.75%, largest hike since 1994 after surprise CPI reading. "
     "Peak rate projected above 3.75%."),
    ("2022-07-27", "hike", 75, "hawkish",
     "Rates raised to 2.25-2.50%. Powell noted 'another unusually large increase' "
     "possible if data warrants."),
    ("2022-09-21", "hike", 75, "hawkish",
     "Rates raised to 3.00-3.25%. Dot plot: peak rate above 4.5% in 2023, "
     "up from 3.75% previously."),
    ("2022-11-02", "hike", 75, "hawkish",
     "Rates raised to 3.75-4.00%. Statement hinted at slower pace but Powell said "
     "peak rate will be higher than September projections."),
    ("2022-12-14", "hike", 50, "hawkish",
     "Rates raised to 4.25-4.50%. Dot plot: peak rate above 5%, down-shifted pace. "
     "Powell: higher-for-longer."),

    # 2023 — hiking slows, pauses, dovish shift
    ("2023-02-01", "hike", 25, "neutral",
     "Rates raised to 4.50-4.75%. Statement acknowledged 'ongoing hikes' still "
     "appropriate but size reduced."),
    ("2023-03-22", "hike", 25, "dovish",
     "Rates raised to 4.75-5.00% despite banking stress (SVB collapse). Statement "
     "softened language on future hikes."),
    ("2023-05-03", "hike", 25, "dovish",
     "Rates raised to 5.00-5.25%. Statement dropped 'some additional' hikes language, "
     "opening door to pause."),
    ("2023-06-14", "hold", 0, "hawkish",
     "Rates held at 5.00-5.25%, first pause in 15 months. But dot plot projected "
     "2 more hikes in 2023."),
    ("2023-07-26", "hike", 25, "neutral",
     "Rates raised to 5.25-5.50%. Powell: data-dependent on future hikes."),
    ("2023-09-20", "hold", 0, "hawkish",
     "Rates held at 5.25-5.50%. Dot plot: 1 more hike in 2023, fewer cuts in 2024."),
    ("2023-11-01", "hold", 0, "dovish",
     "Rates held. Powell acknowledged higher bond yields had tightened financial "
     "conditions, reducing need for more hikes."),
    ("2023-12-13", "hold", 0, "dovish",
     "Rates held. Dot plot: 3 cuts projected for 2024 (up from 2). Powell confirmed "
     "discussion of cuts has begun."),

    # 2024 — the long hold, then cutting
    ("2024-01-31", "hold", 0, "neutral",
     "Rates held at 5.25-5.50%. Powell said March cut unlikely; committee needs "
     "more confidence inflation is falling."),
    ("2024-03-20", "hold", 0, "dovish",
     "Rates held. Dot plot: maintained 3 cuts projected for 2024 despite hotter "
     "recent CPI readings."),
    ("2024-05-01", "hold", 0, "hawkish",
     "Rates held. Powell acknowledged progress on inflation has stalled; "
     "cuts delayed but still likely."),
    ("2024-06-12", "hold", 0, "hawkish",
     "Rates held. Dot plot: only 1 cut projected for 2024 (down from 3 in March)."),
    ("2024-07-31", "hold", 0, "dovish",
     "Rates held at 5.25-5.50%. Powell said cut 'could be on the table' at the next "
     "September meeting."),
    ("2024-09-18", "cut", 50, "dovish",
     "Rates cut to 4.75-5.00%, larger than the 25bp many expected. Powell framed it "
     "as a 'recalibration', not a recession response."),
    ("2024-11-07", "cut", 25, "neutral",
     "Rates cut to 4.50-4.75%. Committee unanimous. Post-election statement "
     "little-changed."),
    ("2024-12-18", "cut", 25, "hawkish",
     "Rates cut to 4.25-4.50% but dot plot projected only 2 cuts in 2025 "
     "(down from 4). Fed sees slower easing path."),
]


def fomc_expected_direction(
    decision: str, bp: int, tone: str, commodity: str,
) -> tuple[str, float, str]:
    """Return (direction, confidence, rationale) for a given FOMC outcome + commodity.

    Commodity ∈ {gold, silver}: rate up → bearish, rate down → bullish.
    Hawkish-in-hold tightens more than hawkish-in-cut; tone modulates.
    """
    # Baseline: cuts bullish for PM, hikes bearish, holds neutral
    if decision in ("cut", "emergency_cut"):
        d, conf = "bullish", 0.65
    elif decision == "hike":
        d, conf = "bearish", 0.60
    else:  # hold
        d, conf = "neutral", 0.45

    # Adjust by tone surprise
    if tone == "hawkish" and decision in ("hold", "cut"):
        # Hawkish cut / hawkish hold = less bullish or even bearish
        if decision == "cut":
            conf = max(0.40, conf - 0.20)
        else:  # hawkish hold
            d, conf = "bearish", 0.50
    elif tone == "dovish" and decision in ("hold", "hike"):
        if decision == "hike":
            conf = max(0.40, conf - 0.15)
        else:  # dovish hold
            d, conf = "bullish", 0.50

    rationale = f"Fed {decision} ({bp}bp) with {tone} tone. "
    if commodity in ("gold", "silver"):
        rationale += "Rate moves inversely drive precious metal opportunity cost."
    return d, conf, rationale


def fomc_news_text(date: str, decision: str, bp: int, context: str) -> str:
    """Build realistic news text from the structured decision."""
    prefix_map = {
        "hike": f"The Federal Reserve raised interest rates by {bp} basis points",
        "cut": f"The Federal Reserve cut interest rates by {bp} basis points",
        "emergency_cut": f"The Federal Reserve announced an emergency {bp} basis point "
                        "rate cut between regularly scheduled meetings",
        "hold": "The Federal Reserve held interest rates steady",
    }
    prefix = prefix_map.get(decision, "The Federal Reserve met")
    return f"{prefix} at the FOMC meeting on {date}. {context}"


def build_fomc_events() -> list[dict]:
    events = []
    for date, decision, bp, tone, context in FOMC_MEETINGS:
        cluster_id = f"fomc_{date.replace('-', '')}"
        news = fomc_news_text(date, decision, bp, context)
        for commodity in ("gold", "silver"):
            direction, conf, rationale = fomc_expected_direction(
                decision, bp, tone, commodity,
            )
            # Timeframe: 1-bp shifts often fade; dovish/hawkish surprises last longer
            timeframe = "medium_term" if tone in ("hawkish", "dovish") else "short_term"
            events.append({
                "event_id": f"fomc_{commodity}_{date.replace('-', '')}",
                "date": date,
                "commodity": commodity,
                "news_text": news,
                "expected_direction": direction,
                "expected_timeframe": timeframe,
                "analyst_rationale": rationale,
                "event_type": "monetary",
                "event_cluster_id": cluster_id,
                "generator": "fomc_template",
            })
    return events


# ============================================================================
# OPEC / OPEC+ MAJOR DECISIONS 2018-2024
# (date, decision, magnitude_mbpd, cluster_id, context)
# decision ∈ {"cut", "increase", "hold", "extend", "surprise_cut"}
# ============================================================================
OPEC_MEETINGS: list[tuple[str, str, float, str, str]] = [
    # 2018
    ("2018-06-22", "increase", 1.0, "opec_jun2018",
     "OPEC agreed at Vienna meeting to raise production by 1 million bpd to moderate "
     "prices, reversing the 2017 cut."),
    ("2018-12-07", "cut", 1.2, "opec_dec2018",
     "OPEC+ agreed to cut oil production by 1.2 million barrels per day starting "
     "January 2019, responding to demand concerns and US shale growth."),
    # 2019
    ("2019-07-01", "extend", 1.2, "opec_jul2019",
     "OPEC+ extended the existing 1.2 million bpd production cuts for another 9 months."),
    ("2019-12-05", "cut", 0.5, "opec_dec2019",
     "OPEC+ agreed to deepen production cuts by an additional 500,000 bpd, "
     "totaling 1.7 million bpd."),
    # 2020 — price war + COVID emergency
    ("2020-03-06", "increase", 2.0, "opec_mar2020_breakup",
     "OPEC+ talks collapsed. Saudi Arabia signaled plans to increase production and "
     "offer discounts, initiating a price war with Russia."),
    ("2020-04-12", "cut", 9.7, "opec_apr2020_emergency",
     "OPEC+ agreed to the largest production cut in history — 9.7 million barrels per day — "
     "effective May 2020 to address the COVID demand collapse."),
    ("2020-06-06", "extend", 9.7, "opec_jun2020",
     "OPEC+ extended the 9.7 million bpd production cut for another month "
     "through July 2020."),
    ("2020-12-03", "increase", 0.5, "opec_dec2020",
     "OPEC+ agreed to a modest 500,000 bpd production increase in January 2021 "
     "instead of the previously planned 2 million bpd."),
    # 2021
    ("2021-01-05", "cut", 1.0, "opec_jan2021_saudi",
     "Saudi Arabia announced a voluntary 1 million bpd production cut for February "
     "and March 2021."),
    ("2021-04-01", "increase", 2.1, "opec_apr2021",
     "OPEC+ agreed to gradually increase production by 2.1 million bpd over May-July."),
    ("2021-07-18", "increase", 0.4, "opec_jul2021",
     "OPEC+ resolved the UAE-Saudi dispute and agreed to gradually raise production "
     "by 400,000 bpd monthly from August."),
    # 2022 — war + price war response
    ("2022-05-05", "increase", 0.4, "opec_may2022",
     "OPEC+ maintained its scheduled 432,000 bpd monthly increase despite Russia "
     "sanctions disrupting supply."),
    ("2022-09-05", "cut", 0.1, "opec_sep2022",
     "OPEC+ announced a symbolic 100,000 bpd production cut for October."),
    ("2022-10-05", "cut", 2.0, "opec_oct2022",
     "OPEC+ agreed to cut oil production by 2 million barrels per day starting November, "
     "largest cut since 2020 despite US pressure."),
    ("2022-12-05", "hold", 0.0, "opec_dec2022",
     "OPEC+ maintained existing 2 Mbpd production cuts, same day as G7 Russia oil price "
     "cap took effect."),
    # 2023
    ("2023-04-03", "surprise_cut", 1.16, "opec_apr2023",
     "OPEC+ announced a surprise voluntary production cut of 1.16 million barrels per "
     "day starting May, on top of existing cuts."),
    ("2023-06-04", "extend", 1.66, "opec_jun2023",
     "OPEC+ extended voluntary production cuts through end of 2024. Saudi Arabia added "
     "an extra 1 million bpd voluntary cut for July."),
    ("2023-08-03", "extend", 1.0, "opec_aug2023_saudi",
     "Saudi Arabia extended the 1 million bpd voluntary cut through September."),
    ("2023-09-05", "extend", 1.0, "opec_sep2023_saudi",
     "Saudi Arabia extended the 1 million bpd voluntary cut through the end of 2023."),
    ("2023-11-30", "extend", 2.2, "opec_nov2023",
     "OPEC+ agreed to extend voluntary production cuts of 2.2 million bpd "
     "through Q1 2024."),
    # 2024
    ("2024-03-03", "extend", 2.2, "opec_mar2024",
     "OPEC+ extended voluntary production cuts of 2.2 million bpd through Q2 2024."),
    ("2024-06-02", "increase", 2.2, "opec_jun2024",
     "OPEC+ agreed to gradually unwind voluntary production cuts starting October 2024, "
     "phased over 12 months."),
    ("2024-09-05", "extend", 2.2, "opec_sep2024",
     "OPEC+ delayed the planned production increase by 2 months to December 2024."),
    ("2024-11-03", "extend", 2.2, "opec_nov2024",
     "OPEC+ delayed the planned unwinding of voluntary cuts by another month."),
    ("2024-12-05", "extend", 2.2, "opec_dec2024",
     "OPEC+ further delayed the planned unwinding of voluntary cuts until April 2025, "
     "with a slower phase-in through 2026."),
]


def opec_expected_direction(decision: str, magnitude: float) -> tuple[str, float, str]:
    """Return (direction, confidence, rationale) for an OPEC+ decision on oil."""
    if decision == "surprise_cut" or (decision == "cut" and magnitude >= 1.0):
        return "bullish", 0.75, (
            f"OPEC+ {decision} of {magnitude:.1f} Mbpd materially tightens supply.")
    if decision == "cut":
        return "bullish", 0.55, (
            f"OPEC+ {decision} of {magnitude:.1f} Mbpd is a supportive signal.")
    if decision == "extend":
        return "bullish", 0.50, (
            f"OPEC+ extension of {magnitude:.1f} Mbpd cuts maintains supply restraint.")
    if decision == "increase" and magnitude >= 1.0:
        return "bearish", 0.60, (
            f"OPEC+ {decision} of {magnitude:.1f} Mbpd loosens supply.")
    if decision == "increase":
        return "bearish", 0.45, (
            f"Modest OPEC+ {decision} of {magnitude:.1f} Mbpd adds marginal supply.")
    return "neutral", 0.40, "OPEC+ maintained existing policy; no material supply change."


def build_opec_events() -> list[dict]:
    events = []
    for date, decision, magnitude, cluster_id, context in OPEC_MEETINGS:
        direction, conf, rationale = opec_expected_direction(decision, magnitude)
        timeframe = "short_term" if decision in ("surprise_cut", "increase") else "medium_term"
        for commodity in ("crude_oil_wti", "crude_oil_brent"):
            events.append({
                "event_id": f"opec_{commodity}_{date.replace('-', '')}",
                "date": date,
                "commodity": commodity,
                "news_text": context,
                "expected_direction": direction,
                "expected_timeframe": timeframe,
                "analyst_rationale": rationale,
                "event_type": "opec",
                "event_cluster_id": cluster_id,
                "generator": "opec_template",
            })
    return events


# ============================================================================
# CPI MONTHLY PRINTS 2018-2024 (selected surprising ones)
# (date, surprise, tone, context)
# surprise: "hot" / "cool" / "inline"
# ============================================================================
CPI_PRINTS: list[tuple[str, str, str]] = [
    # (date, surprise, context)
    ("2018-07-12", "hot", "US June CPI rose 2.9% YoY, highest since 2012."),
    ("2019-01-11", "cool", "US December CPI rose 1.9% YoY, below 2.1% consensus."),
    ("2019-09-12", "inline", "US August CPI rose 1.7% YoY, matching consensus."),
    ("2021-05-12", "hot", "US April CPI surged 4.2% YoY, well above 3.6% consensus, "
                          "triggering inflation debate."),
    ("2021-06-10", "hot", "US May CPI rose 5.0% YoY, 13-year high; core at 3.8%."),
    ("2021-07-13", "hot", "US June CPI rose 5.4% YoY. Powell's 'transitory' thesis "
                          "increasingly questioned."),
    ("2021-10-13", "hot", "US September CPI rose 5.4% YoY."),
    ("2021-11-10", "hot", "US October CPI rose 6.2% YoY, 31-year high."),
    ("2022-01-12", "hot", "US December CPI rose 7.0% YoY, fastest since 1982."),
    ("2022-02-10", "hot", "US January CPI rose 7.5% YoY, accelerating from December."),
    ("2022-06-10", "hot", "US May CPI rose 8.6% YoY, above 8.3% consensus, new "
                          "40-year high. Gasoline at record."),
    ("2022-07-13", "hot", "US June CPI rose 9.1% YoY, above 8.8% consensus, "
                          "widely expected Fed 75bp hike."),
    ("2022-10-13", "hot", "US September CPI rose 8.2% YoY, core accelerated to 6.6%."),
    ("2022-11-10", "cool", "US October CPI rose 7.7% YoY, below 7.9% consensus. "
                           "Core decelerated for first time in months."),
    ("2023-01-12", "cool", "US December CPI fell 0.1% MoM, inflation decelerating."),
    ("2023-02-14", "hot", "US January CPI rose 6.4% YoY, slightly above 6.2% consensus. "
                          "Core moderating."),
    ("2023-07-12", "cool", "US June CPI rose 3.0% YoY, below 3.1% consensus, "
                           "cooling disinflation narrative."),
    ("2023-09-13", "inline", "US August CPI rose 3.7% YoY, in line with consensus."),
    ("2024-02-13", "hot", "US January CPI rose 3.1% YoY, above 2.9% consensus."),
    ("2024-03-12", "hot", "US February CPI rose 3.2% YoY, slightly above 3.1% consensus."),
    ("2024-04-10", "hot", "US March CPI rose 3.5% YoY, third hot print. Fed cut bets "
                          "pushed out."),
    ("2024-05-15", "cool", "US April CPI rose 3.4% YoY, core at 3.6% lowest since 2021."),
    ("2024-07-11", "cool", "US June CPI fell 0.1% MoM, first decline since 2020."),
]


def cpi_expected_direction(surprise: str, commodity: str) -> tuple[str, float, str]:
    """Map CPI surprise to commodity direction."""
    if commodity == "gold":
        if surprise == "hot":
            # Hot CPI → dollar up, rates up → bearish gold near-term
            # BUT also: inflation hedge demand → competing narratives
            return "bearish", 0.50, "Hot CPI raises Fed hawkishness; dollar strengthens."
        if surprise == "cool":
            return "bullish", 0.55, "Cooling inflation opens door to Fed cuts; yields fall."
        return "neutral", 0.40, "In-line CPI; limited catalyst."
    return "neutral", 0.35, "Limited direct commodity channel."


def build_cpi_events() -> list[dict]:
    events = []
    for date, surprise, context in CPI_PRINTS:
        direction, conf, rationale = cpi_expected_direction(surprise, "gold")
        events.append({
            "event_id": f"cpi_gold_{date.replace('-', '')}",
            "date": date,
            "commodity": "gold",
            "news_text": context,
            "expected_direction": direction,
            "expected_timeframe": "short_term",
            "analyst_rationale": rationale,
            "event_type": "macro",
            "event_cluster_id": f"cpi_{date.replace('-', '')}",
            "generator": "cpi_template",
        })
    return events


# ============================================================================
# ADDITIONAL MAJOR EVENTS (hand-curated for diversity)
# These fill gaps: natural gas, wheat/corn weather, copper-China, neutral cases
# ============================================================================
ADDITIONAL_EVENTS: list[dict] = [
    # --- Natural gas ---
    {"event_id": "ng_plains_cold_20180101", "date": "2018-01-03",
     "commodity": "natural_gas",
     "news_text": "Major cold snap grips US Northeast; natural gas heating demand surges "
                  "with windchill-adjusted temperatures below -20F.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Extreme cold spikes gas heating demand.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "ng_mild_20190115", "date": "2019-01-15",
     "commodity": "natural_gas",
     "news_text": "US weather models shifted warmer for late January; natural gas "
                  "storage remains above 5-year average.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Warm forecast + ample storage pressure prices.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "ng_eu_storage_20200901", "date": "2020-09-01",
     "commodity": "natural_gas",
     "news_text": "European natural gas storage hit 93% full, above the 5-year average "
                  "heading into autumn.",
     "expected_direction": "bearish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Full storage reduces winter import urgency.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "ng_freeport_fire_20220608", "date": "2022-06-08",
     "commodity": "natural_gas",
     "news_text": "Freeport LNG export terminal caught fire, forcing extended shutdown. "
                  "Plant represents ~17% of US LNG export capacity.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "US gas trapped onshore = domestic glut near-term.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "ng_winter_storm_20221220", "date": "2022-12-20",
     "commodity": "natural_gas",
     "news_text": "Winter Storm Elliott brought arctic blast across US; gas production "
                  "freeze-offs in Appalachia reported.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Storm-driven demand spike plus supply freeze-offs.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "ng_warm_winter_20230215", "date": "2023-02-15",
     "commodity": "natural_gas",
     "news_text": "European natural gas futures fell below €50/MWh for first time since "
                  "September 2021 on unseasonably warm winter.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Warm winter + high storage = demand destruction.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "ng_houthi_qatar_20240115", "date": "2024-01-15",
     "commodity": "natural_gas",
     "news_text": "Houthi attacks on Red Sea shipping forced Qatar to reroute LNG "
                  "cargoes around Cape of Good Hope, adding weeks to deliveries.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Shipping disruption tightens spot LNG availability in Europe.",
     "event_type": "geopolitical", "generator": "manual"},
    {"event_id": "ng_eu_mild_20241115", "date": "2024-11-15",
     "commodity": "natural_gas",
     "news_text": "European natural gas prices spike on fears Russian transit via "
                  "Ukraine will end with Dec 31 contract expiry.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Loss of transit pipeline tightens EU gas supply winter 2024.",
     "event_type": "geopolitical", "generator": "manual"},

    # --- Silver additions ---
    {"event_id": "silver_industrial_20210401", "date": "2021-04-01",
     "commodity": "silver",
     "news_text": "Silver surged above $25/oz on rising solar panel demand and green "
                  "transition narratives.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Industrial + monetary dual demand.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "silver_squeeze_2_20211001", "date": "2021-10-01",
     "commodity": "silver",
     "news_text": "Silver stuck in range below $24/oz despite industrial demand "
                  "narrative; dollar strength caps metals.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "Conflicting drivers; range-bound.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "silver_dollar_20220115", "date": "2022-01-15",
     "commodity": "silver",
     "news_text": "Silver dropped below $23/oz as dollar index hit 95 on Fed hike "
                  "expectations.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Dollar strength + rising real yields pressure silver.",
     "event_type": "monetary", "generator": "manual"},
    {"event_id": "silver_gold_ratio_20230201", "date": "2023-02-01",
     "commodity": "silver",
     "news_text": "Gold-silver ratio compressed below 80 as silver caught up to gold's rally.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Silver outperforming in monetary rally phases.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "silver_break_20240510", "date": "2024-05-10",
     "commodity": "silver",
     "news_text": "Silver surged to 11-year high above $28/oz on dovish Fed expectations "
                  "and tight physical supply.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Breakout on monetary + industrial demand.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "silver_industrial_demand_20240915", "date": "2024-09-15",
     "commodity": "silver",
     "news_text": "Silver Institute reported 2024 solar silver demand forecast raised "
                  "20% to record levels.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Structural solar demand growth supports silver.",
     "event_type": "supply_disruption", "generator": "manual"},

    # --- Copper ---
    {"event_id": "copper_chile_strike_20191022", "date": "2019-10-22",
     "commodity": "copper",
     "news_text": "Chile's Escondida mine workers voted to reject contract offer, "
                  "raising strike risk at world's largest copper mine.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Potential supply disruption at key mine.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "copper_china_pmi_weak_20220131", "date": "2022-01-30",
     "commodity": "copper",
     "news_text": "China manufacturing PMI fell to 50.1 in January, just above "
                  "contraction line.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Weakening Chinese demand pressure on base metals.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "copper_ev_demand_20230410", "date": "2023-04-10",
     "commodity": "copper",
     "news_text": "Goldman Sachs raised copper demand forecast citing accelerating EV "
                  "adoption and grid investment.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Structural demand upgrade from energy transition.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "copper_china_property_20230718", "date": "2023-07-18",
     "commodity": "copper",
     "news_text": "China Country Garden missed bond payments; property sector stress "
                  "intensifies.",
     "expected_direction": "bearish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Property collapse destroys major copper demand.",
     "event_type": "financial_crisis", "generator": "manual"},
    {"event_id": "copper_first_quantum_20231128", "date": "2023-11-28",
     "commodity": "copper",
     "news_text": "Panama ordered First Quantum Cobre mine closed after Supreme Court "
                  "ruling, removing 1% of global copper supply.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Unexpected mine closure removes supply.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "copper_chile_output_20240302", "date": "2024-03-01",
     "commodity": "copper",
     "news_text": "Chile copper output fell 3% YoY in February amid ore grade declines.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Structural production decline in largest producer.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "copper_china_pmi_recovery_20240531", "date": "2024-05-31",
     "commodity": "copper",
     "news_text": "China May manufacturing PMI rebounded to 50.4, above consensus.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Chinese factory recovery supports industrial metals.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "copper_cofco_20240912", "date": "2024-09-12",
     "commodity": "copper",
     "news_text": "Copper fell 2% as China credit data disappointed, new loans "
                  "hit 15-year low for August.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Weak Chinese credit suggests slow metals demand.",
     "event_type": "macro", "generator": "manual"},

    # --- Wheat/corn ---
    {"event_id": "wheat_australia_drought_20180911", "date": "2018-09-11",
     "commodity": "wheat",
     "news_text": "Australia's ABARES cut wheat harvest forecast 12% to 19.1M tonnes "
                  "amid persistent eastern drought.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Major exporter's lower harvest tightens global supply.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "corn_china_buy_20200713", "date": "2020-07-13",
     "commodity": "corn",
     "news_text": "China purchased 1.76M tonnes of US corn, largest single-day "
                  "purchase on record.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Record Chinese buying signals strong demand.",
     "event_type": "trade_policy", "generator": "manual"},
    {"event_id": "corn_brazil_safrinha_20210621", "date": "2021-06-21",
     "commodity": "corn",
     "news_text": "Brazil safrinha corn harvest forecast cut 15% after severe "
                  "drought and frost damage.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Major second-crop shortfall tightens global balance.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "wheat_french_harvest_20210715", "date": "2021-07-15",
     "commodity": "wheat",
     "news_text": "French wheat harvest disappointing; protein content lowest in years "
                  "due to wet summer.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "EU quality shortfall reduces milling supply.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "corn_ethanol_20220422", "date": "2022-04-22",
     "commodity": "corn",
     "news_text": "Biden administration authorized year-round E15 ethanol sales to "
                  "reduce gasoline prices.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Expanded ethanol mandate increases corn demand.",
     "event_type": "trade_policy", "generator": "manual"},
    {"event_id": "corn_russia_grain_deal_20220722", "date": "2022-07-22",
     "commodity": "corn",
     "news_text": "Russia and Ukraine signed UN-brokered grain export deal; Black Sea "
                  "corridor to reopen.",
     "expected_direction": "bearish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Resumed exports add significant supply.",
     "event_type": "geopolitical", "generator": "manual"},
    {"event_id": "wheat_usda_may_20230512", "date": "2023-05-12",
     "commodity": "wheat",
     "news_text": "USDA May WASDE showed US 2023/24 wheat ending stocks at 556M bushels, "
                  "lowest since 2007/08.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Tight US stocks support prices.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "corn_china_cancel_20240308", "date": "2024-03-08",
     "commodity": "corn",
     "news_text": "China cancelled 500k tonnes of US corn purchases, shifting to "
                  "cheaper Brazilian and Ukrainian supplies.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Lost Chinese demand pressures US prices.",
     "event_type": "trade_policy", "generator": "manual"},

    # --- Neutral / in-line events (important for calibration) ---
    {"event_id": "fed_hold_neutral_20180801", "date": "2018-08-01",
     "commodity": "gold",
     "news_text": "Fed held rates at 1.75-2.00% as widely expected; statement language "
                  "unchanged from prior meeting.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "No surprise; prior guidance reaffirmed.",
     "event_type": "monetary", "generator": "manual"},
    {"event_id": "opec_inline_20210101", "date": "2021-02-03",
     "commodity": "crude_oil_wti",
     "news_text": "OPEC+ Joint Ministerial Monitoring Committee maintained existing "
                  "policy guidance with no new decisions.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "No change from prior guidance.",
     "event_type": "opec", "generator": "manual"},
    {"event_id": "usda_corn_inline_20190712", "date": "2019-07-12",
     "commodity": "corn",
     "news_text": "USDA July WASDE left corn production estimate unchanged at 13.875B "
                  "bushels, matching consensus.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "In-line report; no catalyst.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "china_pmi_inline_20200701", "date": "2020-07-01",
     "commodity": "copper",
     "news_text": "China June manufacturing PMI 50.9, in line with consensus.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "In-line data; no surprise.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "cpi_inline_20221213", "date": "2022-12-13",
     "commodity": "gold",
     "news_text": "US November CPI rose 7.1% YoY, slightly below 7.3% consensus but "
                  "still elevated.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "Mixed signal; high absolute level offsets softer surprise.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "eia_inline_20230607", "date": "2023-06-07",
     "commodity": "crude_oil_wti",
     "news_text": "EIA weekly crude inventories fell 451k barrels, close to consensus "
                  "for 1M barrel draw.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "Near-consensus draw; minor catalyst.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "nfp_inline_20231103", "date": "2023-11-03",
     "commodity": "gold",
     "news_text": "US October jobs report added 150k, near consensus 180k; unemployment "
                  "rose to 3.9%.",
     "expected_direction": "neutral", "expected_timeframe": "short_term",
     "analyst_rationale": "Near-consensus report; mild labor cooling.",
     "event_type": "macro", "generator": "manual"},

    # --- Gold mine disruptions & central bank buying ---
    {"event_id": "gold_cb_buying_20220101", "date": "2022-01-18",
     "commodity": "gold",
     "news_text": "World Gold Council reported central banks purchased 463t of gold in "
                  "2021, highest since 1967.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Structural central-bank demand supports prices.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "gold_russian_reserves_20220228", "date": "2022-02-28",
     "commodity": "gold",
     "news_text": "G7 sanctions targeted Russian central bank reserves, prompting "
                  "speculation about reserve diversification globally.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Reserve diversification accelerates CB gold demand.",
     "event_type": "geopolitical", "generator": "manual"},
    {"event_id": "gold_bric_summit_20230822", "date": "2023-08-22",
     "commodity": "gold",
     "news_text": "BRICS summit discussed de-dollarization and potential gold-backed "
                  "reserve currency; no concrete agreement.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "De-dollarization narrative supports gold demand.",
     "event_type": "geopolitical", "generator": "manual"},
    {"event_id": "gold_china_buying_20240301", "date": "2024-03-01",
     "commodity": "gold",
     "news_text": "People's Bank of China reported 16th consecutive month of gold "
                  "purchases, adding to already-record reserves.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Sustained CB demand from largest buyer.",
     "event_type": "macro", "generator": "manual"},

    # --- Oil supply disruptions ---
    {"event_id": "oil_libya_20180707", "date": "2018-07-09",
     "commodity": "crude_oil_brent",
     "news_text": "Libya's Sharara oilfield (300k bpd) shut after armed attack; "
                  "eastern ports also blocked.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "~300k bpd supply outage from OPEC producer.",
     "event_type": "geopolitical", "generator": "manual"},
    {"event_id": "oil_hurricane_laura_20200826", "date": "2020-08-26",
     "commodity": "crude_oil_wti",
     "news_text": "Hurricane Laura strengthened to Category 4, targeting Gulf of Mexico "
                  "oil infrastructure. ~85% of Gulf output shut.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Major Gulf production outage.",
     "event_type": "weather", "generator": "manual"},
    {"event_id": "oil_libya_hafter_20200118", "date": "2020-01-18",
     "commodity": "crude_oil_brent",
     "news_text": "Libyan warlord Haftar ordered blockade of all eastern oil terminals, "
                  "halting 800k bpd of exports.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Major outage from disputed North African producer.",
     "event_type": "geopolitical", "generator": "manual"},
    {"event_id": "oil_iraq_kurdistan_20230325", "date": "2023-03-25",
     "commodity": "crude_oil_brent",
     "news_text": "Kurdistan pipeline to Turkey shut after arbitration ruling, halting "
                  "~450k bpd of Iraqi exports.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Protracted outage from Middle East producer.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "oil_norway_strike_20221005", "date": "2022-10-05",
     "commodity": "crude_oil_brent",
     "news_text": "Norwegian oil and gas workers announced strike starting October 9, "
                  "potentially cutting ~330k bpd output.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Strike threat to European supplier.",
     "event_type": "supply_disruption", "generator": "manual"},
    {"event_id": "oil_venezuela_sanctions_ease_20221126", "date": "2022-11-26",
     "commodity": "crude_oil_brent",
     "news_text": "US granted Chevron license to resume limited Venezuelan oil "
                  "production, easing some 2019 sanctions.",
     "expected_direction": "bearish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Modest supply addition from sanctions easing.",
     "event_type": "geopolitical", "generator": "manual"},

    # --- Dollar/macro events ---
    {"event_id": "dxy_plaza_20180816", "date": "2018-08-16",
     "commodity": "gold",
     "news_text": "Dollar index hit 14-month high above 96.5 as emerging market "
                  "contagion from Turkey spread.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Strong dollar pressures dollar-denominated commodities.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "dxy_tumble_20200730", "date": "2020-07-30",
     "commodity": "gold",
     "news_text": "Dollar index fell to 2-year low below 93 as Fed committed to "
                  "ultra-accommodative stance.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Weak dollar lifts gold.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "dxy_strong_20240318", "date": "2024-04-15",
     "commodity": "gold",
     "news_text": "Dollar index surged to 6-month high above 106 as Fed cut expectations "
                  "pushed out to late 2024.",
     "expected_direction": "bearish", "expected_timeframe": "short_term",
     "analyst_rationale": "Dollar strength pressures gold.",
     "event_type": "macro", "generator": "manual"},

    # --- Additional miscellaneous ---
    {"event_id": "oil_iran_seizure_20190719", "date": "2019-07-19",
     "commodity": "crude_oil_brent",
     "news_text": "Iran's IRGC seized a British-flagged tanker in the Strait of Hormuz, "
                  "escalating tensions with UK and US.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Hormuz tensions raise supply risk premium.",
     "event_type": "geopolitical", "generator": "manual"},
    {"event_id": "oil_keystone_20210120", "date": "2021-01-20",
     "commodity": "crude_oil_wti",
     "news_text": "Biden administration revoked permit for Keystone XL pipeline on "
                  "inauguration day.",
     "expected_direction": "bearish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Reduced long-run Canadian crude access; slight bearish for WTI "
                          "near-term (no new supply pressure).",
     "event_type": "trade_policy", "generator": "manual"},
    {"event_id": "silver_tesla_solar_20201030", "date": "2020-10-30",
     "commodity": "silver",
     "news_text": "Tesla Solar announced major solar panel manufacturing expansion "
                  "targeting 10GW annual output.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Solar demand directly lifts silver consumption.",
     "event_type": "macro", "generator": "manual"},
    {"event_id": "wheat_kazakh_ban_20220415", "date": "2022-04-15",
     "commodity": "wheat",
     "news_text": "Kazakhstan announced export quota on wheat amid regional food "
                  "security concerns.",
     "expected_direction": "bullish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Additional Central Asian supply removed from market.",
     "event_type": "trade_policy", "generator": "manual"},
    {"event_id": "gold_comex_delivery_20200323", "date": "2020-03-23",
     "commodity": "gold",
     "news_text": "COMEX gold futures disconnected from London spot as delivery issues "
                  "arose amid refinery lockdowns.",
     "expected_direction": "bullish", "expected_timeframe": "short_term",
     "analyst_rationale": "Physical delivery squeeze supports gold price.",
     "event_type": "market_structure", "generator": "manual"},
    {"event_id": "corn_mexico_gmo_20230213", "date": "2023-02-13",
     "commodity": "corn",
     "news_text": "Mexico issued decree phasing out GMO corn imports for human "
                  "consumption by 2024, adding trade friction with US.",
     "expected_direction": "bearish", "expected_timeframe": "medium_term",
     "analyst_rationale": "Reduced Mexican demand for US corn long-term.",
     "event_type": "trade_policy", "generator": "manual"},
]


def load_existing_events() -> list[dict]:
    """Load the hand-curated 144 events (if file exists)."""
    if not EVENTS_PATH.exists():
        return []
    with open(EVENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def merge_and_dedupe(all_events: list[dict]) -> list[dict]:
    """Remove duplicates by (event_id). Later entries win."""
    by_id: dict[str, dict] = {}
    for ev in all_events:
        by_id[ev["event_id"]] = ev
    return sorted(by_id.values(), key=lambda e: e["date"])


def main() -> None:
    existing = load_existing_events()
    print(f"Existing: {len(existing)} events")

    fomc = build_fomc_events()
    opec = build_opec_events()
    cpi = build_cpi_events()
    additional = ADDITIONAL_EVENTS

    print(f"  FOMC-generated: {len(fomc)}")
    print(f"  OPEC-generated: {len(opec)}")
    print(f"  CPI-generated: {len(cpi)}")
    print(f"  Manual additional: {len(additional)}")

    all_events = existing + fomc + opec + cpi + additional
    merged = merge_and_dedupe(all_events)

    # Stats
    from collections import Counter
    by_year = Counter(e["date"][:4] for e in merged)
    by_commodity = Counter(e["commodity"] for e in merged)
    by_direction = Counter(e["expected_direction"] for e in merged)
    by_event_type = Counter(e.get("event_type", "unknown") for e in merged)

    print(f"\nTOTAL after merge+dedup: {len(merged)}")
    print(f"By year: {dict(sorted(by_year.items()))}")
    print(f"By commodity: {dict(sorted(by_commodity.items()))}")
    print(f"By direction: {dict(sorted(by_direction.items()))}")
    print(f"By event type: {dict(sorted(by_event_type.items()))}")

    with open(EVENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {EVENTS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

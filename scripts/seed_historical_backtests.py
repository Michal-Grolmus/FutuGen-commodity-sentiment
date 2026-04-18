"""Seed data/signals_log.jsonl with historical commodity events.

For each curated historical event:
1. Predicts direction based on event context (what an analyst would have said
   AT THE TIME, not knowing the outcome).
2. Fetches actual Yahoo Finance closing price on the event date (price_then).
3. Fetches closing price N trading days later based on timeframe:
   - short_term: 1 trading day after
   - medium_term: 5 trading days after
4. Computes actual direction and correctness.
5. Writes fully populated backtest entry to the log.

Result: the dashboard's Backtest widget shows real accuracy from day 1.

Usage: python scripts/seed_historical_backtests.py
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "signals_log.jsonl"
NEUTRAL_THRESHOLD_PCT = 0.5

# Yahoo Finance tickers
TICKERS = {
    "crude_oil_wti": "CL=F",
    "crude_oil_brent": "BZ=F",
    "natural_gas": "NG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "wheat": "ZW=F",
    "corn": "ZC=F",
    "copper": "HG=F",
}

# Curated historical events. direction = prediction an analyst WOULD have made
# at the time based on the event context, without knowing the outcome.
HISTORICAL_EVENTS = [
    # --- 2022 ---
    {
        "date": "2022-02-24", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.88, "timeframe": "short_term",
        "rationale": "Russia invades Ukraine; major energy exporter, sanctions imminent, supply disruption risk.",
        "source_text": "Russian military forces have launched a full-scale invasion of Ukraine this morning.",
        "event_name": "russia_invades_ukraine",
    },
    {
        "date": "2022-02-24", "commodity": "wheat",
        "direction": "bullish", "confidence": 0.85, "timeframe": "medium_term",
        "rationale": "Ukraine is top-5 wheat exporter. War disrupts Black Sea shipping for months.",
        "source_text": "Russian military forces have launched a full-scale invasion of Ukraine.",
        "event_name": "russia_invades_ukraine_wheat",
    },
    {
        "date": "2022-02-24", "commodity": "natural_gas",
        "direction": "bullish", "confidence": 0.82, "timeframe": "medium_term",
        "rationale": "Russia supplies 40% of European gas. Sanctions will tighten supply for winter.",
        "source_text": "Russian invasion of Ukraine triggers European energy security concerns.",
        "event_name": "russia_invades_ukraine_gas",
    },
    {
        "date": "2022-10-19", "commodity": "crude_oil_wti",
        "direction": "bearish", "confidence": 0.65, "timeframe": "short_term",
        "rationale": "US announces additional 15M barrel SPR release. Short-term supply increase.",
        "source_text": "The Biden administration announced an additional 15 million barrel "
                       "release from the Strategic Petroleum Reserve.",
        "event_name": "spr_release",
    },
    # --- 2023 ---
    {
        "date": "2023-02-01", "commodity": "gold",
        "direction": "bearish", "confidence": 0.60, "timeframe": "short_term",
        "rationale": "Fed raises rates 25bp. Higher rates increase opportunity cost of holding gold.",
        "source_text": "The Federal Reserve raised its benchmark rate by 25 basis points today.",
        "event_name": "fed_feb2023_hike",
    },
    {
        "date": "2023-04-03", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.88, "timeframe": "short_term",
        "rationale": "Surprise OPEC+ production cut of 1.16M bpd starting May. Major supply tightening.",
        "source_text": "OPEC+ announced a voluntary production cut of 1.16 million barrels per day.",
        "event_name": "opec_apr2023_cut",
    },
    {
        "date": "2023-04-03", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.88, "timeframe": "short_term",
        "rationale": "Brent as international benchmark directly affected by OPEC+ supply cut.",
        "source_text": "OPEC+ announced a voluntary production cut of 1.16 million barrels per day.",
        "event_name": "opec_apr2023_cut_brent",
    },
    {
        "date": "2023-05-03", "commodity": "gold",
        "direction": "bearish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Fed raises rates 25bp to 5.25%. Continued hiking cycle pressures non-yielding gold.",
        "source_text": "The Federal Reserve raised rates by another 25 basis points to 5.25 percent.",
        "event_name": "fed_may2023_hike",
    },
    {
        "date": "2023-07-26", "commodity": "gold",
        "direction": "bearish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Fed raises rates 25bp to 5.50%. Restrictive policy stance continues.",
        "source_text": "The Federal Reserve raised rates by 25 basis points to 5.50 percent.",
        "event_name": "fed_jul2023_hike",
    },
    {
        "date": "2023-09-20", "commodity": "gold",
        "direction": "bullish", "confidence": 0.60, "timeframe": "medium_term",
        "rationale": "Fed pauses rate hikes. Dovish signal reduces opportunity cost of holding gold.",
        "source_text": "The Federal Reserve held rates steady, signaling a pause in the tightening cycle.",
        "event_name": "fed_sep2023_pause",
    },
    {
        "date": "2023-10-09", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.75, "timeframe": "short_term",
        "rationale": "Hamas attacks Israel; Middle East geopolitical risk premium spikes.",
        "source_text": "Hamas launched a surprise large-scale attack on Israel from Gaza.",
        "event_name": "israel_hamas_war",
    },
    {
        "date": "2023-11-30", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "OPEC+ extends 2.2M bpd voluntary production cuts into Q1 2024.",
        "source_text": "OPEC+ agreed to extend voluntary production cuts of 2.2 million bpd through Q1 2024.",
        "event_name": "opec_nov2023_extend",
    },
    # --- 2024 ---
    {
        "date": "2024-03-03", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "OPEC+ extends voluntary cuts through Q2 2024. Supply remains restricted.",
        "source_text": "OPEC+ extended voluntary production cuts of 2.2 million bpd through the second quarter.",
        "event_name": "opec_mar2024_extend",
    },
    {
        "date": "2024-04-01", "commodity": "gold",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "Geopolitical tensions in Middle East drive safe-haven demand for gold.",
        "source_text": "Middle East tensions escalate with reported Israeli strike on Iranian consulate in Damascus.",
        "event_name": "iran_tensions_gold",
    },
    {
        "date": "2024-07-31", "commodity": "gold",
        "direction": "bullish", "confidence": 0.65, "timeframe": "short_term",
        "rationale": "Fed signals upcoming rate cuts. Lower real yields support gold.",
        "source_text": "Fed Chair Powell signaled that rate cuts are likely at the next meeting.",
        "event_name": "fed_jul2024_signal",
    },
    {
        "date": "2024-09-18", "commodity": "gold",
        "direction": "bullish", "confidence": 0.80, "timeframe": "short_term",
        "rationale": "Fed cuts rates 50bp, larger than expected. Weaker dollar, lower yields support gold.",
        "source_text": "The Federal Reserve cut its benchmark rate by 50 basis points, a larger-than-expected move.",
        "event_name": "fed_sep2024_cut",
    },
    {
        "date": "2024-11-07", "commodity": "gold",
        "direction": "bearish", "confidence": 0.50, "timeframe": "short_term",
        "rationale": "Post-US-election dollar strength pressures gold near-term. Trump tax/tariff policy expectations.",
        "source_text": "Following the US presidential election, the dollar index surged to multi-month highs.",
        "event_name": "trump_election_gold",
    },
    {
        "date": "2024-12-05", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "OPEC+ delays planned output increase to April 2025. Continued supply restraint.",
        "source_text": "OPEC+ agreed to delay the planned unwinding of voluntary cuts until April 2025.",
        "event_name": "opec_dec2024_delay",
    },
    # --- 2020 (COVID era) ---
    {
        "date": "2020-03-09", "commodity": "crude_oil_wti",
        "direction": "bearish", "confidence": 0.90, "timeframe": "short_term",
        "rationale": "Saudi-Russia price war collapse. Saudi slashes prices after OPEC+ deal breakdown.",
        "source_text": "Saudi Arabia launched an oil price war after failing to reach an agreement with Russia.",
        "event_name": "saudi_russia_price_war",
    },
    {
        "date": "2020-03-16", "commodity": "gold",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "Fed slashes rates to zero and launches $700B QE. Massive monetary stimulus supports gold.",
        "source_text": "The Federal Reserve cut rates to near zero and announced $700 billion in quantitative easing.",
        "event_name": "fed_covid_emergency",
    },
    {
        "date": "2020-04-13", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.65, "timeframe": "medium_term",
        "rationale": "OPEC+ emergency agreement to cut 9.7M bpd — largest cut in history.",
        "source_text": "OPEC+ agreed to cut oil production by 9.7 million barrels per day starting May.",
        "event_name": "opec_covid_emergency_cut",
    },
    {
        "date": "2020-08-05", "commodity": "gold",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Gold breaks above $2000/oz for first time. Momentum plus weak dollar.",
        "source_text": "Gold prices broke above $2,000 per ounce for the first time in history.",
        "event_name": "gold_ath_aug2020",
    },
    # --- 2021 ---
    {
        "date": "2021-01-28", "commodity": "silver",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "WallStreetBets retail squeeze targets silver. Heavy retail buying volume.",
        "source_text": "Retail investors on WallStreetBets coordinated a silver short squeeze campaign.",
        "event_name": "silver_squeeze",
    },
    {
        "date": "2021-02-15", "commodity": "natural_gas",
        "direction": "bullish", "confidence": 0.80, "timeframe": "short_term",
        "rationale": "Winter Storm Uri paralyzes Texas. Major heating demand surge, gas wellhead freezes.",
        "source_text": "Winter Storm Uri brought record cold to Texas, freezing natural gas wellheads.",
        "event_name": "winter_storm_uri",
    },
    {
        "date": "2021-09-20", "commodity": "gold",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Evergrande debt crisis escalates. Safe-haven demand likely.",
        "source_text": "China Evergrande faces imminent default on $300B debt, spooking global markets.",
        "event_name": "evergrande_crisis",
    },
    {
        "date": "2021-10-06", "commodity": "natural_gas",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "European gas prices hit record highs before winter. Global LNG diverted to Europe.",
        "source_text": "European natural gas futures surged to record levels ahead of winter heating season.",
        "event_name": "eu_gas_oct2021",
    },
    # --- 2022 additional ---
    {
        "date": "2022-03-08", "commodity": "natural_gas",
        "direction": "bullish", "confidence": 0.75, "timeframe": "medium_term",
        "rationale": "US bans Russian energy imports. European supply tightens further.",
        "source_text": "President Biden announced a US ban on Russian oil, natural gas, and coal imports.",
        "event_name": "us_russia_energy_ban",
    },
    {
        "date": "2022-03-31", "commodity": "crude_oil_wti",
        "direction": "bearish", "confidence": 0.70, "timeframe": "short_term",
        "rationale": "US releases unprecedented 180M barrels from SPR over 6 months.",
        "source_text": "Biden announced release of 180 million barrels from Strategic Petroleum Reserve.",
        "event_name": "spr_massive_release",
    },
    {
        "date": "2022-05-16", "commodity": "wheat",
        "direction": "bullish", "confidence": 0.75, "timeframe": "medium_term",
        "rationale": "India bans wheat exports. Reduced global supply amid war-driven shortages.",
        "source_text": "India announced a ban on wheat exports effective immediately to ensure food security.",
        "event_name": "india_wheat_ban",
    },
    {
        "date": "2022-06-15", "commodity": "gold",
        "direction": "bearish", "confidence": 0.65, "timeframe": "short_term",
        "rationale": "Fed delivers 75bp hike, largest since 1994. Aggressive tightening hurts gold.",
        "source_text": "The Federal Reserve raised rates by 75 basis points, the largest increase since 1994.",
        "event_name": "fed_jun2022_75bp",
    },
    {
        "date": "2022-07-22", "commodity": "wheat",
        "direction": "bearish", "confidence": 0.60, "timeframe": "medium_term",
        "rationale": "Black Sea Grain Initiative signed, allowing Ukrainian exports via safe corridor.",
        "source_text": "Russia and Ukraine signed UN-brokered deal allowing Ukrainian grain exports through Black Sea.",
        "event_name": "grain_deal_signed",
    },
    {
        "date": "2022-09-26", "commodity": "natural_gas",
        "direction": "bullish", "confidence": 0.60, "timeframe": "short_term",
        "rationale": "Nord Stream pipelines sabotaged. Permanent loss of major Russian gas route.",
        "source_text": "Nord Stream 1 and 2 pipelines were damaged by suspected sabotage, reported gas leaks.",
        "event_name": "nord_stream_sabotage",
    },
    {
        "date": "2022-10-05", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.80, "timeframe": "medium_term",
        "rationale": "OPEC+ cuts production 2M bpd — largest cut since 2020 despite Western pressure.",
        "source_text": "OPEC+ agreed to cut oil production by 2 million barrels per day starting November.",
        "event_name": "opec_oct2022_2M_cut",
    },
    {
        "date": "2022-12-05", "commodity": "crude_oil_brent",
        "direction": "bearish", "confidence": 0.50, "timeframe": "short_term",
        "rationale": "G7 Russia oil price cap at $60/bbl takes effect. Designed to keep Russian oil flowing.",
        "source_text": "G7 price cap on Russian seaborne oil at $60 per barrel took effect today.",
        "event_name": "russia_oil_price_cap",
    },
    # --- 2023 additional ---
    {
        "date": "2023-01-09", "commodity": "copper",
        "direction": "bullish", "confidence": 0.70, "timeframe": "medium_term",
        "rationale": "China reopens after zero-COVID. Industrial metals demand expected to surge.",
        "source_text": "China officially reopened borders and ended zero-COVID policy, boosting industrial outlook.",
        "event_name": "china_reopening",
    },
    {
        "date": "2023-03-10", "commodity": "gold",
        "direction": "bullish", "confidence": 0.80, "timeframe": "short_term",
        "rationale": "SVB collapse triggers US banking crisis. Strong safe-haven demand for gold.",
        "source_text": "Silicon Valley Bank collapsed, the largest US bank failure since 2008 financial crisis.",
        "event_name": "svb_collapse",
    },
    {
        "date": "2023-06-06", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Saudi Arabia announces voluntary 1M bpd cut in July on top of OPEC+ cuts.",
        "source_text": "Saudi Arabia announced a voluntary 1 million bpd production cut for July.",
        "event_name": "saudi_jun2023_cut",
    },
    {
        "date": "2023-06-06", "commodity": "wheat",
        "direction": "bullish", "confidence": 0.60, "timeframe": "medium_term",
        "rationale": "Kakhovka dam destruction floods Ukrainian farmland. Reduced grain output.",
        "source_text": "The Kakhovka dam was destroyed, flooding large agricultural areas in Ukraine.",
        "event_name": "kakhovka_dam",
    },
    {
        "date": "2023-07-17", "commodity": "wheat",
        "direction": "bullish", "confidence": 0.70, "timeframe": "short_term",
        "rationale": "Russia exits Black Sea grain deal. Ukrainian exports face renewed disruption.",
        "source_text": "Russia announced withdrawal from the Black Sea Grain Initiative, "
                       "ending safe passage guarantees.",
        "event_name": "grain_deal_exit",
    },
    {
        "date": "2023-10-27", "commodity": "gold",
        "direction": "bullish", "confidence": 0.60, "timeframe": "short_term",
        "rationale": "Middle East war escalation continues. Strong safe-haven flows into gold.",
        "source_text": "Israeli ground operations in Gaza expanded overnight, escalating Middle East tensions.",
        "event_name": "gaza_ground_op",
    },
    # --- 2024 additional ---
    {
        "date": "2024-02-20", "commodity": "copper",
        "direction": "bullish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "Chinese stimulus measures announced. Increased infrastructure spending drives industrial metals.",
        "source_text": "China's central bank announced larger-than-expected reserve requirement cuts to boost growth.",
        "event_name": "china_stimulus_feb2024",
    },
    {
        "date": "2024-04-12", "commodity": "gold",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Geopolitical escalation fears after Iran-Israel tensions spike.",
        "source_text": "Iran indicated imminent retaliation for Damascus consulate strike, "
                       "raising Middle East war risk.",
        "event_name": "iran_israel_apr2024",
    },
    {
        "date": "2024-06-02", "commodity": "crude_oil_wti",
        "direction": "bearish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "OPEC+ announces gradual unwinding of voluntary cuts starting October.",
        "source_text": "OPEC+ agreed to begin unwinding voluntary production cuts from October 2024.",
        "event_name": "opec_jun2024_unwind",
    },
    {
        "date": "2024-08-02", "commodity": "gold",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Weak US jobs report triggers recession fears and aggressive Fed rate cut expectations.",
        "source_text": "US unemployment rose to 4.3% in July, triggering Sahm Rule recession indicator.",
        "event_name": "weak_jobs_aug2024",
    },
    {
        "date": "2024-08-05", "commodity": "silver",
        "direction": "bearish", "confidence": 0.50, "timeframe": "short_term",
        "rationale": "Global market crash, liquidity squeeze forces commodities selloff.",
        "source_text": "Japanese Nikkei fell 12%, global markets in panic, VIX spiked above 65.",
        "event_name": "aug2024_crash",
    },
    {
        "date": "2024-10-01", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.65, "timeframe": "short_term",
        "rationale": "Iran fires ballistic missile barrage at Israel. Major Middle East escalation.",
        "source_text": "Iran launched approximately 180 ballistic missiles at Israel, major escalation of conflict.",
        "event_name": "iran_strike_oct2024",
    },
    {
        "date": "2024-10-30", "commodity": "copper",
        "direction": "bullish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "China announces fiscal stimulus targeting housing sector. Boost to metals demand.",
        "source_text": "China's Standing Committee announced major fiscal stimulus aimed at "
                       "local government debt and housing.",
        "event_name": "china_stimulus_oct2024",
    },
    {
        "date": "2024-11-25", "commodity": "corn",
        "direction": "bearish", "confidence": 0.50, "timeframe": "medium_term",
        "rationale": "Trump tariff proposals on Mexico/Canada could hurt US corn exports.",
        "source_text": "Trump announced 25% tariffs on Mexico and Canada on day one, "
                       "triggering trade retaliation fears.",
        "event_name": "trump_tariffs_corn",
    },
    # --- 2018-2019 ---
    {
        "date": "2018-07-06", "commodity": "corn",
        "direction": "bearish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "US-China trade war escalation. China applies retaliatory tariffs on US agriculture.",
        "source_text": "China imposed 25% retaliatory tariffs on US agricultural products including corn.",
        "event_name": "china_tariffs_corn_2018",
    },
    {
        "date": "2018-07-06", "commodity": "wheat",
        "direction": "bearish", "confidence": 0.50, "timeframe": "medium_term",
        "rationale": "US agricultural exports to China hit by tariffs; wheat demand weakens.",
        "source_text": "China imposed 25% retaliatory tariffs on US agricultural products.",
        "event_name": "china_tariffs_wheat_2018",
    },
    {
        "date": "2019-09-16", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.85, "timeframe": "short_term",
        "rationale": "Drone attack on Saudi Abqaiq facility knocks out 5% of global oil supply.",
        "source_text": "Drone attacks on Saudi Aramco's Abqaiq and Khurais facilities halted 5.7M bpd production.",
        "event_name": "abqaiq_attack",
    },
    {
        "date": "2019-01-28", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "US sanctions on Venezuelan PDVSA target heavy oil exports. Supply tightens.",
        "source_text": "Trump administration imposed sanctions on Venezuelan state oil firm PDVSA.",
        "event_name": "venezuela_sanctions_2019",
    },
    {
        "date": "2019-08-01", "commodity": "silver",
        "direction": "bullish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "Fed cuts rates first time since 2008. Lower yields support silver as monetary metal.",
        "source_text": "The Federal Reserve cut its benchmark rate for the first time since the 2008 crisis.",
        "event_name": "fed_aug2019_cut_silver",
    },
    # --- 2021 additional ---
    {
        "date": "2021-03-23", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Suez Canal blocked by Ever Given container ship. Global shipping disrupted.",
        "source_text": "The Ever Given container ship ran aground blocking the Suez Canal entirely.",
        "event_name": "suez_blockage",
    },
    {
        "date": "2021-08-30", "commodity": "crude_oil_wti",
        "direction": "bullish", "confidence": 0.60, "timeframe": "short_term",
        "rationale": "Hurricane Ida shuts down ~95% of Gulf of Mexico offshore oil production.",
        "source_text": "Hurricane Ida made landfall in Louisiana, shutting 95% of Gulf of Mexico oil output.",
        "event_name": "hurricane_ida",
    },
    {
        "date": "2021-10-27", "commodity": "copper",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "LME copper stockpiles plunge to 40-year lows. Supply squeeze concerns.",
        "source_text": "LME copper stockpiles dropped to the lowest level since 1974.",
        "event_name": "lme_copper_squeeze_oct2021",
    },
    # --- 2022 additional ---
    {
        "date": "2022-03-07", "commodity": "gold",
        "direction": "bullish", "confidence": 0.70, "timeframe": "short_term",
        "rationale": "Gold near all-time highs on Ukraine war safe-haven flows.",
        "source_text": "Gold spiked near $2,050/oz as investors fled to safe havens amid Ukraine conflict.",
        "event_name": "gold_ukraine_spike",
    },
    {
        "date": "2022-05-04", "commodity": "gold",
        "direction": "bearish", "confidence": 0.60, "timeframe": "short_term",
        "rationale": "Fed 50bp hike, largest since 2000. Hawkish stance pressures gold.",
        "source_text": "The Federal Reserve raised rates by 50 basis points, the largest hike since 2000.",
        "event_name": "fed_may2022_50bp",
    },
    {
        "date": "2022-06-24", "commodity": "copper",
        "direction": "bearish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "Copper enters bear market. Recession fears weigh on industrial metals.",
        "source_text": "LME copper entered a bear market, down 20% from March highs on recession fears.",
        "event_name": "copper_bear_market",
    },
    {
        "date": "2022-12-14", "commodity": "gold",
        "direction": "bearish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Fed hikes 50bp, signals rates higher for longer despite slowing CPI.",
        "source_text": "Fed raised rates 50bp and projected peak rate above 5% through 2023.",
        "event_name": "fed_dec2022_hike",
    },
    # --- 2023 additional ---
    {
        "date": "2023-02-14", "commodity": "gold",
        "direction": "bullish", "confidence": 0.50, "timeframe": "short_term",
        "rationale": "CPI hotter than expected but core moderating. Mixed signal for gold.",
        "source_text": "US CPI rose 6.4% YoY in January, slightly above the 6.2% consensus expectation.",
        "event_name": "cpi_feb2023",
    },
    {
        "date": "2023-08-07", "commodity": "wheat",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Russia attacks Ukrainian Danube grain ports. Alternative export route at risk.",
        "source_text": "Russian drones struck Ukrainian grain port infrastructure on the Danube river.",
        "event_name": "danube_port_attack",
    },
    {
        "date": "2023-10-17", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Israel-Hamas war escalates fears of regional spread. Iran involvement risk.",
        "source_text": "Hezbollah tensions on Israel-Lebanon border threaten to widen Middle East conflict.",
        "event_name": "israel_lebanon_tensions",
    },
    {
        "date": "2023-11-16", "commodity": "corn",
        "direction": "bearish", "confidence": 0.50, "timeframe": "medium_term",
        "rationale": "USDA raises corn production forecast. Supply outlook improves.",
        "source_text": "USDA raised the US corn production estimate to a record 15.234 billion bushels.",
        "event_name": "usda_corn_record",
    },
    # --- 2024 additional ---
    {
        "date": "2024-01-12", "commodity": "crude_oil_brent",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "US and UK launch strikes on Houthi targets in Yemen. Red Sea shipping disrupted.",
        "source_text": "US and UK launched airstrikes against Houthi targets in Yemen over Red Sea attacks.",
        "event_name": "houthi_strikes",
    },
    {
        "date": "2024-03-20", "commodity": "gold",
        "direction": "bullish", "confidence": 0.55, "timeframe": "medium_term",
        "rationale": "Fed holds rates, reaffirms 3 cuts projection for 2024. Dovish tone.",
        "source_text": "Fed held rates steady and maintained median projection of 3 rate cuts in 2024.",
        "event_name": "fed_mar2024_dovish",
    },
    {
        "date": "2024-05-20", "commodity": "copper",
        "direction": "bullish", "confidence": 0.60, "timeframe": "short_term",
        "rationale": "Comex copper short squeeze drives prices to record. Supply tightness narrative.",
        "source_text": "Comex copper surged to record highs as short sellers scrambled to cover positions.",
        "event_name": "copper_short_squeeze_may2024",
    },
    {
        "date": "2024-07-11", "commodity": "silver",
        "direction": "bullish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Silver breaks above $31/oz on dovish Fed and solar demand outlook.",
        "source_text": "Silver broke above $31/oz, approaching decade highs on industrial and monetary demand.",
        "event_name": "silver_jul2024",
    },
    {
        "date": "2024-09-24", "commodity": "copper",
        "direction": "bullish", "confidence": 0.65, "timeframe": "medium_term",
        "rationale": "China unveils comprehensive stimulus package. Major boost for industrial demand.",
        "source_text": "PBOC announced rate cuts, RRR cuts, and housing support in largest stimulus since COVID.",
        "event_name": "china_big_stimulus",
    },
    {
        "date": "2024-12-18", "commodity": "gold",
        "direction": "bearish", "confidence": 0.55, "timeframe": "short_term",
        "rationale": "Fed signals slower rate cut pace for 2025. Hawkish surprise pressures gold.",
        "source_text": "Fed cut rates 25bp but projected only 2 cuts in 2025, below prior 4-cut guidance.",
        "event_name": "fed_dec2024_hawkish_cut",
    },
]


def get_closing_prices(ticker: str, start: str, end: str) -> dict[str, float]:
    """Fetch daily closing prices between start and end. Returns {date_str: close}."""
    try:
        data = yf.Ticker(ticker).history(start=start, end=end)
        if data.empty:
            return {}
        return {str(idx.date()): float(row["Close"]) for idx, row in data.iterrows()}
    except Exception as e:
        print(f"  WARN: yfinance failed for {ticker}: {e}")
        return {}


def find_price_at_or_after(prices: dict[str, float], target_date: str) -> tuple[str, float] | None:
    """Find first trading day >= target_date with a price."""
    sorted_dates = sorted(prices.keys())
    for d in sorted_dates:
        if d >= target_date:
            return d, prices[d]
    return None


def trading_days_after(prices: dict[str, float], start_date: str, n_days: int) -> tuple[str, float] | None:
    """Find the Nth trading day after start_date (inclusive of start counts as 0)."""
    sorted_dates = sorted(prices.keys())
    found_start = False
    count = 0
    for d in sorted_dates:
        if d >= start_date and not found_start:
            found_start = True
            continue
        if found_start:
            count += 1
            if count >= n_days:
                return d, prices[d]
    return None


def backtest_event(event: dict) -> dict | None:
    commodity = event["commodity"]
    ticker = TICKERS.get(commodity)
    if not ticker:
        print(f"  SKIP: no ticker for {commodity}")
        return None

    event_date = event["date"]
    start = event_date
    # Fetch a 20-day window to ensure we have enough trading days after
    end_date = (datetime.strptime(event_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")

    prices = get_closing_prices(ticker, start, end_date)
    if not prices:
        print(f"  SKIP {event['event_name']}: no price data")
        return None

    # price_then: first trading day on/after event date
    then = find_price_at_or_after(prices, event_date)
    if not then:
        print(f"  SKIP {event['event_name']}: no price_then")
        return None
    then_date, price_then = then

    # price_now: 1 trading day later (short) or 5 (medium)
    lag = 1 if event["timeframe"] == "short_term" else 5
    later = trading_days_after(prices, then_date, lag)
    if not later:
        print(f"  SKIP {event['event_name']}: no price_now after +{lag} days")
        return None
    now_date, price_now = later

    change_pct = (price_now - price_then) / price_then * 100
    if change_pct > NEUTRAL_THRESHOLD_PCT:
        actual = "bullish"
    elif change_pct < -NEUTRAL_THRESHOLD_PCT:
        actual = "bearish"
    else:
        actual = "neutral"

    correct = actual == event["direction"]

    # Construct log entry as if the signal was generated on event_date
    event_ts = datetime.strptime(then_date, "%Y-%m-%d").replace(tzinfo=UTC)
    check_ts = datetime.strptime(now_date, "%Y-%m-%d").replace(tzinfo=UTC)

    entry = {
        "id": f"hist_{event['event_name']}",
        "source": "retrospective",
        "timestamp": event_ts.isoformat(),
        "stream_id": "historical_seed",
        "chunk_id": event["event_name"],
        "commodity": commodity,
        "display_name": commodity.replace("_", " ").title().replace("Wti", "WTI"),
        "direction": event["direction"],
        "confidence": event["confidence"],
        "rationale": event["rationale"],
        "timeframe": event["timeframe"],
        "source_text": event["source_text"],
        "price_snapshot": round(price_then, 3),
        "backtest_at": check_ts.isoformat(),
        "backtest_result": {
            "checked_at": check_ts.isoformat(),
            "price_then": round(price_then, 3),
            "price_now": round(price_now, 3),
            "change_pct": round(change_pct, 3),
            "actual_direction": actual,
            "correct": correct,
        },
    }
    status = "OK" if correct else "WRONG"
    print(f"  [{status}] {event['event_name']}: predicted={event['direction']} "
          f"actual={actual} ({change_pct:+.2f}%) [{event['timeframe']}]")
    return entry


def main() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Read existing log, filter out previous historical seeds (so we can re-run)
    existing: list[dict] = []
    if LOG_PATH.exists():
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if not e.get("id", "").startswith("hist_"):
                        existing.append(e)
                except json.JSONDecodeError:
                    continue

    print(f"Seeding {len(HISTORICAL_EVENTS)} historical events...")
    seeded = []
    for event in HISTORICAL_EVENTS:
        entry = backtest_event(event)
        if entry:
            seeded.append(entry)

    # Merge: keep non-historical entries + new historical
    all_entries = existing + seeded
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        for e in all_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    correct = sum(1 for e in seeded if e["backtest_result"]["correct"])
    total = len(seeded)
    print(f"\nSeeded {total} historical backtest entries to {LOG_PATH}")
    print(f"Historical accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
    by_tf: dict[str, list] = {"short_term": [], "medium_term": []}
    for e in seeded:
        by_tf[e["timeframe"]].append(e["backtest_result"]["correct"])
    for tf, results in by_tf.items():
        if results:
            print(f"  {tf}: {sum(results)}/{len(results)} correct "
                  f"({100*sum(results)/len(results):.1f}%)")


if __name__ == "__main__":
    main()

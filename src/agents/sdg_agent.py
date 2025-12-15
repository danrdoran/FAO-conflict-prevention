from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd
from openai import OpenAI

from clients.fao_sdg_client import FAOSDGClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize OpenAI client (expects OPENAI_API_KEY in the environment)
client = OpenAI()

# Initialize FAO SDG client
fao_client = FAOSDGClient()


# ---------------------------------------------------------------------------
# SDG series catalogue (FAO SDG series codes)
# ---------------------------------------------------------------------------


@dataclass
class SDGSeriesInfo:
    sdg_indicator: str
    series_code: str
    name: str
    description: str = ""


# Minimal catalogue – extend as needed
SDG_SERIES_MAP: Dict[str, SDGSeriesInfo] = {
    # 2.1.1 Prevalence of undernourishment
    # UN SDG series code SN_ITK_DEFC (see UNSD metadata and FAO docs).
    "2.1.1": SDGSeriesInfo(
        sdg_indicator="2.1.1",
        series_code="SN_ITK_DEFC",
        name="Prevalence of undernourishment (% of population)",
        description="FAO SDG 2.1.1 series SN_ITK_DEFC: prevalence of undernourishment.",
    ),
    # 2.1.2 Prevalence of moderate or severe food insecurity (FIES)
    # Series code AG_PRD_FIESMS in FAO SDG 2.1.2 dataset.
    "2.1.2": SDGSeriesInfo(
        sdg_indicator="2.1.2",
        series_code="AG_PRD_FIESMS",
        name="Prevalence of moderate or severe food insecurity in the population",
        description="FAO SDG 2.1.2 series AG_PRD_FIESMS (FIES-based).",
    ),
    # 15.1.1 Forest area as a proportion of total land area
    # FAO/UN SDG series code AG_LND_FRST.
    "15.1.1": SDGSeriesInfo(
        sdg_indicator="15.1.1",
        series_code="AG_LND_FRST",
        name="Forest area as a proportion of total land area",
        description="FAO SDG 15.1.1 series AG_LND_FRST.",
    ),
}


# ---------------------------------------------------------------------------
# Planning + results
# ---------------------------------------------------------------------------


@dataclass
class AgentPlan:
    sdg_indicators: List[str]          # e.g. ["2.1.1"]
    series_codes: List[str]            # e.g. ["SN_ITK_DEFC"]
    series_names: List[str]
    areas: List[str]                   # e.g. ["Rwanda", "Kenya"]
    years: Tuple[Optional[int], Optional[int]]  # (start_year, end_year)
    chart_type: str                    # "line", "bar", etc.


@dataclass
class AgentResult:
    plan: AgentPlan
    data: pd.DataFrame
    chart_path: Optional[str]
    narrative: str


# ---------------------------------------------------------------------------
# LLM planning
# ---------------------------------------------------------------------------


def build_indicator_catalog() -> str:
    """Create a short markdown description of available indicators/series."""
    lines = ["Available FAO SDG indicators and series:"]
    for info in SDG_SERIES_MAP.values():
        lines.append(
            f"- SDG {info.sdg_indicator}: {info.name} "
            f"(series code: {info.series_code})"
        )
    return "\n".join(lines)


def plan_from_question(question: str) -> AgentPlan:
    """
    Use GPT-4.1-mini to convert a natural-language question into an AgentPlan.

    The model returns a small JSON object; we then post-process it.
    """
    catalog_text = build_indicator_catalog()

    system_instructions = (
        "You are a planning agent for an SDG data analysis tool using FAO SDG data.\n"
        "You must respond with a SINGLE JSON object, no prose.\n"
        "Fields: sdg_indicators (list of SDG indicator codes like '2.1.1'),\n"
        "areas (list of country or region names as plain text),\n"
        "years (object with optional 'start' and 'end' integer years),\n"
        "chart_type (one of 'line', 'bar', 'scatter').\n"
        "Do NOT invent indicators outside the catalogue; choose from the provided list only.\n"
        "If the question is vague, make a reasonable assumption and document it in an "
        "extra field 'notes'."
    )

    prompt = f"{catalog_text}\n\nUser question: {question}"

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": prompt},
        ],
    )

    raw_text = resp.output_text
    try:
        plan_json = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback: ask the model again but explicitly extract JSON
        fixer = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You will receive some messy text that should contain a JSON object. "
                        "Extract ONLY the JSON object and return it."
                    ),
                },
                {"role": "user", "content": raw_text},
            ],
        )
        plan_json = json.loads(fixer.output_text)

    indicators = plan_json.get("sdg_indicators") or []
    if isinstance(indicators, str):
        indicators = [indicators]

    # Keep only indicators that exist in our catalogue
    indicators = [i for i in indicators if i in SDG_SERIES_MAP]
    if not indicators:
        # Default to a single well-known indicator
        indicators = ["2.1.1"]

    areas = plan_json.get("areas") or []
    if isinstance(areas, str):
        areas = [areas]

    years_obj = plan_json.get("years") or {}
    start_year = years_obj.get("start")
    end_year = years_obj.get("end")

    chart_type = (plan_json.get("chart_type") or "line").lower()
    if chart_type not in {"line", "bar", "scatter"}:
        chart_type = "line"

    series_codes = [SDG_SERIES_MAP[i].series_code for i in indicators]
    series_names = [SDG_SERIES_MAP[i].name for i in indicators]

    return AgentPlan(
        sdg_indicators=indicators,
        series_codes=series_codes,
        series_names=series_names,
        areas=areas,
        years=(start_year, end_year),
        chart_type=chart_type,
    )


# ---------------------------------------------------------------------------
# Data retrieval / filtering
# ---------------------------------------------------------------------------


def _filter_by_areas(df: pd.DataFrame, areas: List[str]) -> pd.DataFrame:
    """Case-insensitive fuzzy-ish filter on area_name."""
    if not areas or df.empty or "area_name" not in df.columns:
        return df

    areas_clean = [a.strip().lower() for a in areas if a.strip()]
    if not areas_clean:
        return df

    mask = False
    area_col = df["area_name"].astype(str).str.lower()
    for a in areas_clean:
        mask = mask | area_col.str.contains(a)
    return df[mask]


def retrieve_data(plan: AgentPlan) -> pd.DataFrame:
    """
    Retrieve SDG series data from FAO for the planned indicators and areas.
    """
    start_year, end_year = plan.years
    frames: List[pd.DataFrame] = []

    for sdg_indicator in plan.sdg_indicators:
        info = SDG_SERIES_MAP[sdg_indicator]
        logger.info("Fetching FAO SDG data: %s (%s)", sdg_indicator, info.series_code)
        df = fao_client.get_series_dataframe(
            series_code=info.series_code,
            start_year=start_year,
            end_year=end_year,
        )

        if df.empty:
            continue

        if plan.areas:
            df = _filter_by_areas(df, plan.areas)

        if df.empty:
            continue

        df = df.copy()
        df["sdg_indicator"] = sdg_indicator
        df["sdg_name"] = info.name

        frames.append(df)

    if not frames:
        return pd.DataFrame(
            columns=[
                "sdg_indicator",
                "sdg_name",
                "series_code",
                "series_name",
                "area_code",
                "area_name",
                "year",
                "value",
            ]
        )

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["sdg_indicator", "area_name", "year"])
    return result


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


def make_chart(plan: AgentPlan, data: pd.DataFrame, output_path: str) -> Optional[str]:
    if data.empty:
        logger.warning("No data, skipping chart creation.")
        return None

    plt.figure(figsize=(10, 6))

    if plan.chart_type == "line":
        for (sdg, area), group in data.groupby(["sdg_indicator", "area_name"]):
            plt.plot(group["year"], group["value"], marker="o", label=f"{area} – {sdg}")
    elif plan.chart_type == "bar":
        # Simple grouped bar by area for the latest year
        latest_year = data["year"].max()
        subset = data[data["year"] == latest_year]
        for sdg, group in subset.groupby("sdg_indicator"):
            x = range(len(group))
            plt.bar(x, group["value"], label=sdg)
            plt.xticks(
                x,
                group["area_name"],
                rotation=45,
                ha="right",
            )
    elif plan.chart_type == "scatter":
        for (sdg, area), group in data.groupby(["sdg_indicator", "area_name"]):
            plt.scatter(group["year"], group["value"], label=f"{area} – {sdg}")
    else:
        # Fallback to line
        for (sdg, area), group in data.groupby(["sdg_indicator", "area_name"]):
            plt.plot(group["year"], group["value"], marker="o", label=f"{area} – {sdg}")

    plt.xlabel("Year")
    plt.ylabel("Value")
    plt.title("FAO SDG indicators")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path


# ---------------------------------------------------------------------------
# Narrative summarization
# ---------------------------------------------------------------------------


def craft_answer(plan: AgentPlan, data: pd.DataFrame) -> str:
    if data.empty:
        return (
            "I attempted to retrieve FAO SDG data for your query, but did not find any "
            "matching observations for the selected indicators/areas/years. "
            "You may want to try a different country name, indicator, or time period."
        )

    # Build a compact textual summary to feed the model
    summary_rows = []
    for sdg in sorted(data["sdg_indicator"].unique()):
        subset = data[data["sdg_indicator"] == sdg]
        for area in sorted(subset["area_name"].unique()):
            sub2 = subset[subset["area_name"] == area]
            years = ", ".join(str(int(y)) for y in sub2["year"].unique())
            min_val = sub2["value"].min()
            max_val = sub2["value"].max()
            summary_rows.append(
                f"SDG {sdg}, area {area}: years={years}, "
                f"min={min_val:.2f}, max={max_val:.2f}"
            )

    summary_text = "\n".join(summary_rows)

    indicator_list = ", ".join(
        f"{i} ({SDG_SERIES_MAP[i].name})" for i in plan.sdg_indicators
    )
    areas_list = ", ".join(plan.areas) if plan.areas else "all available areas"

    system_msg = (
        "You are a data analyst helping a researcher interpret official FAO SDG data.\n"
        "You will receive a list of SDG indicators, areas (countries/regions), and a "
        "summary of the retrieved time series (min, max, years).\n"
        "Write a concise narrative (2–4 short paragraphs) describing trends, "
        "differences between areas, and any policy-relevant insights. "
        "Avoid repeating the raw numbers exhaustively; focus on patterns."
    )

    user_msg = (
        f"Indicators: {indicator_list}\n"
        f"Areas: {areas_list}\n"
        f"Summary of data:\n{summary_text}"
    )

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    )

    return resp.output_text


# ---------------------------------------------------------------------------
# Public Agent API
# ---------------------------------------------------------------------------


class SDGResearchAgent:
    def run(
        self,
        question: str,
        chart_output_path: str = "sdg_chart.png",
    ) -> AgentResult:
        plan = plan_from_question(question)
        data = retrieve_data(plan)
        chart_path = make_chart(plan, data, chart_output_path)
        narrative = craft_answer(plan, data)
        return AgentResult(
            plan=plan,
            data=data,
            chart_path=chart_path,
            narrative=narrative,
        )
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

import os 

ROOT = Path(__file__).resolve().parents[1]   # …/FAO-conflict-prevention
sys.path.insert(0, str(ROOT / "src"))        # add …/FAO-conflict-prevention/src


if "OPENAI_API_KEY" in st.secrets:
    os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

from agents.sdg_agent import SDGResearchAgent
from clients.fao_sdg_client import FAOSDGClient
from rag.ag_policy_rag import AgriculturalPolicyRAGAssistant, PathwaysIndex, load_indicator_catalog


st.set_page_config(page_title="Food Security Policy Assistant for Conflict Prevention", layout="wide")

st.title("Food Security Policy Assistant for Conflict Prevention")

st.markdown(
    """
This decision-support application helps national planners, policy analysts, and researchers explore how food security trends may relate to risks of fragility and violent conflict. It combines:

- **Official SDG time-series data** (for selected food security and agriculture indicators); and
- **Policy guidance from _Pathways for Peace: Inclusive Approaches to Preventing Violent Conflict_ (United Nations & World Bank, 2018).**

The tool is designed to support evidence-informed dialogue and policy design. It does **not** replace national statistics, formal risk assessments, or inclusive consultation processes. Please validate any outputs against official sources and local knowledge.

**Data and privacy note:** Your queries may be processed by an AI service to generate summaries. Avoid entering personal or sensitive information.
"""
)



tab1, tab2 = st.tabs(["SDG Explorer", "Policy Assistant"])


@st.cache_resource
def get_fao_client() -> FAOSDGClient:
    return FAOSDGClient()


@st.cache_resource
def get_area_catalog() -> list[str]:
    # Cached because it downloads once
    return get_fao_client().list_areas()


@st.cache_resource
def get_indicator_specs() -> list:
    catalog_path = ROOT / "src" / "catalogs" / "ag_indicators.yaml"
    return load_indicator_catalog(catalog_path)


@st.cache_resource
def get_pathways_index() -> PathwaysIndex:
    pdf_path = ROOT / "data" / "docs" / "pathways_for_peace.pdf"
    idx = PathwaysIndex(pdf_path=pdf_path, index_dir=ROOT / "rag_store")
    idx.ensure_index(rebuild=False)
    return idx


@st.cache_resource
def get_policy_assistant() -> AgriculturalPolicyRAGAssistant:
    fao = get_fao_client()
    idx = get_pathways_index()
    specs = get_indicator_specs()
    areas = get_area_catalog()
    return AgriculturalPolicyRAGAssistant(
        pathways_index=idx,
        indicator_catalog=specs,
        area_catalog=areas,
        fao_data_fetcher=fao.get_timeseries,
    )


with tab1:
    st.subheader("SDG Explorer")

    with st.expander("About this tab", expanded=True):
        st.markdown(
            """
The **SDG Explorer** provides a quick way to explore and compare trends in selected food security and related SDG indicators across countries and over time.

**What you can do**
- Enter a plain-language question (for example, “Compare undernourishment in two countries since 2010”).
- Generate a simple chart and a short narrative summary of the observed trends.
- Review and download the underlying data table for further analysis.

**How this supports conflict prevention**
Persistent or worsening food insecurity can heighten grievances and stress coping capacities, especially where inequalities and exclusion are present. This tab helps users identify where trends may warrant deeper analysis, targeted monitoring, or preventive policy attention.

**How to interpret results**
The narrative is an automated summary to support initial exploration. It should be complemented with contextual information (prices, livelihoods, climate shocks, displacement, and governance factors) before drawing policy conclusions.
"""
        )

    agent = SDGResearchAgent()

    q = st.text_input(
        "Ask an SDG question (FAO SDG time series + chart + narrative)",
        value="Compare undernourishment (2.1.1) in Kenya and Rwanda since 2010.",
    )

    if st.button("Run SDG analysis", key="run_sdg"):
        with st.spinner("Running SDG analysis..."):
            result = agent.run(q, chart_output_path=str(ROOT / "sdg_chart.png"))

        # st.markdown("### Plan")
        # st.write(result.plan)

        
        st.markdown("### Chart")
        if result.chart_path and Path(result.chart_path).exists():
            st.image(result.chart_path, use_container_width=True)
        else:
            st.info("No chart generated.")

        st.markdown("### Narrative")
        st.write(result.narrative)

        st.markdown("### Data")
        if result.data is None or result.data.empty:
            st.warning("No data returned.")
        else:
            st.dataframe(result.data, use_container_width=True)


with tab2:
    st.subheader("Policy Assistant (draws from Pathways for Peace and curated SDG indicators)")

    with st.expander("About this tab", expanded=True):
        st.markdown(
            """
The **Policy Assistant** supports users in drafting and refining policy options that address food insecurity while reducing risks of fragility and violent conflict.

It combines:
- **Selected SDG indicator trends** for a chosen country/area; and
- **Relevant passages from _Pathways for Peace_** to surface prevention-oriented principles (such as inclusion, addressing grievances, and strengthening institutions).

**What you can do**
- Select a country/area and (optionally) one or more SDG indicators to ground the analysis.
- Pose a policy question (e.g., program design, targeting approaches, sequencing, or risk mitigation).
- Receive a structured answer that highlights policy options, potential trade-offs, and risk-management considerations, alongside the evidence used.

**Important limitations**
Outputs are intended for policy support and research. They are not authoritative recommendations and may omit important context. Use them as a starting point for inter-ministerial review, consultation with affected communities, and alignment with national strategies and budgets.
"""
        )


    # Ensure user has the PDF locally
    pdf_path = ROOT / "data" / "docs" / "pathways_for_peace.pdf"
    if not pdf_path.exists():
        st.error(
            f"Missing PDF: {pdf_path}\n\n"
            "Place the Pathways for Peace PDF at data/docs/pathways_for_peace.pdf "
            "then refresh."
        )
        st.stop()

    assistant = get_policy_assistant()
    specs = get_indicator_specs()

    colA, colB = st.columns(2)

    with colA:
        area = st.selectbox("Country/Area", options=get_area_catalog(), index=0)
        indicator_choices = [f"{s.sdg_indicator} — {s.name}" for s in specs]
        chosen = st.multiselect("Indicators", options=indicator_choices)

    with colB:
        question = st.text_area(
            "Your policy question (conflict prevention lens)",
            height=140,
            value="Design a package to reduce food insecurity in this country while lowering conflict risks. "
                  "Use evidence from SDG trends and Pathways for Peace.",
        )
        topk = 5 #st.slider("How many report passages to retrieve", min_value=3, max_value=10, value=5)

    explicit_codes = []
    for c in chosen:
        # format "2.1.1 — Name"
        explicit_codes.append(c.split("—")[0].strip())

    if st.button("Ask Policy Assistant", key="ask_policy"):
        with st.spinner("Answering..."):
            result = assistant.answer_question(
                question=question,
                explicit_sdg_indicators=explicit_codes or None,
                explicit_areas=[area],
                max_inferred_areas=0,
                k_doc_passages=topk,
            )

        st.markdown("## Answer")
        st.write(result["answer"])

        st.markdown("## Evidence used")
        with st.expander("Pathways for Peace passages"):
            for p in result["doc_passages"]:
                st.markdown(f"**p.{p.page} (score={p.score:.3f})**")
                st.write(p.text)

        with st.expander("SDG series pulled"):
            rows = []
            for item in result.get("sdg_series", []):
                series = item["series"] or {}
                rows.append(
                    {
                        "sdg_indicator": item["sdg_indicator"],
                        "series_code": item["series_code"],
                        "area": item["area"],
                        "n_points": len(series),
                        "min_year": min(series.keys()) if series else None,
                        "max_year": max(series.keys()) if series else None,
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
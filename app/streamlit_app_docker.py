"""
Food Security Policy Assistant for Conflict Prevention
Docker-compatible Streamlit Application

This application integrates FAO SDG indicators with policy guidance from
the Pathways for Peace report to support conflict-sensitive development planning.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

import pandas as pd
import streamlit as st

# =============================================================================
# Path Configuration (Docker-compatible)
# =============================================================================
# In Docker: /app/app/streamlit_app.py -> ROOT = /app
# Locally:   .../FAO-CONFLICT-PREVENTION/app/streamlit_app.py -> ROOT = .../FAO-CONFLICT-PREVENTION
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Also check PYTHONPATH (set in Docker)
if "PYTHONPATH" in os.environ:
    for p in os.environ["PYTHONPATH"].split(os.pathsep):
        if p and p not in sys.path:
            sys.path.insert(0, p)

# =============================================================================
# Secrets Configuration
# =============================================================================
# Cloud Run: use env var injected from Secret Manager.
# Local dev (optional): fall back to .streamlit/secrets.toml if present.

from streamlit.errors import StreamlitSecretNotFoundError

def get_openai_api_key() -> str | None:
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key

    # Only for local dev / Streamlit-managed secrets
    try:
        return st.secrets["OPENAI_API_KEY"]
    except (FileNotFoundError, StreamlitSecretNotFoundError, KeyError):
        return None

OPENAI_API_KEY = get_openai_api_key()
if not OPENAI_API_KEY:
    st.error(
        "Missing OPENAI_API_KEY. On Cloud Run, configure it as an environment variable "
        "via Secret Manager. For local dev, create .streamlit/secrets.toml."
    )
    st.stop()

# If other modules expect it in env:
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# =============================================================================
# Import Application Modules
# =============================================================================
try:
    from agents.sdg_agent import SDGResearchAgent
    from clients.fao_sdg_client import FAOSDGClient
    from rag.ag_policy_rag import (
        AgriculturalPolicyRAGAssistant,
        PathwaysIndex,
        load_indicator_catalog,
    )
except ImportError as e:
    st.error(f"Failed to import required modules: {e}")
    st.info(f"Python path: {sys.path}")
    st.stop()

# =============================================================================
# Page Configuration
# =============================================================================
st.set_page_config(
    page_title="Food Security Policy Assistant for Conflict Prevention",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("Food Security Policy Assistant for Conflict Prevention")

# =============================================================================
# Overall Tool Description
# =============================================================================
st.markdown(
    """
    <div style="background-color: #f0f4f8; padding: 1.5rem; border-radius: 8px; 
                margin-bottom: 1.5rem; border-left: 4px solid #1f77b4;">
    <h4 style="margin-top: 0; color: #1f77b4;">About This Tool</h4>
    <p style="margin-bottom: 0.8rem;">
    This decision-support tool assists <strong>national planners, policy researchers, 
    and development practitioners</strong> in understanding the relationship between 
    food security and conflict prevention. It integrates two complementary capabilities:
    </p>
    <ul style="margin-bottom: 0.8rem;">
        <li><strong>SDG Explorer:</strong> Access and analyze official Sustainable 
        Development Goal (SDG) indicators from the Food and Agriculture Organization 
        (FAO), with automated visualization and narrative interpretation.</li>
        <li><strong>Policy Assistant:</strong> Receive evidence-based policy guidance 
        by combining SDG data with insights from the <em>Pathways for Peace</em> 
        report—a joint United Nations–World Bank flagship study on inclusive approaches 
        to preventing violent conflict.</li>
    </ul>
    <p style="margin-bottom: 0;">
    The tool is designed to support the development of policies that address the 
    structural drivers of conflict, with a particular focus on food insecurity as 
    both a consequence and a contributor to instability.
    </p>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2 = st.tabs(["📊 SDG Explorer", "📋 Policy Assistant"])


# =============================================================================
# Cached Resources
# =============================================================================
@st.cache_resource
def get_fao_client() -> FAOSDGClient:
    """Initialize FAO SDG data client."""
    return FAOSDGClient()


@st.cache_resource
def get_area_catalog() -> list[str]:
    """Load and cache the list of available countries/areas."""
    return get_fao_client().list_areas()


@st.cache_resource
def get_indicator_specs() -> list:
    """Load indicator specifications from YAML catalog."""
    catalog_path = ROOT / "src" / "catalogs" / "ag_indicators.yaml"
    if not catalog_path.exists():
        st.error(f"Indicator catalog not found: {catalog_path}")
        return []
    return load_indicator_catalog(catalog_path)


@st.cache_resource
def get_pathways_index() -> PathwaysIndex:
    """Initialize and cache the Pathways for Peace document index."""
    pdf_path = ROOT / "data" / "docs" / "pathways_for_peace.pdf"
    idx = PathwaysIndex(pdf_path=pdf_path, index_dir=ROOT / "rag_store")
    idx.ensure_index(rebuild=False)
    return idx


@st.cache_resource
def get_policy_assistant() -> AgriculturalPolicyRAGAssistant:
    """Initialize the policy assistant with all required components."""
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


# =============================================================================
# TAB 1: SDG Explorer
# =============================================================================
with tab1:
    st.subheader("SDG Explorer")

    # Informational section
    st.markdown(
        """
        <div style="background-color: #e8f4e8; padding: 1.2rem; border-radius: 8px; 
                    margin-bottom: 1.5rem; border-left: 4px solid #2ca02c;">
        <h5 style="margin-top: 0; color: #2ca02c;">Purpose</h5>
        <p style="margin-bottom: 0.8rem;">
        The SDG Explorer enables you to query official food security and agricultural 
        sustainability indicators from the FAO's SDG database. This module is intended 
        to support <strong>situation analysis</strong> and <strong>trend monitoring</strong> 
        by providing accessible visualizations and plain-language summaries of complex 
        statistical data.
        </p>
        
        <h5 style="color: #2ca02c;">Available Indicators</h5>
        <ul style="margin-bottom: 0.8rem;">
            <li><strong>SDG 2.1.1:</strong> Prevalence of undernourishment (% of population)</li>
            <li><strong>SDG 2.1.2:</strong> Prevalence of moderate or severe food insecurity (FIES)</li>
            <li><strong>SDG 2.4.1:</strong> Proportion of agricultural area under sustainable practices</li>
            <li><strong>SDG 15.1.1:</strong> Forest area as a proportion of total land area</li>
        </ul>
        
        <h5 style="color: #2ca02c;">How to Use</h5>
        <ol style="margin-bottom: 0;">
            <li>Enter your question in natural language in the text field below.</li>
            <li>Click <strong>"Run SDG analysis"</strong> to retrieve the data.</li>
            <li>Review the generated chart, narrative summary, and underlying data table.</li>
        </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Example queries
    with st.expander("📝 Example Questions"):
        st.markdown(
            """
            - *"Compare undernourishment (2.1.1) in Kenya and Rwanda since 2010."*
            - *"Show food insecurity trends in Ethiopia from 2015 to 2022."*
            - *"What is the prevalence of undernourishment in Somalia?"*
            - *"Compare sustainable agriculture indicators across East African countries."*
            """
        )

    agent = SDGResearchAgent()

    q = st.text_input(
        "Enter your question about SDG food security indicators:",
        value="Compare undernourishment (2.1.1) in Kenya and Rwanda since 2010.",
        help="Specify countries, indicators (e.g., 2.1.1, 2.1.2), and time periods.",
    )

    if st.button("Run SDG analysis", key="run_sdg"):
        with st.spinner("Retrieving data from FAO SDG database..."):
            chart_path = ROOT / "sdg_chart.png"
            result = agent.run(q, chart_output_path=str(chart_path))

        st.markdown("---")

        st.markdown("### Visualization")
        if result.chart_path and Path(result.chart_path).exists():
            st.image(result.chart_path, use_container_width=True)
        else:
            st.info("No chart was generated for this query.")

        st.markdown("### Interpretation")
        st.write(result.narrative)

        st.markdown("### Source Data")
        if result.data is None or result.data.empty:
            st.warning("No data was returned. Please verify country names and indicators.")
        else:
            st.caption("Raw data from the FAO SDG database:")
            st.dataframe(result.data, use_container_width=True)


# =============================================================================
# TAB 2: Policy Assistant
# =============================================================================
with tab2:
    st.subheader("Policy Assistant")

    # Informational section
    st.markdown(
        """
        <div style="background-color: #fff3e0; padding: 1.2rem; border-radius: 8px; 
                    margin-bottom: 1.5rem; border-left: 4px solid #ff9800;">
        <h5 style="margin-top: 0; color: #e65100;">Purpose</h5>
        <p style="margin-bottom: 0.8rem;">
        The Policy Assistant provides <strong>evidence-based policy guidance</strong> 
        by synthesizing two authoritative sources: (1) official SDG indicator data from 
        the FAO, and (2) the <em>Pathways for Peace: Inclusive Approaches for Preventing 
        Violent Conflict</em> report, a joint publication of the United Nations and 
        the World Bank.
        </p>
        
        <h5 style="color: #e65100;">Key Features</h5>
        <ul style="margin-bottom: 0.8rem;">
            <li><strong>Contextual Analysis:</strong> Responses are tailored to the 
            specific country or region you select.</li>
            <li><strong>Evidence-Based Recommendations:</strong> Policy suggestions 
            are grounded in the <em>Pathways for Peace</em> framework.</li>
            <li><strong>Transparent Sources:</strong> All responses include citations 
            to specific passages from the source document.</li>
        </ul>
        
        <h5 style="color: #e65100;">How to Use</h5>
        <ol style="margin-bottom: 0;">
            <li>Select a <strong>country or region</strong> from the dropdown menu.</li>
            <li>Optionally, select specific <strong>SDG indicators</strong>.</li>
            <li>Enter your <strong>policy question</strong> in the text area.</li>
            <li>Click <strong>"Ask Policy Assistant"</strong> to receive a response.</li>
        </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Example questions
    with st.expander("📝 Example Policy Questions"):
        st.markdown(
            """
            - *"Design a package to reduce food insecurity while lowering conflict risks."*
            - *"What are the main drivers of food insecurity that could contribute to instability?"*
            - *"How can agricultural investment programmes promote social cohesion?"*
            - *"What early warning indicators should be monitored for food security crises?"*
            """
        )

    # Check for PDF file
    pdf_path = ROOT / "data" / "docs" / "pathways_for_peace.pdf"
    if not pdf_path.exists():
        st.error(
            f"**Configuration Required:** The reference document could not be located.\n\n"
            f"Please ensure that the *Pathways for Peace* PDF is placed at:\n"
            f"`data/docs/pathways_for_peace.pdf`"
        )
        st.stop()

    assistant = get_policy_assistant()
    specs = get_indicator_specs()

    colA, colB = st.columns(2)

    with colA:
        st.markdown("**Step 1: Select Context**")
        area = st.selectbox(
            "Country or Region",
            options=get_area_catalog(),
            index=0,
            help="Select the country or region for policy guidance.",
        )
        indicator_choices = [f"{s.sdg_indicator} — {s.name}" for s in specs]
        chosen = st.multiselect(
            "SDG Indicators (optional)",
            options=indicator_choices,
            help="Optionally select specific indicators to include.",
        )

    with colB:
        st.markdown("**Step 2: Formulate Your Question**")
        question = st.text_area(
            "Policy Question",
            height=140,
            value="Design a package to reduce food insecurity in this country while "
            "lowering conflict risks. Use evidence from SDG trends and Pathways for Peace.",
            help="Enter your policy question for analysis.",
        )
        topk = 5

    explicit_codes = []
    for c in chosen:
        explicit_codes.append(c.split("—")[0].strip())

    if st.button("Ask Policy Assistant", key="ask_policy", type="primary"):
        with st.spinner("Analyzing SDG data and retrieving policy guidance..."):
            result = assistant.answer_question(
                question=question,
                explicit_sdg_indicators=explicit_codes or None,
                explicit_areas=[area],
                max_inferred_areas=0,
                k_doc_passages=topk,
            )

        st.markdown("---")

        st.markdown("## Policy Guidance")
        st.write(result["answer"])

        st.markdown("## Supporting Evidence")

        with st.expander("📄 Pathways for Peace — Relevant Passages"):
            for p in result["doc_passages"]:
                st.markdown(f"**Page {p.page}** *(relevance: {p.score:.3f})*")
                st.markdown(f"> {p.text}")
                st.markdown("---")

        with st.expander("📊 SDG Data Series Consulted"):
            rows = []
            for item in result.get("sdg_series", []):
                series = item["series"] or {}
                rows.append(
                    {
                        "SDG Indicator": item["sdg_indicator"],
                        "Series Code": item["series_code"],
                        "Country/Area": item["area"],
                        "Data Points": len(series),
                        "Earliest Year": min(series.keys()) if series else "N/A",
                        "Latest Year": max(series.keys()) if series else "N/A",
                    }
                )
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("No SDG data series were retrieved for this query.")


# =============================================================================
# Footer
# =============================================================================
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #666; font-size: 0.85rem; padding: 1rem 0;">
    <p>
    <strong>Data Sources:</strong> Food and Agriculture Organization (FAO) SDG Indicators 
    Database; <em>Pathways for Peace: Inclusive Approaches for Preventing Violent 
    Conflict</em> (UN–World Bank, 2018).
    </p>
    <p>
    This tool is intended for informational and analytical purposes. Policy recommendations 
    should be validated through consultation with relevant stakeholders.
    </p>
    </div>
    """,
    unsafe_allow_html=True,
)
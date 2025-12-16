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

# -----------------------------------------------------------------------------
# OVERALL TOOL DESCRIPTION
# -----------------------------------------------------------------------------

st.markdown(
    """
    <div style="background-color: #f0f4f8; padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem; border-left: 4px solid #1f77b4;">
    <h4 style="margin-top: 0; color: #1f77b4;">About This Tool</h4>
    <p style="margin-bottom: 0.8rem;">
    This decision-support tool assists <strong>national planners, policy researchers, and development practitioners</strong> 
    in understanding the relationship between food security and conflict prevention. It integrates two complementary 
    capabilities:
    </p>
    <ul style="margin-bottom: 0.8rem;">
        <li><strong>SDG Explorer:</strong> Access and analyze official Sustainable Development Goal (SDG) indicators 
        from the Food and Agriculture Organization (FAO), with automated visualization and narrative interpretation.</li>
        <li><strong>Policy Assistant:</strong> Receive evidence-based policy guidance by combining SDG data with 
        insights from the <em>Pathways for Peace</em> report—a joint United Nations–World Bank flagship study on 
        inclusive approaches to preventing violent conflict.</li>
    </ul>
    <p style="margin-bottom: 0;">
    The tool is designed to support the development of policies that address the structural drivers of conflict, 
    with a particular focus on food insecurity as both a consequence and a contributor to instability.
    </p>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2 = st.tabs(["📊 SDG Explorer", "📋 Policy Assistant"])


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


# -----------------------------------------------------------------------------
# TAB 1: SDG EXPLORER
# -----------------------------------------------------------------------------

with tab1:
    st.subheader("SDG Explorer")
    
    # Informational section for Tab 1
    with st.container():
        st.markdown(
            """
            <div style="background-color: #e8f4e8; padding: 1.2rem; border-radius: 8px; margin-bottom: 1.5rem; border-left: 4px solid #2ca02c;">
            <h5 style="margin-top: 0; color: #2ca02c;">Purpose</h5>
            <p style="margin-bottom: 0.8rem;">
            The SDG Explorer enables you to query official food security and agricultural sustainability indicators 
            from the FAO's SDG database. This module is intended to support <strong>situation analysis</strong> and 
            <strong>trend monitoring</strong> by providing accessible visualizations and plain-language summaries 
            of complex statistical data.
            </p>
            
            <h5 style="color: #2ca02c;">Available Indicators</h5>
            <ul style="margin-bottom: 0.8rem;">
                <li><strong>SDG 2.1.1:</strong> Prevalence of undernourishment (percentage of population)</li>
                <li><strong>SDG 2.1.2:</strong> Prevalence of moderate or severe food insecurity (FIES)</li>
                <li><strong>SDG 2.4.1:</strong> Proportion of agricultural area under sustainable practices</li>
                <li><strong>SDG 15.1.1:</strong> Forest area as a proportion of total land area</li>
            </ul>
            
            <h5 style="color: #2ca02c;">How to Use</h5>
            <ol style="margin-bottom: 0;">
                <li>Enter your question in natural language in the text field below. You may specify countries, 
                indicators, and time periods.</li>
                <li>Click <strong>"Run SDG analysis"</strong> to retrieve the data.</li>
                <li>Review the generated chart, narrative summary, and underlying data table.</li>
            </ol>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # Example queries help box
    with st.expander("📝 Example Questions"):
        st.markdown(
            """
            The following examples illustrate the types of queries this module can address:
            
            - *"Compare undernourishment (2.1.1) in Kenya and Rwanda since 2010."*
            - *"Show food insecurity trends in Ethiopia from 2015 to 2022."*
            - *"What is the prevalence of undernourishment in Somalia?"*
            - *"Compare sustainable agriculture indicators across East African countries."*
            
            You may combine multiple countries and indicators in a single query. The system will 
            interpret your request and retrieve the most relevant data.
            """
        )
    
    agent = SDGResearchAgent()

    q = st.text_input(
        "Enter your question about SDG food security indicators:",
        value="Compare undernourishment (2.1.1) in Kenya and Rwanda since 2010.",
        help="Specify countries, indicators (e.g., 2.1.1, 2.1.2), and time periods as needed.",
    )

    if st.button("Run SDG analysis", key="run_sdg"):
        with st.spinner("Retrieving data from FAO SDG database and generating analysis..."):
            result = agent.run(q, chart_output_path=str(ROOT / "sdg_chart.png"))

        st.markdown("---")
        
        st.markdown("### Visualization")
        if result.chart_path and Path(result.chart_path).exists():
            st.image(result.chart_path, use_container_width=True)
        else:
            st.info("No chart was generated for this query. This may occur if no data is available for the specified parameters.")

        st.markdown("### Interpretation")
        st.write(result.narrative)

        st.markdown("### Source Data")
        if result.data is None or result.data.empty:
            st.warning("No data was returned for the specified query. Please verify the country names and indicator codes, or try a different time period.")
        else:
            st.caption("The table below displays the raw data retrieved from the FAO SDG database. You may download this data for further analysis.")
            st.dataframe(result.data, use_container_width=True)


# -----------------------------------------------------------------------------
# TAB 2: POLICY ASSISTANT
# -----------------------------------------------------------------------------

with tab2:
    st.subheader("Policy Assistant")
    
    # Informational section for Tab 2
    with st.container():
        st.markdown(
            """
            <div style="background-color: #fff3e0; padding: 1.2rem; border-radius: 8px; margin-bottom: 1.5rem; border-left: 4px solid #ff9800;">
            <h5 style="margin-top: 0; color: #e65100;">Purpose</h5>
            <p style="margin-bottom: 0.8rem;">
            The Policy Assistant provides <strong>evidence-based policy guidance</strong> by synthesizing two 
            authoritative sources: (1) official SDG indicator data from the FAO, and (2) the 
            <em>Pathways for Peace: Inclusive Approaches for Preventing Violent Conflict</em> report, a joint 
            publication of the United Nations and the World Bank.
            </p>
            <p style="margin-bottom: 0.8rem;">
            This module is designed to support <strong>policy formulation</strong> and <strong>programme design</strong> 
            by connecting empirical data on food security conditions with established frameworks for conflict-sensitive 
            development.
            </p>
            
            <h5 style="color: #e65100;">Key Features</h5>
            <ul style="margin-bottom: 0.8rem;">
                <li><strong>Contextual Analysis:</strong> Responses are tailored to the specific country or region 
                you select, drawing on relevant SDG data.</li>
                <li><strong>Evidence-Based Recommendations:</strong> Policy suggestions are grounded in the 
                <em>Pathways for Peace</em> framework, which emphasizes prevention, inclusion, and addressing 
                structural drivers of conflict.</li>
                <li><strong>Transparent Sources:</strong> All responses include citations to specific passages 
                from the source document and the SDG data series consulted.</li>
            </ul>
            
            <h5 style="color: #e65100;">How to Use</h5>
            <ol style="margin-bottom: 0;">
                <li>Select a <strong>country or region</strong> from the dropdown menu.</li>
                <li>Optionally, select specific <strong>SDG indicators</strong> to focus the analysis.</li>
                <li>Enter your <strong>policy question</strong> in the text area. Frame your question around 
                conflict prevention, food security, or related development challenges.</li>
                <li>Click <strong>"Ask Policy Assistant"</strong> to receive a synthesized response with supporting evidence.</li>
            </ol>
            </div>
            """,
            unsafe_allow_html=True,
        )
    
    # Example queries help box
    with st.expander("📝 Example Policy Questions"):
        st.markdown(
            """
            The Policy Assistant is designed to address questions that connect food security with conflict prevention. Examples include:
            
            - *"Design a package to reduce food insecurity in this country while lowering conflict risks."*
            - *"What are the main drivers of food insecurity that could contribute to instability in this region?"*
            - *"How can agricultural investment programmes be designed to promote social cohesion?"*
            - *"What early warning indicators should be monitored to anticipate food security crises?"*
            - *"What role can food security interventions play in post-conflict recovery?"*
            
            The assistant will draw on both quantitative SDG data and qualitative guidance from the 
            <em>Pathways for Peace</em> report to formulate its response.
            """
        )

    # Ensure user has the PDF locally
    pdf_path = ROOT / "data" / "docs" / "pathways_for_peace.pdf"
    if not pdf_path.exists():
        st.error(
            f"**Configuration Required:** The reference document could not be located.\n\n"
            f"Please ensure that the *Pathways for Peace* PDF is placed at:\n"
            f"`data/docs/pathways_for_peace.pdf`\n\n"
            f"Then refresh this page to continue."
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
            help="Select the country or region for which you would like policy guidance.",
        )
        indicator_choices = [f"{s.sdg_indicator} — {s.name}" for s in specs]
        chosen = st.multiselect(
            "SDG Indicators (optional)",
            options=indicator_choices,
            help="Optionally select specific indicators to include in the analysis. If none are selected, the assistant will determine which indicators are most relevant to your question.",
        )

    with colB:
        st.markdown("**Step 2: Formulate Your Question**")
        question = st.text_area(
            "Policy Question",
            height=140,
            value="Design a package to reduce food insecurity in this country while lowering conflict risks. "
                  "Use evidence from SDG trends and Pathways for Peace.",
            help="Enter your policy question. The assistant will synthesize SDG data and conflict prevention guidance to formulate a response.",
        )
        topk = 5  # Number of document passages to retrieve

    explicit_codes = []
    for c in chosen:
        # format "2.1.1 — Name"
        explicit_codes.append(c.split("—")[0].strip())

    if st.button("Ask Policy Assistant", key="ask_policy", type="primary"):
        with st.spinner("Analyzing SDG data and retrieving relevant policy guidance..."):
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
        st.caption("The following sections display the source materials consulted in generating the response above.")
        
        with st.expander("📄 Pathways for Peace — Relevant Passages", expanded=False):
            st.markdown(
                """
                The passages below were retrieved from *Pathways for Peace: Inclusive Approaches for 
                Preventing Violent Conflict* (United Nations and World Bank, 2018). Each passage is 
                accompanied by its page number and a relevance score.
                """
            )
            for p in result["doc_passages"]:
                st.markdown(f"**Page {p.page}** *(relevance score: {p.score:.3f})*")
                st.markdown(f"> {p.text}")
                st.markdown("---")

        with st.expander("📊 SDG Data Series Consulted", expanded=False):
            st.markdown(
                """
                The table below summarizes the SDG indicator data retrieved from the FAO database 
                for this analysis. This data informed the quantitative aspects of the policy guidance.
                """
            )
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


# -----------------------------------------------------------------------------
# FOOTER
# -----------------------------------------------------------------------------

st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #666; font-size: 0.85rem; padding: 1rem 0;">
    <p>
    <strong>Data Sources:</strong> Food and Agriculture Organization (FAO) SDG Indicators Database; 
    <em>Pathways for Peace: Inclusive Approaches for Preventing Violent Conflict</em> (UN–World Bank, 2018).
    </p>
    <p>
    This tool is intended for informational and analytical purposes. Policy recommendations should be 
    validated through consultation with relevant stakeholders and subject-matter experts.
    </p>
    </div>
    """,
    unsafe_allow_html=True,
)
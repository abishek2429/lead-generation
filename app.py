"""
IncuBrix Growth Studio — Multi-Channel Creator Discovery & Outbound Engine.
Professional B2B SaaS Dashboard for creator discovery, deduplication, quality gate verification,
source-linked evidence inspection, algorithmic scoring, and multi-channel campaign orchestration.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# Optional pandas with resilient fallback
try:
    import pandas as pd
    HAS_PANDAS = True
except (ImportError, OSError):
    pd = None
    HAS_PANDAS = False

from src.config import load_config
from src.database import Database
from src.deduplication import canonicalize_url, deduplicate_batch
from src.discovery.import_csv import CSVDiscovery
from src.discovery.youtube_api import YouTubeAPIDiscovery, YouTubeAPIError
from src.exports import (
    ASSESSMENT_WORKBOOK_HEADERS,
    DAY4_OUTREACH_HEADERS,
    EVIDENCE_ITEM_HEADERS,
    OUTREACH_PREPARATION_HEADERS,
    OUTREACH_TEMPLATE_HEADERS,
    VERIFICATION_LOG_HEADERS,
    export_evidence_items_csv,
    export_leads_csv,
    export_outreach_all_qualified_csv,
    export_outreach_preparations_csv,
    export_outreach_priority_a_csv,
    export_outreach_templates_csv,
    export_summary_json,
    export_workbook_pack,
    format_lead_row,
)
from src.logging_config import generate_run_id, get_logger, setup_logging
from src.models import (
    CampaignOutreachRecord,
    DeliveryEvent,
    InvalidStateTransitionError,
    Lead,
    OutreachPreparation,
    OutreachState,
    OutreachTemplate,
    QualificationStatus,
    SuppressionRecord,
)
from src.verification.channels import (
    normalize_segment,
    select_channels_for_lead,
)
from src.verification.evidence import (
    create_evidence_items_for_lead,
    is_safe_public_url,
    safe_http_head_or_get,
)
from src.verification.outreach import (
    generate_outreach_for_lead,
    prepare_all_qualified_outreach,
    prepare_priority_a_outreach_batch,
)
from src.verification.qualification import (
    classify_candidate_gates,
    evaluate_hard_gates,
    qualify_lead,
    rank_and_assign_priorities,
    validate_country_mix,
)
from src.verification.seed_testing import (
    AUTHORIZED_TEST_DOMAINS,
    AUTHORIZED_TEST_ENDPOINTS,
    OutreachSimulator,
    SeedSimulator,
    contains_pii,
    generate_opaque_tracking_link,
    generate_tracking_link,
    is_authorized_test_endpoint,
    transition_record_state,
)
from src.verification.templates import (
    SENDER_IDENTITY,
    get_all_templates,
)


def current_utc_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# Page configuration
st.set_page_config(
    page_title="IncuBrix Lead Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for Minimalist, Professional B2B SaaS Dashboard
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #0f172a;
    }

    /* Background and Layout */
    .stApp {
        background-color: #f8fafc;
    }

    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e2e8f0;
    }

    /* Headings */
    h1, h2, h3, h4, h5, h6 {
        color: #0f172a;
        font-weight: 600;
        letter-spacing: -0.015em;
    }

    /* SaaS Header Container */
    .saas-header {
        margin-bottom: 20px;
        padding-bottom: 14px;
        border-bottom: 1px solid #e2e8f0;
    }

    .saas-title {
        font-size: 1.45rem;
        font-weight: 600;
        color: #0f172a;
        margin: 0 0 4px 0;
    }

    .saas-subtitle {
        font-size: 0.85rem;
        color: #64748b;
        margin: 0;
    }

    /* KPI Cards */
    .saas-kpi-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 14px 18px;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
        margin-bottom: 12px;
    }

    .saas-kpi-label {
        font-size: 0.75rem;
        font-weight: 600;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 4px;
    }

    .saas-kpi-value {
        font-size: 1.7rem;
        font-weight: 700;
        color: #0f172a;
        line-height: 1.2;
    }

    .saas-kpi-subtext {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-top: 3px;
    }

    /* Content Cards */
    .saas-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 18px 20px;
        margin-bottom: 16px;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.02);
    }

    .saas-card-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: #0f172a;
        margin-bottom: 12px;
    }

    /* Status Badges */
    .badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.72rem;
        font-weight: 600;
        line-height: 1.4;
        text-transform: uppercase;
        letter-spacing: 0.02em;
    }

    .badge-qualified {
        background-color: #ecfdf5;
        color: #047857;
        border: 1px solid #a7f3d0;
    }

    .badge-needs-review {
        background-color: #fffbeb;
        color: #b45309;
        border: 1px solid #fde68a;
    }

    .badge-disqualified {
        background-color: #fef2f2;
        color: #b91c1c;
        border: 1px solid #fecaca;
    }

    .badge-discovered {
        background-color: #f8fafc;
        color: #475569;
        border: 1px solid #cbd5e1;
    }

    .badge-priority-a {
        background-color: #eff6ff;
        color: #1d4ed8;
        border: 1px solid #bfdbfe;
    }

    .badge-channel {
        background-color: #f1f5f9;
        color: #334155;
        border: 1px solid #e2e8f0;
    }

    /* Brand Header in Sidebar */
    .sidebar-brand {
        padding: 4px 0 16px 0;
        border-bottom: 1px solid #e2e8f0;
        margin-bottom: 14px;
    }

    .brand-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #0f172a;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .brand-subtitle {
        font-size: 0.72rem;
        color: #64748b;
        margin-top: 2px;
    }

    .sidebar-footer {
        padding-top: 14px;
        margin-top: 24px;
        border-top: 1px solid #e2e8f0;
        font-size: 0.72rem;
        color: #94a3b8;
    }

    /* Streamlit table adjustments */
    div[data-testid="stDataFrame"] {
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        background: #ffffff;
    }

    /* Restrained button styling */
    div.stButton > button:first-child {
        border-radius: 6px;
        font-weight: 500;
        font-size: 0.85rem;
        transition: all 0.15s ease;
    }

    /* Compact expander styling */
    div[data-testid="stExpander"] {
        border: 1px solid #e2e8f0 !important;
        border-radius: 6px !important;
        background: #ffffff !important;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_metric_card(label: str, value: Any, subtext: str = "") -> None:
    """Render a minimalist SaaS KPI card."""
    st.markdown(
        f"""
        <div class="saas-kpi-card">
            <div class="saas-kpi-label">{label}</div>
            <div class="saas-kpi-value">{value}</div>
            <div class="saas-kpi-subtext">{subtext}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_table(data: List[Dict[str, Any]]) -> None:
    """Render structured table using native Streamlit dataframe with clean HTML fallback."""
    if not data:
        st.info("No records to display.")
        return

    if HAS_PANDAS and pd is not None:
        try:
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True, hide_index=True)
            return
        except Exception:
            pass

    # Pure HTML / CSS minimalist table rendering fallback
    headers = list(data[0].keys())
    html = [
        '<div style="overflow-x:auto; max-height:420px; border-radius:6px; border:1px solid #e2e8f0; margin:10px 0; background:#ffffff;">',
        '<table style="width:100%; border-collapse:collapse; font-size:0.84rem; text-align:left;">',
        '<thead style="background:#f8fafc; position:sticky; top:0; z-index:2;"><tr>',
    ]
    for h in headers:
        html.append(
            f'<th style="padding:8px 12px; border-bottom:1px solid #e2e8f0; color:#475569; font-weight:600; font-size:0.78rem;">{h}</th>'
        )
    html.append('</tr></thead><tbody>')

    for i, row in enumerate(data):
        bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
        html.append(f'<tr style="background:{bg}; border-bottom:1px solid #f1f5f9;">')
        for h in headers:
            raw_val = row.get(h)
            val = str(raw_val) if raw_val is not None else "-"
            lower_v = val.lower()
            if lower_v == "qualified":
                val = '<span class="badge badge-qualified">QUALIFIED</span>'
            elif lower_v == "discovered":
                val = '<span class="badge badge-discovered">DISCOVERED</span>'
            elif lower_v == "needs_review":
                val = '<span class="badge badge-needs-review">NEEDS REVIEW</span>'
            elif lower_v == "disqualified":
                val = '<span class="badge badge-disqualified">DISQUALIFIED</span>'
            elif val == "A":
                val = '<span class="badge badge-priority-a">A</span>'
            elif val.startswith("http://") or val.startswith("https://"):
                val = f'<a href="{val}" target="_blank" style="color:#2563eb; text-decoration:none; font-weight:500;">Link ↗</a>'

            html.append(f'<td style="padding:8px 12px; color:#0f172a;">{val}</td>')
        html.append('</tr>')

    html.append('</tbody></table></div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def auto_seed_if_empty(database: Database, app_config: Any) -> None:
    """
    If database is empty on fresh deployment, auto-seed baseline candidate fixtures
    so the live engine displays full pipeline data immediately.
    """
    try:
        if database.get_metrics().get("total_candidates", 0) > 0:
            return

        sample_candidates = Path("data/input/candidates_sample.csv")
        if not sample_candidates.is_file():
            sample_candidates = Path(__file__).resolve().parent / "data" / "input" / "candidates_sample.csv"

        if not sample_candidates.is_file():
            return

        importer = CSVDiscovery()
        sample_leads, _ = importer.parse_csv(sample_candidates, run_id="init_seed")
        if not sample_leads:
            return

        to_insert, _, _ = deduplicate_batch([], sample_leads, run_id="init_seed")
        for lead in to_insert:
            database.insert_lead(lead)

        now_ref = datetime.now(timezone.utc)
        all_evs = []
        leads = database.get_all_leads()
        for lead in leads:
            q_lead, vlog = qualify_lead(lead, app_config, reference_date=now_ref, run_id="init_seed")
            database.update_lead(q_lead)
            database.log_verification(vlog)
            evs = create_evidence_items_for_lead(q_lead, reference_date=now_ref)
            database.insert_evidence_items(evs)
            all_evs.extend(evs)

        ranked = rank_and_assign_priorities(leads, max_priority_a=25, reference_date=now_ref)
        for r in ranked:
            database.update_lead(r)

        outreaches = prepare_all_qualified_outreach(ranked, all_evs)
        database.save_outreach_preparations(outreaches)

        export_workbook_pack(
            database.get_all_leads(),
            output_dir="data/output",
            verification_logs=database.get_verification_logs(),
            evidence_items=database.get_all_evidence_items(),
            outreach_preparations=database.get_outreach_preparations(),
            allow_synthetic=False,
        )
    except Exception as exc:
        get_logger("app").warning(f"Auto-seed on initial launch skipped: {exc}")


# Initialize application dependencies
@st.cache_resource
def get_app_dependencies():
    setup_logging()
    cfg = load_config()
    db = Database(cfg.database_path)
    auto_seed_if_empty(db, cfg)
    return cfg, db

config, db = get_app_dependencies()

# Check query parameters for opaque tracking link clicks (Safe Simulation)
if "trk" in st.query_params or st.query_params.get("action") == "track":
    trk_token = st.query_params.get("trk") or st.query_params.get("token")
    if trk_token:
        try:
            ev, created = OutreachSimulator.simulate_interaction(
                opaque_id=trk_token,
                event_type="CLICK",
                test_account_id="candidate_browser_test",
                db=db,
            )
            st.toast(
                f"Simulated click recorded (Token: {trk_token[:8]}...)",
                icon="ℹ️",
            )
        except Exception:
            pass

# Initialize session state
if "run_id" not in st.session_state:
    st.session_state.run_id = generate_run_id()
if "nav_section" not in st.session_state:
    st.session_state.nav_section = "Overview"

# ==============================================================================
# SIDEBAR NAVIGATION
# ==============================================================================
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="brand-title">
                <span>⚡</span> IncuBrix Lead Engine
            </div>
            <div class="brand-subtitle">Creator Discovery & Outbound Studio</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    nav_options = [
        "Overview",
        "Discover Leads",
        "Qualified Leads",
        "Outreach",
        "Exports",
        "Settings",
    ]

    nav_icons = {
        "Overview": "📊",
        "Discover Leads": "📥",
        "Qualified Leads": "⚖️",
        "Outreach": "✉️",
        "Exports": "📤",
        "Settings": "⚙️",
    }

    selected_nav = st.radio(
        "Navigation",
        options=nav_options,
        format_func=lambda x: f"{nav_icons[x]}  {x}",
        label_visibility="collapsed",
        key="main_navigation_radio",
    )
    st.session_state.nav_section = selected_nav

    # Sidebar footer: minimal system status
    st.markdown(
        f"""
        <div class="sidebar-footer">
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                <span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:#10b981;"></span>
                <span style="color:#475569; font-weight:500;">System Active</span>
            </div>
            <div>Run ID: <code>{st.session_state.run_id[:12]}...</code></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Fetch shared metrics
metrics = db.get_metrics()
total_cands = metrics["total_candidates"]
review_cands = metrics.get("needs_review", 0)
qual_cands = metrics.get("qualified", 0)
real_qual_cands = metrics.get("real_qualified", 0)
disq_cands = metrics.get("disqualified", 0)
syn_cands = metrics.get("synthetic_candidates", 0)
pri_a_count = metrics.get("priority_a_count", metrics["priority_breakdown"].get("A", 0))
fresh_rate = metrics.get("evidence_freshness_rate", 1.0)


# ==============================================================================
# SECTION 1: OVERVIEW
# ==============================================================================
if selected_nav == "Overview":
    st.markdown(
        """
        <div class="saas-header">
            <h1 class="saas-title">Pipeline Overview</h1>
            <p class="saas-subtitle">Operational summary of creator discovery, quality gate verification, and geographic distribution.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 4 Key Metrics Derived Directly from Active Database
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_metric_card("Total Candidates", total_cands, f"{syn_cands} benchmark fixtures")
    with m2:
        render_metric_card("Qualified Leads", qual_cands, f"{real_qual_cands} real production leads")
    with m3:
        render_metric_card("Priority A Leads", pri_a_count, "Top tier (capped at 25)")
    with m4:
        render_metric_card("Needs Review", review_cands, "Requires proof verification")

    col_geo, col_seg = st.columns([1.1, 1])

    with col_geo:
        st.markdown(
            """
            <div class="saas-card-title">Target Geographic Distribution & Policy Compliance</div>
            """,
            unsafe_allow_html=True,
        )
        all_leads = db.get_all_leads()
        mix_res = validate_country_mix(all_leads, config.qualification_policy)

        # 3 Policy Gate Status Indicators
        p1, p2, p3 = st.columns(3)
        with p1:
            st.metric("Approved Share", f"{mix_res['share_allowed_countries']*100:.1f}%", help="Target: ≥ 80% in approved geographies")
        with p2:
            st.metric("Distinct Countries", f"{mix_res['distinct_countries']}", help="Target: ≥ 3 distinct countries")
        with p3:
            st.metric("Max Single Country", f"{mix_res['max_single_country_share']*100:.1f}%", help="Target: ≤ 60% max share")

        if mix_res["meets_policy"]:
            st.success("Target geographic distribution complies with all policy gates.", icon="✅")
        else:
            for w in mix_res["warnings"]:
                st.warning(w, icon="⚠️")

        if mix_res["total_qualified"] > 0:
            c_data = [
                {"Country": k, "Qualified Leads": v, "Share": f"{(v / mix_res['total_qualified']) * 100:.1f}%"}
                for k, v in sorted(mix_res["breakdown"].items(), key=lambda x: x[1], reverse=True)
            ]
            render_table(c_data)
        else:
            st.info("No qualified leads in database yet. Run qualification in Qualified Leads.")

    with col_seg:
        st.markdown(
            """
            <div class="saas-card-title">Creator Segment Distribution</div>
            """,
            unsafe_allow_html=True,
        )
        seg_data = metrics.get("segment_breakdown", {})
        if seg_data:
            s_data = [
                {"Creator Segment": k, "Candidates": v, "Share": f"{(v / max(1, total_cands)) * 100:.1f}%"}
                for k, v in sorted(seg_data.items(), key=lambda x: x[1], reverse=True)
            ]
            render_table(s_data)
        else:
            st.info("No candidate records found in database.")

        st.markdown(
            """
            <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:12px 14px; margin-top:14px;">
                <div style="font-size:0.75rem; font-weight:600; color:#475569; text-transform:uppercase; margin-bottom:6px;">
                    Qualification Policy Baseline
                </div>
                <div style="font-size:0.8rem; color:#64748b; line-height:1.5;">
                    • 10 Hard Gates with zero guessed contact tolerance<br>
                    • Activity mode: ≥ 8 items in 30d OR ≥ 2 long-form in 60d<br>
                    • Contact activity max: 60 days | Evidence freshness max: 30 days<br>
                    • Priority A tier capped at top 25 scored creators
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Recent Operational Verification Activity
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="saas-card-title">Recent Verification Activity</div>
        """,
        unsafe_allow_html=True,
    )
    vlogs = db.get_verification_logs(limit=5)
    if vlogs:
        vlog_rows = [
            {
                "Timestamp (UTC)": l.timestamp[:19].replace("T", " "),
                "Platform ID": l.platform_id,
                "Status Before": l.status_before or "-",
                "Status After": l.status_after or "-",
                "Score": l.score,
                "Priority": l.priority or "-",
                "Audit Outcome": ", ".join(l.disqualification_reasons) if l.disqualification_reasons else "All 10 Gates Passed",
            }
            for l in vlogs
        ]
        render_table(vlog_rows)
    else:
        st.info("No verification logs recorded yet. Evaluate candidates in Qualified Leads.")

    # Developer Diagnostics in a clean expander
    with st.expander("System Diagnostics & Evidence Health"):
        d1, d2, d3 = st.columns(3)
        with d1:
            st.metric("Evidence Freshness", f"{fresh_rate * 100:.0f}%", help="Percentage of evidence checked within last 30 days")
        with d2:
            st.metric("Total Evidence Items", metrics.get("total_evidence_items", 0))
        with d3:
            st.metric("Disqualified Leads", disq_cands)
        st.caption(f"Database Path: `{config.database_path}` | Session Run ID: `{st.session_state.run_id}`")


# ==============================================================================
# SECTION 2: DISCOVER LEADS
# ==============================================================================
elif selected_nav == "Discover Leads":
    st.markdown(
        """
        <div class="saas-header">
            <h1 class="saas-title">Discover Leads</h1>
            <p class="saas-subtitle">Import candidate creators from CSV datasets or discover active channels via the YouTube Data API.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    disc_mode = st.radio(
        "Discovery Source",
        ["CSV Dataset Ingestion", "YouTube Data API v3 (Live)"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if disc_mode == "CSV Dataset Ingestion":
        st.markdown(
            """
            <div class="saas-card-title">Import Candidate Dataset</div>
            """,
            unsafe_allow_html=True,
        )

        csv_choice = st.radio(
            "Source Selection:",
            ["Standard Benchmark Dataset (data/input/candidates_sample.csv)", "Upload Custom CSV File"],
            horizontal=True,
        )

        importer = CSVDiscovery()

        if "candidates_sample.csv" in csv_choice:
            sample_path = Path("data/input/candidates_sample.csv")
            if sample_path.is_file():
                if st.button("Load & Preview Benchmark Candidates", type="secondary"):
                    with st.spinner("Parsing benchmark dataset..."):
                        leads, errs = importer.parse_csv(sample_path, run_id=st.session_state.run_id)
                        if errs:
                            for e in errs:
                                st.warning(e)
                        st.session_state.preview_leads = leads
                        st.success(f"Loaded {len(leads)} candidate records from benchmark sample.")
            else:
                st.error("Sample candidates file not found at data/input/candidates_sample.csv")
        else:
            uploaded_file = st.file_uploader("Upload CSV file", type=["csv"], help="CSV must contain creator identifiers and profile URLs.")
            if uploaded_file is not None:
                if st.button("Parse Uploaded CSV", type="secondary"):
                    with st.spinner("Parsing uploaded file..."):
                        bytes_data = io.BytesIO(uploaded_file.getvalue())
                        leads, errs = importer.parse_csv(bytes_data, run_id=st.session_state.run_id)
                        if errs:
                            for e in errs:
                                st.warning(e)
                        st.session_state.preview_leads = leads
                        st.success(f"Successfully parsed {len(leads)} candidate records.")

        if "preview_leads" in st.session_state and st.session_state.preview_leads:
            p_leads = st.session_state.preview_leads
            st.markdown(f"**Previewing {len(p_leads)} Candidates:**")
            preview_data = [
                {
                    "Creator Name": l.creator_name,
                    "Segment": l.creator_type,
                    "Country": l.country or "-",
                    "Platform ID": l.platform_id,
                    "Profile URL": l.official_profile_url,
                    "Status": l.qualification_status,
                }
                for l in p_leads[:20]
            ]
            render_table(preview_data)
            if len(p_leads) > 20:
                st.caption(f"Showing first 20 of {len(p_leads)} parsed records.")

            if st.button("Deduplicate & Save Candidates to Database", type="primary"):
                existing = db.get_all_leads()
                with st.spinner("Deduplicating and saving candidate records..."):
                    to_insert, to_update, stats = deduplicate_batch(
                        existing_leads=existing,
                        incoming_candidates=p_leads,
                        run_id=st.session_state.run_id,
                    )

                    for item in to_insert:
                        db.insert_lead(item)
                    for item in to_update:
                        db.update_lead(item)

                st.success(
                    f"Processed {stats['total_incoming']} candidates: "
                    f"**{stats['new_records']} new** inserted, "
                    f"**{stats['merged_records']} merged**, "
                    f"**{stats['exact_duplicates']} duplicate** rejected."
                )
                del st.session_state.preview_leads
                st.rerun()

    else:
        st.markdown(
            """
            <div class="saas-card-title">YouTube Channel Discovery (Official Data API v3)</div>
            """,
            unsafe_allow_html=True,
        )
        yt_client = YouTubeAPIDiscovery(api_key=config.youtube_api_key)

        if not yt_client.is_configured():
            st.info(
                "Local Discovery Mode Active — YouTube API key is not configured. Searches use local mock fixtures. "
                "You can configure an API key in **Settings**.",
                icon="ℹ️",
            )

        q_col1, q_col2, q_col3 = st.columns([3, 1, 1.5])
        with q_col1:
            search_query = st.text_input("Keywords / Query", value="creator podcast interview")
        with q_col2:
            max_res = st.number_input("Max Results", min_value=1, max_value=25, value=5)
        with q_col3:
            creator_type = st.selectbox("Target Segment", config.qualification_policy.allowed_segments, index=0)

        if st.button("Search YouTube API", type="primary"):
            with st.spinner("Searching YouTube channels..."):
                try:
                    yt_candidates = yt_client.search_channels(
                        query=search_query,
                        max_results=int(max_res),
                        creator_type=creator_type,
                        run_id=st.session_state.run_id,
                    )
                    st.session_state.yt_candidates = yt_candidates
                    st.success(f"Discovered {len(yt_candidates)} candidate channels.")
                except YouTubeAPIError as e:
                    st.error(f"YouTube API Error: {e}")

        if "yt_candidates" in st.session_state and st.session_state.yt_candidates:
            yt_cands = st.session_state.yt_candidates
            st.markdown(f"**Found {len(yt_cands)} Channels:**")
            yt_preview = [
                {
                    "Creator Name": c.creator_name,
                    "Segment": c.creator_type,
                    "Country": c.country or "Pending Verification",
                    "Channel ID": c.platform_id,
                    "Profile URL": c.official_profile_url,
                    "Recent Uploads": len(c.recent_content_urls),
                }
                for c in yt_cands
            ]
            render_table(yt_preview)

            if st.button("Deduplicate & Save Discovered Channels to Database", type="primary"):
                existing = db.get_all_leads()
                with st.spinner("Saving channels..."):
                    to_insert, to_update, stats = deduplicate_batch(
                        existing_leads=existing,
                        incoming_candidates=yt_cands,
                        run_id=st.session_state.run_id,
                    )

                    for item in to_insert:
                        db.insert_lead(item)
                    for item in to_update:
                        db.update_lead(item)

                st.success(
                    f"Processed {stats['total_incoming']} channels: "
                    f"**{stats['new_records']} new** inserted, "
                    f"**{stats['merged_records']} merged**, "
                    f"**{stats['exact_duplicates']} duplicate** rejected."
                )
                del st.session_state.yt_candidates
                st.rerun()

        # Optional developer API smoke test
        with st.expander("API Diagnostics & Smoke Test"):
            if st.button("Execute YouTube API Smoke Test", type="secondary"):
                with st.spinner("Executing bounded smoke test..."):
                    res = yt_client.smoke_test(save_metadata=True)
                    if res.get("configured") and res.get("success"):
                        st.success(f"Smoke Test Passed: Retrieved {res.get('records_retrieved')} creator records.")
                    elif not res.get("configured"):
                        st.info(f"{res.get('message')}")
                    else:
                        st.error(f"Smoke test failed: {', '.join(res.get('errors', []))}")


# ==============================================================================
# SECTION 3: QUALIFIED LEADS
# ==============================================================================
elif selected_nav == "Qualified Leads":
    st.markdown(
        """
        <div class="saas-header">
            <h1 class="saas-title">Qualified Leads</h1>
            <p class="saas-subtitle">Search, filter, and inspect qualified creators evaluated against the 10 policy hard gates and 5-dimension scoring.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Batch Qualification Pipeline Action
    with st.expander("🚀 Qualification Engine & Pipeline Execution", expanded=False):
        q_col1, q_col2 = st.columns([2, 1])
        with q_col1:
            eval_scope = st.radio(
                "Evaluation Scope:",
                ["Pending Candidates Only ('discovered' status)", "Re-evaluate All Leads in Database"],
                horizontal=True,
            )
        with q_col2:
            st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
            run_eval_btn = st.button("Run Qualification Pipeline", type="primary")

        if run_eval_btn:
            all_db_leads = db.get_all_leads()
            if eval_scope.startswith("Pending"):
                targets = [l for l in all_db_leads if l.qualification_status == QualificationStatus.DISCOVERED.value]
            else:
                targets = all_db_leads

            if not targets:
                st.info("No candidates match the selected evaluation scope.")
            else:
                qual_count = 0
                review_count = 0
                disq_count = 0
                now_ref = datetime.now(timezone.utc)

                with st.spinner(f"Evaluating {len(targets)} candidates against qualification gates..."):
                    all_ev_items = []
                    for candidate in targets:
                        evaluated, vlog = qualify_lead(
                            lead=candidate,
                            config=config,
                            reference_date=now_ref,
                            run_id=st.session_state.run_id,
                        )
                        db.update_lead(evaluated)
                        db.log_verification(vlog)

                        ev_items = create_evidence_items_for_lead(evaluated, reference_date=now_ref)
                        db.insert_evidence_items(ev_items)
                        all_ev_items.extend(ev_items)

                        if evaluated.qualification_status == QualificationStatus.QUALIFIED.value:
                            qual_count += 1
                        elif evaluated.qualification_status == QualificationStatus.NEEDS_REVIEW.value:
                            review_count += 1
                        else:
                            disq_count += 1

                    # Rank and assign priorities (capped at top 25 Priority A)
                    all_leads_pool = db.get_all_leads()
                    ranked = rank_and_assign_priorities(all_leads_pool, max_priority_a=25, reference_date=now_ref)
                    for rl in ranked:
                        db.update_lead(rl)

                    # Prepare personalized outreach sequences
                    all_outreach = prepare_all_qualified_outreach(ranked, all_ev_items)
                    db.save_outreach_preparations(all_outreach)
                    pri_a_preps_count = sum(1 for p in all_outreach if (getattr(p, "priority", "") or "").upper() == "A")

                st.success(
                    f"Qualification Pipeline Complete: **{qual_count} Qualified**, **{review_count} Needs Review**, **{disq_count} Disqualified**. "
                    f"Generated {len(all_ev_items)} evidence records and prepared {len(all_outreach)} outreach sequences ({pri_a_preps_count} Priority A)."
                )
                st.rerun()

    # Search & Filter Controls
    all_table_leads = db.get_all_leads()
    distinct_countries = sorted(list({l.country for l in all_table_leads if l.country}))

    f_search_col, f_stat_col, f_pri_col, f_cntry_col, f_fix_col = st.columns([2.5, 1.5, 1.2, 1.5, 1.3])
    with f_search_col:
        search_kw = st.text_input("Search Creator or ID", "", placeholder="Filter by name or platform ID...")
    with f_stat_col:
        f_status = st.selectbox("Status", ["All", "qualified", "needs_review", "discovered", "disqualified"])
    with f_pri_col:
        f_priority = st.selectbox("Priority", ["All", "A", "B", "C"])
    with f_cntry_col:
        f_country = st.selectbox("Country", ["All"] + distinct_countries)
    with f_fix_col:
        f_fixture = st.selectbox("Data Type", ["All", "Real Only", "Fixtures Only"])

    # Apply in-memory filters
    filtered_table = all_table_leads
    if f_status != "All":
        filtered_table = [l for l in filtered_table if l.qualification_status.lower() == f_status.lower()]
    if f_priority != "All":
        filtered_table = [l for l in filtered_table if (l.priority or "").upper() == f_priority.upper()]
    if f_country != "All":
        filtered_table = [l for l in filtered_table if (l.country or "").lower() == f_country.lower()]
    if f_fixture == "Real Only":
        filtered_table = [l for l in filtered_table if not getattr(l, "is_synthetic", False)]
    elif f_fixture == "Fixtures Only":
        filtered_table = [l for l in filtered_table if getattr(l, "is_synthetic", False)]
    if search_kw.strip():
        kw = search_kw.strip().lower()
        filtered_table = [
            l for l in filtered_table
            if kw in l.creator_name.lower() or kw in l.platform_id.lower()
        ]

    st.markdown(f"**Displaying {len(filtered_table)} of {len(all_table_leads)} creators:**")

    if filtered_table:
        display_rows = [
            {
                "Creator Name": l.creator_name,
                "Segment": l.creator_type,
                "Country": l.country or "-",
                "Status": l.qualification_status,
                "Score": f"{l.score:.1f}" if l.score else "-",
                "Priority": l.priority or "-",
                "Contact Channel": f"{l.business_contact_type or 'None'}: {l.business_contact_value or 'Missing'}".strip(": "),
                "Disqualification Reasons": "; ".join(l.disqualification_reasons) if l.disqualification_reasons else "All Passed",
            }
            for l in filtered_table
        ]
        render_table(display_rows)
    else:
        st.info("No creators match the active search and filter criteria.")

    # Individual Creator Detail Inspector
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="saas-card-title">Creator Detail Inspector</div>
        """,
        unsafe_allow_html=True,
    )

    if filtered_table:
        lead_options = {f"{l.creator_name} ({l.platform_id}) [{l.qualification_status.upper()}]": l for l in filtered_table}
        selected_key = st.selectbox("Select Creator to Inspect:", list(lead_options.keys()), label_visibility="collapsed")
        inspected = lead_options[selected_key]

        insp_col1, insp_col2 = st.columns([1, 1.2])

        with insp_col1:
            st.markdown(f"### {inspected.creator_name}")
            st.markdown(f"**Segment:** `{inspected.creator_type}` | **Country:** `{inspected.country or 'None'}` | **Language:** `{inspected.language}`")
            st.markdown(f"**Official Profile:** [{inspected.official_profile_url}]({inspected.official_profile_url})")

            # Status pill
            if inspected.qualification_status == "qualified":
                st.markdown(f"**Status:** <span class='badge badge-qualified'>QUALIFIED (Score: {inspected.score:.1f} | Priority {inspected.priority})</span>", unsafe_allow_html=True)
            elif inspected.qualification_status == "discovered":
                st.markdown(f"**Status:** <span class='badge badge-discovered'>DISCOVERED (Pending Evaluation)</span>", unsafe_allow_html=True)
            elif inspected.qualification_status == "needs_review":
                st.markdown(f"**Status:** <span class='badge badge-needs-review'>NEEDS REVIEW (Proof Unverified)</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"**Status:** <span class='badge badge-disqualified'>DISQUALIFIED</span>", unsafe_allow_html=True)

            if getattr(inspected, "is_synthetic", False):
                st.caption("ℹ️ **Benchmark Fixture:** Isolated from production CRM exports.")

            st.markdown("##### Verified Contact & Evidence Endpoints:")
            st.markdown(f"• **Contact:** `{inspected.business_contact_type or 'None'}` {inspected.business_contact_value or '*Missing*'}")
            st.markdown(f"• **Contact Source URL:** {inspected.business_contact_source_url or '*Missing*'}")
            st.markdown(f"• **Contact Activity Date:** `{inspected.business_contact_last_active or 'Missing'}`")
            st.markdown(f"• **Commercial Offer URL:** {inspected.commercial_evidence_url or '*Missing*'}")
            st.markdown(f"• **Workflow Need URL:** {inspected.workflow_need_evidence_url or '*Missing*'}")
            st.markdown(f"• **Evidence Checked Date:** `{inspected.evidence_checked_at or 'Missing'}`")

        with insp_col2:
            st.markdown("### Quality Gate Audit & Scoring")
            now_dt = datetime.now(timezone.utc)
            status_gate, reasons_gate = classify_candidate_gates(inspected, config.qualification_policy, reference_date=now_dt)

            if status_gate == "qualified":
                st.success("All 10 Non-Negotiable Hard Gates Passed", icon="✅")
                st.markdown(f"**Total Score: {inspected.score:.1f} / 100 | Priority Tier: {inspected.priority or 'B'}**")
                if inspected.score_breakdown:
                    score_rows = [
                        {
                            "Dimension": "1. Content Workflow Need",
                            "Points": f"{inspected.score_breakdown.get('workflow_need', {}).get('points', 0)} / 30",
                            "Reason": inspected.score_breakdown.get('workflow_need', {}).get('reason', '-'),
                        },
                        {
                            "Dimension": "2. Target Segment Fit",
                            "Points": f"{inspected.score_breakdown.get('segment_fit', {}).get('points', 0)} / 25",
                            "Reason": inspected.score_breakdown.get('segment_fit', {}).get('reason', '-'),
                        },
                        {
                            "Dimension": "3. Commercial Intent",
                            "Points": f"{inspected.score_breakdown.get('commercial_intent', {}).get('points', 0)} / 20",
                            "Reason": inspected.score_breakdown.get('commercial_intent', {}).get('reason', '-'),
                        },
                        {
                            "Dimension": "4. Publishing Consistency",
                            "Points": f"{inspected.score_breakdown.get('publishing_consistency', {}).get('points', 0)} / 15",
                            "Reason": inspected.score_breakdown.get('publishing_consistency', {}).get('reason', '-'),
                        },
                        {
                            "Dimension": "5. Contact Channel Quality",
                            "Points": f"{inspected.score_breakdown.get('contact_channel_quality', {}).get('points', 0)} / 10",
                            "Reason": inspected.score_breakdown.get('contact_channel_quality', {}).get('reason', '-'),
                        },
                    ]
                    render_table(score_rows)
                else:
                    st.caption("Score breakdown details available after running pipeline.")
            elif status_gate == "needs_review":
                st.warning("Needs Review — Missing Verified Public Evidence:", icon="⚠️")
                for r in reasons_gate:
                    st.markdown(f"• **{r}**")
                st.caption("Matches segment and country, but public commercial intent, workflow bottleneck, or active business contact requires proof.")
            else:
                st.error("Disqualified by Policy Hard Gates:", icon="❌")
                for r in reasons_gate:
                    st.markdown(f"• **{r}**")

    # Source-Linked Evidence Inspector in an expander
    with st.expander("Source-Linked Evidence Records"):
        all_evs = db.get_all_evidence_items()
        ev_filter_col1, ev_filter_col2 = st.columns([1, 1])
        with ev_filter_col1:
            ev_status_filter = st.selectbox("Verification Status", ["All", "verified", "unverified", "failed", "stale"])
        with ev_filter_col2:
            ev_type_filter = st.selectbox("Claim Type", ["All", "official_identity", "recent_content", "commercial_offer", "workflow_need", "business_contact", "contact_activity", "country_language"])

        filtered_evs = all_evs
        if ev_status_filter != "All":
            filtered_evs = [e for e in filtered_evs if e.verification_status.lower() == ev_status_filter.lower()]
        if ev_type_filter != "All":
            filtered_evs = [e for e in filtered_evs if e.evidence_type.lower() == ev_type_filter.lower()]

        if filtered_evs:
            ev_table_rows = [
                {
                    "Platform ID": e.platform_id,
                    "Claim Type": e.evidence_type,
                    "Status": e.verification_status.upper(),
                    "Method": e.verification_method,
                    "Factual Claim": e.short_factual_description,
                    "Source URL": e.source_url if len(e.source_url) <= 45 else e.source_url[:42] + "...",
                    "Checked (UTC)": e.checked_at[:19] if e.checked_at else "-",
                }
                for e in filtered_evs[:30]
            ]
            render_table(ev_table_rows)
            if len(filtered_evs) > 30:
                st.caption(f"Showing first 30 of {len(filtered_evs)} evidence records.")
        else:
            st.info("No evidence records match the selected filter.")


# ==============================================================================
# SECTION 4: OUTREACH
# ==============================================================================
elif selected_nav == "Outreach":
    st.markdown(
        """
        <div class="saas-header">
            <h1 class="saas-title">Outreach Studio</h1>
            <p class="saas-subtitle">Review deterministic channel routing (Email, LinkedIn, Instagram) and personalized 3-touch outreach sequences.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    preparations = db.get_outreach_preparations()
    all_leads = db.get_all_leads()
    leads_by_id = {l.platform_id: l for l in all_leads}

    # Summary metrics
    pri_a_preps = [p for p in preparations if (getattr(p, "priority", "A") or "A").upper() == "A"]
    suitable_count = sum(1 for p in preparations if getattr(p, "channel_suitability_status", "suitable") == "suitable")
    review_count = sum(1 for p in preparations if getattr(p, "channel_suitability_status", "suitable") == "needs_review")

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        render_metric_card("Prepared Sequences", len(preparations), "All qualified creators")
    with s2:
        render_metric_card("Priority A Sequences", len(pri_a_preps), "Top tier (capped at 25)")
    with s3:
        render_metric_card("Channel Suitable", suitable_count, "Passed contact validation")
    with s4:
        render_metric_card("Needs Proof Review", review_count, "Flagged channel suitability")

    # Filter Bar
    f_p_col, f_s_col, f_c_col, f_cntry_col = st.columns(4)
    with f_p_col:
        out_priority_filter = st.selectbox("Priority Tier", ["All", "Priority A Only", "Priority B Only", "Priority C Only"])
    with f_s_col:
        out_segment_filter = st.selectbox("Creator Segment", ["All", "podcaster", "youtube_creator", "coach", "consultant", "educator"])
    with f_c_col:
        out_suitability_filter = st.selectbox("Channel Suitability", ["All", "suitable", "needs_review"])
    with f_cntry_col:
        distinct_countries = sorted(list({l.country for l in all_leads if l.country}))
        out_country_filter = st.selectbox("Country", ["All"] + distinct_countries)

    # Filter preparations
    filtered_preps = preparations
    if out_priority_filter == "Priority A Only":
        filtered_preps = [p for p in filtered_preps if (p.priority or "").upper() == "A"]
    elif out_priority_filter == "Priority B Only":
        filtered_preps = [p for p in filtered_preps if (p.priority or "").upper() == "B"]
    elif out_priority_filter == "Priority C Only":
        filtered_preps = [p for p in filtered_preps if (p.priority or "").upper() == "C"]

    if out_segment_filter != "All":
        filtered_preps = [p for p in filtered_preps if normalize_segment(getattr(p, "segment", "")) == out_segment_filter]

    if out_suitability_filter != "All":
        filtered_preps = [p for p in filtered_preps if getattr(p, "channel_suitability_status", "suitable").lower() == out_suitability_filter.lower()]

    if out_country_filter != "All":
        filtered_preps = [
            p for p in filtered_preps
            if (leads_by_id.get(p.platform_id) and (leads_by_id[p.platform_id].country or "").lower() == out_country_filter.lower())
        ]

    st.markdown(f"**Displaying {len(filtered_preps)} of {len(preparations)} prepared sequences:**")

    if not filtered_preps:
        st.info("No outreach sequences match the selected filters. Run qualification in Qualified Leads to generate sequences.")
    else:
        for idx, prep in enumerate(filtered_preps, 1):
            p_suit = getattr(prep, "channel_suitability_status", "suitable")
            p_val = getattr(prep, "validation_status", "valid")
            suit_badge = "🟢 Suitable" if p_suit == "suitable" else "🟡 Needs Review"
            lead_ref = leads_by_id.get(prep.platform_id)
            country_label = lead_ref.country if lead_ref and lead_ref.country else "Unknown"
            primary_ch = getattr(prep, "primary_channel", "email")

            card_label = (
                f"#{idx} — {prep.creator_name} ({prep.platform_id}) | "
                f"Priority: {prep.priority} | Score: {prep.score:.1f} | "
                f"Channel: {primary_ch.upper()} | {suit_badge}"
            )

            with st.expander(card_label, expanded=(idx == 1)):
                col_left, col_right = st.columns([1, 1.2])

                with col_left:
                    st.markdown("##### Channel Routing & Grounding")
                    st.markdown(f"• **Segment:** `{getattr(prep, 'segment', '')}` | **Country:** `{country_label}`")
                    st.markdown(f"• **Primary Channel:** `{primary_ch.upper()}`")
                    st.markdown(f"• **Verified Contact:** `{getattr(prep, 'primary_contact_value', '') or 'Not Verified'}`")
                    if getattr(prep, "primary_contact_source_url", ""):
                        st.markdown(f"• **Source URL:** [{prep.primary_contact_source_url}]({prep.primary_contact_source_url})")
                    st.caption(f"**Routing Rationale:** {getattr(prep, 'primary_channel_reason', '')}")

                    backup_ch = getattr(prep, "backup_channel", "")
                    if backup_ch:
                        st.markdown(f"• **Backup Channel:** `{backup_ch.upper()}` ({getattr(prep, 'backup_contact_value', '')})")

                    st.markdown("##### Verified Content Grounding:")
                    st.markdown(f"• **Cited Content URL:** [{prep.specific_content_source_url}]({prep.specific_content_source_url})")
                    st.markdown(f"• **Sender Identity:** `{getattr(prep, 'sender_identity', SENDER_IDENTITY)}`")
                    st.markdown(f"• **Preparation State:** `{getattr(prep, 'outreach_status', 'DRAFT')}`")

                with col_right:
                    st.markdown("##### 3-Touch Sequence Review & Editing")

                    edit_subject = st.text_input(
                        "Subject Line:",
                        value=prep.subject_line,
                        key=f"subj_{prep.platform_id}_{prep.id}",
                    )

                    edit_msg1 = st.text_area(
                        "Touch 1: Personalized Initial Message (Grounded in Verified Bottleneck):",
                        value=prep.proposed_first_message,
                        height=140,
                        key=f"t1_{prep.platform_id}_{prep.id}",
                    )

                    edit_fu1 = st.text_area(
                        f"Touch 2: Value-Add Follow-up (+{prep.follow_up_1_delay_days}d delay):",
                        value=prep.follow_up_1,
                        height=100,
                        key=f"t2_{prep.platform_id}_{prep.id}",
                    )

                    edit_fu2 = st.text_area(
                        f"Touch 3: Clean Breakup Follow-up (+{prep.follow_up_2_delay_days}d delay):",
                        value=prep.follow_up_2,
                        height=90,
                        key=f"t3_{prep.platform_id}_{prep.id}",
                    )

                    st.caption(f"Opt-Out Language: {prep.opt_out_language}")

                    if st.button(f"Save Sequence for {prep.creator_name}", key=f"save_{prep.platform_id}_{prep.id}", type="primary"):
                        prep.subject_line = edit_subject
                        prep.proposed_first_message = edit_msg1
                        prep.follow_up_1 = edit_fu1
                        prep.follow_up_2 = edit_fu2
                        prep.updated_at = current_utc_iso()
                        db.update_outreach_preparation(prep)
                        st.success(f"Updated outreach sequence for {prep.creator_name} in database.")
                        st.rerun()

    # Safe Outreach Delivery & Reply Simulator in an expander
    with st.expander("Safe Outreach Delivery & State Machine Simulator (Sandbox Test Mode)"):
        st.info(
            "Outreach Simulator Workflow: Operates strictly against internally controlled test accounts (@incubrix.local). "
            "Never contacts real creators or social platforms. Used to verify state machine transitions and opt-out suppression.",
            icon="🛡️",
        )

        existing_campaign_records = db.get_campaign_outreach_records()
        distinct_camps = sorted(list({r.campaign_id for r in existing_campaign_records if r.campaign_id}))
        if not distinct_camps:
            distinct_camps = ["camp_2026_q4_seed"]

        camp_col1, camp_col2 = st.columns([2, 1])
        with camp_col1:
            active_sim_campaign = st.selectbox("Simulation Campaign Scope:", distinct_camps, key="sim_camp_select")
        with camp_col2:
            st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
            if st.button("Provision Test Records for Campaign", type="secondary"):
                pri_a_preps = [p for p in preparations if (getattr(p, "priority", "A") or "A").upper() == "A"]
                if not pri_a_preps:
                    pri_a_preps = preparations[:5]

                prov_count = 0
                for p in pri_a_preps:
                    lead_obj = leads_by_id.get(p.platform_id)
                    if lead_obj and lead_obj.id:
                        OutreachSimulator.create_campaign_record(
                            lead=lead_obj,
                            campaign_id=active_sim_campaign,
                            channel=p.primary_channel,
                            contact_endpoint="candidate@incubrix.local",
                            test_account_id="growth.candidate@incubrix.local",
                            db=db,
                        )
                        prov_count += 1
                st.success(f"Provisioned {prov_count} test records in campaign '{active_sim_campaign}' (State: draft).")
                st.rerun()

        camp_summary = OutreachSimulator.get_campaign_summary(campaign_id=active_sim_campaign, db=db)
        cs1, cs2, cs3, cs4, cs5, cs6, cs7 = st.columns(7)
        with cs1:
            st.metric("Drafts", camp_summary["draft_count"])
        with cs2:
            st.metric("Approved", camp_summary["approved_count"])
        with cs3:
            st.metric("Sim Sends", camp_summary["sent_count"])
        with cs4:
            st.metric("Clicks", camp_summary["simulated_clicks"])
        with cs5:
            st.metric("Replied", camp_summary["replied_count"])
        with cs6:
            st.metric("Opt-Outs", camp_summary["opted_out_count"])
        with cs7:
            st.metric("Closed", camp_summary["closed_count"])

        camp_records = db.get_campaign_outreach_records(campaign_id=active_sim_campaign)
        if camp_records:
            rec_options = {f"Lead #{r.lead_id}: {r.creator_name} [{r.state.upper()}]": r for r in camp_records}
            selected_rec_key = st.selectbox("Select Test Record to Transition:", list(rec_options.keys()), key="sim_rec_picker")
            selected_rec = rec_options[selected_rec_key]

            st.markdown(f"**Current State:** `{selected_rec.state.upper()}` | **Endpoint:** `{selected_rec.contact_endpoint}`")
            token = selected_rec.opaque_id or "c1a8f9b23e4d"
            _, tracking_url = generate_opaque_tracking_link(base_url="http://localhost:8501", opaque_id=token)
            st.caption(f"Opaque Tracking URL (Zero PII): `{tracking_url}`")

            t_btn1, t_btn2, t_btn3, t_btn4, t_btn5 = st.columns(5)
            with t_btn1:
                if st.button("1. Approve", disabled=(selected_rec.state != "draft"), key=f"app_{selected_rec.id}"):
                    OutreachSimulator.approve_for_test(selected_rec, db=db)
                    st.rerun()
            with t_btn2:
                if st.button("2. Send", disabled=(selected_rec.state != "approved_for_test"), key=f"snd_{selected_rec.id}"):
                    OutreachSimulator.simulate_send(selected_rec, db=db)
                    st.rerun()
            with t_btn3:
                if st.button("3. Click", disabled=(selected_rec.state not in ("sent_in_test", "replied_in_test")), key=f"clk_{selected_rec.id}"):
                    OutreachSimulator.simulate_interaction(selected_rec.opaque_id, "CLICK", db=db)
                    st.rerun()
            with t_btn4:
                if st.button("4. Reply", disabled=(selected_rec.state != "sent_in_test"), key=f"rpl_{selected_rec.id}"):
                    OutreachSimulator.simulate_interaction(selected_rec.opaque_id, "REPLY", reply_text="Interested in learning more.", db=db)
                    st.rerun()
            with t_btn5:
                if st.button("5. Opt-Out", disabled=(selected_rec.state in ("opted_out", "closed")), key=f"opt_{selected_rec.id}"):
                    OutreachSimulator.simulate_opt_out(selected_rec, db=db)
                    st.rerun()


# ==============================================================================
# SECTION 5: EXPORTS
# ==============================================================================
elif selected_nav == "Exports":
    st.markdown(
        """
        <div class="saas-header">
            <h1 class="saas-title">Data Exports & Deliverables</h1>
            <p class="saas-subtitle">Download standardized CSV exports for CRM ingestion, qualification auditing, and campaign execution.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    all_export_leads = db.get_all_leads()
    leads_by_id = {l.platform_id: l for l in all_export_leads}
    vlogs_export = db.get_verification_logs()
    evs_export = db.get_all_evidence_items()
    preps_export = db.get_outreach_preparations()

    # Isolation Setting
    allow_syn_export = st.checkbox(
        "Include benchmark test fixtures in exports (Inspection mode)",
        value=False,
        help="When unchecked, synthetic test fixtures are strictly excluded so production exports contain only verified real leads.",
    )

    # Calculate real export counts before downloading
    if allow_syn_export:
        q_count = len([l for l in all_export_leads if l.qualification_status == "qualified"])
        p_a_count = len([p for p in preps_export if (getattr(p, "priority", "") or "").upper() == "A"])
        all_q_prep_count = len(preps_export)
    else:
        q_count = len([l for l in all_export_leads if l.qualification_status == "qualified" and not getattr(l, "is_synthetic", False)])
        p_a_count = len([p for p in preps_export if (getattr(p, "priority", "") or "").upper() == "A" and not getattr(leads_by_id.get(p.platform_id), "is_synthetic", False)])
        all_q_prep_count = len([p for p in preps_export if not getattr(leads_by_id.get(p.platform_id), "is_synthetic", False)])

    cands_count = len(all_export_leads)
    nr_count = len([l for l in all_export_leads if l.qualification_status == "needs_review"])
    disq_count = len([l for l in all_export_leads if l.qualification_status == "disqualified"])
    ev_count = len(evs_export)

    if not allow_syn_export and q_count == 0:
        st.caption("ℹ️ **Production Isolation Active:** 0 real qualified records in database. Enable benchmark test fixtures above to export sample candidate records.")

    # Primary Action: Generate Deliverables
    if st.button("Generate Complete Deliverables Package", type="primary"):
        with st.spinner("Generating export package in data/output/..."):
            pack_paths = export_workbook_pack(
                all_export_leads,
                output_dir="data/output",
                verification_logs=vlogs_export,
                evidence_items=evs_export,
                outreach_preparations=preps_export,
                allow_synthetic=allow_syn_export,
            )
            export_outreach_priority_a_csv(preps_export, "data/output/outreach_priority_a.csv", allow_synthetic=allow_syn_export)
            export_outreach_all_qualified_csv(preps_export, "data/output/outreach_all_qualified.csv", allow_synthetic=allow_syn_export)
            export_outreach_templates_csv(None, "data/output/outreach_templates.csv")
        st.success("Deliverables package generated successfully in `data/output/`.")

    # Refresh output files on disk to guarantee accurate downloads
    export_workbook_pack(
        all_export_leads,
        output_dir="data/output",
        verification_logs=vlogs_export,
        evidence_items=evs_export,
        outreach_preparations=preps_export,
        allow_synthetic=allow_syn_export,
    )
    export_outreach_priority_a_csv(preps_export, "data/output/outreach_priority_a.csv", allow_synthetic=allow_syn_export)
    export_outreach_all_qualified_csv(preps_export, "data/output/outreach_all_qualified.csv", allow_synthetic=allow_syn_export)
    export_outreach_templates_csv(None, "data/output/outreach_templates.csv")

    st.markdown("<br>", unsafe_allow_html=True)

    # Grouped Download Cards
    exp_col1, exp_col2, exp_col3 = st.columns(3)

    with exp_col1:
        st.markdown("##### 1. Qualified CRM Deliverables")

        # qualified_leads.csv
        p_ql = Path("data/output/qualified_leads.csv")
        if p_ql.exists():
            st.download_button(
                label=f"⬇️ qualified_leads.csv ({q_count} records)",
                data=p_ql.read_text(encoding="utf-8"),
                file_name="qualified_leads.csv",
                mime="text/csv",
                key="dl_btn_ql",
                help="Real qualified creators passing all 10 hard gates with verified evidence.",
            )

        # priority_a_outreach.csv
        p_pao = Path("data/output/priority_a_outreach.csv")
        if p_pao.exists():
            st.download_button(
                label=f"⬇️ priority_a_outreach.csv ({p_a_count} records)",
                data=p_pao.read_text(encoding="utf-8"),
                file_name="priority_a_outreach.csv",
                mime="text/csv",
                key="dl_btn_pao",
                help="Top 25 Priority A leads with 3 personalized touches grounded in verified content.",
            )

        # outreach_all_qualified.csv
        p_oaq = Path("data/output/outreach_all_qualified.csv")
        if p_oaq.exists():
            st.download_button(
                label=f"⬇️ outreach_all_qualified.csv ({all_q_prep_count} records)",
                data=p_oaq.read_text(encoding="utf-8"),
                file_name="outreach_all_qualified.csv",
                mime="text/csv",
                key="dl_btn_oaq",
                help="Complete sequence preparations for all qualified leads.",
            )

    with exp_col2:
        st.markdown("##### 2. Auditing & Pipeline Records")

        # all_candidates.csv
        p_ac = Path("data/output/all_candidates.csv")
        if p_ac.exists():
            st.download_button(
                label=f"⬇️ all_candidates.csv ({cands_count} records)",
                data=p_ac.read_text(encoding="utf-8"),
                file_name="all_candidates.csv",
                mime="text/csv",
                key="dl_btn_ac",
                help="Complete register of all discovered and imported candidates.",
            )

        # needs_review.csv
        p_nr = Path("data/output/needs_review.csv")
        if p_nr.exists():
            st.download_button(
                label=f"⬇️ needs_review.csv ({nr_count} records)",
                data=p_nr.read_text(encoding="utf-8"),
                file_name="needs_review.csv",
                mime="text/csv",
                key="dl_btn_nr",
                help="Creators matching target profile but pending verified proof.",
            )

        # disqualification_audit.csv
        p_da = Path("data/output/disqualification_audit.csv")
        if p_da.exists():
            st.download_button(
                label=f"⬇️ disqualification_audit.csv ({disq_count} records)",
                data=p_da.read_text(encoding="utf-8"),
                file_name="disqualification_audit.csv",
                mime="text/csv",
                key="dl_btn_da",
                help="Explicit policy gate failure reasons for non-qualified candidates.",
            )

        # evidence_items.csv
        p_ei = Path("data/output/evidence_items.csv")
        if p_ei.exists():
            st.download_button(
                label=f"⬇️ evidence_items.csv ({ev_count} records)",
                data=p_ei.read_text(encoding="utf-8"),
                file_name="evidence_items.csv",
                mime="text/csv",
                key="dl_btn_ei",
                help="Source-linked evidence records supporting creator claims.",
            )

    with exp_col3:
        st.markdown("##### 3. Templates & Quality Reports")

        # outreach_templates.csv
        p_ot = Path("data/output/outreach_templates.csv")
        if p_ot.exists():
            st.download_button(
                label="⬇️ outreach_templates.csv (15 templates)",
                data=p_ot.read_text(encoding="utf-8"),
                file_name="outreach_templates.csv",
                mime="text/csv",
                key="dl_btn_ot",
                help="15 segment x channel template matrix (45 touches total).",
            )

        # verification_audit_log.csv
        p_val = Path("data/output/verification_audit_log.csv")
        if p_val.exists():
            st.download_button(
                label="⬇️ verification_audit_log.csv",
                data=p_val.read_text(encoding="utf-8"),
                file_name="verification_audit_log.csv",
                mime="text/csv",
                key="dl_btn_val",
                help="Full audit trail tracking gate evaluations and timestamps.",
            )

        # audit_and_quality_report.json
        p_aqr = Path("data/output/audit_and_quality_report.json")
        if p_aqr.exists():
            st.download_button(
                label="⬇️ audit_and_quality_report.json",
                data=p_aqr.read_text(encoding="utf-8"),
                file_name="audit_and_quality_report.json",
                mime="application/json",
                key="dl_btn_aqr",
                help="Structured JSON quality report including freshness and country mix metrics.",
            )


# ==============================================================================
# SECTION 6: SETTINGS
# ==============================================================================
elif selected_nav == "Settings":
    st.markdown(
        """
        <div class="saas-header">
            <h1 class="saas-title">Settings & System Status</h1>
            <p class="saas-subtitle">API credential configuration, database storage status, and qualification policy parameters.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    set_col1, set_col2 = st.columns([1, 1])

    with set_col1:
        st.markdown("##### YouTube Data API Integration")
        api_status = "Configured (Live API Discovery)" if config.youtube_api_key else "Local Discovery Mode Active"
        badge_class = "badge-qualified" if config.youtube_api_key else "badge-discovered"
        st.markdown(f"Status: <span class='badge {badge_class}'>{api_status}</span>", unsafe_allow_html=True)

        new_key = st.text_input(
            "YouTube API Key",
            value=config.youtube_api_key or "",
            type="password",
            help="Optional Google Cloud API key for live search. If blank, local discovery mode is used.",
        )
        if new_key != (config.youtube_api_key or ""):
            config.youtube_api_key = new_key if new_key.strip() else None
            st.success("API configuration updated for current session.")

        st.caption("Endpoints used: search.list, channels.list, videos.list.")

        st.markdown("---")
        st.markdown("##### Storage & Session Environment")
        st.markdown(f"• **SQLite Database:** `{config.database_path}`")
        st.markdown(f"• **Input Directory:** `{config.input_dir}`")
        st.markdown(f"• **Output Directory:** `{config.output_dir}`")
        st.markdown(f"• **Session Run ID:** `{st.session_state.run_id}`")

        if st.button("Generate New Session Run ID", type="secondary"):
            st.session_state.run_id = generate_run_id()
            st.success("Generated new session Run ID.")
            st.rerun()

    with set_col2:
        st.markdown("##### Qualification Policy Parameters")
        pol = config.qualification_policy
        st.markdown(f"• **Approved Segments:** `{', '.join(pol.allowed_segments)}`")
        st.markdown(f"• **Excluded Types:** `{', '.join(pol.excluded_types)}`")
        st.markdown(f"• **Target Geographies:** `{', '.join(pol.allowed_countries)}`")
        st.markdown(f"• **Primary Language:** `{pol.primary_language}`")
        st.markdown(f"• **Activity Mode:** `{pol.activity_gate.mode}` (≥{pol.activity_gate.content_items_last_30_days_min} in 30d OR ≥{pol.activity_gate.long_form_items_last_60_days_min} long-form in 60d)")
        st.markdown(f"• **Contact Activity Max:** `{pol.contact_activity_days_max} days`")
        st.markdown(f"• **Evidence Freshness Max:** `{pol.evidence_freshness_days_max} days`")
        st.markdown(f"• **Guessed Contacts:** `Strictly Prohibited`")

        st.markdown("##### 5-Dimension Scoring Weights (Max 100):")
        sc = config.scoring_after_hard_gates
        st.markdown(f"• Content Workflow Need: **{sc.workflow_need} pts**")
        st.markdown(f"• Target Segment Fit: **{sc.segment_fit} pts**")
        st.markdown(f"• Commercial Intent: **{sc.commercial_intent} pts**")
        st.markdown(f"• Publishing Consistency: **{sc.publishing_consistency} pts**")
        st.markdown(f"• Contact Channel Quality: **{sc.contact_channel_quality} pts**")

    # Developer Diagnostics Expander
    with st.expander("Technical Diagnostics & Security Sandboxes"):
        diag_col1, diag_col2 = st.columns([1, 1])

        with diag_col1:
            st.markdown("###### URL SSRF & Hostname Safety Auditor")
            test_url = st.text_input("Enter URL to audit safety:", value="https://www.youtube.com/@hubermanlab")
            if st.button("Audit URL", type="secondary"):
                is_safe, reason = is_safe_public_url(test_url)
                if is_safe:
                    st.success(f"Safe Public URL: Passes all SSRF and hostname restrictions.")
                else:
                    st.error(f"Blocked URL: {reason}")

        with diag_col2:
            st.markdown("###### Active Suppression List")
            suppressed = db.get_suppression_list()
            if suppressed:
                sup_rows = [
                    {
                        "Endpoint": s.contact_value,
                        "Channel": s.channel.upper(),
                        "Reason": s.reason,
                        "Opt-Out Time": s.opted_out_at[:19].replace("T", " "),
                    }
                    for s in suppressed
                ]
                render_table(sup_rows)
            else:
                st.caption("Suppression list is currently empty.")

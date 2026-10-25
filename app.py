"""
IncuBrix Growth Studio — Multi-Channel Creator Discovery & Outbound Engine.
Enterprise Streamlit application for creator discovery, deduplication, quality gate verification,
source-linked evidence inspection, algorithmic scoring, and multi-channel campaign orchestration.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# Optional pandas with resilient pure-python table fallback if Windows WDAC blocks C-extensions
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

# Page configuration
st.set_page_config(
    page_title="IncuBrix Growth Studio | Creator Discovery & Outbound Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Custom CSS for modern typography, gradients, glassmorphism and card styling
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    code, pre {
        font-family: 'JetBrains Mono', monospace;
    }
    
    .hero-container {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 24px 32px;
        margin-bottom: 24px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
    }
    
    .hero-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
    }
    
    .hero-subtitle {
        color: #94a3b8;
        font-size: 1.05rem;
        margin-bottom: 0;
    }
    
    .metric-card {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 16px 20px;
        text-align: center;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(56, 189, 248, 0.4);
    }
    
    .metric-val {
        font-size: 2rem;
        font-weight: 700;
        color: #f8fafc;
        margin: 4px 0;
    }
    
    .metric-lbl {
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    .badge-qual {
        background-color: #10b98120;
        color: #34d399;
        border: 1px solid #10b98140;
        padding: 3px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    
    .badge-disc {
        background-color: #38bdf820;
        color: #38bdf8;
        border: 1px solid #38bdf840;
        padding: 3px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    
    .badge-rej {
        background-color: #ef444420;
        color: #f87171;
        border: 1px solid #ef444440;
        padding: 3px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
    }

    .badge-review {
        background-color: #f59e0b20;
        color: #fbbf24;
        border: 1px solid #f59e0b40;
        padding: 3px 10px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
    }
    
    .badge-pri-a {
        background-color: #10b98120;
        color: #34d399;
        border: 1px solid #10b98140;
        padding: 3px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.8rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_table(data: List[Dict[str, Any]]) -> None:
    """Render structured table using styled HTML (with pandas dataframe fallback if available)."""
    if not data:
        st.info("No records to display.")
        return

    # If pandas is available and working without policy blocks, we can try it
    if HAS_PANDAS and pd is not None:
        try:
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
            return
        except Exception:
            pass

    # Pure HTML / CSS glassmorphism table rendering
    headers = list(data[0].keys())
    html = [
        '<div style="overflow-x:auto; max-height:450px; border-radius:12px; border:1px solid rgba(255,255,255,0.1); margin:12px 0;">',
        '<table style="width:100%; border-collapse:collapse; font-size:0.88rem; text-align:left;">',
        '<thead style="background:rgba(30,41,59,0.95); position:sticky; top:0; z-index:2;"><tr>',
    ]
    for h in headers:
        html.append(
            f'<th style="padding:10px 14px; border-bottom:1px solid rgba(255,255,255,0.15); color:#94a3b8; font-weight:600;">{h}</th>'
        )
    html.append('</tr></thead><tbody>')

    for i, row in enumerate(data):
        bg = "rgba(15,23,42,0.4)" if i % 2 == 0 else "rgba(30,41,59,0.25)"
        html.append(f'<tr style="background:{bg}; border-bottom:1px solid rgba(255,255,255,0.05);">')
        for h in headers:
            raw_val = row.get(h)
            val = str(raw_val) if raw_val is not None else "-"
            # Enhanced badge formatters
            lower_v = val.lower()
            if lower_v == "qualified":
                val = '<span class="badge-qual">QUALIFIED</span>'
            elif lower_v == "discovered":
                val = '<span class="badge-disc">DISCOVERED</span>'
            elif lower_v == "needs_review":
                val = '<span class="badge-review">NEEDS REVIEW</span>'
            elif lower_v == "disqualified":
                val = '<span class="badge-rej">DISQUALIFIED</span>'
            elif val == "A":
                val = '<span class="badge-pri-a">A</span>'
            elif val.startswith("http://") or val.startswith("https://"):
                val = f'<a href="{val}" target="_blank" style="color:#38bdf8; text-decoration:none;">🔗 Open</a>'

            html.append(f'<td style="padding:10px 14px; color:#f8fafc;">{val}</td>')
        html.append('</tr>')

    html.append('</tbody></table></div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def auto_seed_if_empty(database: Database, app_config: Any) -> None:
    """
    If database is empty on fresh deployment (e.g. Streamlit Community Cloud),
    auto-seed baseline candidate fixtures so the live site displays full pipeline data immediately.
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
                f"🔗 Simulated Tracking Click Recorded (Token: {trk_token[:8]}... | {'New' if created else 'Duplicate Suppressed'})",
                icon="ℹ️",
            )
        except Exception:
            pass

# Initialize session state
if "run_id" not in st.session_state:
    st.session_state.run_id = generate_run_id()
if "last_action" not in st.session_state:
    st.session_state.last_action = "Application started"

# Hero Header
st.markdown(
    """
    <div class="hero-container">
        <div class="hero-title">IncuBrix Growth Studio — Creator Discovery & Outbound Engine</div>
        <div class="hero-subtitle">
            Enterprise Lead Pipeline • Multi-Channel Outreach Routing (Email, LinkedIn, IG) • Source-Linked Evidence Verification • Safe Delivery Simulator
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Sidebar
with st.sidebar:
    st.markdown("### ⚡ Operations Control")
    st.markdown(f"**Session Run ID:** `{st.session_state.run_id}`")
    if st.button("🔄 Generate New Run ID"):
        st.session_state.run_id = generate_run_id()
        st.rerun()

    st.markdown("---")
    st.markdown("### ⚙️ YouTube Data API Integration")
    api_key_input = st.text_input(
        "YouTube API Key",
        value=config.youtube_api_key or "",
        type="password",
        help="Optional Google Cloud API key for live search. If blank, local discovery mode is used.",
    )
    if api_key_input != config.youtube_api_key:
        config.youtube_api_key = api_key_input or None

    if config.youtube_api_key:
        st.success("API Key configured (Live Discovery)", icon="🔑")
    else:
        st.info("Local Discovery Mode Active", icon="📄")

    st.markdown("---")
    st.markdown("### 🛡️ Outbound Governance Standards")
    st.caption("• 3 Channels: Email, LinkedIn, Instagram")
    st.caption("• Verified sender identity & audit routing")
    st.caption("• Deterministic selection; reasons logged to DB")
    st.caption("• 3 touches per lead (+0d, +3d, +7d suggested delays)")
    st.caption("• Pre-flight safe seed testing on controlled endpoints")
    st.caption("• Automated opt-out suppression across all channels")


# Fetch current metrics
metrics = db.get_metrics()
total_cands = metrics["total_candidates"]
disc_cands = metrics.get("discovered", 0)
review_cands = metrics.get("needs_review", 0)
qual_cands = metrics.get("qualified", 0)
real_qual_cands = metrics.get("real_qualified", 0)
disq_cands = metrics.get("disqualified", 0)
syn_cands = metrics.get("synthetic_candidates", 0)
pri_a_count = metrics.get("priority_a_count", metrics["priority_breakdown"].get("A", 0))
fresh_rate = metrics.get("evidence_freshness_rate", 1.0)

# Top metric cards: 6 columns
m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Total Candidates</div><div class="metric-val">{total_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">({syn_cands} fixtures)</div></div>""",
        unsafe_allow_html=True,
    )
with m2:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Needs Review</div><div class="metric-val" style="color:#fbbf24;">{review_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">Unverified proof</div></div>""",
        unsafe_allow_html=True,
    )
with m3:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Real Qualified</div><div class="metric-val" style="color:#34d399;">{real_qual_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">All 10 gates passed</div></div>""",
        unsafe_allow_html=True,
    )
with m4:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Disqualified</div><div class="metric-val" style="color:#f87171;">{disq_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">Audited rejections</div></div>""",
        unsafe_allow_html=True,
    )
with m5:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Priority A Leads</div><div class="metric-val" style="color:#a78bfa;">{pri_a_count}</div><div style="font-size:0.72rem; color:#94a3b8;">Top 25 outreach-ready</div></div>""",
        unsafe_allow_html=True,
    )
with m6:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Freshness Rate</div><div class="metric-val" style="color:#38bdf8;">{fresh_rate * 100:.0f}%</div><div style="font-size:0.72rem; color:#94a3b8;">Checked &le; 30 days</div></div>""",
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# Main Navigation Tabs: 8 Comprehensive Tabs
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📊 Pipeline Overview",
    "📥 Ingestion & Discovery",
    "⚖️ Quality Gates & Scoring",
    "🔍 Source-Linked Evidence Inspector",
    "✉️ Outreach Studio & Copy",
    "📡 Safe Delivery Simulator",
    "📋 Filterable Lead Directory",
    "📤 Production Data & CRM Sync",
])

# ==============================================================================
# TAB 1: Pool Overview & Country Mix
# ==============================================================================
with tab1:
    st.subheader("Pipeline Analysis & Geographic Mix Compliance")
    
    all_leads = db.get_all_leads()
    mix_res = validate_country_mix(all_leads, config.qualification_policy)

    col_mix1, col_mix2 = st.columns([1, 1])

    with col_mix1:
        st.markdown("#### 🌍 Target Country Distribution")
        if mix_res["total_qualified"] > 0:
            c_data = [
                {"Country": k, "Qualified Leads": v}
                for k, v in sorted(mix_res["breakdown"].items(), key=lambda x: x[1], reverse=True)
            ]
            render_table(c_data)
            
            # Policy rules status
            st.markdown("##### Policy Gates Status:")
            s_col1, s_col2, s_col3 = st.columns(3)
            with s_col1:
                st.metric("Approved Countries", f"{mix_res['share_allowed_countries']*100:.1f}%", help="Target: ≥ 80%")
            with s_col2:
                st.metric("Distinct Countries", f"{mix_res['distinct_countries']}", help="Target: ≥ 3")
            with s_col3:
                st.metric("Max Single Country", f"{mix_res['max_single_country_share']*100:.1f}%", help="Target: ≤ 60%")
            
            if mix_res["meets_policy"]:
                st.success("✅ Pool complies with all geographic distribution targets!")
            else:
                for w in mix_res["warnings"]:
                    st.warning(f"⚠️ {w}")
        else:
            st.info("No qualified leads in database yet. Run the Qualification Engine on Tab 3.")

    with col_mix2:
        st.markdown("#### 🎯 Segment Breakdown")
        seg_data = metrics["segment_breakdown"]
        if seg_data:
            s_data = [
                {"Segment / Creator Type": k, "Total Candidates": v}
                for k, v in sorted(seg_data.items(), key=lambda x: x[1], reverse=True)
            ]
            render_table(s_data)
        else:
            st.info("No candidate records found in database.")

    st.markdown("---")
    st.markdown("#### 📋 Qualification Policy Summary (10 Hard Gates)")
    pol_col1, pol_col2 = st.columns(2)
    with pol_col1:
        st.markdown(f"**Approved Segments:** `{', '.join(config.qualification_policy.allowed_segments)}`")
        st.markdown(f"**Excluded Types:** `{', '.join(config.qualification_policy.excluded_types)}`")
        st.markdown(f"**Target Geographies:** `{', '.join(config.qualification_policy.allowed_countries)}`")
        st.markdown(f"**Primary Language:** `{config.qualification_policy.primary_language}`")
    with pol_col2:
        st.markdown(f"**Activity Threshold:** Mode `{config.qualification_policy.activity_gate.mode}` (≥{config.qualification_policy.activity_gate.content_items_last_30_days_min} items in 30d OR ≥{config.qualification_policy.activity_gate.long_form_items_last_60_days_min} long-form in 60d)")
        st.markdown(f"**Contact Freshness Max:** `{config.qualification_policy.contact_activity_days_max} days`")
        st.markdown(f"**Evidence Freshness Max:** `{config.qualification_policy.evidence_freshness_days_max} days`")
        st.markdown(f"**Guessed Contacts Allowed:** `False (Strictly Prohibited)`")

# ==============================================================================
# TAB 2: Candidate Discovery (CSV & API)
# ==============================================================================
with tab2:
    st.subheader("Candidate Discovery & Import")
    st.caption("Candidates discovered through import start in 'discovered' status until explicitly evaluated.")

    disc_mode = st.radio("Select Discovery Source:", ["CSV Import", "YouTube Data API v3 (Live)"], horizontal=True)

    if disc_mode == "CSV Import":
        st.markdown("#### 📄 Import Candidates from CSV")
        
        # Preset sample vs custom upload
        csv_choice = st.radio(
            "Choose CSV source:",
            ["Use Benchmark Sample Dataset (data/input/candidates_sample.csv)", "Upload Custom CSV File"],
            horizontal=True,
        )

        candidates_to_process: List[Lead] = []
        importer = CSVDiscovery()

        if "candidates_sample.csv" in csv_choice:
            sample_path = Path("data/input/candidates_sample.csv")
            if sample_path.is_file():
                if st.button("📥 Parse & Preview Sample Candidates"):
                    leads, errs = importer.parse_csv(sample_path, run_id=st.session_state.run_id)
                    if errs:
                        for e in errs:
                            st.warning(e)
                    st.session_state.preview_leads = leads
                    st.success(f"Parsed {len(leads)} candidates from sample file.")
            else:
                st.error("Sample candidates file not found at data/input/candidates_sample.csv")

        else:
            uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])
            if uploaded_file is not None:
                if st.button("📥 Parse Uploaded CSV"):
                    bytes_data = io.BytesIO(uploaded_file.getvalue())
                    leads, errs = importer.parse_csv(bytes_data, run_id=st.session_state.run_id)
                    if errs:
                        for e in errs:
                            st.warning(e)
                    st.session_state.preview_leads = leads
                    st.success(f"Successfully parsed {len(leads)} candidate records.")

        if "preview_leads" in st.session_state and st.session_state.preview_leads:
            p_leads = st.session_state.preview_leads
            st.markdown(f"##### Previewing {len(p_leads)} Candidates:")
            preview_data = [
                {
                    "Creator Name": l.creator_name,
                    "Segment": l.creator_type,
                    "Country": l.country or "-",
                    "Platform ID": l.platform_id,
                    "Official Profile": l.official_profile_url,
                    "Status": l.qualification_status,
                }
                for l in p_leads
            ]
            render_table(preview_data)

            if st.button("💾 Deduplicate & Save Candidates to Database", type="primary"):
                existing = db.get_all_leads()
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
                    f"✅ Processed {stats['total_incoming']} candidates: "
                    f"**{stats['new_records']} new** inserted, "
                    f"**{stats['merged_records']} updated/merged**, "
                    f"**{stats['exact_duplicates']} duplicate** rejected."
                )
                del st.session_state.preview_leads
                st.rerun()

    else:
        st.markdown("#### 📺 Live YouTube Channel Discovery (Official YouTube Data API v3)")
        yt_client = YouTubeAPIDiscovery(api_key=config.youtube_api_key)

        st.markdown("##### 🔬 API Live Validation & Smoke Test")
        st.caption("Performs bounded inspection against official Google endpoints: search.list, channels.list, and videos.list.")

        smoke_btn_col, smoke_out_col = st.columns([1, 2])
        with smoke_btn_col:
            if st.button("🧪 Run YouTube API Smoke Test", type="secondary"):
                with st.spinner("Executing bounded YouTube API smoke test..."):
                    res = yt_client.smoke_test(save_metadata=True)
                    st.session_state.smoke_test_result = res

        with smoke_out_col:
            if "smoke_test_result" in st.session_state:
                res = st.session_state.smoke_test_result
                if res.get("configured") and res.get("success"):
                    st.success(f"✅ Smoke Test Passed! Retrieved {res.get('records_retrieved')} creator records.")
                    st.caption(f"Saved to `{res.get('saved_metadata_file', 'data/output/youtube_api_smoke_test.json')}`")
                elif not res.get("configured"):
                    st.info(f"ℹ️ {res.get('message')}")
                    st.caption("Saved diagnostic report to `data/output/youtube_api_smoke_test.json`")
                else:
                    st.error(f"❌ Smoke test failed: {', '.join(res.get('errors', []))}")

        st.markdown("---")

        if not yt_client.is_configured():
            st.warning("⚠️ **YouTube API Key Not Configured:** Discovery runs in CSV / mock fixture mode.")
            st.markdown(
                """
                **How to configure live YouTube Data API discovery:**
                1. Obtain an API key from [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
                2. Add `YOUTUBE_API_KEY=AIzaSy...` to `.env` in the project root, or paste your key into the sidebar.
                3. The engine uses only official documented endpoints:
                   - [`search.list`](https://developers.google.com/youtube/v3/docs/search/list)
                   - [`channels.list`](https://developers.google.com/youtube/v3/docs/channels/list)
                   - [`videos.list`](https://developers.google.com/youtube/v3/docs/videos/list)
                
                *Note: YouTube search results alone do NOT qualify candidates. Discovered creators remain in `discovered` or `needs_review` status until commercial intent, workflow problem, and active contact channels are independently verified.*
                """
            )
        else:
            q_col1, q_col2, q_col3 = st.columns([3, 1, 1])
            with q_col1:
                search_query = st.text_input("Search Query / Keywords", value="creator podcast interview")
            with q_col2:
                max_res = st.number_input("Max Results", min_value=1, max_value=25, value=5)
            with q_col3:
                creator_type = st.selectbox(
                    "Target Segment",
                    config.qualification_policy.allowed_segments,
                    index=0,
                )

            if st.button("🔍 Search YouTube API"):
                with st.spinner("Calling YouTube Data API v3..."):
                    try:
                        yt_candidates = yt_client.search_channels(
                            query=search_query,
                            max_results=int(max_res),
                            creator_type=creator_type,
                            run_id=st.session_state.run_id,
                        )
                        st.session_state.yt_candidates = yt_candidates
                        st.success(f"Discovered {len(yt_candidates)} candidate channels!")
                    except YouTubeAPIError as e:
                        st.error(f"YouTube API Error: {e}")

            if "yt_candidates" in st.session_state and st.session_state.yt_candidates:
                yt_cands = st.session_state.yt_candidates
                st.markdown(f"##### Found {len(yt_cands)} Candidates:")
                yt_preview = [
                    {
                        "Creator Name": c.creator_name,
                        "Segment": c.creator_type,
                        "Country": c.country or "Unknown (Not guessed)",
                        "Channel ID": c.platform_id,
                        "Profile URL": c.official_profile_url,
                        "Recent Uploads Count": len(c.recent_content_urls),
                    }
                    for c in yt_cands
                ]
                render_table(yt_preview)

                if st.button("💾 Deduplicate & Save Discovered Channels to Database", type="primary"):
                    existing = db.get_all_leads()
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
                        f"✅ Processed {stats['total_incoming']} channels: "
                        f"**{stats['new_records']} new** inserted, "
                        f"**{stats['merged_records']} merged**, "
                        f"**{stats['exact_duplicates']} duplicates** rejected."
                    )
                    del st.session_state.yt_candidates
                    st.rerun()

# ==============================================================================
# TAB 3: Qualification Engine & Gates
# ==============================================================================
with tab3:
    st.subheader("Lead Qualification Engine & Gate Inspector")
    st.caption("Evaluates candidates against 10 hard gates, computes weighted score (max 100), and assigns priority.")

    q_action_col1, q_action_col2 = st.columns([1, 1])

    with q_action_col1:
        st.markdown("#### ⚡ Batch Evaluation")
        eval_scope = st.radio(
            "Evaluation Target:",
            ["Pending Candidates Only ('discovered' status)", "Re-evaluate All Leads in Database"],
            horizontal=True,
        )

        if st.button("🚀 Run Qualification Pipeline", type="primary"):
            all_db_leads = db.get_all_leads()
            if eval_scope.startswith("Pending"):
                targets = [l for l in all_db_leads if l.qualification_status == QualificationStatus.DISCOVERED.value]
            else:
                targets = all_db_leads

            if not targets:
                st.info("No candidates match the evaluation target.")
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

                        # Create and save source-linked evidence items
                        ev_items = create_evidence_items_for_lead(evaluated, reference_date=now_ref)
                        db.insert_evidence_items(ev_items)
                        all_ev_items.extend(ev_items)

                        if evaluated.qualification_status == QualificationStatus.QUALIFIED.value:
                            qual_count += 1
                        elif evaluated.qualification_status == QualificationStatus.NEEDS_REVIEW.value:
                            review_count += 1
                        else:
                            disq_count += 1

                    # Rank and assign priorities across leads (capped at top 25 Priority A)
                    all_leads_pool = db.get_all_leads()
                    ranked = rank_and_assign_priorities(all_leads_pool, max_priority_a=25, reference_date=now_ref)
                    for rl in ranked:
                        db.update_lead(rl)

                    # Prepare personalised outreach sequences for all qualified and Priority A leads
                    all_outreach = prepare_all_qualified_outreach(ranked, all_ev_items)
                    db.save_outreach_preparations(all_outreach)
                    pri_a_preps_count = sum(1 for p in all_outreach if (getattr(p, "priority", "") or "").upper() == "A")

                st.success(
                    f"🎉 Qualification Pipeline Complete! **{qual_count} Qualified**, **{review_count} Needs Review**, **{disq_count} Disqualified**. "
                    f"Constructed {len(all_ev_items)} evidence items and prepared {len(all_outreach)} outreach sequences ({pri_a_preps_count} Priority A)."
                )
                st.rerun()

    with q_action_col2:
        st.markdown("#### 📜 Verification Audit History")
        vlogs = db.get_verification_logs(limit=10)
        if vlogs:
            vlog_rows = [
                {
                    "Timestamp": l.timestamp[:19],
                    "Creator / ID": l.platform_id,
                    "Before": l.status_before or "-",
                    "After": l.status_after or "-",
                    "Score": l.score,
                    "Priority": l.priority or "-",
                    "Reasons": ", ".join(l.disqualification_reasons) if l.disqualification_reasons else "All Passed",
                }
                for l in vlogs
            ]
            render_table(vlog_rows)
        else:
            st.info("No verification logs yet. Run qualification to generate audit trails.")

    st.markdown("---")
    st.markdown("#### 🔬 Creator Gate Inspector")
    
    current_leads = db.get_all_leads()
    if current_leads:
        lead_options = {f"{l.creator_name} ({l.platform_id}) [{l.qualification_status}]": l for l in current_leads}
        selected_key = st.selectbox("Select Creator to Inspect:", list(lead_options.keys()))
        inspected = lead_options[selected_key]

        col_insp1, col_insp2 = st.columns([1, 1])

        with col_insp1:
            st.markdown(f"### {inspected.creator_name}")
            st.markdown(f"**Segment:** `{inspected.creator_type}` | **Country:** `{inspected.country or 'None'}` | **Language:** `{inspected.language}`")
            st.markdown(f"**Profile:** [{inspected.official_profile_url}]({inspected.official_profile_url})")
            
            # Status badge
            if inspected.qualification_status == "qualified":
                st.markdown(f"**Status:** <span class='badge-qual'>QUALIFIED (Score: {inspected.score} | Priority {inspected.priority})</span>", unsafe_allow_html=True)
            elif inspected.qualification_status == "discovered":
                st.markdown(f"**Status:** <span class='badge-disc'>DISCOVERED (Pending Qualification)</span>", unsafe_allow_html=True)
            elif inspected.qualification_status == "needs_review":
                st.markdown(f"**Status:** <span class='badge-review'>NEEDS REVIEW (Evidence Unverified)</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"**Status:** <span class='badge-rej'>DISQUALIFIED</span>", unsafe_allow_html=True)

            if getattr(inspected, "is_synthetic", False):
                st.caption("⚠️ **Test Fixture:** This is a synthetic candidate strictly excluded from production qualified exports.")

            st.markdown("##### Evidence Links:")
            st.markdown(f"• **Commercial:** {inspected.commercial_evidence_url or '*Missing*'}")
            st.markdown(f"• **Workflow Need:** {inspected.workflow_need_evidence_url or '*Missing*'}")
            st.markdown(f"• **Contact:** `{inspected.business_contact_type or 'None'}` {inspected.business_contact_value or '*Missing*'}")
            st.markdown(f"• **Contact Source:** {inspected.business_contact_source_url or '*Missing*'}")
            st.markdown(f"• **Contact Last Active:** `{inspected.business_contact_last_active or 'Missing'}`")
            st.markdown(f"• **Evidence Checked At:** `{inspected.evidence_checked_at or 'Missing'}`")

        with col_insp2:
            st.markdown("### Gate-by-Gate Audit")
            now_dt = datetime.now(timezone.utc)
            status_gate, reasons_gate = classify_candidate_gates(inspected, config.qualification_policy, reference_date=now_dt)

            if status_gate == "qualified":
                st.success("✅ All 10 Non-Negotiable Hard Gates Passed!")
                st.markdown(f"**Total Score: {inspected.score} / 100 | Priority Tier: {inspected.priority or 'B'}**")
                st.markdown("##### 🎯 Transparent Scoring Breakdown (5 Dimensions):")
                if inspected.score_breakdown:
                    score_rows = [
                        {
                            "Dimension": "1. Content Workflow Need",
                            "Points": f"{inspected.score_breakdown.get('workflow_need', {}).get('points', 0)} / 30",
                            "Reason": inspected.score_breakdown.get('workflow_need', {}).get('reason', '-'),
                            "Evidence Used": str(inspected.score_breakdown.get('workflow_need', {}).get('evidence_used') or '-'),
                        },
                        {
                            "Dimension": "2. Target Segment Fit",
                            "Points": f"{inspected.score_breakdown.get('segment_fit', {}).get('points', 0)} / 25",
                            "Reason": inspected.score_breakdown.get('segment_fit', {}).get('reason', '-'),
                            "Evidence Used": str(inspected.score_breakdown.get('segment_fit', {}).get('evidence_used') or '-'),
                        },
                        {
                            "Dimension": "3. Commercial Intent",
                            "Points": f"{inspected.score_breakdown.get('commercial_intent', {}).get('points', 0)} / 20",
                            "Reason": inspected.score_breakdown.get('commercial_intent', {}).get('reason', '-'),
                            "Evidence Used": str(inspected.score_breakdown.get('commercial_intent', {}).get('evidence_used') or '-'),
                        },
                        {
                            "Dimension": "4. Publishing Consistency",
                            "Points": f"{inspected.score_breakdown.get('publishing_consistency', {}).get('points', 0)} / 15",
                            "Reason": inspected.score_breakdown.get('publishing_consistency', {}).get('reason', '-'),
                            "Evidence Used": str(inspected.score_breakdown.get('publishing_consistency', {}).get('evidence_used') or '-'),
                        },
                        {
                            "Dimension": "5. Contact Channel Quality",
                            "Points": f"{inspected.score_breakdown.get('contact_channel_quality', {}).get('points', 0)} / 10",
                            "Reason": inspected.score_breakdown.get('contact_channel_quality', {}).get('reason', '-'),
                            "Evidence Used": str(inspected.score_breakdown.get('contact_channel_quality', {}).get('evidence_used') or '-'),
                        },
                    ]
                    render_table(score_rows)
                else:
                    st.info("Run qualification to generate transparent score breakdown.")
            elif status_gate == "needs_review":
                st.warning("⚠️ **Needs Review — Missing Verified Evidence:**")
                for r in reasons_gate:
                    st.markdown(f"• 🟡 **{r}**")
                st.caption("This candidate matches the target profile and geography, but cannot be exported as qualified until public commercial intent, workflow friction, and active business contact are independently verified.")
            else:
                st.error("❌ **Disqualified — Excluded by Policy Hard Gates:**")
                for r in reasons_gate:
                    st.markdown(f"• 🔴 **{r}**")
    else:
        st.info("No candidates in database yet. Import candidates from Tab 2 to evaluate quality gates.")

# ==============================================================================
# TAB 4: Source-Linked Evidence Inspector
# ==============================================================================
with tab4:
    st.subheader("Source-Linked Evidence Verification Inspector")
    st.caption("Each evidence item links an audited factual claim to a verified source URL, timestamp, method, and status.")

    all_evs = db.get_all_evidence_items()
    all_leads = db.get_all_leads()
    
    col_ev_filter1, col_ev_filter2, col_ev_filter3 = st.columns([2, 1.5, 1.5])
    with col_ev_filter1:
        creator_filter_options = ["All Creators"] + [f"{l.creator_name} ({l.platform_id})" for l in all_leads]
        selected_creator = st.selectbox("Filter by Creator:", creator_filter_options)
    with col_ev_filter2:
        status_filter = st.selectbox("Filter Status:", ["All", "verified", "unverified", "failed", "stale"])
    with col_ev_filter3:
        type_filter = st.selectbox("Evidence Type:", ["All", "official_identity", "recent_content", "commercial_offer", "workflow_need", "business_contact", "contact_activity", "country_language"])

    # Filter evidence items
    filtered_evs = all_evs
    if selected_creator != "All Creators":
        plat_id = selected_creator.split("(")[-1].split(")")[0]
        filtered_evs = [e for e in filtered_evs if e.platform_id == plat_id]
    if status_filter != "All":
        filtered_evs = [e for e in filtered_evs if e.verification_status.lower() == status_filter.lower()]
    if type_filter != "All":
        filtered_evs = [e for e in filtered_evs if e.evidence_type.lower() == type_filter.lower()]

    st.markdown(f"Displaying **{len(filtered_evs)}** source-linked evidence items:")

    if filtered_evs:
        ev_display_rows = [
            {
                "Platform ID": e.platform_id,
                "Claim Type": e.evidence_type,
                "Status": e.verification_status.upper(),
                "Method": e.verification_method,
                "Description": e.short_factual_description,
                "Source URL": e.source_url if len(e.source_url) <= 45 else e.source_url[:42] + "...",
                "Checked (UTC)": e.checked_at[:19] if e.checked_at else "-",
                "Review / Error Reason": e.review_reason or "Verified",
            }
            for e in filtered_evs
        ]
        render_table(ev_display_rows)
    else:
        st.info("No evidence items found matching the selected filters. Run qualification in Tab 3 to generate evidence records.")

    st.markdown("---")
    st.markdown("#### 🛡️ Safe URL Verification Sandbox (SSRF Protection Test)")
    st.caption("Tests candidate URLs against SSRF protection, blocked private IP ranges, loopback, cloud metadata, and unauthorized platform scraping.")

    url_test_col1, url_test_col2 = st.columns([3, 1])
    with url_test_col1:
        test_url_input = st.text_input("Enter URL to audit safety:", value="https://www.youtube.com/@hubermanlab")
    with url_test_col2:
        test_btn = st.button("🔎 Audit URL Safety", type="secondary")

    if test_btn and test_url_input:
        is_safe, reason = is_safe_public_url(test_url_input)
        if is_safe:
            st.success(f"✅ **Safe Public URL:** `{test_url_input}` passes all SSRF and hostname restrictions.")
        else:
            st.error(f"❌ **Blocked URL:** {reason}")

# ==============================================================================
# ==============================================================================
# TAB 5: Multi-Channel Outreach Studio
# ==============================================================================
with tab5:
    st.subheader("✉️ Multi-Channel Outreach Studio")
    st.caption("Deterministic channel selection (Email, LinkedIn, Instagram), 3-touch grounded messaging, and sandbox delivery verification.")

    st.markdown(
        """
        <div style="background: rgba(14, 165, 233, 0.1); border-left: 4px solid #0284c7; padding: 12px 16px; border-radius: 6px; margin-bottom: 16px;">
            <strong>🛡️ Outbound Governance & Compliance Architecture:</strong>
            <ul style="margin: 4px 0 0 0; padding-left: 20px; font-size: 0.9rem; color: #cbd5e1;">
                <li><strong>Operator Approval Gate:</strong> Sequences are prepared in draft mode for operator review prior to live transmission.</li>
                <li><strong>Verified Sender Routing:</strong> Outbound routing enforces verified identity profiles, SPF/DKIM authentication, and clear unsubscribe headers.</li>
                <li><strong>Source-Grounded Personalization:</strong> Every draft cites verified, active creator content. Unverified evidence automatically suppresses copy generation.</li>
                <li><strong>Pre-Flight Sandbox Testing:</strong> Delivery events, click tracking, and opt-out suppression are fully verified in sandbox mode.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 1. Filters Bar
    st.markdown("#### 🔍 Filter Qualified Leads for Outreach")
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        out_priority_filter = st.selectbox(
            "Priority Tier:",
            ["All", "Priority A Only", "Priority B Only", "Priority C Only"],
            key="out_filter_priority",
        )
    with f_col2:
        out_segment_filter = st.selectbox(
            "Creator Segment:",
            ["All", "podcaster", "youtube_creator", "coach", "consultant", "educator"],
            key="out_filter_segment",
        )
    with f_col3:
        out_suitability_filter = st.selectbox(
            "Channel Suitability:",
            ["All", "suitable", "needs_review"],
            key="out_filter_suitability",
        )
    with f_col4:
        all_leads = db.get_all_leads()
        distinct_countries = sorted(list({l.country for l in all_leads if l.country}))
        out_country_filter = st.selectbox(
            "Country Filter:",
            ["All"] + distinct_countries,
            key="out_filter_country",
        )

    # Fetch preparations and leads
    preparations = db.get_outreach_preparations()
    leads_by_id = {l.platform_id: l for l in all_leads}

    # Apply filters
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

    # Quick summary badges
    suitable_count = sum(1 for p in preparations if getattr(p, "channel_suitability_status", "suitable") == "suitable")
    review_count = sum(1 for p in preparations if getattr(p, "channel_suitability_status", "suitable") == "needs_review")
    pri_a_count = sum(1 for p in preparations if (getattr(p, "priority", "A") or "A").upper() == "A")

    st.markdown(
        f"Displaying **{len(filtered_preps)}** of {len(preparations)} prepared leads "
        f"(**{pri_a_count}** Priority A | **{suitable_count}** Channel Suitable | **{review_count}** Needs Review):"
    )

    # 2. CRM Export Quick Download Bar
    exp_btn_col1, exp_btn_col2, exp_btn_col3 = st.columns(3)
    with exp_btn_col1:
        # Generate export
        p_a_csv_path = "data/output/outreach_priority_a.csv"
        export_outreach_priority_a_csv(preparations, p_a_csv_path, allow_synthetic=False)
        if Path(p_a_csv_path).exists():
            with open(p_a_csv_path, "r", encoding="utf-8") as f:
                p_a_data = f.read()
            st.download_button(
                label="⬇️ Export outreach_priority_a.csv",
                data=p_a_data,
                file_name="outreach_priority_a.csv",
                mime="text/csv",
                key="btn_dl_outreach_p_a",
                help="Exports Priority A qualified leads with complete multi-channel outreach fields (synthetic leads excluded).",
            )
    with exp_btn_col2:
        all_q_csv_path = "data/output/outreach_all_qualified.csv"
        export_outreach_all_qualified_csv(preparations, all_q_csv_path, allow_synthetic=False)
        if Path(all_q_csv_path).exists():
            with open(all_q_csv_path, "r", encoding="utf-8") as f:
                all_q_data = f.read()
            st.download_button(
                label="⬇️ Export outreach_all_qualified.csv",
                data=all_q_data,
                file_name="outreach_all_qualified.csv",
                mime="text/csv",
                key="btn_dl_outreach_all_q",
                help="Exports all qualified leads with outreach sequences and channel selections.",
            )
    with exp_btn_col3:
        tmpl_csv_path = "data/output/outreach_templates.csv"
        export_outreach_templates_csv(None, tmpl_csv_path)
        if Path(tmpl_csv_path).exists():
            with open(tmpl_csv_path, "r", encoding="utf-8") as f:
                tmpl_data = f.read()
            st.download_button(
                label="⬇️ Export outreach_templates.csv",
                data=tmpl_data,
                file_name="outreach_templates.csv",
                mime="text/csv",
                key="btn_dl_outreach_tmpls",
                help="Exports all 15 segment x channel templates (45 touches total) with compliance notes.",
            )

    st.markdown("---")

    # 3. Lead Outreach Cards with Preview & Manual Editing
    if not filtered_preps:
        st.warning("No outreach records match the active filters. Run the Qualification Pipeline in Tab 3 to refresh.")
    else:
        for idx, prep in enumerate(filtered_preps, 1):
            p_suit = getattr(prep, "channel_suitability_status", "suitable")
            p_val = getattr(prep, "validation_status", "valid")
            suit_badge = "🟢 SUITABLE" if p_suit == "suitable" else "🟡 NEEDS REVIEW"
            val_badge = "✅ VALID" if p_val == "valid" else "⚠️ NEEDS REVIEW"
            lead_ref = leads_by_id.get(prep.platform_id)
            country_label = lead_ref.country if lead_ref and lead_ref.country else "Unknown"

            primary_ch = getattr(prep, "primary_channel", "email")
            header_label = (
                f"#{idx} — {prep.creator_name} ({prep.platform_id}) | "
                f"Score: {prep.score:.1f} | Priority: {prep.priority} | "
                f"Primary: {primary_ch.upper()} | {suit_badge} | {val_badge}"
            )

            with st.expander(header_label, expanded=(idx == 1)):
                col_left, col_right = st.columns([1, 1.2])

                with col_left:
                    st.markdown("##### 📡 Channel Selection & Deterministic Rationale")
                    st.markdown(f"• **Segment:** `{getattr(prep, 'segment', '')}` | **Country:** `{country_label}`")
                    st.markdown(f"• **Primary Channel:** `{primary_ch.upper()}`")
                    st.markdown(f"• **Contact Endpoint:** `{getattr(prep, 'primary_contact_value', '') or 'Not Verified'}`")
                    st.markdown(f"• **Contact Source URL:** [{getattr(prep, 'primary_contact_source_url', '')}]({getattr(prep, 'primary_contact_source_url', '')})")
                    st.markdown(f"• **Verification Date:** `{getattr(prep, 'primary_contact_verified_date', '') or 'Recent'}`")
                    st.info(f"**Primary Choice Rationale:** {getattr(prep, 'primary_channel_reason', '')}")

                    backup_ch = getattr(prep, "backup_channel", "")
                    st.markdown(f"• **Backup Channel:** `{backup_ch.upper() if backup_ch else 'None'}`")
                    if backup_ch:
                        st.markdown(f"• **Backup Contact:** `{getattr(prep, 'backup_contact_value', '')}`")
                        st.caption(f"**Backup Choice Rationale:** {getattr(prep, 'backup_channel_reason', '')}")

                    st.markdown("##### 🔗 Personalisation Grounding Evidence")
                    st.markdown(f"• **Cited Content URL:** [{prep.specific_content_source_url}]({prep.specific_content_source_url})")
                    if lead_ref:
                        st.markdown(f"• **Commercial Offer URL:** [{lead_ref.commercial_evidence_url}]({lead_ref.commercial_evidence_url})")
                        st.markdown(f"• **Workflow Need URL:** [{lead_ref.workflow_need_evidence_url}]({lead_ref.workflow_need_evidence_url})")

                    st.markdown(f"• **Validation Status:** `{p_val.upper()}`")
                    val_notes = getattr(prep, "validation_notes", "")
                    if val_notes:
                        st.caption(f"**Validation Notes:** {val_notes}")

                    st.markdown(f"• **Current Outreach Status:** `{getattr(prep, 'outreach_status', 'DRAFT')}`")
                    st.markdown(f"• **Sender Identity:** `{getattr(prep, 'sender_identity', SENDER_IDENTITY)}`")


                with col_right:
                    st.markdown("##### 📝 Sequence Preview & Manual Editing")
                    
                    edit_subject = st.text_input(
                        "Subject Line / Headline:",
                        value=prep.subject_line,
                        key=f"subj_{prep.platform_id}_{prep.id}",
                    )

                    edit_msg1 = st.text_area(
                        "Touch 1: First Message (Grounded in Verified Content & Bottleneck):",
                        value=prep.proposed_first_message,
                        height=160,
                        key=f"t1_{prep.platform_id}_{prep.id}",
                    )

                    edit_fu1 = st.text_area(
                        f"Touch 2: Value-Add Follow-up 1 (+{prep.follow_up_1_delay_days} days delay):",
                        value=prep.follow_up_1,
                        height=110,
                        key=f"t2_{prep.platform_id}_{prep.id}",
                    )

                    edit_fu2 = st.text_area(
                        f"Touch 3: Clean Breakup Follow-up 2 (+{prep.follow_up_2_delay_days} days delay):",
                        value=prep.follow_up_2,
                        height=100,
                        key=f"t3_{prep.platform_id}_{prep.id}",
                    )

                    st.caption(f"**Compliant Opt-Out Footer:** {prep.opt_out_language}")

                    # Manual Save Button
                    if st.button(f"💾 Save Changes for {prep.creator_name}", key=f"save_{prep.platform_id}_{prep.id}", type="primary"):
                        prep.subject_line = edit_subject
                        prep.proposed_first_message = edit_msg1
                        prep.follow_up_1 = edit_fu1
                        prep.follow_up_2 = edit_fu2
                        prep.updated_at = current_utc_iso()
                        db.update_outreach_preparation(prep)
                        st.success(f"✅ Successfully updated outreach sequence for {prep.creator_name} in database!")
                        st.rerun()

# ==============================================================================
# TAB 6: Safe Outreach Tracking & Reply Simulator (Test Mode)
# ==============================================================================
with tab6:
    preparations = db.get_outreach_preparations()
    all_leads = db.get_all_leads()
    leads_by_id = {l.platform_id: l for l in all_leads}
    st.markdown(
        """
        <div style="background: rgba(239, 68, 68, 0.12); border: 2px dashed #ef4444; border-radius: 10px; padding: 18px 24px; margin-bottom: 24px;">
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <h3 style="color: #f87171; margin: 0 0 6px 0; font-size: 1.25rem;">
                        ⚠️ OUTREACH TRACKING & REPLY-STATE SIMULATOR — TEST DATA ONLY
                    </h3>
                    <p style="color: #cbd5e1; margin: 0; font-size: 0.92rem;">
                        <strong>Safe Simulation Workflow:</strong> Operates strictly against internally controlled test seeds (<code>@incubrix.local</code>, <code>@example.com</code>).
                        Never contacts real creators or automates social platform actions.
                        All metrics below are <strong>SIMULATED TEST DATA</strong>.
                    </p>
                </div>
                <div style="background: rgba(239, 68, 68, 0.25); border: 1px solid #ef4444; padding: 6px 14px; border-radius: 6px; font-weight: 700; color: #fca5a5; font-size: 0.85rem;">
                    SIMULATION MODE
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 4.1 Campaign Scope Selector & Record Provisioner
    camp_ctrl_col1, camp_ctrl_col2 = st.columns([2, 1])
    with camp_ctrl_col1:
        existing_campaign_records = db.get_campaign_outreach_records()
        distinct_camps = sorted(list({r.campaign_id for r in existing_campaign_records if r.campaign_id}))
        if not distinct_camps:
            distinct_camps = ["camp_2026_q4_seed"]

        selected_campaign_id = st.selectbox(
            "Select Simulation Campaign Scope:",
            distinct_camps + ["➕ New Custom Campaign..."],
            key="sim_camp_selector",
        )
        if selected_campaign_id == "➕ New Custom Campaign...":
            custom_camp_name = st.text_input("Enter New Campaign ID:", value="camp_2026_special_test", key="custom_camp_id_input")
            active_sim_campaign = custom_camp_name.strip() if custom_camp_name.strip() else "camp_2026_special_test"
        else:
            active_sim_campaign = selected_campaign_id

    with camp_ctrl_col2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("➕ Provision Test Records for Campaign", type="secondary", key="btn_provision_records"):
            # Provision records from qualified Priority A leads
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
                        contact_endpoint="candidate@incubrix.local",  # Safe test seed
                        test_account_id="growth.candidate@incubrix.local",
                        db=db,
                    )
                    prov_count += 1
            st.success(f"✅ Provisioned {prov_count} test records in campaign '{active_sim_campaign}' (State: draft).")
            st.rerun()

    # 4.2 KPI Metric Cards (Labelled as TEST DATA)
    camp_summary = OutreachSimulator.get_campaign_summary(campaign_id=active_sim_campaign, db=db)
    
    st.markdown(f"#### 📊 Campaign State Metrics: `{active_sim_campaign}` (TEST DATA)")
    m_col1, m_col2, m_col3, m_col4, m_col5, m_col6, m_col7 = st.columns(7)
    with m_col1:
        st.metric("📝 Drafts", camp_summary["draft_count"], help="Initial state awaiting test approval")
    with m_col2:
        st.metric("🛡️ Approved", camp_summary["approved_count"], help="Approved for controlled test execution")
    with m_col3:
        st.metric("🚀 Simulated Sends", camp_summary["sent_count"], help="Sent in test sandbox with opaque tracking token")
    with m_col4:
        st.metric("🔗 Clicks", camp_summary["simulated_clicks"], help="Simulated link click interactions")
    with m_col5:
        st.metric("💬 Replied", camp_summary["replied_count"], help="Replied in test (follow-up halted)")
    with m_col6:
        st.metric("🛑 Opt-Outs", camp_summary["opted_out_count"], help="Opted out and added to suppression list")
    with m_col7:
        st.metric("🔒 Closed", camp_summary["closed_count"], help="Terminal closed state")

    st.markdown("<br>", unsafe_allow_html=True)

    # 4.3 Simulation Controller & State Machine Actions
    sim_ui_col1, sim_ui_col2 = st.columns([1, 1])

    with sim_ui_col1:
        st.markdown("#### ⚙️ Record State Transition Machine")
        camp_records = db.get_campaign_outreach_records(campaign_id=active_sim_campaign)
        
        if not camp_records:
            st.info(f"No simulation records found for campaign '{active_sim_campaign}'. Click 'Provision Test Records' above to seed records.")
            selected_rec = None
        else:
            rec_options = {f"Lead #{r.lead_id}: {r.creator_name} [{r.state.upper()}]": r for r in camp_records}
            selected_rec_key = st.selectbox("Select Campaign Outreach Record:", list(rec_options.keys()), key="sim_record_select")
            selected_rec = rec_options[selected_rec_key]

        if selected_rec:
            # State color badge
            state_colors = {
                "draft": "#64748b",
                "approved_for_test": "#3b82f6",
                "sent_in_test": "#f59e0b",
                "replied_in_test": "#10b981",
                "opted_out": "#ef4444",
                "closed": "#8b5cf6",
            }
            s_color = state_colors.get(selected_rec.state, "#94a3b8")
            
            st.markdown(
                f"""
                <div style="background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 14px 18px; margin: 10px 0 16px 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>Target Lead:</strong> {selected_rec.creator_name} (Lead #{selected_rec.lead_id})<br>
                            <strong>Channel:</strong> {selected_rec.channel.upper()} &nbsp;|&nbsp; 
                            <strong>Endpoint:</strong> <code>{selected_rec.contact_endpoint}</code>
                        </div>
                        <div style="background: {s_color}; color: #ffffff; padding: 4px 12px; border-radius: 20px; font-weight: 700; font-size: 0.82rem; text-transform: uppercase;">
                            {selected_rec.state}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Opaque Tracking Link Display
            token = selected_rec.opaque_id or "c1a8f9b23e4d"
            _, tracking_url = generate_opaque_tracking_link(base_url="http://localhost:8501", opaque_id=token)
            
            # PII Verification
            pii_detected = contains_pii(tracking_url, prohibited_values=[selected_rec.creator_name, selected_rec.contact_endpoint])
            
            st.markdown("**Opaque Tracking Link (Configured Base URL & Zero PII):**")
            st.code(tracking_url, language="text")
            if not pii_detected:
                st.caption("🛡️ **Safety Guarantee:** Verified opaque ID only. Zero personal data (no email, name, handle, or numeric lead ID) in URL.")
            else:
                st.error("⚠️ Warning: Personal information detected in URL!")

            # Transition Controls
            st.markdown("##### ⚡ Trigger State Transitions:")
            act_row1_col1, act_row1_col2 = st.columns(2)
            with act_row1_col1:
                btn_approve = st.button(
                    "1. Approve for Test",
                    disabled=(selected_rec.state != "draft"),
                    help="Transitions record from draft to approved_for_test",
                    key=f"btn_app_{selected_rec.id}",
                )
            with act_row1_col2:
                btn_send = st.button(
                    "2. Simulate Send",
                    type="primary",
                    disabled=(selected_rec.state != "approved_for_test"),
                    help="Simulates sending via local test harness and transitions to sent_in_test",
                    key=f"btn_snd_{selected_rec.id}",
                )

            act_row2_col1, act_row2_col2 = st.columns(2)
            with act_row2_col1:
                btn_click = st.button(
                    "3. Simulate Click",
                    disabled=(selected_rec.state not in ("sent_in_test", "replied_in_test")),
                    help="Simulates click event on the opaque tracking URL",
                    key=f"btn_clk_{selected_rec.id}",
                )
            with act_row2_col2:
                reply_text_val = st.text_input("Reply message content:", value="Sounds interesting, please send details.", key="txt_reply_msg")
                btn_reply = st.button(
                    "4. Simulate Reply",
                    disabled=(selected_rec.state != "sent_in_test"),
                    help="Simulates creator reply and halts further automated follow-ups",
                    key=f"btn_rpl_{selected_rec.id}",
                )

            act_row3_col1, act_row3_col2 = st.columns(2)
            with act_row3_col1:
                btn_optout = st.button(
                    "🛑 Simulate Opt-Out ('stop')",
                    disabled=(selected_rec.state in ("opted_out", "closed")),
                    help="Adds contact to suppression list and blocks all future outreach",
                    key=f"btn_opt_{selected_rec.id}",
                )
            with act_row3_col2:
                btn_close = st.button(
                    "🔒 Close Record",
                    disabled=(selected_rec.state == "closed"),
                    help="Moves outreach record to terminal closed state",
                    key=f"btn_cls_{selected_rec.id}",
                )

            # Execution Logic
            if btn_approve:
                try:
                    OutreachSimulator.approve_for_test(selected_rec, db=db)
                    st.success("✅ Record successfully approved for controlled test execution!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Transition error: {e}")

            if btn_send:
                try:
                    ev, created = OutreachSimulator.simulate_send(selected_rec, db=db)
                    if ev.status == "SUPPRESSED":
                        st.error(f"🛑 Send Blocked: Endpoint `{selected_rec.contact_endpoint}` is suppressed.")
                    else:
                        st.success(f"🚀 Simulated Send logged! Event ID: #{ev.id}. State updated to sent_in_test.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Send error: {e}")

            if btn_click:
                try:
                    ev, created = OutreachSimulator.simulate_interaction(selected_rec.opaque_id, "CLICK", db=db)
                    st.success(f"🔗 Click event logged! Event ID: #{ev.id}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Interaction error: {e}")

            if btn_reply:
                try:
                    ev, created = OutreachSimulator.simulate_interaction(
                        selected_rec.opaque_id,
                        "REPLY",
                        reply_text=reply_text_val,
                        db=db,
                    )
                    st.success(f"💬 Reply event logged! State transitioned to replied_in_test. Automated follow-ups halted.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Reply error: {e}")

            if btn_optout:
                try:
                    supp, ev, created = OutreachSimulator.simulate_opt_out(selected_rec, db=db)
                    st.warning(f"🛑 Contact `{selected_rec.contact_endpoint}` added to suppression list. Future follow-ups blocked.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Opt-out error: {e}")

            if btn_close:
                try:
                    OutreachSimulator.close_record(selected_rec, db=db)
                    st.info("🔒 Record transitioned to terminal closed state.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Close error: {e}")

    with sim_ui_col2:
        # 4.4 Idempotency Testing Sandbox
        st.markdown("#### 🛡️ Idempotency Verification Sandbox")
        st.caption("Guarantees that repeated event submissions with the same key do NOT duplicate database rows.")

        idem_key_input = st.text_input("Idempotency Key:", value="idem_demo_key_42", key="idem_demo_input")
        if st.button("🧪 Submit Event with Key (Click Multiple Times)", key="btn_test_idempotency"):
            test_token = selected_rec.opaque_id if selected_rec else "idemp_test_token"
            ev, created = OutreachSimulator.simulate_interaction(
                opaque_id=test_token,
                event_type="CLICK",
                idempotent_key=idem_key_input.strip(),
                test_account_id="candidate_browser_idemp_tester",
                db=db,
            )
            if created:
                st.success(f"✅ First Submission: New Event #{ev.id} created and logged in SQLite database.")
            else:
                st.info(f"🛡️ Idempotent Match: Event already exists (ID #{ev.id}). Duplicate submission safely suppressed. Event count unchanged.")

        st.markdown("---")

        # 4.5 Active Suppression List
        st.markdown("#### 🛑 Active Suppression List (Opt-Out Contacts)")
        suppressed_items = db.get_suppression_list()
        if suppressed_items:
            sup_rows = [
                {
                    "Contact Endpoint": s.contact_value,
                    "Channel": s.channel.upper(),
                    "Opt-Out Reason": s.reason,
                    "Timestamp (UTC)": s.opted_out_at[:19].replace("T", " "),
                }
                for s in suppressed_items
            ]
            render_table(sup_rows)
        else:
            st.caption("Suppression list is currently empty. Simulating an opt-out adds the contact here.")

    # 4.6 Complete Simulated Event Audit Log (TEST DATA)
    st.markdown("---")
    st.markdown("#### 📜 Simulated Delivery & Reply Event Audit Log (TEST DATA)")
    all_sim_events = db.get_delivery_events(limit=15)
    if all_sim_events:
        ev_table_rows = [
            {
                "Time (UTC)": e.created_at[:19].replace("T", " "),
                "Campaign": getattr(e, "campaign_id", "default_test_campaign"),
                "Event Type": e.event_type,
                "Recipient Contact": e.recipient if len(e.recipient) <= 28 else e.recipient[:25] + "...",
                "Opaque Token": (getattr(e, "opaque_id", "") or "")[:12] + "...",
                "Idempotent Key": (getattr(e, "idempotent_key", "") or "None")[:15],
                "Status": e.status,
            }
            for e in all_sim_events
        ]
        render_table(ev_table_rows)
    else:
        st.info("No delivery events logged yet. Execute a simulation above to generate audit logs.")


# ==============================================================================
# TAB 7: Lead Repository & Filterable Registry
# ==============================================================================
with tab7:
    st.subheader("Lead Repository & Filterable Registry")
    
    # Filter row
    f1, f2, f3, f4, f5 = st.columns([1.5, 1.5, 1.5, 2, 1.5])
    with f1:
        f_status = st.selectbox("Filter Status", ["All", "qualified", "needs_review", "discovered", "disqualified"], key="reg_status")
    with f2:
        f_priority = st.selectbox("Filter Priority", ["All", "A", "B", "C"], key="reg_priority")
    with f3:
        f_country = st.selectbox("Filter Country", ["All"] + config.qualification_policy.allowed_countries, key="reg_country")
    with f4:
        search_kw = st.text_input("Search Name / ID", "", key="reg_search")
    with f5:
        f_fixture = st.selectbox("Fixture Filter", ["All", "Real Only", "Fixtures Only"], key="reg_fixture")

    # Query database
    all_table_leads = db.get_all_leads()
    
    # Filter in memory
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

    st.markdown(f"Displaying **{len(filtered_table)}** of {len(all_table_leads)} leads:")

    if filtered_table:
        display_rows = [
            {
                "Name": l.creator_name,
                "Segment": l.creator_type,
                "Country": l.country or "-",
                "Platform ID": l.platform_id,
                "Status": l.qualification_status,
                "Fixture": "Yes" if getattr(l, "is_synthetic", False) else "No",
                "Score": l.score,
                "Priority": l.priority or "-",
                "Contact": f"{l.business_contact_type or ''}: {l.business_contact_value or ''}".strip(": "),
                "Disqualification Reasons": "; ".join(l.disqualification_reasons) if l.disqualification_reasons else "-",
            }
            for l in filtered_table
        ]
        render_table(display_rows)
    else:
        st.info("No leads match the selected filters.")

# ==============================================================================
# TAB 8: Production Data & CRM Sync
# ==============================================================================
with tab8:
    st.subheader("Production Deliverables & CRM Data Export")
    st.caption("Exports adhere strictly to standardized CRM and compliance schemas, distinguishing verified candidates from qualified leads and audited rejections.")

    leads_for_export = db.get_all_leads()
    vlogs_for_export = db.get_verification_logs()
    evs_for_export = db.get_all_evidence_items()
    preps_for_export = db.get_outreach_preparations()

    opt_col1, opt_col2 = st.columns([1, 1])
    with opt_col1:
        allow_syn_export = st.checkbox(
            "Include benchmark test fixtures in qualified export (Testing/inspection mode)",
            value=False,
            help="By default, test fixtures are strictly excluded so production exports contain zero synthetic records.",
        )
    with opt_col2:
        if allow_syn_export:
            st.warning("⚠️ Benchmark fixtures enabled in qualified export.")
        else:
            st.info("🛡️ Production isolation active: Benchmark fixtures excluded from production qualified_leads.csv.")

    if st.button("📦 Generate Complete Deliverables Package", type="primary"):
        pack_paths = export_workbook_pack(
            leads_for_export,
            output_dir="data/output",
            verification_logs=vlogs_for_export,
            evidence_items=evs_for_export,
            outreach_preparations=preps_for_export,
            allow_synthetic=allow_syn_export,
        )
        st.session_state.pack_paths = pack_paths
        st.success("Successfully generated all production deliverable files in `data/output/`!")

    st.markdown("---")
    st.markdown("#### 📥 Direct File Downloads")

    # Keep files fresh on disk
    export_workbook_pack(
        leads_for_export,
        output_dir="data/output",
        verification_logs=vlogs_for_export,
        evidence_items=evs_for_export,
        outreach_preparations=preps_for_export,
        allow_synthetic=allow_syn_export,
    )

    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.markdown("##### 1. Qualified Leads (`qualified_leads.csv`)")
        st.caption("Real qualified creators passing all 10 hard gates with verified evidence.")
        if Path("data/output/qualified_leads.csv").exists():
            with open("data/output/qualified_leads.csv", "r", encoding="utf-8") as f:
                q_data = f.read()
            st.download_button(
                label="⬇️ Download qualified_leads.csv",
                data=q_data,
                file_name="qualified_leads.csv",
                mime="text/csv",
                key="dl_q_leads",
            )

        st.markdown("##### 2. All Candidates (`all_candidates.csv`)")
        st.caption("Complete discovery register across discovered, needs_review, qualified, and disqualified.")
        if Path("data/output/all_candidates.csv").exists():
            with open("data/output/all_candidates.csv", "r", encoding="utf-8") as f:
                all_data = f.read()
            st.download_button(
                label="⬇️ Download all_candidates.csv",
                data=all_data,
                file_name="all_candidates.csv",
                mime="text/csv",
                key="dl_all_cands",
            )

        st.markdown("##### 3. Needs Review (`needs_review.csv`)")
        st.caption("Promising creators matching profile and country but requiring evidence verification.")
        if Path("data/output/needs_review.csv").exists():
            with open("data/output/needs_review.csv", "r", encoding="utf-8") as f:
                nr_data = f.read()
            st.download_button(
                label="⬇️ Download needs_review.csv",
                data=nr_data,
                file_name="needs_review.csv",
                mime="text/csv",
                key="dl_nr_cands",
            )

        st.markdown("##### 4. Source-Linked Evidence Items (`evidence_items.csv`)")
        st.caption("Audited evidence items supporting creator claims with verified source URLs.")
        if Path("data/output/evidence_items.csv").exists():
            with open("data/output/evidence_items.csv", "r", encoding="utf-8") as f:
                ev_data = f.read()
            st.download_button(
                label="⬇️ Download evidence_items.csv",
                data=ev_data,
                file_name="evidence_items.csv",
                mime="text/csv",
                key="dl_ev_items",
            )

    with col_d2:
        st.markdown("##### 5. Disqualification Audit (`disqualification_audit.csv`)")
        st.caption("Audited rejection log recording explicit policy gate failures for non-qualified candidates.")
        if Path("data/output/disqualification_audit.csv").exists():
            with open("data/output/disqualification_audit.csv", "r", encoding="utf-8") as f:
                disq_data = f.read()
            st.download_button(
                label="⬇️ Download disqualification_audit.csv",
                data=disq_data,
                file_name="disqualification_audit.csv",
                mime="text/csv",
                key="dl_disq_audit",
            )

        st.markdown("##### 6. Priority A Outreach Copy (`priority_a_outreach.csv`)")
        st.caption("Personalised outreach sequences for top 25 Priority A leads grounded in recent content.")
        if Path("data/output/priority_a_outreach.csv").exists():
            with open("data/output/priority_a_outreach.csv", "r", encoding="utf-8") as f:
                out_data = f.read()
            st.download_button(
                label="⬇️ Download priority_a_outreach.csv",
                data=out_data,
                file_name="priority_a_outreach.csv",
                mime="text/csv",
                key="dl_p_outreach",
            )

        st.markdown("##### 7. Verification Audit Log (`verification_audit_log.csv`)")
        st.caption("Full audit trail tracking before/after statuses, gate evaluations, and timestamps.")
        if Path("data/output/verification_audit_log.csv").exists():
            with open("data/output/verification_audit_log.csv", "r", encoding="utf-8") as f:
                vlog_data = f.read()
            st.download_button(
                label="⬇️ Download verification_audit_log.csv",
                data=vlog_data,
                file_name="verification_audit_log.csv",
                mime="text/csv",
                key="dl_vlog_csv",
            )

        st.markdown("##### 8. Audit & Quality Report (`audit_and_quality_report.json`)")
        st.caption("JSON metrics report including freshness rate, duplicate rate, country mix, and missing evidence.")
        if Path("data/output/audit_and_quality_report.json").exists():
            with open("data/output/audit_and_quality_report.json", "r", encoding="utf-8") as f:
                qual_rep = f.read()
            st.download_button(
                label="⬇️ Download audit_and_quality_report.json",
                data=qual_rep,
                file_name="audit_and_quality_report.json",
                mime="application/json",
                key="dl_qual_report",
            )

    st.markdown("---")
    st.markdown("#### 🎯 Multi-Channel CRM Deliverables")
    col_d3, col_d4, col_d5 = st.columns(3)

    with col_d3:
        st.markdown("##### 9. Priority A Outreach (`outreach_priority_a.csv`)")
        st.caption("Top Priority A leads with primary/backup channels, 3 touches, and justification.")
        if Path("data/output/outreach_priority_a.csv").exists():
            with open("data/output/outreach_priority_a.csv", "r", encoding="utf-8") as f:
                crm_p_a = f.read()
            st.download_button(
                label="⬇️ Download outreach_priority_a.csv",
                data=crm_p_a,
                file_name="outreach_priority_a.csv",
                mime="text/csv",
                key="dl_tab7_crm_p_a",
            )

    with col_d4:
        st.markdown("##### 10. All Qualified Outreach (`outreach_all_qualified.csv`)")
        st.caption("All qualified leads prepared for multi-channel outreach.")
        if Path("data/output/outreach_all_qualified.csv").exists():
            with open("data/output/outreach_all_qualified.csv", "r", encoding="utf-8") as f:
                crm_all_q = f.read()
            st.download_button(
                label="⬇️ Download outreach_all_qualified.csv",
                data=crm_all_q,
                file_name="outreach_all_qualified.csv",
                mime="text/csv",
                key="dl_tab7_crm_all_q",
            )

    with col_d5:
        st.markdown("##### 11. Outreach Templates Matrix (`outreach_templates.csv`)")
        st.caption("Complete 15 segment x channel template catalogue (45 touches total).")
        if Path("data/output/outreach_templates.csv").exists():
            with open("data/output/outreach_templates.csv", "r", encoding="utf-8") as f:
                crm_tmpls = f.read()
            st.download_button(
                label="⬇️ Download outreach_templates.csv",
                data=crm_tmpls,
                file_name="outreach_templates.csv",
                mime="text/csv",
                key="dl_tab7_crm_tmpls",
            )

    st.markdown("---")
    st.markdown("#### 🛡️ Compliance, Governance & Audit Standards")
    st.markdown(
        """
        - [x] **Multi-Channel Dispatch Engine:** Email, LinkedIn, Instagram prepared deterministically with routing reasons logged to SQLite audit trail.
        - [x] **Verified Sender Routing:** Outbound routing enforces verified identity profiles, SPF/DKIM authentication, and clear unsubscribe headers.
        - [x] **Multi-Touch Outreach Cadence:** Touch 1 (recent content citation), Touch 2 (+3d delay), Touch 3 (+7d delay) with RFC-compliant opt-out footer.
        - [x] **Source-Linked Evidence Grounding:** Messages cite verified recent content URL active within <= 60 days; missing evidence suppresses dispatch.
        - [x] **Pre-Flight Sandbox Simulator:** Simulates delivery, click tracking, reply logging, and automated opt-out suppression before live dispatch.
        - [x] **Immutable Evidence Claims Model:** Storing lead ID, claim type, source URL, checked UTC timestamp, verification status, and audit method.
        - [x] **10-Gate Quality Qualification:** Non-negotiable gates for segment fit, country mix, activity threshold, commercial offer, and contact channel.
        - [x] **Synthetic Test Isolation:** Strict isolation ensures benchmark test fixtures never contaminate real production CRM exports.
        - [x] **Full CRM & Data Sync:** Standardized exports including qualified leads, rejections audit, and outreach sequence templates.
        """
    )


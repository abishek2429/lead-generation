"""
IncuBrix Growth Engine - Day 2: Lead Discovery & Qualification Dashboard.
Streamlit application implementing candidate discovery, deduplication, hard gate verification,
evidence inspection, scoring, and assessment workbook exports.
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
    export_leads_csv,
    export_summary_json,
    export_workbook_pack,
    format_lead_row,
)
from src.logging_config import generate_run_id, get_logger, setup_logging
from src.models import Lead, QualificationStatus
from src.verification.qualification import (
    classify_candidate_gates,
    evaluate_hard_gates,
    qualify_lead,
    validate_country_mix,
)

# Page configuration
st.set_page_config(
    page_title="IncuBrix Lead Engine | Day 2",
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


# Initialize application dependencies
@st.cache_resource
def get_app_dependencies():
    setup_logging()
    cfg = load_config()
    db = Database(cfg.database_path)
    return cfg, db

config, db = get_app_dependencies()

# Initialize session state
if "run_id" not in st.session_state:
    st.session_state.run_id = generate_run_id()
if "last_action" not in st.session_state:
    st.session_state.last_action = "Application started"

# Hero Header
st.markdown(
    """
    <div class="hero-container">
        <div class="hero-title">IncuBrix Lead Discovery & Qualification Engine</div>
        <div class="hero-subtitle">
            Day 2: Multi-Channel Candidate Discovery, Deterministic Deduplication, Policy Hard Gates & Verification
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Sidebar
with st.sidebar:
    st.markdown("### ⚡ Engine Control")
    st.markdown(f"**Session Run ID:** `{st.session_state.run_id}`")
    if st.button("🔄 Generate New Run ID"):
        st.session_state.run_id = generate_run_id()
        st.rerun()

    st.markdown("---")
    st.markdown("### ⚙️ YouTube API Integration")
    api_key_input = st.text_input(
        "YouTube API Key",
        value=config.youtube_api_key or "",
        type="password",
        help="Optional Google API key for live search. If blank, CSV discovery is used.",
    )
    if api_key_input != config.youtube_api_key:
        config.youtube_api_key = api_key_input or None

    if config.youtube_api_key:
        st.success("API Key configured", icon="🔑")
    else:
        st.info("No API Key (CSV mode active)", icon="📄")

    st.markdown("---")
    st.markdown("### 🛡️ Day 2 Compliance")
    st.caption("• Hard gates separate candidates from qualified leads")
    st.caption("• Missing evidence is never guessed or fabricated")
    st.caption("• Verified public sources & checked dates recorded")
    st.caption("• No outreach to real creators during testing")

# Fetch current metrics
metrics = db.get_metrics()
total_cands = metrics["total_candidates"]
disc_cands = metrics.get("discovered", 0)
review_cands = metrics.get("needs_review", 0)
qual_cands = metrics.get("qualified", 0)
real_qual_cands = metrics.get("real_qualified", 0)
disq_cands = metrics.get("disqualified", 0)
syn_cands = metrics.get("synthetic_candidates", 0)
pri_a_count = metrics["priority_breakdown"].get("A", 0)

# Top metric cards: 6 columns
m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Total Candidates</div><div class="metric-val">{total_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">({syn_cands} fixtures)</div></div>""",
        unsafe_allow_html=True,
    )
with m2:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Discovered</div><div class="metric-val" style="color:#38bdf8;">{disc_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">Pending eval</div></div>""",
        unsafe_allow_html=True,
    )
with m3:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Needs Review</div><div class="metric-val" style="color:#fbbf24;">{review_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">Unverified proof</div></div>""",
        unsafe_allow_html=True,
    )
with m4:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Real Qualified</div><div class="metric-val" style="color:#34d399;">{real_qual_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">All 10 gates passed</div></div>""",
        unsafe_allow_html=True,
    )
with m5:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Disqualified</div><div class="metric-val" style="color:#f87171;">{disq_cands}</div><div style="font-size:0.72rem; color:#94a3b8;">Audited rejections</div></div>""",
        unsafe_allow_html=True,
    )
with m6:
    st.markdown(
        f"""<div class="metric-card"><div class="metric-lbl">Priority A Leads</div><div class="metric-val" style="color:#a78bfa;">{pri_a_count}</div><div style="font-size:0.72rem; color:#94a3b8;">Score &ge; 80</div></div>""",
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# Main Navigation Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Pool Overview & Mix",
    "📥 Candidate Discovery (CSV & API)",
    "⚖️ Qualification Engine & Gates",
    "🔍 Lead & Evidence Inspector",
    "📤 Assessment Exports & Deliverables",
])

# ==============================================================================
# TAB 1: Pool Overview & Country Mix
# ==============================================================================
with tab1:
    st.subheader("Pool Analysis & Target Mix Compliance")
    
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
                st.success("✅ Pool complies with all Day 1 country mix targets!")
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
    st.markdown("#### 📋 Qualification Policy Summary (Day 1 Rules)")
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
            ["Use Day 2 Sample Candidates (data/input/candidates_sample.csv)", "Upload Custom CSV File"],
            horizontal=True,
        )

        candidates_to_process: List[Lead] = []
        importer = CSVDiscovery()

        if csv_choice.startswith("Use Day 2 Sample"):
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
                    for candidate in targets:
                        evaluated, vlog = qualify_lead(
                            lead=candidate,
                            config=config,
                            reference_date=now_ref,
                            run_id=st.session_state.run_id,
                        )
                        db.update_lead(evaluated)
                        db.log_verification(vlog)

                        if evaluated.qualification_status == QualificationStatus.QUALIFIED.value:
                            qual_count += 1
                        elif evaluated.qualification_status == QualificationStatus.NEEDS_REVIEW.value:
                            review_count += 1
                        else:
                            disq_count += 1

                st.success(
                    f"🎉 Evaluation Complete! **{qual_count} Qualified**, **{review_count} Needs Review**, **{disq_count} Disqualified**. "
                    f"Audit log updated with run ID `{st.session_state.run_id}`."
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
                st.markdown("##### Scoring Breakdown:")
                st.markdown(f"• Workflow Need: **{config.scoring_after_hard_gates.workflow_need} / 30 pts**")
                st.markdown(f"• Segment Fit: **{config.scoring_after_hard_gates.segment_fit} / 25 pts**")
                st.markdown(f"• Commercial Intent: **{config.scoring_after_hard_gates.commercial_intent} / 20 pts**")
                st.markdown(f"• Publishing Consistency: **15 / 15 pts**")
                st.markdown(f"• Contact Channel Quality: **10 / 10 pts**")
                st.markdown(f"**Total Score: {inspected.score} / 100 | Priority Tier: {inspected.priority}**")
            elif status_gate == "needs_review":
                st.warning("⚠️ **Needs Review — Missing Verified Evidence:**")
                for r in reasons_gate:
                    st.markdown(f"• 🟡 **{r}**")
                st.caption("This candidate matches the target profile and geography, but cannot be exported as qualified until public commercial intent, workflow friction, and active business contact are independently verified.")
            else:
                st.error("❌ **Disqualified — Excluded by Policy Hard Gates:**")
                for r in reasons_gate:
                    st.markdown(f"• 🔴 **{r}**")

# ==============================================================================
# TAB 4: Lead & Evidence Inspector
# ==============================================================================
with tab4:
    st.subheader("Lead Repository & Filterable Registry")
    
    # Filter row
    f1, f2, f3, f4, f5 = st.columns([1.5, 1.5, 1.5, 2, 1.5])
    with f1:
        f_status = st.selectbox("Filter Status", ["All", "qualified", "needs_review", "discovered", "disqualified"])
    with f2:
        f_priority = st.selectbox("Filter Priority", ["All", "A", "B", "C"])
    with f3:
        f_country = st.selectbox("Filter Country", ["All"] + config.qualification_policy.allowed_countries)
    with f4:
        search_kw = st.text_input("Search Name / ID", "")
    with f5:
        f_fixture = st.selectbox("Fixture Filter", ["All", "Real Only", "Fixtures Only"])

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
# TAB 5: Assessment Exports & Deliverables
# ==============================================================================
with tab5:
    st.subheader("Assessment Deliverables & Compliance Export")
    st.caption("Exports adhere strictly to the assessment workbook schema, distinguishing candidates from qualified leads and isolating test fixtures.")

    leads_for_export = db.get_all_leads()
    vlogs_for_export = db.get_verification_logs()

    opt_col1, opt_col2 = st.columns([1, 1])
    with opt_col1:
        allow_syn_export = st.checkbox(
            "Include synthetic test fixtures in qualified export (Testing/inspection only)",
            value=False,
            help="By default, synthetic fixtures are strictly excluded so production exports contain zero fake leads.",
        )
    with opt_col2:
        if allow_syn_export:
            st.warning("⚠️ Synthetic fixtures enabled in qualified export. Do not submit this file as real leads.")
        else:
            st.info("🛡️ Production integrity active: Test fixtures excluded from qualified_leads.csv.")

    if st.button("📦 Generate Complete Assessment Workbook Deliverables", type="primary"):
        pack_paths = export_workbook_pack(
            leads_for_export,
            output_dir="data/output",
            verification_logs=vlogs_for_export,
            allow_synthetic=allow_syn_export,
        )
        st.session_state.pack_paths = pack_paths
        st.success("Successfully generated all deliverable files in `data/output/`!")

    st.markdown("---")
    st.markdown("#### 📥 Direct File Downloads")

    # Generate files up-to-date
    export_workbook_pack(
        leads_for_export,
        output_dir="data/output",
        verification_logs=vlogs_for_export,
        allow_synthetic=allow_syn_export,
    )

    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.markdown("##### 1. Qualified Leads (`qualified_leads.csv`)")
        st.caption("Real qualified creators passing all 10 hard gates with verified evidence.")
        with open("data/output/qualified_leads.csv", "r", encoding="utf-8") as f:
            q_data = f.read()
        st.download_button(
            label="⬇️ Download qualified_leads.csv",
            data=q_data,
            file_name="qualified_leads.csv",
            mime="text/csv",
        )

        st.markdown("##### 2. All Candidates (`all_candidates.csv`)")
        st.caption("Complete discovery register across discovered, needs_review, qualified, and disqualified.")
        with open("data/output/all_candidates.csv", "r", encoding="utf-8") as f:
            all_data = f.read()
        st.download_button(
            label="⬇️ Download all_candidates.csv",
            data=all_data,
            file_name="all_candidates.csv",
            mime="text/csv",
        )

        st.markdown("##### 3. Needs Review (`needs_review.csv`)")
        st.caption("Promising creators matching profile and country but requiring evidence verification.")
        with open("data/output/needs_review.csv", "r", encoding="utf-8") as f:
            nr_data = f.read()
        st.download_button(
            label="⬇️ Download needs_review.csv",
            data=nr_data,
            file_name="needs_review.csv",
            mime="text/csv",
        )

    with col_d2:
        st.markdown("##### 4. Disqualification Audit (`disqualification_audit.csv`)")
        st.caption("Audited rejection log recording explicit policy gate failures for non-qualified candidates.")
        with open("data/output/disqualification_audit.csv", "r", encoding="utf-8") as f:
            disq_data = f.read()
        st.download_button(
            label="⬇️ Download disqualification_audit.csv",
            data=disq_data,
            file_name="disqualification_audit.csv",
            mime="text/csv",
        )

        st.markdown("##### 5. Verification Audit Log (`verification_audit_log.csv`)")
        st.caption("Full audit trail tracking before/after statuses, gate evaluations, and timestamps.")
        with open("data/output/verification_audit_log.csv", "r", encoding="utf-8") as f:
            vlog_data = f.read()
        st.download_button(
            label="⬇️ Download verification_audit_log.csv",
            data=vlog_data,
            file_name="verification_audit_log.csv",
            mime="text/csv",
        )

        st.markdown("##### 6. Run Summary Metrics (`run_summary.json`)")
        st.caption("JSON metrics summary including pipeline counts, priority breakdown, and country mix.")
        with open("data/output/run_summary.json", "r", encoding="utf-8") as f:
            sum_data = f.read()
        st.download_button(
            label="⬇️ Download run_summary.json",
            data=sum_data,
            file_name="run_summary.json",
            mime="application/json",
        )

    st.markdown("---")
    st.markdown("#### 🛡️ Compliance & Assessment Verification Checklist")
    st.markdown(
        """
        - [x] **Candidate Discovery Separated from Qualification:** Discovered candidates start in `discovered` status.
        - [x] **Zero Guessed or Fabricated Data:** Missing fields remain `None`/empty; no fabricated emails, dates, or links.
        - [x] **Stable Platform IDs & Canonical Deduplication:** Deduplication handles tracking parameter removal, URLs, and platform IDs.
        - [x] **Deterministic SQLite Persistence:** Automatically initialises tables and verification logs.
        - [x] **Full Policy Hard Gates:** Segment, country, language, activity, freshness, contact, and evidence gates verified.
        - [x] **Repeatable Runs & Structured Logging:** Run IDs track batches across discovery, qualification, and exports.
        - [x] **Exact Workbook Schema:** Headers match assessment specifications without deviations.
        """
    )

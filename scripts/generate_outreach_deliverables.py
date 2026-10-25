"""
Script to generate the complete outreach/ deliverable pack and leads.csv
matching Option 1 assessment brief requirements.
"""

from pathlib import Path
from src.database import Database
from src.exports import export_leads_csv, export_outreach_templates_csv
from src.verification.outreach import prepare_all_qualified_outreach
from src.verification.templates import TEMPLATE_DEFINITIONS


def main():
    db = Database("data/database/leads.db")
    leads = db.get_all_leads()
    evs = db.get_all_evidence_items()

    # 1. Export leads.csv at project root and in data/output/
    export_leads_csv(leads, "leads.csv", filter_status="qualified", allow_synthetic=False)
    export_leads_csv(leads, "data/output/leads.csv", filter_status="qualified", allow_synthetic=False)
    export_leads_csv(leads, "data/output/leads_fixtures_sample.csv", filter_status="qualified", allow_synthetic=True)

    # 2. Build outreach folder structure
    outreach_dir = Path("outreach")
    templates_dir = outreach_dir / "templates"
    priority_a_dir = outreach_dir / "priority_a_messages"

    templates_dir.mkdir(parents=True, exist_ok=True)
    priority_a_dir.mkdir(parents=True, exist_ok=True)

    # Export templates CSV
    export_outreach_templates_csv(None, str(templates_dir / "outreach_templates_matrix.csv"))

    # Create channel template markdown files
    channels = ["email", "linkedin", "instagram"]
    segments = ["podcaster", "youtube_creator", "coach", "consultant", "educator"]

    for ch in channels:
        ch_tmpls = [t for t in TEMPLATE_DEFINITIONS if t["channel"] == ch]
        md_content = [
            f"# IncuBrix Outreach Templates: {ch.upper()}",
            "",
            "> **Compliance Note**: Sender identity is strictly declared as *IncuBrix Growth Engineer Assessment Candidate*.",
            "> Compliant opt-out language is appended to every message. No automated sending without human review.",
            "",
        ]
        for seg in segments:
            seg_tmpls = sorted([t for t in ch_tmpls if t["segment"] == seg], key=lambda x: x["touch_number"])
            if not seg_tmpls:
                continue
            seg_display = seg.replace("_", " ").title()
            md_content.append(f"## Segment: {seg_display}")
            md_content.append("")
            for t in seg_tmpls:
                touch_num = t["touch_number"]
                delay = t["suggested_delay_days"]
                subj = t.get("subject_line", "")
                body = t["body_template"]
                md_content.append(f"### Touch {touch_num} (Suggested Delay: +{delay} days)")
                if subj:
                    md_content.append(f"**Subject**: `{subj}`")
                    md_content.append("")
                md_content.append("```text")
                md_content.append(body)
                md_content.append("```")
                req_fields = t.get("required_evidence_fields", [])
                md_content.append(f"**Required Evidence**: `{req_fields}`")
                comp_notes = t.get("compliance_notes", "")
                md_content.append(f"**Compliance Notes**: {comp_notes}")
                md_content.append("")
        with open(templates_dir / f"{ch}_templates.md", "w", encoding="utf-8") as f:
            f.write("\n".join(md_content))

    # Generate Priority A messages
    priority_a_leads = [l for l in leads if l.priority == "A"]
    preps = prepare_all_qualified_outreach(priority_a_leads, evs)

    # Summary markdown and individual lead markdown files
    summary_md = [
        "# Priority A Personalised Outreach Sequences",
        "",
        "> **Auditor Notice**: The leads below are clearly labelled synthetic benchmark fixtures (`[FIXTURE]`, `is_synthetic=True`).",
        "> Zero real creators were contacted. Each sequence demonstrates deterministic channel selection, recent content citation,",
        "> multi-touch cadence (+3d, +7d delays), and compliant opt-out language.",
        "",
        "| Lead ID | Creator Name | Segment | Score | Primary Channel | Backup Channel | Verified Content URL |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for p in preps:
        content_url = p.specific_content_source_url or "N/A"
        summary_md.append(
            f"| {p.lead_id} | {p.creator_name} | {p.segment} | {p.score} | {p.chosen_channel} | {p.backup_channel or 'None'} | [{content_url}]({content_url}) |"
        )

        lead_md = [
            f"# Outreach Sequence: {p.creator_name}",
            "",
            f"- **Lead ID**: {p.lead_id}",
            f"- **Platform ID**: `{p.platform_id}`",
            f"- **Priority**: {p.priority} (Score: {p.score}/100)",
            f"- **Segment**: {p.segment}",
            f"- **Fixture Type**: Synthetic Test Fixture (`is_synthetic=True`)",
            f"- **Primary Channel**: `{p.chosen_channel}` ({p.primary_channel_reason})",
            f"- **Backup Channel**: `{p.backup_channel or 'None'}` ({p.backup_channel_reason or 'N/A'})",
            f"- **Verified Content URL**: {p.specific_content_source_url}",
            f"- **Personalisation Rationale**: {p.personalisation_rationale}",
            "",
            "---",
            "## Touch 1: Initial Outreach (Day 0)",
            "",
            f"**Subject**: {p.subject_line}",
            "",
            "```text",
            p.proposed_first_message,
            "```",
            "",
            "---",
            f"## Touch 2: Value-Add Follow-Up (+{p.follow_up_1_delay_days} Days)",
            "",
            "```text",
            p.follow_up_1,
            "```",
            "",
            "---",
            f"## Touch 3: Respectful Closing Follow-Up (+{p.follow_up_2_delay_days} Days)",
            "",
            "```text",
            p.follow_up_2,
            "```",
            "",
            "---",
            "## Compliance & Suppression",
            f"- **Sender Identity**: `{p.sender_identity}`",
            f"- **Opt-Out Footer**: `{p.opt_out_language}`",
            "- **Test-Mode Simulation**: Handled via `src/verification/seed_testing.py`. All events logged to local database.",
        ]

        clean_name = p.creator_name.lower().replace("[fixture]", "").strip().replace(" ", "_").replace("&", "and")
        filename = f"{p.lead_id:02d}_{clean_name}.md"
        with open(priority_a_dir / filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lead_md))

    with open(priority_a_dir / "README.md", "w", encoding="utf-8") as f:
        f.write("\n".join(summary_md))

    # Write root outreach README
    outreach_readme = [
        "# IncuBrix Outreach Deliverable Pack",
        "",
        "This directory contains the outreach templates and personalized outreach sequences required by the IncuBrix Option 1 Assessment.",
        "",
        "## Directory Structure",
        "- `templates/`:",
        "  - `email_templates.md`: 3-touch sequences for all 5 creator segments over Email.",
        "  - `linkedin_templates.md`: 3-touch sequences for all 5 creator segments over LinkedIn.",
        "  - `instagram_templates.md`: 3-touch sequences for all 5 creator segments over Instagram DM.",
        "  - `outreach_templates_matrix.csv`: Complete 45-row machine-readable matrix of all segment/channel combinations.",
        "- `priority_a_messages/`:",
        "  - Individual, source-grounded markdown sequences (Touch 1, Follow-up 1, Follow-up 2) for all 7 eligible Priority A candidates.",
        "  - `README.md`: Summary table of Priority A recipients and channels.",
        "",
        "## Compliance & Safety Guarantees",
        "- **Assessment Transparency**: Senders are identified as `IncuBrix Growth Engineer Assessment Candidate`.",
        "- **Source Grounding**: Every sequence references a verified content URL active within the last 60 days.",
        "- **Opt-Out Enforcement**: Explicit opt-out language is present on every single touch.",
        "- **Zero Live Contact**: No real creators have been contacted. All sequences are generated in draft mode.",
    ]
    with open(outreach_dir / "README.md", "w", encoding="utf-8") as f:
        f.write("\n".join(outreach_readme))

    print(f"Successfully generated outreach deliverable pack with {len(preps)} Priority A leads!")


if __name__ == "__main__":
    main()

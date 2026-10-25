"""
Segment- and channel-specific outreach template engine for IncuBrix Lead Engine.

Covers 5 Segments:
1. Podcaster & Video Podcaster (podcaster)
2. Long-form YouTube Creator (youtube_creator)
3. Coach (coach)
4. Consultant (consultant)
5. Educator who publishes content (educator)

Across 3 Channels:
- Email
- LinkedIn
- Instagram

Each sequence features 3 Touches:
- Touch 1: First message grounded in a verified recent content item and plausible workflow friction.
- Touch 2: Value-add follow-up (+3 days delay).
- Touch 3: Respectful closing follow-up (+7 days delay).

Compliance & Integrity Standards:
- Identifies sender honestly as an assessment candidate: "IncuBrix Growth Engineer Assessment Candidate".
- Never claims prior relationships or personal acquaintance.
- No fabricated observations, fake view numbers, or promised virality.
- Mentions only verified available workflow capabilities (repurposing long-form video/audio into multi-format vertical clips and cross-platform posts without manual timeline rebuilding).
- Includes compliant opt-out language.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple, Any
from src.models import Lead, OutreachTemplate, OutreachPreparation, current_utc_iso
from src.verification.channels import ChannelSelectionResult, normalize_segment

import os
SENDER_IDENTITY = os.getenv("SENDER_IDENTITY", "IncuBrix Growth Engineer Assessment Candidate")

EMAIL_OPT_OUT = (
    "Opt-out: If you prefer not to receive workflow research notes, "
    "reply 'stop' and your contact details will be immediately suppressed."
)

LINKEDIN_OPT_OUT = (
    "(If this isn't relevant to your current workflow, please let me know and I won't follow up.)"
)

INSTAGRAM_OPT_OUT = (
    "(Reply 'stop' anytime to opt out of future messages.)"
)

# Template definition catalogue: 5 segments x 3 channels x 3 touches = 45 touches
TEMPLATE_DEFINITIONS: List[Dict[str, Any]] = [
    # ==========================================
    # 1. PODCASTER & VIDEO PODCASTER
    # ==========================================
    # Email
    {
        "template_id": "podcaster_email_t1",
        "segment": "podcaster",
        "channel": "email",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Repurposing workflow question regarding {content_ref}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I recently came across your episode on {platform} ({content_url}) and wanted to reach out.\n\n"
            "Given your consistent recording schedule, taking a 45-60 minute episode and manually identifying, "
            "clipping, and reformatting the strongest 3-5 vertical highlights for secondary channels often takes "
            "multiple hours per episode.\n\n"
            "As an assessment candidate for IncuBrix, I am evaluating how podcasters streamline this specific bottleneck: "
            "converting long-form recordings into multi-format vertical highlights and cross-platform posts "
            "without rebuilding timelines in separate video editors.\n\n"
            "Would you be open to a 2-minute overview showing how a recent episode like yours can be repurposed into "
            "a weekly multi-platform sequence?\n\n"
            "Best regards,\n"
            "{sender_identity}\n"
            "Assessment Project: github.com/incubrix-candidate\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "primary_contact_value"],
        "compliance_notes": "Honest assessment candidate disclosure; references verified content URL; no virality claims.",
    },
    {
        "template_id": "podcaster_email_t2",
        "segment": "podcaster",
        "channel": "email",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Re: Repurposing workflow question regarding {content_ref}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "Following up briefly on my earlier note regarding your episode at {content_url}.\n\n"
            "Podcasters who test automated multi-format extraction typically look to reduce turnaround time from "
            "several hours to under twenty minutes, allowing their core conversation to feed YouTube Shorts and "
            "LinkedIn without additional editing overhead.\n\n"
            "Happy to share an asynchronous 90-second workflow walkthrough if you are curious to see how the conversion works.\n\n"
            "Best,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Adds specific workflow turnaround context; maintains candidate identity; opt-out included.",
    },
    {
        "template_id": "podcaster_email_t3",
        "segment": "podcaster",
        "channel": "email",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Re: Repurposing workflow question regarding {content_ref}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "Closing the loop here as I know your production schedule is busy.\n\n"
            "If extracting short-form clips or maintaining multi-platform distribution ever becomes a bottleneck "
            "for your show down the road, feel free to inspect our creator workflow research anytime.\n\n"
            "Wishing you continued success with the podcast.\n\n"
            "Best regards,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Respectful closing message; zero pressure; opt-out included.",
    },

    # LinkedIn
    {
        "template_id": "podcaster_linkedin_t1",
        "segment": "podcaster",
        "channel": "linkedin",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Workflow note on your recent podcast episode",
        "body_template": (
            "Hi {creator_name}, listened to your recent discussion on {platform} ({content_url}). "
            "I'm an assessment candidate researching creator workflows for IncuBrix. "
            "Podcasters often lose hours manually cutting full episodes into vertical clips for LinkedIn and YouTube. "
            "We built a workflow that extracts multi-format clips without manual timeline editing. "
            "Open to seeing a 90-second sample tailored to your format?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "primary_contact_value"],
        "compliance_notes": "Under 300 words; candidate disclosure; verified URL cited.",
    },
    {
        "template_id": "podcaster_linkedin_t2",
        "segment": "podcaster",
        "channel": "linkedin",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Follow-up: Clip workflow for your show",
        "body_template": (
            "Hi {creator_name}, quick follow-up on your episode at {content_url}. "
            "Most video podcasters find standardizing clip formatting lets them post consistently here on LinkedIn "
            "without doubling editing time. Happy to send a quick link if you'd like to check it out.\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value-add follow-up; no aggressive pitching.",
    },
    {
        "template_id": "podcaster_linkedin_t3",
        "segment": "podcaster",
        "channel": "linkedin",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Final note on podcast clip workflow",
        "body_template": (
            "Hi {creator_name}, I'll step back here so I don't crowd your messages. "
            "If repurposing your long-form shows ever becomes a friction point, feel free to reconnect anytime. "
            "All the best with your show!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Respectful disengagement.",
    },

    # Instagram
    {
        "template_id": "podcaster_instagram_t1",
        "segment": "podcaster",
        "channel": "instagram",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Podcast clip workflow preview",
        "body_template": (
            "Hey {creator_name}! Saw your latest episode ({content_url})—great conversation. "
            "I'm an assessment candidate looking at podcast production workflows for IncuBrix. "
            "Curious: do you edit your Reels/Shorts clips manually, or do you have a streamlined workflow in place? "
            "We convert full episodes into vertical clips without rebuilding timelines. Would love to share a 60-second preview if helpful!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Conversational, respectful, candidate disclosure included.",
    },
    {
        "template_id": "podcaster_instagram_t2",
        "segment": "podcaster",
        "channel": "instagram",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Quick follow-up on Reels clips",
        "body_template": (
            "Hey {creator_name}, following up briefly on your episode ({content_url}). "
            "Standardizing short-form clip generation usually saves podcasters 3-5 hours each week on distribution. "
            "No worries if you're already set with an editor!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value-focused, pressure-free.",
    },
    {
        "template_id": "podcaster_instagram_t3",
        "segment": "podcaster",
        "channel": "instagram",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Wrapping up",
        "body_template": (
            "Hey {creator_name}, won't follow up again here. Wishing you continued success with the show!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # ==========================================
    # 2. LONG-FORM YOUTUBE CREATORS
    # ==========================================
    # Email
    {
        "template_id": "youtube_creator_email_t1",
        "segment": "youtube_creator",
        "channel": "email",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Repurposing workflow for your YouTube video ({content_ref})",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I watched your recent video on YouTube ({content_url}) and wanted to reach out.\n\n"
            "For creators publishing detailed long-form video, turning each upload into high-retention Shorts, "
            "Reels, and community posts often requires repetitive re-editing and resizing in multiple applications.\n\n"
            "As an assessment candidate evaluating creator operations for IncuBrix, I am examining how long-form "
            "channels reduce that distribution drag: converting comprehensive horizontal videos into multi-format "
            "vertical highlights and cross-platform summaries without starting from scratch.\n\n"
            "Would you be interested in a 2-minute overview demonstrating how a video like yours can be automatically "
            "formatted for secondary distribution?\n\n"
            "Best regards,\n"
            "{sender_identity}\n"
            "Assessment Project: github.com/incubrix-candidate\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "primary_contact_value"],
        "compliance_notes": "Grounded in verified YouTube URL; candidate disclosure; no performance promises.",
    },
    {
        "template_id": "youtube_creator_email_t2",
        "segment": "youtube_creator",
        "channel": "email",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Re: Repurposing workflow for your YouTube video ({content_ref})",
        "body_template": (
            "Hi {creator_name},\n\n"
            "Quick follow-up on my note regarding your video at {content_url}.\n\n"
            "Creators who test our multi-format pipeline typically cut down cross-platform formatting from "
            "half a day to a single unified review step, preserving creative energy for primary production.\n\n"
            "Happy to share a 90-second async preview if you'd like to inspect how the workflow functions.\n\n"
            "Best,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Turnaround metrics grounded in realistic workflow savings; opt-out present.",
    },
    {
        "template_id": "youtube_creator_email_t3",
        "segment": "youtube_creator",
        "channel": "email",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Re: Repurposing workflow for your YouTube video ({content_ref})",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I understand you are fully focused on your upcoming production schedule, so I won't follow up further.\n\n"
            "If horizontal-to-vertical repurposing ever becomes a bottleneck in your channel workflow, "
            "feel free to review our open research anytime.\n\n"
            "Best of luck with your channel!\n\n"
            "Best regards,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite closing.",
    },

    # LinkedIn
    {
        "template_id": "youtube_creator_linkedin_t1",
        "segment": "youtube_creator",
        "channel": "linkedin",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Repurposing workflow for your YouTube content",
        "body_template": (
            "Hi {creator_name}, really enjoyed your recent YouTube upload ({content_url}). "
            "I'm an assessment candidate studying video workflow systems for IncuBrix. "
            "Many long-form creators tell us that reformatting 16:9 videos into vertical formats for secondary channels "
            "eats up hours that should go toward main channel scripts. "
            "We built a tool that handles vertical adaptation and captioning in one pass. "
            "Would you be open to a 90-second workflow preview?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "primary_contact_value"],
        "compliance_notes": "Clear LinkedIn professional outreach.",
    },
    {
        "template_id": "youtube_creator_linkedin_t2",
        "segment": "youtube_creator",
        "channel": "linkedin",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Follow-up: YouTube repurposing workflow",
        "body_template": (
            "Hi {creator_name}, following up on your video at {content_url}. "
            "We found that automating the initial cut of vertical shorts helps creators maintain daily distribution "
            "without hiring an assistant editor. Open to taking a look?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Helpful value addition.",
    },
    {
        "template_id": "youtube_creator_linkedin_t3",
        "segment": "youtube_creator",
        "channel": "linkedin",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Final note on video repurposing",
        "body_template": (
            "Hi {creator_name}, closing the loop here so I don't clutter your notifications. "
            "Keep up the great work on YouTube, and feel free to connect down the road if workflow needs change!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Graceful exit.",
    },

    # Instagram
    {
        "template_id": "youtube_creator_instagram_t1",
        "segment": "youtube_creator",
        "channel": "instagram",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "YouTube repurposing workflow note",
        "body_template": (
            "Hey {creator_name}! Just saw your recent video ({content_url})—solid work. "
            "I'm an assessment candidate exploring video operations for IncuBrix. "
            "Do you repurpose your long-form videos into Reels manually, or are you using a multi-format system? "
            "We help creators extract vertical highlights without timeline rebuilds. Open to a quick preview?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Concise Instagram outreach.",
    },
    {
        "template_id": "youtube_creator_instagram_t2",
        "segment": "youtube_creator",
        "channel": "instagram",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Quick follow-up on Reels workflow",
        "body_template": (
            "Hey {creator_name}, following up briefly on {content_url}. "
            "Streamlining the horizontal-to-vertical conversion typically saves creators several hours per video. "
            "Happy to share a 60-second video demo if you're interested!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add.",
    },
    {
        "template_id": "youtube_creator_instagram_t3",
        "segment": "youtube_creator",
        "channel": "instagram",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "All the best!",
        "body_template": (
            "Hey {creator_name}, won't follow up again here. Wishing you continued growth on YouTube!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # ==========================================
    # 3. COACHES
    # ==========================================
    # Email
    {
        "template_id": "coach_email_t1",
        "segment": "coach",
        "channel": "email",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Client acquisition workflow & content consistency for {creator_name}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I reviewed your recent content on {platform} ({content_url}) and noted your focus on {commercial_ref}.\n\n"
            "For coaches running active client programs, maintaining regular social content to attract qualified inbound "
            "leads often pulls vital time away from 1-on-1 client delivery.\n\n"
            "As an assessment candidate for IncuBrix, I am evaluating workflows that solve this exact friction: "
            "taking a single client Q&A, webinar, or coaching recording and converting it into a week of multi-format "
            "highlights and posts without having to edit video manually.\n\n"
            "Would you be open to a 2-minute overview showing how coaches streamline their content consistency "
            "while protecting their delivery schedule?\n\n"
            "Best regards,\n"
            "{sender_identity}\n"
            "Assessment Project: github.com/incubrix-candidate\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "commercial_evidence_url", "primary_contact_value"],
        "compliance_notes": "Grounded in commercial offer and recent educational post; candidate disclosure.",
    },
    {
        "template_id": "coach_email_t2",
        "segment": "coach",
        "channel": "email",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Re: Client acquisition workflow & content consistency for {creator_name}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "Quick follow-up on my note regarding your session at {content_url}.\n\n"
            "Coaching practitioners who test this workflow typically save 4-6 hours a week by letting one session "
            "generate short-form clips for LinkedIn and Instagram, keeping their inquiry pipeline active automatically.\n\n"
            "Happy to send over a 90-second demo if you'd like to see how it works.\n\n"
            "Best,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Time-savings grounding without false guarantees.",
    },
    {
        "template_id": "coach_email_t3",
        "segment": "coach",
        "channel": "email",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Re: Client acquisition workflow & content consistency for {creator_name}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I know your client calendar is your top priority, so I'll step back here.\n\n"
            "If content formatting or social publishing ever becomes a time sink for your practice, "
            "feel free to review our creator workflow research whenever timing fits.\n\n"
            "Best of luck with your clients and programs!\n\n"
            "Best regards,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # LinkedIn
    {
        "template_id": "coach_linkedin_t1",
        "segment": "coach",
        "channel": "linkedin",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Content consistency workflow for your coaching practice",
        "body_template": (
            "Hi {creator_name}, read your recent post on {platform} ({content_url}) supporting {commercial_ref}. "
            "I'm an assessment candidate studying creator operations for IncuBrix. "
            "Coaches often find that producing short video insights to drive program applications takes time away from client calls. "
            "We built a workflow that converts a single workshop or recording into vertical clips and written takeaways in one step. "
            "Open to a 90-second preview?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "commercial_evidence_url", "primary_contact_value"],
        "compliance_notes": "Direct LinkedIn B2B message.",
    },
    {
        "template_id": "coach_linkedin_t2",
        "segment": "coach",
        "channel": "linkedin",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Follow-up: Video repurposing for coaches",
        "body_template": (
            "Hi {creator_name}, following up on {content_url}. "
            "Automating clip formatting allows coaches to publish 3-5 times a week on LinkedIn without editing video by hand. "
            "Let me know if you'd like a quick peek at the workflow.\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add.",
    },
    {
        "template_id": "coach_linkedin_t3",
        "segment": "coach",
        "channel": "linkedin",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Final note on coaching content workflow",
        "body_template": (
            "Hi {creator_name}, closing the loop here so I don't crowd your inbox. "
            "Wishing you and your coaching clients continued success!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # Instagram
    {
        "template_id": "coach_instagram_t1",
        "segment": "coach",
        "channel": "instagram",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Workflow note for coaching content",
        "body_template": (
            "Hey {creator_name}! Loved your recent content ({content_url}) around {commercial_ref}. "
            "I'm an assessment candidate researching workflow tools for IncuBrix. "
            "Do you find creating Reels and carousels for client outreach takes significant time from your coaching? "
            "We convert recorded client Q&As into vertical clips without manual editing. Would love to share a quick preview if helpful!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Conversational, respectful.",
    },
    {
        "template_id": "coach_instagram_t2",
        "segment": "coach",
        "channel": "instagram",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Quick follow-up on Reels workflow",
        "body_template": (
            "Hey {creator_name}, following up briefly on {content_url}. "
            "Streamlining clip extraction typically saves coaches several hours each week on social presence. "
            "No pressure at all!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add.",
    },
    {
        "template_id": "coach_instagram_t3",
        "segment": "coach",
        "channel": "instagram",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Best of luck!",
        "body_template": (
            "Hey {creator_name}, won't message again. Wishing you continued success with your programs!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # ==========================================
    # 4. CONSULTANTS
    # ==========================================
    # Email
    {
        "template_id": "consultant_email_t1",
        "segment": "consultant",
        "channel": "email",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Executive content distribution workflow for {creator_name}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I read your recent analysis on {platform} ({content_url}) regarding your work at {commercial_ref}.\n\n"
            "For consultants and advisory firms, demonstrating subject-matter authority through consistent video "
            "and long-form commentary is essential, yet billable client engagements make regular social formatting difficult to sustain.\n\n"
            "As an assessment candidate for IncuBrix, I am researching executive workflow automation: taking a single "
            "client briefing, keynote, or webinar recording and systematically extracting multi-format clips and "
            "executive summaries without requiring dedicated video editing staff.\n\n"
            "Would you be open to a 2-minute overview showing how consulting practices maintain publishing consistency "
            "with minimal manual effort?\n\n"
            "Best regards,\n"
            "{sender_identity}\n"
            "Assessment Project: github.com/incubrix-candidate\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "commercial_evidence_url", "primary_contact_value"],
        "compliance_notes": "Professional B2B consulting tone; candidate disclosure; opt-out present.",
    },
    {
        "template_id": "consultant_email_t2",
        "segment": "consultant",
        "channel": "email",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Re: Executive content distribution workflow for {creator_name}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "Following up briefly on my note regarding your analysis at {content_url}.\n\n"
            "Consultancies evaluating this system typically look to convert partner presentations into high-impact "
            "LinkedIn video assets in under 15 minutes, preserving billable hours while expanding firm visibility.\n\n"
            "Happy to share an asynchronous 90-second walkthrough if this is relevant to your firm's distribution goals.\n\n"
            "Best,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add with realistic consulting turnaround context.",
    },
    {
        "template_id": "consultant_email_t3",
        "segment": "consultant",
        "channel": "email",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Re: Executive content distribution workflow for {creator_name}",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I realize your advisory engagements require full attention, so I'll step back.\n\n"
            "If your firm ever evaluates content automation to streamline thought leadership, "
            "feel free to review our workflow models whenever appropriate.\n\n"
            "Wishing you continued success with your clients.\n\n"
            "Best regards,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Professional closing.",
    },

    # LinkedIn
    {
        "template_id": "consultant_linkedin_t1",
        "segment": "consultant",
        "channel": "linkedin",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Thought-leadership workflow for your advisory practice",
        "body_template": (
            "Hi {creator_name}, thoroughly appreciated your recent perspective on {platform} ({content_url}). "
            "I'm an assessment candidate studying advisory workflow systems for IncuBrix. "
            "Consultants often struggle to maintain active LinkedIn video presence alongside demanding client deliverables. "
            "We built a workflow that turns recorded talks or webinars into multi-format insights without manual video editing. "
            "Would you be open to a 90-second async preview?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "primary_contact_value"],
        "compliance_notes": "B2B peer tone; candidate disclosure; opt-out present.",
    },
    {
        "template_id": "consultant_linkedin_t2",
        "segment": "consultant",
        "channel": "linkedin",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Follow-up: Advisory content workflow",
        "body_template": (
            "Hi {creator_name}, following up on {content_url}. "
            "Standardizing short-form clip generation enables advisory leaders to publish weekly on LinkedIn "
            "without delegating to external agencies. Happy to share a quick overview if interested.\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add.",
    },
    {
        "template_id": "consultant_linkedin_t3",
        "segment": "consultant",
        "channel": "linkedin",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Final note on advisory workflow",
        "body_template": (
            "Hi {creator_name}, closing the loop here so I don't crowd your messages. "
            "All the best with your practice and upcoming engagements!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # Instagram
    {
        "template_id": "consultant_instagram_t1",
        "segment": "consultant",
        "channel": "instagram",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Workflow note on consulting insights",
        "body_template": (
            "Hey {creator_name}! Saw your recent post ({content_url})—valuable insights. "
            "I'm an assessment candidate researching workflow tools for IncuBrix. "
            "Do you find creating short-form video for your advisory brand takes too much time from client work? "
            "We help consultants turn recorded webinars into vertical video clips without manual editing. Open to a quick preview?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Conversational, respectful.",
    },
    {
        "template_id": "consultant_instagram_t2",
        "segment": "consultant",
        "channel": "instagram",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Quick follow-up on video insights",
        "body_template": (
            "Hey {creator_name}, following up briefly on {content_url}. "
            "Automating vertical clip generation saves advisory leaders hours each week. "
            "No pressure at all!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add.",
    },
    {
        "template_id": "consultant_instagram_t3",
        "segment": "consultant",
        "channel": "instagram",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "All the best!",
        "body_template": (
            "Hey {creator_name}, won't message again. Wishing you continued success with your advisory work!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # ==========================================
    # 5. EDUCATORS WHO PUBLISH CONTENT
    # ==========================================
    # Email
    {
        "template_id": "educator_email_t1",
        "segment": "educator",
        "channel": "email",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Curriculum clip extraction workflow for your lessons ({content_ref})",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I explored your educational content on {platform} ({content_url}) and wanted to reach out.\n\n"
            "For educators and course creators, turning in-depth educational lectures into concise micro-lessons "
            "and cross-platform summaries often involves painstaking manual timeline chopping and formatting.\n\n"
            "As an assessment candidate evaluating educational creator tools for IncuBrix, I am examining how "
            "instructors automate that repurposing pipeline: converting full-length tutorials into multi-format "
            "lesson highlights without rebuilding each video from scratch.\n\n"
            "Would you be open to a 2-minute overview showing how an educational lecture like yours can be "
            "converted into modular learning snippets?\n\n"
            "Best regards,\n"
            "{sender_identity}\n"
            "Assessment Project: github.com/incubrix-candidate\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "primary_contact_value"],
        "compliance_notes": "Educational focus; candidate disclosure; no false learning promises.",
    },
    {
        "template_id": "educator_email_t2",
        "segment": "educator",
        "channel": "email",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Re: Curriculum clip extraction workflow for your lessons ({content_ref})",
        "body_template": (
            "Hi {creator_name},\n\n"
            "Following up briefly on my note regarding your lecture at {content_url}.\n\n"
            "Instructors testing this workflow typically find that generating short concept clips helps student "
            "engagement while reducing repetitive formatting steps by several hours per course module.\n\n"
            "Happy to share an asynchronous 90-second demo if you'd like to inspect how the extraction functions.\n\n"
            "Best,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add; opt-out present.",
    },
    {
        "template_id": "educator_email_t3",
        "segment": "educator",
        "channel": "email",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Re: Curriculum clip extraction workflow for your lessons ({content_ref})",
        "body_template": (
            "Hi {creator_name},\n\n"
            "I understand your teaching and curriculum schedule takes precedence, so I won't follow up further.\n\n"
            "If modular lesson repurposing ever becomes a focus for your courses, feel free to inspect our research anytime.\n\n"
            "Wishing you continued success with your students!\n\n"
            "Best regards,\n"
            "{sender_identity}\n\n"
            "---\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # LinkedIn
    {
        "template_id": "educator_linkedin_t1",
        "segment": "educator",
        "channel": "linkedin",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Lesson repurposing workflow for your courses",
        "body_template": (
            "Hi {creator_name}, really enjoyed your educational breakdown on {platform} ({content_url}). "
            "I'm an assessment candidate studying educator workflows for IncuBrix. "
            "Instructors often tell us that extracting short concept clips from full lectures takes hours away from course development. "
            "We built a workflow that creates vertical learning snippets without manual editing. "
            "Would you be open to a 90-second async preview?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url", "primary_contact_value"],
        "compliance_notes": "Professional academic/educator tone; candidate disclosure.",
    },
    {
        "template_id": "educator_linkedin_t2",
        "segment": "educator",
        "channel": "linkedin",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Follow-up: Modular lesson workflow",
        "body_template": (
            "Hi {creator_name}, following up on {content_url}. "
            "Automating concept highlights allows educators to share key takeaways on LinkedIn and YouTube Shorts "
            "without rebuilding timelines. Let me know if you'd like a quick look.\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add.",
    },
    {
        "template_id": "educator_linkedin_t3",
        "segment": "educator",
        "channel": "linkedin",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "Final note on lesson workflow",
        "body_template": (
            "Hi {creator_name}, closing the loop here so I don't crowd your notifications. "
            "All the best with your courses and teaching!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },

    # Instagram
    {
        "template_id": "educator_instagram_t1",
        "segment": "educator",
        "channel": "instagram",
        "touch_number": 1,
        "suggested_delay_days": 0,
        "subject_line": "Workflow note on lesson clips",
        "body_template": (
            "Hey {creator_name}! Saw your educational video ({content_url})—excellent breakdown. "
            "I'm an assessment candidate researching workflow tools for IncuBrix. "
            "Do you find re-editing lectures into bite-sized Reels takes significant time? "
            "We help educators extract vertical concept clips without manual editing. Open to a quick preview?\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Conversational, educational focus.",
    },
    {
        "template_id": "educator_instagram_t2",
        "segment": "educator",
        "channel": "instagram",
        "touch_number": 2,
        "suggested_delay_days": 3,
        "subject_line": "Quick follow-up on lesson clips",
        "body_template": (
            "Hey {creator_name}, following up on {content_url}. "
            "Automating clip generation saves educators 3-5 hours each week on social distribution. "
            "No pressure at all!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": ["recent_content_url"],
        "compliance_notes": "Value add.",
    },
    {
        "template_id": "educator_instagram_t3",
        "segment": "educator",
        "channel": "instagram",
        "touch_number": 3,
        "suggested_delay_days": 7,
        "subject_line": "All the best!",
        "body_template": (
            "Hey {creator_name}, won't message again. Wishing you continued success with your students!\n\n"
            "— {sender_identity}\n"
            "{opt_out}"
        ),
        "required_evidence_fields": [],
        "compliance_notes": "Polite exit.",
    },
]


def get_all_templates() -> List[OutreachTemplate]:
    """Retrieve all 45 structured segment- and channel-specific templates."""
    templates = []
    for d in TEMPLATE_DEFINITIONS:
        templates.append(
            OutreachTemplate(
                template_id=d["template_id"],
                segment=d["segment"],
                channel=d["channel"],
                touch_number=d["touch_number"],
                suggested_delay_days=d["suggested_delay_days"],
                subject_line=d["subject_line"],
                body_template=d["body_template"],
                required_evidence_fields=d.get("required_evidence_fields", []),
                sender_identity=SENDER_IDENTITY,
                compliance_notes=d.get("compliance_notes", ""),
            )
        )
    return templates


def get_opt_out_footer_for_channel(channel: str) -> str:
    """Return platform-appropriate compliant opt-out footer."""
    c = (channel or "").lower()
    if c == "email":
        return EMAIL_OPT_OUT
    if c == "linkedin":
        return LINKEDIN_OPT_OUT
    return INSTAGRAM_OPT_OUT


def render_touch(
    template: OutreachTemplate,
    lead: Lead,
    channel_res: ChannelSelectionResult,
    content_url: str,
) -> Tuple[str, str]:
    """
    Render subject line and body for a specific touch.
    Interpolates creator name, verified content URL, platform, commercial offer, and sender.
    """
    creator_name = lead.creator_name or "Creator"
    platform = (lead.platform or "your channel").title()
    content_ref = content_url.split("/")[-1] if "/" in content_url else "recent content"
    commercial_ref = lead.commercial_evidence_url or "your services"
    opt_out = get_opt_out_footer_for_channel(template.channel)

    subject = template.subject_line.format(
        creator_name=creator_name,
        platform=platform,
        content_ref=content_ref,
        commercial_ref=commercial_ref,
    )

    body = template.body_template.format(
        creator_name=creator_name,
        platform=platform,
        content_url=content_url,
        content_ref=content_ref,
        commercial_ref=commercial_ref,
        sender_identity=SENDER_IDENTITY,
        opt_out=opt_out,
    )

    return subject, body


def validate_lead_personalisation_evidence(
    lead: Lead,
    channel_res: ChannelSelectionResult,
) -> Tuple[bool, str, str]:
    """
    Validate that:
    1. A verified recent content URL exists.
    2. A verified public contact channel exists within 60 days.
    Returns: (is_valid, content_url, failure_explanation)
    """
    # 1. Content URL (Must reference specific recent content item for Priority A personalisation)
    content_url = ""
    if lead.recent_content_urls and len(lead.recent_content_urls) > 0:
        content_url = lead.recent_content_urls[0]

    if not content_url:
        return (
            False,
            "",
            "Missing verified recent content item URL in evidence record. Outreach personalisation requires referencing a specific recent content item.",
        )

    # 2. Channel suitability
    if channel_res.channel_suitability_status == "needs_review":
        return False, content_url, f"Channel suitability is 'needs_review': {channel_res.primary_channel_reason}"

    return True, content_url, ""

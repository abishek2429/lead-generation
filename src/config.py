"""
Configuration management for IncuBrix Lead Discovery & Qualification Engine.
Loads environment variables and parses qualification_config.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables from .env if present
load_dotenv()


class ActivityGateConfig(BaseModel):
    mode: str = "either"
    content_items_last_30_days_min: int = 8
    long_form_items_last_60_days_min: int = 2


class QualificationPolicy(BaseModel):
    allowed_segments: List[str] = Field(
        default_factory=lambda: [
            "podcaster",
            "video_podcaster",
            "youtube_video_first_creator",
            "coach_creator",
            "consultant_creator",
            "educator_creator",
        ]
    )
    excluded_types: List[str] = Field(
        default_factory=lambda: [
            "agency",
            "management_firm",
            "generic_brand",
            "publication",
            "directory",
            "fan_account",
        ]
    )
    allowed_countries: List[str] = Field(
        default_factory=lambda: [
            "United States",
            "Canada",
            "United Kingdom",
            "Ireland",
            "Australia",
            "New Zealand",
            "Singapore",
        ]
    )
    minimum_share_allowed_countries: float = 0.8
    minimum_distinct_countries: int = 3
    maximum_share_single_country: float = 0.6
    primary_language: str = "English"
    activity_gate: ActivityGateConfig = Field(default_factory=ActivityGateConfig)
    commercial_evidence_required: bool = True
    workflow_need_evidence_required: bool = True
    public_business_contact_required: bool = True
    contact_activity_days_max: int = 60
    evidence_freshness_days_max: int = 30
    official_profile_required: bool = True
    stable_platform_id_required: bool = True
    guessed_contacts_allowed: bool = False
    deduplicate_by: List[str] = Field(
        default_factory=lambda: ["platform_id", "canonical_profile_url"]
    )
    must_not_contact_real_creators: bool = True


class ScoringWeights(BaseModel):
    workflow_need: int = 30
    segment_fit: int = 25
    commercial_intent: int = 20
    publishing_consistency: int = 15
    contact_channel_quality: int = 10


class PriorityACriteria(BaseModel):
    count_minimum: int = 25
    require_personalised_first_message: bool = True
    follow_ups_required: int = 2
    must_reference_specific_recent_content: bool = True


class AppConfig(BaseModel):
    config_version: str = "1.0"
    created_date: str = "2026-10-25"
    qualification_policy: QualificationPolicy = Field(default_factory=QualificationPolicy)
    scoring_after_hard_gates: ScoringWeights = Field(default_factory=ScoringWeights)
    priority_a: PriorityACriteria = Field(default_factory=PriorityACriteria)
    country_mix_planning_targets: Dict[str, int] = Field(
        default_factory=lambda: {
            "United States": 300,
            "United Kingdom": 200,
            "Canada": 150,
            "Australia": 120,
            "Ireland": 80,
            "Singapore": 80,
            "New Zealand": 70,
        }
    )
    # Environment variables
    youtube_api_key: Optional[str] = Field(default=None, repr=False)
    database_path: str = "data/database/leads.db"
    input_dir: str = "data/input"
    output_dir: str = "data/output"
    log_level: str = "INFO"
    test_base_url: str = "http://localhost:8501"
    simulator_port: int = 8502


def find_config_file(explicit_path: Optional[str] = None) -> Optional[Path]:
    """Find qualification_config.json in explicit path, config/, or current directory."""
    candidates = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    env_cfg = os.getenv("CONFIG_PATH")
    if env_cfg:
        candidates.append(Path(env_cfg))
    candidates.extend([
        Path("config/qualification_config.json"),
        Path("qualification_config.json"),
        Path(__file__).resolve().parent.parent / "config" / "qualification_config.json",
        Path(__file__).resolve().parent.parent / "qualification_config.json",
    ])
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from JSON file and merge with environment variables."""
    cfg_file = find_config_file(config_path)
    data: Dict[str, Any] = {}
    if cfg_file and cfg_file.is_file():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"Warning: Failed to parse configuration from {cfg_file}: {exc}")

    # Map country mix key if present in json
    country_targets = data.get("country_mix_planning_targets_not_actual_leads", {})
    if not country_targets and "country_mix_planning_targets" in data:
        country_targets = data["country_mix_planning_targets"]

    policy_data = data.get("qualification_policy", {})
    scoring_data = data.get("scoring_after_hard_gates", {})
    priority_data = data.get("priority_a", {})

    policy = QualificationPolicy(**policy_data) if policy_data else QualificationPolicy()
    scoring = ScoringWeights(**scoring_data) if scoring_data else ScoringWeights()
    priority = PriorityACriteria(**priority_data) if priority_data else PriorityACriteria()

    app_config = AppConfig(
        config_version=data.get("config_version", "1.0"),
        created_date=data.get("created_date", "2026-10-25"),
        qualification_policy=policy,
        scoring_after_hard_gates=scoring,
        priority_a=priority,
        country_mix_planning_targets=country_targets or {
            "United States": 300,
            "United Kingdom": 200,
            "Canada": 150,
            "Australia": 120,
            "Ireland": 80,
            "Singapore": 80,
            "New Zealand": 70,
        },
        youtube_api_key=os.getenv("YOUTUBE_API_KEY") or None,
        database_path=os.getenv("DATABASE_PATH", "data/database/leads.db"),
        input_dir=os.getenv("INPUT_DIR", "data/input"),
        output_dir=os.getenv("OUTPUT_DIR", "data/output"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        test_base_url=os.getenv("TEST_BASE_URL", "http://localhost:8501"),
        simulator_port=int(os.getenv("SIMULATOR_PORT", "8502")),
    )
    return app_config

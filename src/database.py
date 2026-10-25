"""
SQLite persistence layer for IncuBrix Lead Discovery Engine.
Automatically initializes tables and audit logs, ensuring idempotent schema creation and thread-safe operations.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from src.deduplication import canonicalize_url
from src.logging_config import get_logger
from src.models import (
    CampaignOutreachRecord,
    DeliveryEvent,
    EvidenceItem,
    InvalidStateTransitionError,
    Lead,
    OutreachPreparation,
    OutreachState,
    QualificationStatus,
    SuppressionRecord,
    VerificationLog,
)

logger = get_logger("database")


class Database:
    """SQLite repository managing leads, evidence items, and verification audit logs."""

    def __init__(self, db_path: str = "data/database/leads.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a contextual database connection with row factory enabled."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initialize database schema, tables, and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Leads table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_name TEXT NOT NULL,
                creator_type TEXT NOT NULL,
                country TEXT,
                language TEXT DEFAULT 'English',
                platform TEXT NOT NULL,
                platform_id TEXT NOT NULL,
                official_profile_url TEXT NOT NULL,
                candidate_source_url TEXT NOT NULL,
                recent_content_urls TEXT DEFAULT '[]',
                recent_content_dates TEXT DEFAULT '[]',
                commercial_evidence_url TEXT,
                workflow_need_evidence_url TEXT,
                business_contact_type TEXT,
                business_contact_value TEXT,
                business_contact_source_url TEXT,
                business_contact_last_active TEXT,
                evidence_checked_at TEXT,
                qualification_status TEXT NOT NULL DEFAULT 'discovered',
                disqualification_reasons TEXT DEFAULT '[]',
                score REAL DEFAULT 0.0,
                priority TEXT,
                score_breakdown TEXT DEFAULT '{}',
                first_discovered_at TEXT NOT NULL,
                last_checked_at TEXT,
                last_run_id TEXT,
                is_synthetic INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Migrations for existing databases
            try:
                cursor.execute("ALTER TABLE leads ADD COLUMN is_synthetic INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE leads ADD COLUMN score_breakdown TEXT DEFAULT '{}';")
            except sqlite3.OperationalError:
                pass

            # Evidence items table (Source-linked proof store)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS evidence_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                platform TEXT NOT NULL,
                platform_id TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                source_url TEXT NOT NULL,
                short_factual_description TEXT NOT NULL,
                content_date TEXT,
                checked_at TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                verification_method TEXT NOT NULL,
                review_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
            );
            """)

            # Outreach preparation table (Personalised copy for Priority A leads)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS outreach_preparations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                platform_id TEXT NOT NULL,
                creator_name TEXT NOT NULL,
                score REAL DEFAULT 0.0,
                priority TEXT NOT NULL DEFAULT 'A',
                segment TEXT DEFAULT '',
                primary_channel TEXT NOT NULL DEFAULT 'email',
                primary_channel_reason TEXT DEFAULT '',
                primary_contact_value TEXT DEFAULT '',
                primary_contact_source_url TEXT DEFAULT '',
                primary_contact_verified_date TEXT DEFAULT '',
                backup_channel TEXT DEFAULT '',
                backup_channel_reason TEXT DEFAULT '',
                backup_contact_value TEXT DEFAULT '',
                backup_contact_source_url TEXT DEFAULT '',
                channel_suitability_status TEXT DEFAULT 'suitable',
                subject_line TEXT DEFAULT '',
                proposed_first_message TEXT NOT NULL,
                follow_up_1 TEXT NOT NULL,
                follow_up_2 TEXT NOT NULL,
                follow_up_1_delay_days INTEGER DEFAULT 3,
                follow_up_2_delay_days INTEGER DEFAULT 7,
                chosen_channel TEXT NOT NULL,
                specific_content_source_url TEXT NOT NULL,
                personalisation_rationale TEXT NOT NULL,
                opt_out_language TEXT NOT NULL,
                sender_identity TEXT DEFAULT 'IncuBrix Growth Engineer Assessment Candidate',
                validation_status TEXT DEFAULT 'valid',
                validation_notes TEXT DEFAULT '',
                outreach_status TEXT DEFAULT 'DRAFT',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                is_synthetic INTEGER DEFAULT 0,
                FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
            );
            """)

            # Migrations for existing outreach_preparations tables
            outreach_cols_to_add = [
                ("segment", "TEXT DEFAULT ''"),
                ("primary_channel", "TEXT NOT NULL DEFAULT 'email'"),
                ("primary_channel_reason", "TEXT DEFAULT ''"),
                ("primary_contact_value", "TEXT DEFAULT ''"),
                ("primary_contact_source_url", "TEXT DEFAULT ''"),
                ("primary_contact_verified_date", "TEXT DEFAULT ''"),
                ("backup_channel_reason", "TEXT DEFAULT ''"),
                ("backup_contact_value", "TEXT DEFAULT ''"),
                ("backup_contact_source_url", "TEXT DEFAULT ''"),
                ("channel_suitability_status", "TEXT DEFAULT 'suitable'"),
                ("subject_line", "TEXT DEFAULT ''"),
                ("follow_up_1_delay_days", "INTEGER DEFAULT 3"),
                ("follow_up_2_delay_days", "INTEGER DEFAULT 7"),
                ("sender_identity", "TEXT DEFAULT 'IncuBrix Growth Engineer Assessment Candidate'"),
                ("validation_status", "TEXT DEFAULT 'valid'"),
                ("validation_notes", "TEXT DEFAULT ''"),
                ("outreach_status", "TEXT DEFAULT 'DRAFT'"),
                ("updated_at", "TEXT"),
            ]
            for col_name, col_type in outreach_cols_to_add:
                try:
                    cursor.execute(f"ALTER TABLE outreach_preparations ADD COLUMN {col_name} {col_type};")
                except sqlite3.OperationalError:
                    pass

            # Safe seed testing delivery simulation events table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS delivery_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                platform_id TEXT NOT NULL,
                recipient_contact TEXT NOT NULL,
                channel TEXT NOT NULL,
                touch_number INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                tracking_token TEXT,
                message_snippet TEXT,
                event_payload TEXT DEFAULT '{}',
                timestamp TEXT NOT NULL,
                is_authorized_seed INTEGER DEFAULT 1,
                FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
            );
            """)

            # Migrations for existing delivery_events tables
            delivery_cols_to_add = [
                ("campaign_id", "TEXT DEFAULT 'default_test_campaign'"),
                ("test_account_id", "TEXT DEFAULT 'candidate_test_account'"),
                ("idempotent_key", "TEXT"),
                ("opaque_id", "TEXT"),
            ]
            for col_name, col_type in delivery_cols_to_add:
                try:
                    cursor.execute(f"ALTER TABLE delivery_events ADD COLUMN {col_name} {col_type};")
                except sqlite3.OperationalError:
                    pass

            # Campaign outreach records table (unique outreach record per lead and campaign)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaign_outreach_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                campaign_id TEXT NOT NULL,
                platform_id TEXT NOT NULL,
                creator_name TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'email',
                contact_endpoint TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'draft',
                tracking_token TEXT,
                opaque_id TEXT,
                test_account_id TEXT,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                is_synthetic INTEGER DEFAULT 0,
                UNIQUE(lead_id, campaign_id),
                FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE CASCADE
            );
            """)

            # Global suppression list table for opt-outs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS suppression_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_value TEXT UNIQUE NOT NULL,
                channel TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT 'Opt-out requested',
                opted_out_at TEXT NOT NULL
            );
            """)

            # Audit / Verification logs table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                platform TEXT NOT NULL,
                platform_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status_before TEXT,
                status_after TEXT,
                disqualification_reasons TEXT DEFAULT '[]',
                score REAL DEFAULT 0.0,
                priority TEXT,
                timestamp TEXT NOT NULL,
                run_id TEXT,
                details TEXT DEFAULT '{}',
                FOREIGN KEY (lead_id) REFERENCES leads (id) ON DELETE SET NULL
            );
            """)

            # Indexes for fast deduplication, filtering, and foreign keys
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_platform_key ON leads (platform, platform_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_profile_url ON leads (official_profile_url);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (qualification_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads (priority);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_synthetic ON leads (is_synthetic);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vlogs_lead_id ON verification_logs (lead_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vlogs_run_id ON verification_logs (run_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_lead_id ON evidence_items (lead_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence_items (evidence_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outreach_lead_id ON outreach_preparations (lead_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outreach_priority ON outreach_preparations (priority);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_platform ON delivery_events (platform_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON delivery_events (event_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_campaign ON delivery_events (campaign_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaign_records_camp ON campaign_outreach_records (campaign_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaign_records_state ON campaign_outreach_records (state);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaign_records_opaque ON campaign_outreach_records (opaque_id);")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_events_idempotent ON delivery_events (idempotent_key) WHERE idempotent_key IS NOT NULL;")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_suppression_contact ON suppression_list (contact_value);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_lead_type ON evidence_items (lead_id, evidence_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_checked_at ON evidence_items (checked_at);")

        logger.debug(f"Database initialized at {self.db_path}")

    def insert_lead(self, lead: Lead) -> Lead:
        """Insert a new candidate record into the database."""
        lead_dict = lead.to_db_dict()
        lead_dict.pop("id", None)

        cols = list(lead_dict.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, lead_dict)
            lead.id = cursor.lastrowid
        return lead

    def insert_leads_batch(self, leads: List[Lead]) -> List[Lead]:
        """
        Batch insert candidate records in a single transaction for maximum throughput.
        Sets the generated database id on each inserted lead.
        """
        if not leads:
            return []

        sample_dict = leads[0].to_db_dict()
        sample_dict.pop("id", None)
        cols = list(sample_dict.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for lead in leads:
                lead_dict = lead.to_db_dict()
                lead_dict.pop("id", None)
                cursor.execute(sql, lead_dict)
                lead.id = cursor.lastrowid
        return leads

    def update_lead(self, lead: Lead) -> Lead:
        """Update an existing lead record by ID or platform identifier."""
        if not lead.id:
            existing = self.get_lead_by_platform_id(lead.platform, lead.platform_id)
            if existing and existing.id:
                lead.id = existing.id
            else:
                return self.insert_lead(lead)

        lead_dict = lead.to_db_dict()
        lead_id = lead_dict.pop("id")
        set_clause = ", ".join([f"{c} = :{c}" for c in lead_dict.keys()])
        lead_dict["id"] = lead_id
        lead_dict["updated_at"] = datetime.now(timezone.utc).isoformat()

        sql = f"UPDATE leads SET {set_clause}, updated_at = :updated_at WHERE id = :id"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, lead_dict)
        return lead

    def update_leads_batch(self, leads: List[Lead]) -> List[Lead]:
        """
        Batch update lead records in a single transaction for maximum throughput.
        """
        if not leads:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        sample_dict = leads[0].to_db_dict()
        sample_dict.pop("id", None)
        set_clause = ", ".join([f"{c} = :{c}" for c in sample_dict.keys()])
        update_sql = f"UPDATE leads SET {set_clause}, updated_at = :updated_at WHERE id = :id"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for lead in leads:
                if not lead.id:
                    cursor.execute(
                        "SELECT id FROM leads WHERE LOWER(platform) = LOWER(?) AND LOWER(platform_id) = LOWER(?) LIMIT 1",
                        (lead.platform.strip(), lead.platform_id.strip()),
                    )
                    row = cursor.fetchone()
                    if row:
                        lead.id = row[0]
                    else:
                        lead_dict = lead.to_db_dict()
                        lead_dict.pop("id", None)
                        cols = list(lead_dict.keys())
                        placeholders = [f":{c}" for c in cols]
                        sql = f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
                        cursor.execute(sql, lead_dict)
                        lead.id = cursor.lastrowid
                        continue

                lead_dict = lead.to_db_dict()
                lead_dict["updated_at"] = now_iso
                cursor.execute(update_sql, lead_dict)
        return leads

    def get_lead_by_id(self, lead_id: int) -> Optional[Lead]:
        """Fetch lead by database primary key."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
            row = cursor.fetchone()
            if row:
                return Lead.from_db_row(dict(row))
        return None

    def get_lead_by_platform_id(self, platform: str, platform_id: str) -> Optional[Lead]:
        """Fetch lead by platform and platform_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM leads WHERE LOWER(platform) = LOWER(?) AND LOWER(platform_id) = LOWER(?) LIMIT 1",
                (platform.strip(), platform_id.strip()),
            )
            row = cursor.fetchone()
            if row:
                return Lead.from_db_row(dict(row))
        return None

    def get_lead_by_profile_url(self, url: str) -> Optional[Lead]:
        """Fetch lead by official profile URL (checks canonicalized form)."""
        canon = canonicalize_url(url)
        all_leads = self.get_all_leads()
        for lead in all_leads:
            if canonicalize_url(lead.official_profile_url) == canon:
                return lead
        return None

    def get_all_leads(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        country: Optional[str] = None,
        is_synthetic: Optional[bool] = None,
    ) -> List[Lead]:
        """Retrieve all leads matching optional status, priority, country, or synthetic filters."""
        query = "SELECT * FROM leads WHERE 1=1"
        params: List[Any] = []

        if status:
            query += " AND LOWER(qualification_status) = LOWER(?)"
            params.append(status)
        if priority:
            query += " AND UPPER(priority) = UPPER(?)"
            params.append(priority)
        if country:
            query += " AND LOWER(country) = LOWER(?)"
            params.append(country)
        if is_synthetic is not None:
            query += " AND is_synthetic = ?"
            params.append(1 if is_synthetic else 0)

        query += " ORDER BY score DESC, id ASC"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [Lead.from_db_row(dict(r)) for r in rows]

    def log_verification(self, log_entry: VerificationLog) -> int:
        """Record verification audit log entry."""
        log_dict = log_entry.to_db_dict()
        log_dict.pop("id", None)
        cols = list(log_dict.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO verification_logs ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, log_dict)
            return cursor.lastrowid or 0

    def log_verifications_batch(self, log_entries: List[VerificationLog]) -> None:
        """Batch record verification audit log entries in a single transaction."""
        if not log_entries:
            return

        sample_dict = log_entries[0].to_db_dict()
        sample_dict.pop("id", None)
        cols = list(sample_dict.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO verification_logs ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        dicts = []
        for log_entry in log_entries:
            d = log_entry.to_db_dict()
            d.pop("id", None)
            dicts.append(d)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, dicts)

    def get_verification_logs(
        self,
        platform_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[VerificationLog]:
        """Retrieve verification logs."""
        query = "SELECT * FROM verification_logs WHERE 1=1"
        params: List[Any] = []
        if platform_id:
            query += " AND LOWER(platform_id) = LOWER(?)"
            params.append(platform_id.strip())
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                row_dict = dict(r)
                if isinstance(row_dict.get("disqualification_reasons"), str):
                    try:
                        row_dict["disqualification_reasons"] = json.loads(row_dict["disqualification_reasons"])
                    except Exception:
                        row_dict["disqualification_reasons"] = []
                if isinstance(row_dict.get("details"), str):
                    try:
                        row_dict["details"] = json.loads(row_dict["details"])
                    except Exception:
                        row_dict["details"] = {}
                results.append(VerificationLog(**row_dict))
            return results

    def get_metrics(self) -> Dict[str, Any]:
        """Calculate summary metrics across candidates and qualified leads."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM leads")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'discovered'")
            discovered = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'needs_review'")
            needs_review = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'qualified'")
            qualified = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'disqualified'")
            disqualified = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE is_synthetic = 1")
            synthetic_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE is_synthetic = 0")
            real_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'qualified' AND is_synthetic = 0")
            real_qualified = cursor.fetchone()[0]

            # Priority counts for real qualified leads (or all if testing)
            cursor.execute("SELECT priority, COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'qualified' GROUP BY priority")
            priority_counts = {row[0] or "Unassigned": row[1] for row in cursor.fetchall()}

            # Country counts
            cursor.execute("SELECT country, COUNT(*) FROM leads GROUP BY country")
            country_counts = {row[0] or "Unknown": row[1] for row in cursor.fetchall()}

            # Country counts for real qualified leads
            cursor.execute("SELECT country, COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'qualified' AND is_synthetic = 0 GROUP BY country")
            real_country_counts = {row[0] or "Unknown": row[1] for row in cursor.fetchall()}

            # Segment counts
            cursor.execute("SELECT creator_type, COUNT(*) FROM leads GROUP BY creator_type")
            segment_counts = {row[0] or "Unknown": row[1] for row in cursor.fetchall()}

            # Priority A count
            cursor.execute("SELECT COUNT(*) FROM leads WHERE LOWER(qualification_status) = 'qualified' AND UPPER(priority) = 'A'")
            priority_a_count = cursor.fetchone()[0]

            # Missing evidence analysis across candidate pool
            cursor.execute("SELECT COUNT(*) FROM leads WHERE commercial_evidence_url IS NULL OR commercial_evidence_url = ''")
            missing_commercial = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE workflow_need_evidence_url IS NULL OR workflow_need_evidence_url = ''")
            missing_workflow = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE business_contact_value IS NULL OR business_contact_value = ''")
            missing_contact = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM leads WHERE business_contact_last_active IS NULL OR business_contact_last_active = ''")
            missing_activity = cursor.fetchone()[0]

            missing_evidence_summary = {
                "missing_commercial_offer": missing_commercial,
                "missing_workflow_need": missing_workflow,
                "missing_business_contact": missing_contact,
                "missing_contact_activity": missing_activity,
            }

            # Evidence freshness rate: fraction of evidence items checked within last 30 days
            cursor.execute("SELECT COUNT(*) FROM evidence_items")
            total_evidence = cursor.fetchone()[0]

            now_dt = datetime.now(timezone.utc)
            cutoff_iso = datetime.fromtimestamp(now_dt.timestamp() - 30 * 86400, tz=timezone.utc).isoformat()
            cursor.execute("SELECT COUNT(*) FROM evidence_items WHERE checked_at >= ?", (cutoff_iso,))
            fresh_evidence_count = cursor.fetchone()[0]

            freshness_rate = round(fresh_evidence_count / total_evidence, 3) if total_evidence > 0 else 1.0

            return {
                "total_candidates": total,
                "discovered": discovered,
                "needs_review": needs_review,
                "qualified": qualified,
                "disqualified": disqualified,
                "synthetic_candidates": synthetic_count,
                "real_candidates": real_count,
                "real_qualified": real_qualified,
                "priority_a_count": priority_a_count,
                "priority_breakdown": priority_counts,
                "country_breakdown": country_counts,
                "real_country_breakdown": real_country_counts,
                "segment_breakdown": segment_counts,
                "missing_evidence_summary": missing_evidence_summary,
                "evidence_freshness_rate": freshness_rate,
                "total_evidence_items": total_evidence,
            }

    # -------------------------------------------------------------------------
    # Evidence Items Operations
    # -------------------------------------------------------------------------
    def insert_evidence_item(self, item: EvidenceItem) -> EvidenceItem:
        """Insert a single source-linked evidence item."""
        d = item.to_db_dict()
        d.pop("id", None)
        cols = list(d.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO evidence_items ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, d)
            item.id = cursor.lastrowid
        return item

    def insert_evidence_items(self, items: List[EvidenceItem]) -> None:
        """Batch insert multiple source-linked evidence items."""
        if not items:
            return

        sample_dict = items[0].to_db_dict()
        sample_dict.pop("id", None)
        cols = list(sample_dict.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO evidence_items ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        dicts = []
        for item in items:
            d = item.to_db_dict()
            d.pop("id", None)
            dicts.append(d)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, dicts)

    def get_evidence_for_lead(self, lead_id: int) -> List[EvidenceItem]:
        """Retrieve all source-linked evidence items for a given lead."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM evidence_items WHERE lead_id = ? ORDER BY id ASC", (lead_id,))
            return [EvidenceItem.from_db_row(dict(r)) for r in cursor.fetchall()]

    def get_all_evidence_items(self) -> List[EvidenceItem]:
        """Retrieve all source-linked evidence items."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM evidence_items ORDER BY id ASC")
            return [EvidenceItem.from_db_row(dict(r)) for r in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Outreach Preparations Operations (Priority A Leads)
    # -------------------------------------------------------------------------
    def save_outreach_preparations(self, preps: List[OutreachPreparation]) -> None:
        """Save or replace personalised outreach preparation records."""
        if not preps:
            return

        sample_dict = preps[0].to_db_dict()
        sample_dict.pop("id", None)
        cols = list(sample_dict.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO outreach_preparations ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for p in preps:
                cursor.execute("DELETE FROM outreach_preparations WHERE platform_id = ?", (p.platform_id,))
                d = p.to_db_dict()
                d.pop("id", None)
                cursor.execute(sql, d)

    def get_outreach_preparations(
        self,
        is_synthetic: Optional[bool] = None,
        priority: Optional[str] = None,
        channel_suitability: Optional[str] = None,
    ) -> List[OutreachPreparation]:
        """Retrieve personalised outreach preparations with optional filters."""
        query = "SELECT * FROM outreach_preparations WHERE 1=1"
        params: List[Any] = []

        if is_synthetic is not None:
            query += " AND is_synthetic = ?"
            params.append(1 if is_synthetic else 0)

        if priority is not None:
            query += " AND priority = ?"
            params.append(priority.upper())

        if channel_suitability is not None:
            query += " AND channel_suitability_status = ?"
            params.append(channel_suitability.lower())

        query += " ORDER BY score DESC, id ASC"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [OutreachPreparation.from_db_row(dict(r)) for r in cursor.fetchall()]

    def get_outreach_preparation_by_platform_id(self, platform_id: str) -> Optional[OutreachPreparation]:
        """Retrieve an outreach preparation record by platform ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM outreach_preparations WHERE platform_id = ?", (platform_id,))
            row = cursor.fetchone()
            if row:
                return OutreachPreparation.from_db_row(dict(row))
            return None

    def update_outreach_preparation(self, prep: OutreachPreparation) -> None:
        """Update an existing outreach preparation record (e.g. after manual editing or status change)."""
        d = prep.to_db_dict()
        pid = prep.platform_id
        d.pop("id", None)
        set_clause = ", ".join([f"{k} = :{k}" for k in d.keys()])
        sql = f"UPDATE outreach_preparations SET {set_clause} WHERE platform_id = :platform_id"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, d)

    # -------------------------------------------------------------------------
    # Delivery Events Operations (Safe Seed Testing)
    # -------------------------------------------------------------------------
    def log_delivery_event(self, event: DeliveryEvent) -> DeliveryEvent:
        """Log a delivery simulation or interaction event."""
        d = event.to_db_dict()
        d.pop("id", None)
        cols = list(d.keys())
        placeholders = [f":{c}" for c in cols]
        sql = f"INSERT INTO delivery_events ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, d)
            event.id = cursor.lastrowid
        return event

    def get_delivery_events(
        self,
        lead_id: Optional[int] = None,
        platform_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[DeliveryEvent]:
        """Retrieve simulated delivery event history."""
        query = "SELECT * FROM delivery_events WHERE 1=1"
        params: List[Any] = []
        if lead_id is not None:
            query += " AND lead_id = ?"
            params.append(lead_id)
        if platform_id is not None:
            query += " AND platform_id = ?"
            params.append(platform_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [DeliveryEvent.from_db_row(dict(r)) for r in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Suppression List Operations (Opt-Outs)
    # -------------------------------------------------------------------------
    def is_contact_suppressed(self, contact_value: Optional[str], channel: Optional[str] = None) -> bool:
        """Check if contact value is present in global suppression list."""
        if not contact_value or not isinstance(contact_value, str):
            return False
        clean = contact_value.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if channel:
                cursor.execute(
                    "SELECT 1 FROM suppression_list WHERE contact_value = ? AND (LOWER(channel) = ? OR LOWER(channel) = 'all') LIMIT 1",
                    (clean, channel.strip().lower()),
                )
            else:
                cursor.execute("SELECT 1 FROM suppression_list WHERE contact_value = ? LIMIT 1", (clean,))
            return cursor.fetchone() is not None

    def add_to_suppression_list(
        self,
        contact_value_or_record: Any,
        channel: Optional[str] = None,
        reason: str = "Opt-out requested",
    ) -> SuppressionRecord:
        """Add a contact value or SuppressionRecord to the global suppression list to halt future outreach."""
        if isinstance(contact_value_or_record, SuppressionRecord):
            rec = contact_value_or_record
            clean = rec.contact_value.strip().lower()
            rec.contact_value = clean
        else:
            clean = str(contact_value_or_record).strip().lower()
            rec = SuppressionRecord(
                contact_value=clean,
                channel=channel or "all",
                reason=reason,
            )
        d = rec.to_db_dict()
        d.pop("id", None)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO suppression_list (contact_value, channel, reason, opted_out_at) VALUES (:contact_value, :channel, :reason, :opted_out_at)",
                d,
            )
            rec.id = cursor.lastrowid
        logger.info(f"Contact '{clean}' added to suppression list ({rec.reason}).")
        return rec

    def get_suppression_list(self) -> List[SuppressionRecord]:
        """Retrieve all suppressed contacts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM suppression_list ORDER BY id DESC")
            return [SuppressionRecord.from_db_row(dict(r)) for r in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Campaign Outreach Records (Safe Simulator)
    # -------------------------------------------------------------------------
    def save_campaign_outreach_record(self, record: CampaignOutreachRecord) -> CampaignOutreachRecord:
        """Insert or update a unique campaign outreach record per lead and campaign."""
        d = record.to_db_dict()
        record_id = d.pop("id", None)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if record_id:
                d["id"] = record_id
                cols = [f"{c} = :{c}" for c in d.keys() if c != "id"]
                cursor.execute(f"UPDATE campaign_outreach_records SET {', '.join(cols)} WHERE id = :id", d)
                record.id = record_id
            else:
                cursor.execute(
                    """
                    INSERT INTO campaign_outreach_records (
                        lead_id, campaign_id, platform_id, creator_name, channel,
                        contact_endpoint, state, tracking_token, opaque_id, test_account_id,
                        notes, created_at, updated_at, is_synthetic
                    ) VALUES (
                        :lead_id, :campaign_id, :platform_id, :creator_name, :channel,
                        :contact_endpoint, :state, :tracking_token, :opaque_id, :test_account_id,
                        :notes, :created_at, :updated_at, :is_synthetic
                    )
                    ON CONFLICT(lead_id, campaign_id) DO UPDATE SET
                        creator_name = excluded.creator_name,
                        channel = excluded.channel,
                        contact_endpoint = excluded.contact_endpoint,
                        state = excluded.state,
                        tracking_token = excluded.tracking_token,
                        opaque_id = excluded.opaque_id,
                        test_account_id = excluded.test_account_id,
                        notes = excluded.notes,
                        updated_at = excluded.updated_at,
                        is_synthetic = excluded.is_synthetic
                    """,
                    d,
                )
                if cursor.lastrowid:
                    record.id = cursor.lastrowid
                else:
                    existing = self.get_campaign_outreach_record(record.lead_id, record.campaign_id)
                    if existing:
                        record.id = existing.id
        return record

    def get_campaign_outreach_record(self, lead_id: int, campaign_id: str) -> Optional[CampaignOutreachRecord]:
        """Fetch unique outreach record for a lead and campaign."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM campaign_outreach_records WHERE lead_id = ? AND campaign_id = ? LIMIT 1",
                (lead_id, campaign_id),
            )
            row = cursor.fetchone()
            if row:
                return CampaignOutreachRecord.from_db_row(dict(row))
        return None

    def get_campaign_outreach_record_by_opaque_id(self, opaque_id: str) -> Optional[CampaignOutreachRecord]:
        """Fetch outreach record by opaque tracking token."""
        if not opaque_id:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM campaign_outreach_records WHERE opaque_id = ? LIMIT 1",
                (opaque_id.strip(),),
            )
            row = cursor.fetchone()
            if row:
                return CampaignOutreachRecord.from_db_row(dict(row))
        return None

    def get_campaign_outreach_records(
        self,
        campaign_id: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[CampaignOutreachRecord]:
        """List outreach records optionally filtered by campaign or state."""
        query = "SELECT * FROM campaign_outreach_records WHERE 1=1"
        params: List[Any] = []
        if campaign_id:
            query += " AND campaign_id = ?"
            params.append(campaign_id)
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY id ASC"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [CampaignOutreachRecord.from_db_row(dict(r)) for r in cursor.fetchall()]

    def update_campaign_outreach_record(self, record: CampaignOutreachRecord) -> CampaignOutreachRecord:
        """Update an existing campaign outreach record."""
        return self.save_campaign_outreach_record(record)

    def get_delivery_event_by_idempotent_key(self, idempotent_key: str) -> Optional[DeliveryEvent]:
        """Fetch delivery event by idempotent key if it exists."""
        if not idempotent_key:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM delivery_events WHERE idempotent_key = ? LIMIT 1",
                (idempotent_key,),
            )
            row = cursor.fetchone()
            if row:
                return DeliveryEvent.from_db_row(dict(row))
        return None

    def log_idempotent_event(self, event: DeliveryEvent) -> Tuple[DeliveryEvent, bool]:
        """
        Log an event ensuring idempotency.
        If an event with the same non-empty idempotent_key already exists:
        returns (existing_event, False) without duplicate database insertion.
        Otherwise inserts the event and returns (new_event, True).
        """
        if event.idempotent_key:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM delivery_events WHERE idempotent_key = ? LIMIT 1",
                    (event.idempotent_key,),
                )
                row = cursor.fetchone()
                if row:
                    logger.debug(f"Idempotent event suppressed: key {event.idempotent_key} already logged.")
                    return DeliveryEvent.from_db_row(dict(row)), False

        # Not duplicate or no key provided, insert new event
        logged = self.log_delivery_event(event)
        return logged, True


# Module-level default database singleton helper
_DEFAULT_DB: Optional[Database] = None


def get_default_database() -> Database:
    """Retrieve or create default database instance."""
    global _DEFAULT_DB
    if _DEFAULT_DB is None:
        _DEFAULT_DB = Database()
    return _DEFAULT_DB


def get_outreach_preparations(
    is_synthetic: Optional[bool] = None,
    priority: Optional[str] = None,
    channel_suitability: Optional[str] = None,
    db: Optional[Database] = None,
) -> List[OutreachPreparation]:
    database = db or get_default_database()
    return database.get_outreach_preparations(is_synthetic, priority, channel_suitability)


def get_outreach_preparation_by_platform_id(
    platform_id: str,
    db: Optional[Database] = None,
) -> Optional[OutreachPreparation]:
    database = db or get_default_database()
    return database.get_outreach_preparation_by_platform_id(platform_id)


def update_outreach_preparation(
    prep: OutreachPreparation,
    db: Optional[Database] = None,
) -> None:
    database = db or get_default_database()
    database.update_outreach_preparation(prep)


def save_outreach_preparations(
    preps: List[OutreachPreparation],
    db: Optional[Database] = None,
) -> None:
    database = db or get_default_database()
    database.save_outreach_preparations(preps)


def log_delivery_event(
    event: DeliveryEvent,
    db: Optional[Database] = None,
) -> DeliveryEvent:
    database = db or get_default_database()
    return database.log_delivery_event(event)


def log_idempotent_event(
    event: DeliveryEvent,
    db: Optional[Database] = None,
) -> Tuple[DeliveryEvent, bool]:
    database = db or get_default_database()
    return database.log_idempotent_event(event)


def get_delivery_event_by_idempotent_key(
    idempotent_key: str,
    db: Optional[Database] = None,
) -> Optional[DeliveryEvent]:
    database = db or get_default_database()
    return database.get_delivery_event_by_idempotent_key(idempotent_key)


def get_delivery_events(
    lead_id: Optional[int] = None,
    platform_id: Optional[str] = None,
    limit: int = 100,
    db: Optional[Database] = None,
) -> List[DeliveryEvent]:
    database = db or get_default_database()
    return database.get_delivery_events(lead_id, platform_id, limit)


def is_contact_suppressed(
    contact_value: Optional[str],
    channel: Optional[str] = None,
    db: Optional[Database] = None,
) -> bool:
    database = db or get_default_database()
    return database.is_contact_suppressed(contact_value, channel)


def add_to_suppression_list(
    contact_value_or_record: Any,
    channel: Optional[str] = None,
    reason: str = "Opt-out requested",
    db: Optional[Database] = None,
) -> SuppressionRecord:
    database = db or get_default_database()
    return database.add_to_suppression_list(contact_value_or_record, channel, reason)


def get_suppression_list(db: Optional[Database] = None) -> List[SuppressionRecord]:
    database = db or get_default_database()
    return database.get_suppression_list()


def save_campaign_outreach_record(
    record: CampaignOutreachRecord,
    db: Optional[Database] = None,
) -> CampaignOutreachRecord:
    database = db or get_default_database()
    return database.save_campaign_outreach_record(record)


def get_campaign_outreach_record(
    lead_id: int,
    campaign_id: str,
    db: Optional[Database] = None,
) -> Optional[CampaignOutreachRecord]:
    database = db or get_default_database()
    return database.get_campaign_outreach_record(lead_id, campaign_id)


def get_campaign_outreach_record_by_opaque_id(
    opaque_id: str,
    db: Optional[Database] = None,
) -> Optional[CampaignOutreachRecord]:
    database = db or get_default_database()
    return database.get_campaign_outreach_record_by_opaque_id(opaque_id)


def get_campaign_outreach_records(
    campaign_id: Optional[str] = None,
    state: Optional[str] = None,
    db: Optional[Database] = None,
) -> List[CampaignOutreachRecord]:
    database = db or get_default_database()
    return database.get_campaign_outreach_records(campaign_id, state)


def update_campaign_outreach_record(
    record: CampaignOutreachRecord,
    db: Optional[Database] = None,
) -> CampaignOutreachRecord:
    database = db or get_default_database()
    return database.update_campaign_outreach_record(record)


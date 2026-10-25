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
from src.models import Lead, QualificationStatus, VerificationLog

logger = get_logger("database")


class Database:
    """SQLite repository managing leads and verification audit logs."""

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
                first_discovered_at TEXT NOT NULL,
                last_checked_at TEXT,
                last_run_id TEXT,
                is_synthetic INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Migration for existing databases
            try:
                cursor.execute("ALTER TABLE leads ADD COLUMN is_synthetic INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass

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

            # Indexes for fast deduplication and filtering
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_platform_key ON leads (platform, platform_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_profile_url ON leads (official_profile_url);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (qualification_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads (priority);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_synthetic ON leads (is_synthetic);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vlogs_lead_id ON verification_logs (lead_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vlogs_run_id ON verification_logs (run_id);")

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

            # Segment counts
            cursor.execute("SELECT creator_type, COUNT(*) FROM leads GROUP BY creator_type")
            segment_counts = {row[0] or "Unknown": row[1] for row in cursor.fetchall()}

            return {
                "total_candidates": total,
                "discovered": discovered,
                "needs_review": needs_review,
                "qualified": qualified,
                "disqualified": disqualified,
                "synthetic_candidates": synthetic_count,
                "real_candidates": real_count,
                "real_qualified": real_qualified,
                "priority_breakdown": priority_counts,
                "country_breakdown": country_counts,
                "segment_breakdown": segment_counts,
            }

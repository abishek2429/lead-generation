"""
Local HTTP test server and endpoint harness for IncuBrix Outreach Simulator.

SAFETY GUARANTEE:
- Simulation and local test workflow only.
- Never sends messages to real creators or external platforms.
- Listens locally on 127.0.0.1.
- All events and responses are strictly marked as SIMULATED TEST DATA.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple

from src.database import Database, get_default_database
from src.logging_config import get_logger
from src.models import (
    CampaignOutreachRecord,
    InvalidStateTransitionError,
    OutreachState,
)
from src.verification.seed_testing import (
    OutreachSimulator,
    UnauthorizedEndpointError,
)

logger = get_logger("simulator_server")


class SimulatorRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for local test harness endpoints."""

    db: Optional[Database] = None

    def _send_json(self, status_code: int, data: Dict[str, Any]) -> None:
        """Send a formatted JSON response with CORS and safety headers."""
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Simulation-Mode", "TEST_DATA_ONLY")
        self.end_headers()
        self.wfile.write(response_bytes)

    def _send_html(self, status_code: int, html: str) -> None:
        """Send HTML response."""
        response_bytes = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("X-Simulation-Mode", "TEST_DATA_ONLY")
        self.end_headers()
        self.wfile.write(response_bytes)

    def _read_json_body(self) -> Dict[str, Any]:
        """Read and parse JSON from request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON body: {exc}")

    def do_GET(self) -> None:
        """Handle GET requests (health checks, stats, tracking redirects)."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/health"):
            self._send_json(200, {
                "status": "healthy",
                "service": "IncuBrix Outreach Simulator Local Endpoint",
                "mode": "SIMULATION_TEST_ONLY",
                "safety_notice": "No real creators are contacted by this test harness.",
            })
            return

        # Tracking link click endpoint: GET /track?id=<opaque_id> or GET /?trk=<opaque_id>
        if path == "/track" or "trk" in query:
            opaque_id = query.get("id", [None])[0] or query.get("trk", [None])[0]
            if not opaque_id:
                self._send_json(400, {"error": "Missing opaque tracking id parameter ('id' or 'trk')."})
                return

            test_account = query.get("test_account_id", ["candidate_test_account"])[0]
            idem_key = query.get("idempotent_key", [None])[0]

            try:
                ev, created = OutreachSimulator.simulate_interaction(
                    opaque_id=opaque_id,
                    event_type="CLICK",
                    test_account_id=test_account,
                    idempotent_key=idem_key,
                    db=self.db,
                )
                html = f"""<!DOCTYPE html>
<html>
<head><title>IncuBrix Simulator Tracking Test</title></head>
<body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; text-align: center;">
  <div style="background: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border-radius: 8px; border: 1px solid #334155;">
    <h2 style="color: #38bdf8;">SIMULATED CLICK RECORDED</h2>
    <p><strong>Tracking Token (Opaque):</strong> {opaque_id}</p>
    <p><strong>Status:</strong> {ev.status} ({'New Event' if created else 'Duplicate Suppressed via Idempotency'})</p>
    <p><strong>Timestamp (UTC):</strong> {ev.timestamp}</p>
    <p style="color: #94a3b8; font-size: 13px;">This event was recorded in the local test SQLite database.</p>
  </div>
</body>
</html>"""
                self._send_html(200, html)
            except Exception as exc:
                logger.error(f"Error handling tracking click: {exc}")
                self._send_json(500, {"error": str(exc)})
            return

        # Simulation stats endpoint: GET /api/simulate/stats?campaign_id=<camp>
        if path == "/api/simulate/stats":
            campaign_id = query.get("campaign_id", [None])[0]
            stats = OutreachSimulator.get_campaign_summary(campaign_id=campaign_id, db=self.db)
            self._send_json(200, stats)
            return

        self._send_json(404, {"error": f"Endpoint not found: {path}"})

    def do_POST(self) -> None:
        """Handle POST requests for simulation events."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        # 1. Simulate Send Endpoint: POST /api/simulate/send
        if path == "/api/simulate/send":
            lead_id = body.get("lead_id")
            campaign_id = body.get("campaign_id", "default_test_campaign")
            test_account_id = body.get("test_account_id", "candidate_test_account")
            idempotent_key = body.get("idempotent_key")

            if lead_id is None:
                self._send_json(400, {"error": "Missing required field 'lead_id'."})
                return

            database = self.db or get_default_database()
            record = database.get_campaign_outreach_record(int(lead_id), campaign_id)
            if not record:
                self._send_json(404, {
                    "error": f"No outreach record found for lead_id {lead_id} and campaign '{campaign_id}'.",
                })
                return

            try:
                ev, created = OutreachSimulator.simulate_send(
                    record=record,
                    test_account_id=test_account_id,
                    idempotent_key=idempotent_key,
                    db=self.db,
                )
                self._send_json(200, {
                    "event_id": ev.id,
                    "event_type": ev.event_type,
                    "status": ev.status,
                    "created": created,
                    "is_duplicate": not created,
                    "opaque_id": ev.opaque_id,
                    "timestamp": ev.timestamp,
                    "record_state": record.state,
                    "is_simulated": True,
                    "label": "TEST DATA ONLY",
                })
            except UnauthorizedEndpointError as exc:
                self._send_json(403, {"error": str(exc), "safety_violation": True})
            except InvalidStateTransitionError as exc:
                self._send_json(409, {"error": str(exc), "invalid_transition": True})
            except Exception as exc:
                logger.error(f"Error in /api/simulate/send: {exc}")
                self._send_json(500, {"error": str(exc)})
            return

        # 2. Simulate Click Endpoint: POST /api/simulate/click
        if path == "/api/simulate/click":
            opaque_id = body.get("opaque_id")
            if not opaque_id:
                self._send_json(400, {"error": "Missing required field 'opaque_id'."})
                return

            test_account_id = body.get("test_account_id", "candidate_test_account")
            idempotent_key = body.get("idempotent_key")

            try:
                ev, created = OutreachSimulator.simulate_interaction(
                    opaque_id=opaque_id,
                    event_type="CLICK",
                    test_account_id=test_account_id,
                    idempotent_key=idempotent_key,
                    db=self.db,
                )
                self._send_json(200, {
                    "event_id": ev.id,
                    "event_type": ev.event_type,
                    "status": ev.status,
                    "created": created,
                    "is_duplicate": not created,
                    "timestamp": ev.timestamp,
                    "is_simulated": True,
                })
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        # 3. Simulate Reply Endpoint: POST /api/simulate/reply
        if path == "/api/simulate/reply":
            opaque_id = body.get("opaque_id")
            if not opaque_id:
                self._send_json(400, {"error": "Missing required field 'opaque_id'."})
                return

            reply_text = body.get("reply_text", "Interested in your creator workflow tooling.")
            test_account_id = body.get("test_account_id", "candidate_test_account")
            idempotent_key = body.get("idempotent_key")

            try:
                ev, created = OutreachSimulator.simulate_interaction(
                    opaque_id=opaque_id,
                    event_type="REPLY",
                    test_account_id=test_account_id,
                    reply_text=reply_text,
                    idempotent_key=idempotent_key,
                    db=self.db,
                )
                self._send_json(200, {
                    "event_id": ev.id,
                    "event_type": ev.event_type,
                    "status": ev.status,
                    "created": created,
                    "is_duplicate": not created,
                    "timestamp": ev.timestamp,
                    "is_simulated": True,
                })
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        # 4. Simulate Opt-Out Endpoint: POST /api/simulate/opt-out
        if path == "/api/simulate/opt-out":
            contact = body.get("contact")
            if not contact:
                self._send_json(400, {"error": "Missing required field 'contact'."})
                return

            channel = body.get("channel", "email")
            campaign_id = body.get("campaign_id", "default_test_campaign")
            reason = body.get("reason", "Creator requested opt-out (simulated)")
            test_account_id = body.get("test_account_id", "candidate_test_account")
            idempotent_key = body.get("idempotent_key")

            try:
                supp, ev, created = OutreachSimulator.simulate_opt_out(
                    contact_or_record=contact,
                    channel=channel,
                    campaign_id=campaign_id,
                    test_account_id=test_account_id,
                    reason=reason,
                    idempotent_key=idempotent_key,
                    db=self.db,
                )
                self._send_json(200, {
                    "contact": supp.contact_value,
                    "suppressed": True,
                    "reason": supp.reason,
                    "created": created,
                    "is_duplicate": not created,
                    "timestamp": ev.timestamp,
                    "is_simulated": True,
                })
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        self._send_json(404, {"error": f"POST endpoint not found: {path}"})


def run_simulator_server(
    host: str = "127.0.0.1",
    port: int = 8502,
    db: Optional[Database] = None,
) -> None:
    """Run the local simulator endpoint server."""
    SimulatorRequestHandler.db = db
    server_address = (host, port)
    httpd = HTTPServer(server_address, SimulatorRequestHandler)
    print(f"=================================================================")
    print(f"  IncuBrix Outreach Simulator Test Server running at:")
    print(f"  http://{host}:{port}/")
    print(f"  SAFETY: Local test harness only. Zero external contact.")
    print(f"=================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping simulator server.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IncuBrix Outreach Simulator Test Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8502, help="Port (default 8502)")
    args = parser.parse_args()
    run_simulator_server(host=args.host, port=args.port)

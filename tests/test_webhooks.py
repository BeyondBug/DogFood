"""A committed audit action produces an authenticated, retryable webhook."""

import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from src.core import audit
from src.db import connect, initialize, utc_now
from src.webhooks import deliver_due


class Receiver(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.received.append((body, self.headers["X-BeyondBug-Signature"]))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


class WebhookTests(unittest.TestCase):
    def test_audit_outbox_delivers_signed_payload(self):
        Receiver.received = []
        server = HTTPServer(("127.0.0.1", 0), Receiver)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3")}):
                    initialize()
                    with closing(connect()) as db:
                        db.execute("INSERT INTO users(id,email,name,created_at) VALUES('org','org@example.org','Organizer',?)",
                                   (utc_now(),))
                        db.execute("INSERT INTO events(id,name,submissions_close,created_at) VALUES('event','Event',?,?)",
                                   (utc_now(), utc_now()))
                        db.execute("INSERT INTO webhook_subscriptions(id,event_id,url,secret_hex,created_by,created_at)"
                                   " VALUES('hook','event',?,?, 'org', ?)",
                                   (f"http://127.0.0.1:{server.server_port}/hook", "ab" * 32, utc_now()))
                        audit(db, "event", "org", "project.submitted", "project", "project-1", {"status": "submitted"})
                        db.commit()
                    self.assertEqual(deliver_due(), 1)
                    self.assertEqual(deliver_due(), 0)
                    self.assertEqual(len(Receiver.received), 1)
                    body, signature_header = Receiver.received[0]
                    self.assertEqual(json.loads(body)["action"], "project.submitted")
                    self.assertEqual(signature_header,
                                     "sha256=" + hmac.new(bytes.fromhex("ab" * 32), body, hashlib.sha256).hexdigest())
                    with closing(connect()) as db:
                        row = db.execute("SELECT status,attempts FROM webhook_deliveries").fetchone()
                        self.assertEqual((row["status"], row["attempts"]), ("delivered", 1))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

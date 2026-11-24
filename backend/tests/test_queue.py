import unittest
from unittest.mock import patch

from sqlalchemy import select

from researchhub.auth import hash_password, require_project, verify_password
from researchhub.db import connect
from researchhub.models import events, jobs, memberships, metadata, organizations, projects, users
from researchhub.queue import IdempotencyConflict, cancel, claim, finish, heartbeat, recover, submit


class QueueContract(unittest.TestCase):
    def setUp(self):
        self.engine = connect("sqlite://")
        metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(organizations.insert().values(id="org", name="Synthetic Lab"))
            connection.execute(projects.insert().values(id="project", organization_id="org", name="A"))
            connection.execute(projects.insert().values(id="other", organization_id="org", name="B"))
            connection.execute(users.insert().values(id="user", username="researcher", password_hash="fixture"))
            connection.execute(memberships.insert().values(project_id="project", user_id="user", role="researcher"))

    def test_submission_is_idempotent_and_payload_bound(self):
        with self.engine.begin() as conn:
            first = submit(conn, "project", "key", "test", {"a": 2})
            second = submit(conn, "project", "key", "test", {"a": 2})
            self.assertEqual(first["id"], second["id"])
            with self.assertRaises(IdempotencyConflict):
                submit(conn, "project", "key", "test", {"a": 3})
            self.assertEqual(len(conn.execute(select(events)).all()), 1)

    def test_expired_worker_cannot_overwrite_result(self):
        with patch("researchhub.queue.now_ms", return_value=1_000), self.engine.begin() as conn:
            job = submit(conn, "project", "key", "test", {}, timeout_ms=100)
            first = claim(conn, "worker-1")
            self.assertIsNone(claim(conn, "worker-2"))
        with patch("researchhub.queue.now_ms", return_value=1_100), self.engine.begin() as conn:
            self.assertEqual(recover(conn), 1)
            self.assertEqual(heartbeat(conn, job["id"], first["token"]), "LOST")
        with patch("researchhub.queue.now_ms", return_value=1_350), self.engine.begin() as conn:
            second = claim(conn, "worker-2")
            self.assertEqual(second["attempt"], 2)
            self.assertTrue(finish(conn, job["id"], second["token"], result={"ok": 2}))
            self.assertFalse(finish(conn, job["id"], first["token"], result={"ok": 1}))
            self.assertEqual(conn.execute(select(jobs.c.result)).scalar_one(), {"ok": 2})

    def test_cancellation_wins_when_committed_before_finish(self):
        with self.engine.begin() as conn:
            job = submit(conn, "project", "key", "test", {})
            lease = claim(conn, "worker")
            with self.assertRaises(LookupError):
                cancel(conn, "other", job["id"])
            self.assertEqual(cancel(conn, "project", job["id"]), "CANCEL_REQUESTED")
            self.assertTrue(finish(conn, job["id"], lease["token"], result={"ok": True}))
            state, result = conn.execute(select(jobs.c.state, jobs.c.result)).one()
            self.assertEqual((state, result), ("CANCELLED", None))

    def test_retry_exhaustion_is_recorded(self):
        with self.engine.begin() as conn:
            job = submit(conn, "project", "key", "test", {}, max_attempts=1)
            lease = claim(conn, "worker")
            self.assertTrue(finish(conn, job["id"], lease["token"], error="transient", retryable=True))
            self.assertIsNone(claim(conn, "worker"))
            self.assertEqual(conn.execute(select(jobs.c.state)).scalar_one(), "FAILED")
            reasons = conn.execute(select(events.c.reason).order_by(events.c.id)).scalars().all()
            self.assertEqual(reasons, ["submitted", "claimed", "transient", "dead_letter"])

    def test_project_access_is_role_scoped(self):
        with self.engine.begin() as conn:
            require_project(conn, "user", "project", {"researcher"})
            with self.assertRaises(PermissionError):
                require_project(conn, "user", "other", {"researcher"})
            with self.assertRaises(PermissionError):
                require_project(conn, "user", "project", {"finance"})

    def test_passwords_are_salted_and_verified(self):
        password = "synthetic-only-phrase"
        first = hash_password(password)
        self.assertNotEqual(first, hash_password(password))
        self.assertTrue(verify_password(password, first))
        self.assertFalse(verify_password("different-password", first))


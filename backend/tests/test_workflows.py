import unittest

from sqlalchemy import select

from researchhub.db import connect
from researchhub.models import metadata, organizations, projects, workflow_runs
from researchhub.plugins import summarize
from researchhub.queue import claim, finish
from researchhub.workflows import reconcile, start


def node(*deps):
    return {"depends_on": list(deps), "plugin": "summary@1", "parameters": {"observations": [1, 2, 3]}}


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.engine = connect("sqlite://")
        metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(organizations.insert().values(id="org", name="Lab"))
            conn.execute(projects.insert().values(id="project", organization_id="org", name="Research"))

    def test_dependency_and_parallel_roots(self):
        with self.engine.begin() as conn:
            start(conn, "project", {"first": node(), "second": node(), "report": node("first", "second")})
            reconcile(conn)
            one, two = claim(conn, "worker-1"), claim(conn, "worker-2")
            self.assertNotEqual(one["id"], two["id"])
            self.assertIsNone(claim(conn, "worker-3"))
            finish(conn, one["id"], one["token"], result={})
            reconcile(conn)
            self.assertIsNone(claim(conn, "worker-3"))
        with self.engine.begin() as conn:
            finish(conn, two["id"], two["token"], result={})
            reconcile(conn)
            report = claim(conn, "worker-3")
            finish(conn, report["id"], report["token"], result={})
            reconcile(conn)
            self.assertEqual(conn.execute(select(workflow_runs.c.state)).scalar_one(), "SUCCEEDED")

    def test_failed_parent_blocks_descendants(self):
        with self.engine.begin() as conn:
            start(conn, "project", {"parent": node(), "child": node("parent"), "grandchild": node("child")})
            reconcile(conn)
            job = claim(conn, "worker-1")
            finish(conn, job["id"], job["token"], error="fixture")
            reconcile(conn)
            state, nodes = conn.execute(select(workflow_runs.c.state, workflow_runs.c.nodes)).one()
            self.assertEqual(state, "FAILED")
            self.assertEqual(nodes["grandchild"]["state"], "BLOCKED")
            self.assertIsNone(claim(conn, "worker-2"))

    def test_cycle_rejected(self):
        with self.engine.begin() as conn:
            with self.assertRaisesRegex(ValueError, "cycle"):
                start(conn, "project", {"a": node("b"), "b": node("a")})

    def test_summary_known_result(self):
        result = summarize({"observations": [1, 2, 3]})
        self.assertEqual(result, {"count": 3, "min": 1, "max": 3, "mean": "2", "sample_variance": "1"})
        with self.assertRaises(ValueError):
            summarize({"observations": [True, 1]})


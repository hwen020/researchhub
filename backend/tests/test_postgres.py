import os
import hashlib
import base64
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from researchhub.db import connect
from researchhub.finance import decide, request_funds
from researchhub.auth import hash_password
from researchhub.models import api_rate_limits, budgets, events, jobs, memberships, metadata, organizations, projects, system_audit, users
from researchhub.queue import cancel, claim, finish, submit
from researchhub.resource_policy import AGING_MS, QueueFull, project_usage
from researchhub.models import workflow_runs
from researchhub.provenance import manifest
from researchhub.workflow_versions import create_schedule, publish, start_version, trigger_due
from researchhub.workflows import cancel_run, get_run, reconcile, rerun, start

URL = os.environ.get("RESEARCHHUB_TEST_DATABASE")


@unittest.skipUnless(URL, "Requires a disposable PostgreSQL test database")
class PostgresIntegration(unittest.TestCase):
    def setUp(self):
        self.schema = "rh_" + uuid4().hex
        default = connect(URL)
        self.addCleanup(default.dispose)
        with default.begin() as conn:
            conn.execute(text("CREATE SCHEMA " + self.schema))

        def cleanup_schema():
            with default.begin() as conn:
                conn.execute(text("DROP SCHEMA " + self.schema + " CASCADE"))

        self.addCleanup(cleanup_schema)
        self.url = make_url(URL).update_query_dict({"options": "-csearch_path=" + self.schema})
        self.engine = connect(self.url)
        self.addCleanup(self.engine.dispose)
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(organizations.insert().values(id="org", name="Lab"))
            conn.execute(projects.insert().values(id="project", organization_id="org", name="Research"))
            conn.execute(budgets.insert().values(project_id="project", limit=100))
            conn.execute(users.insert(), [
                {"id": user, "username": user, "password_hash": "fixture",
                 "platform_admin": 0, "must_change_password": 0}
                for user in ("requester", "reviewer")
            ])

    def test_competing_claims_and_repeated_submissions(self):
        def enqueue(_):
            with self.engine.begin() as conn:
                return submit(conn, "project", "shared", "summary@1", {"observations": [1, 2]})["id"]

        def reserve(worker):
            with self.engine.begin() as conn:
                return claim(conn, str(worker))

        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(len(set(pool.map(enqueue, range(12)))), 1)
            leases = [job for job in pool.map(reserve, range(12)) if job]
        self.assertEqual(len(leases), 1)

    def test_scheduler_rotates_three_projects_and_reserves_concurrent_capacity(self):
        with self.engine.begin() as conn:
            for project in ("second", "third"):
                conn.execute(projects.insert().values(
                    id=project, organization_id="org", name=project, max_concurrent=1,
                ))
            conn.execute(projects.update().where(projects.c.id == "project").values(
                max_concurrent=1, quota_cpu=2,
            ))
            for project in ("project", "second", "third"):
                for index in range(4):
                    submit(conn, project, str(index), "summary@1", {}, cpu_units=2)

        def reserve(index):
            with self.engine.begin() as conn:
                return claim(conn, "worker-" + str(index))

        with ThreadPoolExecutor(max_workers=8) as pool:
            first_round = [job for job in pool.map(reserve, range(8)) if job]
        self.assertCountEqual([job["project_id"] for job in first_round], ["project", "second", "third"])
        with self.engine.begin() as conn:
            for job in first_round:
                self.assertEqual(project_usage(conn, job["project_id"])["cpu_units"], 2)
                cancel(conn, job["project_id"], job["id"])
                self.assertEqual(project_usage(conn, job["project_id"])["active"], 1)
                self.assertTrue(finish(conn, job["id"], job["token"]))
                self.assertEqual(project_usage(conn, job["project_id"])["active"], 0)
        self.assertCountEqual([reserve(index)["project_id"] for index in range(3)],
                              ["project", "second", "third"])

    def test_scheduler_aging_and_capability_match(self):
        with self.engine.begin() as conn:
            old = submit(conn, "project", "old", "summary@1", {})
            urgent = submit(conn, "project", "urgent", "summary@1", {}, priority=10)
            genomic = submit(conn, "project", "genomic", "age-association@1", {}, memory_units=4)
            worker = claim(conn, "general", capabilities=("GENERAL",))
            self.assertEqual(worker["id"], urgent["id"])
            submit(conn, "project", "new-urgent", "summary@1", {}, priority=10)
            conn.execute(jobs.update().where(jobs.c.id == old["id"]).values(
                created_at=old["created_at"] - 10 * AGING_MS,
            ))
            self.assertEqual(claim(conn, "general", capabilities=("GENERAL",))["id"], old["id"])
            self.assertIsNone(claim(conn, "small", capabilities=("GENOMICS",), memory_units=3))
            self.assertEqual(claim(conn, "genomics", capabilities=("GENOMICS",), memory_units=4)["id"],
                             genomic["id"])

    def test_scheduler_backpressure_is_serial_and_preserves_idempotency(self):
        with self.engine.begin() as conn:
            conn.execute(projects.update().values(max_queued=3))

        def enqueue(index):
            try:
                with self.engine.begin() as conn:
                    return submit(conn, "project", str(index), "summary@1", {})["id"]
            except QueueFull:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted = list(pool.map(enqueue, range(16)))
        self.assertEqual(len([job for job in admitted if job]), 3)
        index = next(i for i, job in enumerate(admitted) if job)
        self.assertEqual(enqueue(index), admitted[index])
        with self.engine.begin() as conn:
            lease = claim(conn, "worker")
            with self.assertRaises(QueueFull):
                submit(conn, "project", "extra", "summary@1", {})
            self.assertTrue(finish(conn, lease["id"], lease["token"], result={}))
            self.assertIsNotNone(submit(conn, "project", "extra", "summary@1", {}))

    def test_demo_guest_reads_only_fixed_genomics_workflow(self):
        from fastapi.testclient import TestClient
        from researchhub import api, demo_fixture

        password = "synthetic-demo-fixture-only"
        with tempfile.TemporaryDirectory() as storage, patch.dict(os.environ, {
            "DATABASE_URL": self.url.render_as_string(hide_password=False),
            "RESEARCHHUB_STORAGE": storage,
            "RESEARCHHUB_DEMO_MODE": "1",
            "RESEARCHHUB_DEMO_PASSWORD": password,
        }), patch.object(api, "engine", self.engine):
            with self.engine.begin() as conn:
                conn.execute(users.insert().values(
                    id="legacy-admin", username="fixture-admin",
                    password_hash=hash_password(password), platform_admin=1,
                ))
            demo_fixture.seed()
            demo_fixture.seed()
            env = os.environ.copy()
            processes = []
            try:
                for program in ("scheduler", "worker", "worker"):
                    processes.append(subprocess.Popen(
                        [sys.executable, "-m", "researchhub." + program], env=env,
                        stdout=subprocess.DEVNULL,
                    ))
                guest = ("demo-guest", password)
                project = "/projects/" + demo_fixture.PROJECT_ID
                with TestClient(api.app) as client:
                    self.assertEqual(client.get("/projects", auth=("fixture-admin", password)).status_code, 401)
                    self.assertEqual(len(client.get("/projects", auth=guest).json()), 1)
                    self.assertEqual(client.post(project + "/jobs", auth=guest,
                                                 headers={"Idempotency-Key": "guest"},
                                                 json={"plugin": "summary@1", "parameters": {}}).status_code, 403)
                    self.assertEqual(client.post(project + "/datasets", auth=guest,
                                                 json={"name": "private"}).status_code, 403)
                    self.assertEqual(client.get("/admin/workers", auth=guest).status_code, 403)
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        runs = client.get(project + "/workflows", auth=guest).json()
                        if runs[0]["state"] != "RUNNING":
                            break
                        time.sleep(0.2)
                    self.assertEqual(runs[0]["state"], "SUCCEEDED")
                    job_id = runs[0]["nodes"]["report"]["job_id"]
                    for kind in ("manifest", "json", "csv"):
                        response = client.get(f"{project}/jobs/{job_id}/download/{kind}", auth=guest)
                        self.assertEqual(response.status_code, 200)
                        if kind == "manifest":
                            self.assertEqual(response.json()["dataset"]["version"], 1)
                            self.assertEqual(response.json()["dataset"]["sha256"], demo_fixture.checksum(demo_fixture.DATA))
                        if kind == "json":
                            self.assertEqual(len(response.json()["associations"]), 2)
            finally:
                for process in processes:
                    process.terminate()
                for process in processes:
                    process.wait(timeout=10)

    def test_workflow_versions_conditions_and_partial_rerun(self):
        def node(*parents, when=None):
            return {"depends_on": list(parents), "when": when, "plugin": "summary@1",
                    "parameters": {"observations": {"$parameter": "values"}}}

        template = {
            "root": node(),
            "branch": node("root", when={"mode": "result_equals", "node": "root", "field": "count", "value": 3}),
            "skipped": node("root", when={"mode": "failure"}),
            "final": node("branch", "skipped", when={"mode": "always"}),
        }
        with self.engine.begin() as conn:
            first = publish(conn, "project", template, {"values": [1, 2]}, name="Synthetic")
            run = start_version(conn, "project", first["id"], {"values": [1, 2, 3]})
            second = publish(conn, "project", template, {"values": [9, 10]}, definition_id=first["definition_id"])
            self.assertEqual(second["version"], 2)
            reconcile(conn)
            root = claim(conn, "root")
            finish(conn, root["id"], root["token"], result={"count": 3})
            reconcile(conn)
            branch = claim(conn, "branch")
            finish(conn, branch["id"], branch["token"], error="fixture")
            reconcile(conn)
            final = claim(conn, "final")
            finish(conn, final["id"], final["token"], result={"count": 3})
            reconcile(conn)
            before = manifest(conn, "project", run)
            self.assertEqual(before["state"], "FAILED")
            self.assertEqual(before["version"]["id"], first["id"])
            self.assertEqual(before["nodes"]["skipped"]["state"], "SKIPPED")
            self.assertEqual(before["nodes"]["root"]["parameters"]["observations"], [1, 2, 3])
            child = rerun(conn, "project", run, "branch")
            reconcile(conn)
            for name in ("branch", "final"):
                job = claim(conn, "rerun-worker")
                self.assertTrue(job["idempotency_key"].endswith(":" + name))
                finish(conn, job["id"], job["token"], result={"count": 3})
                reconcile(conn)
            after = manifest(conn, "project", child)
            self.assertEqual(after["state"], "SUCCEEDED")
            self.assertEqual(after["parent_run_id"], run)
            self.assertEqual(after["nodes"]["root"]["job_id"], root["id"])
            self.assertNotEqual(after["nodes"]["final"]["job_id"], final["id"])
            self.assertEqual(manifest(conn, "project", run), before)

    def test_workflow_cancel_and_dual_scheduler_deduplication(self):
        template = {"root": {"depends_on": [], "plugin": "summary@1",
                             "parameters": {"observations": [1, 2]}}}
        with self.engine.begin() as conn:
            version = publish(conn, "project", template, {}, name="Schedule")
            schedule = create_schedule(conn, "project", version["id"], {}, "2025-01-01T10:00:00-08:00",
                                       "America/Tijuana", None)

        def scheduler(_):
            with self.engine.begin() as conn:
                return trigger_due(conn)

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(scheduler, range(2))), [0, 1])
        with self.engine.begin() as conn:
            self.assertEqual(trigger_due(conn), 0)
            run = conn.execute(select(workflow_runs.c.id)).scalar_one()
            reconcile(conn)
            lease = claim(conn, "worker")
            self.assertEqual(cancel_run(conn, "project", run), "CANCEL_REQUESTED")
            with self.assertRaises(ValueError):
                rerun(conn, "project", run)
            self.assertTrue(finish(conn, lease["id"], lease["token"], result={}))
            reconcile(conn)
            self.assertEqual(get_run(conn, "project", run)["state"], "CANCELLED")
            self.assertIsNotNone(rerun(conn, "project", run))

    def test_mobility_pipeline_exports_screened_metrics_and_geojson(self):
        from fastapi.testclient import TestClient
        from researchhub import api
        from researchhub.registry import register, upload
        from researchhub.storage import LocalStorage

        project = str(uuid4())
        password = "synthetic-mobility-password"
        dataset_bytes = (
            b"participant_id,timestamp_utc,latitude,longitude,steps\n"
            b"synthetic01,2025-01-01T00:00:00Z,0,0,10\n"
            b"synthetic01,2025-01-01T00:10:00Z,0.001,0,20\n"
            b"synthetic01,2025-01-01T00:11:00Z,2,0,30\n"
        )
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "RESEARCHHUB_STORAGE": root, "RESEARCHHUB_WORKER_CAPABILITIES": "GENERAL,GENOMICS,GEOSPATIAL",
        }), patch.object(api, "engine", self.engine):
            with self.engine.begin() as conn:
                conn.execute(projects.insert().values(id=project, organization_id="org", name="Mobility"))
                conn.execute(users.update().where(users.c.id == "requester").values(password_hash=hash_password(password)))
                conn.execute(memberships.insert().values(project_id=project, user_id="requester", role="researcher"))
                dataset = register(conn, project, "requester", "Synthetic points")
                upload(conn, LocalStorage(root), project, dataset, dataset_bytes)
            for program in ("scheduler", "worker", "worker"):
                self.launch("-m", "researchhub." + program, stdout=subprocess.DEVNULL)
            endpoint = "/projects/" + project
            credentials = ("requester", password)
            with TestClient(api.app) as client:
                response = client.post(endpoint + "/research-workflows", auth=credentials, json={
                    "discipline": "mobility", "dataset": {"id": dataset, "version": 1}, "timezone": "UTC",
                })
                self.assertEqual(response.status_code, 200, response.text)
                run_id = response.json()["id"]
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    with self.engine.connect() as conn:
                        summary = manifest(conn, project, run_id)
                    if summary["state"] != "RUNNING":
                        break
                    time.sleep(0.2)
                self.assertEqual(summary["state"], "SUCCEEDED")
                root_node = summary["nodes"]["dataset-validation"]
                export = summary["nodes"]["exports"]
                self.assertEqual(root_node["dataset"]["sha256"], hashlib.sha256(dataset_bytes).hexdigest())
                self.assertEqual(export["dataset"]["upstream"]["sha256"],
                                 summary["nodes"]["spatial-aggregation"]["output_sha256"])
                downloads = f'{endpoint}/jobs/{export["job_id"]}/download/'
                csv_result = client.get(downloads + "csv", auth=credentials)
                self.assertEqual(csv_result.status_code, 200)
                self.assertIn("synthetic01,2025-01-01,3,60,0.111,1,0,0", csv_result.text)
                geojson = client.get(downloads + "geojson", auth=credentials)
                self.assertEqual(geojson.status_code, 200)
                features = geojson.json()["features"]
                self.assertEqual(len(features), 1)
                self.assertEqual(features[0]["geometry"]["coordinates"], [[0, 0], [0, 0.001]])

    def test_v1_schema_upgrades_and_preserves_existing_workflow(self):
        from alembic import command
        from alembic.config import Config
        from researchhub.workflows import definition_checksum

        schema = "rh_" + uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA " + schema))
        url = self.url.update_query_dict({"options": "-csearch_path=" + schema})
        engine = connect(url)
        config = Config("alembic.ini")
        try:
            with patch.dict(os.environ, {"DATABASE_URL": url.render_as_string(hide_password=False)}):
                command.upgrade(config, "0006")
                definition = {"root": {"depends_on": [], "plugin": "summary@1",
                                       "parameters": {"observations": [1, 2]}}}
                with engine.begin() as conn:
                    conn.execute(organizations.insert().values(id="legacy-org", name="Legacy Lab"))
                    conn.execute(projects.insert().values(id="legacy", organization_id="legacy-org", name="Legacy"))
                    conn.execute(text(
                        "INSERT INTO workflow_runs (id, project_id, definition, node_order, nodes, state, checked_at) "
                        "VALUES ('legacy-run', 'legacy', CAST(:definition AS json), "
                        "'[\"root\"]', '{\"root\": {\"state\": \"WAITING\"}}', 'RUNNING', 0)"
                    ), {"definition": json.dumps(definition)})
                command.upgrade(config, "head")
                command.check(config)
                with engine.begin() as conn:
                    run = get_run(conn, "legacy", "legacy-run")
                    self.assertEqual(run["definition_checksum"], definition_checksum(definition))
                    self.assertIsNone(run["version_id"])
                    reconcile(conn)
                    self.assertEqual(claim(conn, "worker")["project_id"], "legacy")
        finally:
            engine.dispose()
            with self.engine.begin() as conn:
                conn.execute(text("DROP SCHEMA " + schema + " CASCADE"))

    def test_budget_row_lock_prevents_overspending(self):
        with self.engine.begin() as conn:
            requests = [request_funds(conn, "project", "requester", key, 70, "Lab time") for key in ("a", "b")]

        def approve(request_id):
            try:
                with self.engine.begin() as conn:
                    return decide(conn, "project", request_id, "reviewer", True)
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(approve, requests), ["APPROVED", "Insufficient project budget"])
        with self.engine.begin() as conn:
            self.assertEqual(conn.execute(select(budgets.c.spent)).scalar_one(), 70)

    def test_cancellation_and_completion_race_have_one_terminal_outcome(self):
        with self.engine.begin() as conn:
            job = submit(conn, "project", "race", "summary@1", {"observations": [1, 2]})
            lease = claim(conn, "worker")

        def cancel_job():
            with self.engine.begin() as conn:
                return cancel(conn, "project", job["id"])

        def complete_job():
            with self.engine.begin() as conn:
                return finish(conn, job["id"], lease["token"], result={"mean": "1.5"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            cancellation = pool.submit(cancel_job)
            completion = pool.submit(complete_job)
            self.assertTrue(completion.result())
            self.assertIn(cancellation.result(), ("SUCCEEDED", "CANCEL_REQUESTED"))
        with self.engine.begin() as conn:
            state, result = conn.execute(select(jobs.c.state, jobs.c.result)).one()
            self.assertIn((state, result), (("CANCELLED", None), ("SUCCEEDED", {"mean": "1.5"})))

    def test_http_project_isolation_and_dataset_manifest(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        project, other = str(uuid4()), str(uuid4())
        password = "synthetic fixture only"
        with self.engine.begin() as conn:
            conn.execute(projects.insert(), [
                {"id": key, "organization_id": "org", "name": name}
                for key, name in ((project, "Primary"), (other, "Other"))
            ])
            for name, allowed in (("primary", project), ("other", other)):
                conn.execute(users.insert().values(id=name, username=name, password_hash=hash_password(password)))
                conn.execute(memberships.insert().values(project_id=allowed, user_id=name, role="pi"))
        with tempfile.TemporaryDirectory() as directory, patch.object(api, "engine", self.engine), patch.dict(
            os.environ, RESEARCHHUB_STORAGE=directory, RESEARCHHUB_CODE_VERSION="fixture",
        ), TestClient(api.app) as client:
            base = "/projects/" + project
            owner, outsider = ("primary", password), ("other", password)
            created = client.post(base + "/datasets", json={"name": "Synthetic observations"}, auth=owner)
            assert created.status_code == 200, created.text
            dataset_id = created.json()["id"]
            version_url = base + "/datasets/" + dataset_id + "/versions"
            version = client.post(version_url, content=b"value\n1\n2\n3\n",
                                  headers={"Content-Type": "text/csv"}, auth=owner)
            assert version.status_code == 200, version.text
            body = {"plugin": "summary@1", "dataset": {"id": dataset_id, "version": 1}}
            result = client.post(base + "/jobs", json=body, headers={"Idempotency-Key": "dataset-job"}, auth=owner)
            assert result.status_code == 200, result.text
            job_url = base + "/jobs/" + result.json()["id"]
            with self.engine.begin() as conn:
                lease = claim(conn, "manifest-worker")
                finish(conn, lease["id"], lease["token"], result={"mean": "2"})
            manifest = client.get(job_url + "/download/manifest", auth=owner).json()
            self.assertEqual(manifest["dataset"], {"id": dataset_id, "version": 1, "sha256": version.json()["checksum"]})
            self.assertEqual(manifest["inputs"], {"observations": [1, 2, 3]})
            self.assertEqual(manifest["output_sha256"], hashlib.sha256(b'{"mean":"2"}').hexdigest())
            self.assertEqual(manifest["plugin_version"], "1")
            self.assertEqual(manifest["code_version"], "fixture")
            for path in (base + "/jobs", job_url + "/events", job_url + "/download/manifest",
                         version_url + "/1", base + "/audit"):
                self.assertEqual(client.get(path, auth=outsider).status_code, 404)
            actions = {entry["action"] for entry in client.get(base + "/audit", auth=owner).json()}
            self.assertEqual(actions, {"dataset_registered", "dataset_uploaded", "job_submission", "job_artifact_download"})

    def test_admin_account_rotation_and_project_member_audit(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        organization, admin_id, pi_id = (str(uuid4()) for _ in range(3))
        admin_password, pi_password, changed_password = "admin fixture password", "project pi fixture password", "changed fixture password"
        with self.engine.begin() as conn:
            conn.execute(organizations.insert().values(id=organization, name="Admin fixture lab"))
            conn.execute(users.insert(), [
                {"id": admin_id, "username": "fixture-admin", "password_hash": hash_password(admin_password),
                 "platform_admin": 1, "must_change_password": 0},
                {"id": pi_id, "username": "fixture-pi-admin", "password_hash": hash_password(pi_password),
                 "platform_admin": 0, "must_change_password": 0},
            ])

        with patch.object(api, "engine", self.engine), TestClient(api.app) as client:
            admin = ("fixture-admin", admin_password)
            pi = ("fixture-pi-admin", pi_password)
            created = client.post("/admin/projects", json={
                "organization_id": organization, "name": "Managed fixture", "budget_limit": 1000,
            }, auth=admin)
            self.assertEqual(created.status_code, 200, created.text)
            project = created.json()["id"]
            with self.engine.begin() as conn:
                conn.execute(memberships.insert().values(project_id=project, user_id=pi_id, role="pi"))

            account = client.post("/admin/accounts", json={"username": "fixture-new-member"}, auth=admin)
            self.assertEqual(account.status_code, 200, account.text)
            self.assertEqual(account.headers.get("cache-control"), "no-store")
            temporary = account.json()["temporary_password"]
            pending = ("fixture-new-member", temporary)
            self.assertTrue(client.get("/auth/status", auth=pending).json()["must_change_password"])
            self.assertEqual(client.get("/projects", auth=pending).status_code, 403)
            self.assertEqual(client.post("/auth/password", json={"password": changed_password}, auth=pending).status_code, 200)
            member = ("fixture-new-member", changed_password)

            base = "/projects/" + project + "/members"
            self.assertEqual(client.post(base, json={"username": member[0], "role": "researcher"}, auth=pi).status_code, 200)
            self.assertEqual(client.post(base, json={"username": member[0], "role": "pi"}, auth=pi).status_code, 403)
            self.assertEqual(client.patch(base + "/" + member[0], json={"role": "finance"}, auth=pi).status_code, 200)
            self.assertEqual(client.delete(base + "/" + member[0], auth=pi).status_code, 200)
            self.assertEqual(client.delete(base + "/fixture-pi-admin", auth=admin).status_code, 409)

            project_actions = {row["action"] for row in client.get("/projects/" + project + "/audit", auth=pi).json()}
            self.assertEqual(project_actions, {"project_created", "membership_added", "membership_role_changed", "membership_removed"})
            with self.engine.begin() as conn:
                system_actions = set(conn.execute(select(system_audit.c.action)).scalars())
                self.assertEqual(system_actions, {"account_created", "password_changed"})

    def test_concurrent_pi_removals_preserve_one_project_pi(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        organization, project, admin_id, first_pi, second_pi = (str(uuid4()) for _ in range(5))
        admin_password = "admin fixture password"
        with self.engine.begin() as conn:
            conn.execute(organizations.insert().values(id=organization, name="Concurrent PI fixture"))
            conn.execute(projects.insert().values(id=project, organization_id=organization, name="PI guard"))
            conn.execute(budgets.insert().values(project_id=project, limit=0, spent=0))
            conn.execute(users.insert(), [
                {"id": admin_id, "username": "fixture-pi-guard-admin", "password_hash": hash_password(admin_password),
                 "platform_admin": 1, "must_change_password": 0},
                {"id": first_pi, "username": "fixture-first-pi", "password_hash": "fixture",
                 "platform_admin": 0, "must_change_password": 0},
                {"id": second_pi, "username": "fixture-second-pi", "password_hash": "fixture",
                 "platform_admin": 0, "must_change_password": 0},
            ])
            conn.execute(memberships.insert(), [
                {"project_id": project, "user_id": first_pi, "role": "pi"},
                {"project_id": project, "user_id": second_pi, "role": "pi"},
            ])

        def remove(username):
            with TestClient(api.app) as client:
                return client.delete(
                    f"/projects/{project}/members/{username}",
                    auth=("fixture-pi-guard-admin", admin_password),
                ).status_code

        with patch.object(api, "engine", self.engine), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(remove, ("fixture-first-pi", "fixture-second-pi")))
        self.assertCountEqual(outcomes, [200, 409])
        with self.engine.begin() as conn:
            remaining = conn.execute(select(func.count()).select_from(memberships).where(
                memberships.c.project_id == project, memberships.c.role == "pi",
            )).scalar_one()
        self.assertEqual(remaining, 1)

    def test_invalid_basic_auth_returns_json_without_browser_challenge(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        with patch.object(api, "engine", self.engine), TestClient(api.app) as client:
            for credentials in (None, ("unknown", "wrong fixture password"), ("requester", "wrong fixture password")):
                with self.subTest(has_credentials=credentials is not None):
                    response = client.get("/projects", auth=credentials)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.json(), {"detail": "Invalid credentials"})
                    self.assertNotIn("www-authenticate", response.headers)

    def launch(self, *args, **kwargs):
        environment = dict(os.environ, DATABASE_URL=self.url.render_as_string(hide_password=False))
        process = subprocess.Popen([sys.executable, "-B", *args], env=environment, **kwargs)

        def stop():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            if process.stdout is not None:
                process.stdout.close()

        self.addCleanup(stop)
        return process

    def test_scheduler_restart_preserves_parallel_roots_and_dependency(self):
        def node(*parents):
            return {"depends_on": list(parents), "plugin": "summary@1",
                    "parameters": {"observations": [1, 2, 3]}}

        with self.engine.begin() as conn:
            run = start(conn, "project", {"a": node(), "b": node(), "report": node("a", "b")})

        def status():
            with self.engine.connect() as conn:
                return conn.execute(select(workflow_runs).where(workflow_runs.c.id == run)).mappings().one()

        def wait_for(condition):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if condition():
                    return
                time.sleep(.1)
            self.fail("Timed out waiting for workflow state")

        first = self.launch("-m", "researchhub.scheduler", stdout=subprocess.DEVNULL)
        wait_for(lambda: all("job_id" in status()["nodes"][name] for name in ("a", "b")))
        first.kill()
        first.wait(timeout=10)
        snapshot = status()["nodes"]
        self.assertNotIn("job_id", snapshot["report"])
        self.launch("-m", "researchhub.worker", stdout=subprocess.DEVNULL)
        self.launch("-m", "researchhub.worker", stdout=subprocess.DEVNULL)
        self.launch("-m", "researchhub.scheduler", stdout=subprocess.DEVNULL)
        wait_for(lambda: status()["state"] == "SUCCEEDED")
        final = status()["nodes"]
        self.assertEqual({final[name]["job_id"] for name in ("a", "b")},
                         {snapshot[name]["job_id"] for name in ("a", "b")})
        self.assertNotIn(final["report"]["job_id"], {final["a"]["job_id"], final["b"]["job_id"]})

    def test_worker_computes_after_abrupt_process_loss(self):
        with self.engine.begin() as conn:
            job = submit(conn, "project", "restart", "summary@1", {"observations": [1, 2, 3]}, timeout_ms=2500)

        # A separate process takes a real lease and is killed before it can release it.
        script = (
            "import time; from researchhub.db import connect; from researchhub.queue import claim\n"
            "with connect().begin() as conn: job = claim(conn, 'terminated-worker')\n"
            "print(job['token'], flush=True); time.sleep(30)\n"
        )
        abandoned = self.launch("-c", script, stdout=subprocess.PIPE, text=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(abandoned.stdout.readline)
            try:
                token = reading.result(timeout=12).strip()
            finally:
                abandoned.kill()
                abandoned.wait(timeout=10)
        self.assertTrue(token)
        self.launch("-m", "researchhub.worker", stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 16
        while time.monotonic() < deadline:
            with self.engine.begin() as conn:
                current = conn.execute(select(jobs).where(jobs.c.id == job["id"])).mappings().one()
                if current["state"] == "SUCCEEDED":
                    break
            time.sleep(.1)
        self.assertEqual(current["state"], "SUCCEEDED")
        self.assertEqual(current["attempt"], 2)
        self.assertEqual(current["result"]["mean"], "2")
        with self.engine.begin() as conn:
            self.assertFalse(finish(conn, job["id"], token, result={"stale": True}))
            history = conn.execute(select(events.c.reason).where(events.c.job_id == job["id"])).scalars().all()
            self.assertIn("deadline_exceeded", history)

    def test_rate_limits_persist_across_engines_and_reject_without_job_write(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        organization, project, user_id = (str(uuid4()) for _ in range(3))
        password = "rate limit fixture password"
        with self.engine.begin() as conn:
            conn.execute(organizations.insert().values(id=organization, name="Rate limit fixture"))
            conn.execute(projects.insert().values(id=project, organization_id=organization, name="Limited project"))
            conn.execute(budgets.insert().values(project_id=project, limit=0, spent=0))
            conn.execute(users.insert().values(
                id=user_id, username="rate-limit-user", password_hash=hash_password(password),
            ))
            conn.execute(memberships.insert().values(project_id=project, user_id=user_id, role="pi"))

        other_engine = connect(self.url)
        self.addCleanup(other_engine.dispose)
        with patch.object(api, "engine", self.engine), patch.object(api, "AUTH_FAILURE_LIMIT", 2):
            with TestClient(api.app) as client:
                for expected in (401, 401, 429):
                    response = client.get("/projects", auth=("unknown-rate-user", "wrong fixture password"))
                    self.assertEqual(response.status_code, expected)
                    if expected == 429:
                        self.assertTrue(response.headers.get("Retry-After"))

        with patch.object(api, "engine", self.engine), patch.object(api, "AUTH_FAILURE_LIMIT", 10), \
             patch.object(api, "JOB_SUBMISSION_LIMIT", 1), TestClient(api.app) as client:
            path = f"/projects/{project}/jobs"
            body = {"plugin": "summary@1", "parameters": {"observations": [1, 2]}}
            headers = {"Idempotency-Key": "first-job"}
            self.assertEqual(client.post(path, json=body, headers=headers,
                                         auth=("rate-limit-user", password)).status_code, 200)
            with patch.object(api, "engine", other_engine), TestClient(api.app) as other_client:
                limited = other_client.post(path, json=body, headers={"Idempotency-Key": "second-job"},
                                            auth=("rate-limit-user", password))
            self.assertEqual(limited.status_code, 429)
            self.assertTrue(limited.headers.get("Retry-After"))
            with self.engine.begin() as conn:
                self.assertEqual(conn.execute(select(func.count()).select_from(jobs).where(
                    jobs.c.project_id == project,
                )).scalar_one(), 1)
                self.assertGreater(conn.execute(select(func.count()).select_from(api_rate_limits)).scalar_one(), 0)

    def test_metrics_pair_persisted_job_events_and_bound_http_samples(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        metric_time = int(time.time() * 1000)
        password = "metrics fixture password"
        with self.engine.begin() as conn:
            conn.execute(users.insert().values(
                id="metrics-admin", username="metrics-admin", password_hash=hash_password(password),
                platform_admin=1,
            ))
            job = submit(conn, "project", "metrics-job", "summary@1", {"observations": [1, 2]})
            conn.execute(events.delete().where(events.c.job_id == job["id"]))
            conn.execute(events.insert(), [
                {"job_id": job["id"], "attempt": 0, "state": "QUEUED", "reason": "submitted", "timestamp": metric_time - 20_000},
                {"job_id": job["id"], "attempt": 1, "state": "RUNNING", "reason": "claimed", "timestamp": metric_time - 17_000},
                {"job_id": job["id"], "attempt": 1, "state": "RETRYING", "reason": "retry", "timestamp": metric_time - 12_000},
                {"job_id": job["id"], "attempt": 2, "state": "RUNNING", "reason": "claimed", "timestamp": metric_time - 11_000},
                {"job_id": job["id"], "attempt": 2, "state": "SUCCEEDED", "reason": "finished", "timestamp": metric_time - 6_000},
            ])

        with api._http_metrics_lock:
            api._http_duration_samples.clear()
            api._http_status_classes.clear()
        with patch.object(api, "engine", self.engine), patch.object(api, "now_ms", return_value=metric_time), \
             TestClient(api.app) as client:
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/projects").status_code, 401)
            response = client.get("/metrics", auth=("metrics-admin", password))
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["job_queue_wait_ms"], {"count": 2, "p50": 1000, "p95": 3000, "max": 3000})
            self.assertEqual(body["job_execution_ms"], {"count": 2, "p50": 5000, "p95": 5000, "max": 5000})
            self.assertEqual(body["job_metrics_window"], {"hours": 24, "max_events": 20_000})
            self.assertEqual(body["http_requests"]["duration_ms"]["count"], 2)
            self.assertEqual(body["http_requests"]["status_classes"], {"2xx": 1, "4xx": 1})
            with api._http_metrics_lock:
                api._http_duration_samples.extend(float(value) for value in range(api.HTTP_METRICS_SAMPLE_LIMIT + 1))
            capped = client.get("/metrics", auth=("metrics-admin", password)).json()["http_requests"]
            self.assertEqual(capped["duration_ms"]["count"], api.HTTP_METRICS_SAMPLE_LIMIT)
            self.assertEqual(capped["duration_ms"]["max"], float(api.HTTP_METRICS_SAMPLE_LIMIT))
            self.assertEqual(capped["sample_limit"], api.HTTP_METRICS_SAMPLE_LIMIT)

    def test_api_restart_preserves_submitted_job_and_idempotency(self):
        username = "api-restart-user"
        password = "api restart fixture password"
        user_id = str(uuid4())
        project_id = str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(users.insert().values(
                id=user_id, username=username, password_hash=hash_password(password),
                platform_admin=0, must_change_password=0,
            ))
            conn.execute(projects.insert().values(
                id=project_id, organization_id="org", name="API restart fixture",
            ))
            conn.execute(budgets.insert().values(project_id=project_id, limit=1000, spent=0))
            conn.execute(memberships.insert().values(project_id=project_id, user_id=user_id, role="pi"))

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

        def request(path, method="GET", body=None, key=None):
            headers = {"Authorization": authorization}
            data = None
            if body is not None:
                headers["Content-Type"] = "application/json"
                data = json.dumps(body).encode()
            if key is not None:
                headers["Idempotency-Key"] = key
            request_object = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request_object, timeout=2) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = json.loads(exc.read())
                return exc.code, detail

        def wait_until_ready():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(base_url + "/readyz", timeout=1) as response:
                        if response.status == 200:
                            return
                except (OSError, urllib.error.URLError):
                    time.sleep(.1)
            self.fail("API did not become ready")

        server_args = ("-m", "uvicorn", "researchhub.api:app", "--host", "127.0.0.1", "--port", str(port))
        with patch.dict(os.environ, RESEARCHHUB_STORAGE=tempfile.gettempdir()):
            first = self.launch(*server_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_until_ready()
        path = f"/projects/{project_id}/jobs"
        body = {"plugin": "summary@1", "parameters": {"observations": [2, 4, 6]}}
        status, created = request(path, "POST", body, "api-restart-idempotency")
        self.assertEqual(status, 200, created)
        first.terminate()
        first.wait(timeout=10)

        with patch.dict(os.environ, RESEARCHHUB_STORAGE=tempfile.gettempdir()):
            second = self.launch(*server_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_until_ready()
        status, rows = request(path)
        self.assertEqual(status, 200)
        persisted = next(row for row in rows if row["id"] == created["id"])
        self.assertEqual(persisted["state"], "QUEUED")
        status, repeated = request(path, "POST", body, "api-restart-idempotency")
        self.assertEqual(status, 200)
        self.assertEqual(repeated["id"], created["id"])

    def test_api_reports_database_unavailable_then_recovers(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        unavailable = connect(self.url.set(port=1).update_query_dict({"connect_timeout": "1"}))
        self.addCleanup(unavailable.dispose)
        with patch.object(api, "engine", unavailable), TestClient(api.app) as client:
            response = client.get("/readyz")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"detail": "Database unavailable"})
        with patch.object(api, "engine", self.engine), TestClient(api.app) as client:
            response = client.get("/readyz")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ready"})


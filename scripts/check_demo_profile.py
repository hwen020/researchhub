"""Verify the fixed synthetic Render-compatible profile against a local URL."""
import argparse
import base64
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check(base_url):
    password = os.environ["RESEARCHHUB_DEMO_PASSWORD"]

    def request(path, username=None, body=None, expected=200):
        headers = {}
        if username:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = "Basic " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(base_url + "/api" + path, headers=headers, data=body), timeout=5) as response:
                assert response.status == expected
                return response.read()
        except HTTPError as exc:
            if exc.code != expected:
                raise

    guest = "demo-guest"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            readiness = json.loads(request("/readyz"))
            if readiness["status"] == "ready":
                break
        except (URLError, TimeoutError):
            pass
        time.sleep(1)
    else:
        raise TimeoutError("Demo readiness did not recover")

    projects = json.loads(request("/projects", guest))
    assert len(projects) == 1 and projects[0]["role"] == "researcher"
    project = "/projects/" + projects[0]["id"]
    request("/projects", "fixture-admin", expected=401)
    request(project + "/datasets", guest, body=b'{"name":"private"}', expected=403)
    request("/admin/organizations", guest, expected=403)

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        runs = json.loads(request(project + "/workflows", guest))
        assert len(runs) == 1
        run = runs[0]
        if run["state"] == "SUCCEEDED":
            break
        assert run["state"] == "RUNNING"
        time.sleep(1)
    else:
        raise TimeoutError("Fixed Genomics workflow did not complete")

    assert all(node["state"] == "SUCCEEDED" for node in run["nodes"].values())
    report = project + "/jobs/" + run["nodes"]["report"]["job_id"] + "/download/"
    result = json.loads(request(report + "json", guest))
    manifest = json.loads(request(report + "manifest", guest))
    lineage = json.loads(request(project + "/workflows/" + run["id"] + "/provenance", guest))
    csv_report = request(report + "csv", guest)
    assert len(result["associations"]) == 2
    assert manifest["dataset"]["version"] == 1 and len(manifest["dataset"]["sha256"]) == 64
    assert b"spearman_rho" in csv_report and lineage["version"]["id"]
    print("Demo readiness, guest restrictions, Genomics pipeline, lineage and exports passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    check(parser.parse_args().base_url.rstrip("/"))

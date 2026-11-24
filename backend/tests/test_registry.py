import tempfile
import unittest

from researchhub.db import connect
from researchhub.models import metadata, organizations, projects, users
from researchhub.plugins import aging_associations
from researchhub.registry import download, register, upload
from researchhub.storage import LocalStorage, checksum


class RegistryTest(unittest.TestCase):
    def test_immutable_versions_and_project_scope(self):
        engine = connect("sqlite://")
        self.addCleanup(engine.dispose)
        metadata.create_all(engine)
        original = b"value\n1\n"
        with tempfile.TemporaryDirectory() as folder, engine.begin() as conn:
            store = LocalStorage(folder)
            conn.execute(organizations.insert().values(id="org", name="Research"))
            conn.execute(projects.insert().values(id="project", organization_id="org", name="A"))
            conn.execute(users.insert().values(id="owner", username="owner", password_hash="fixture"))
            dataset = register(conn, "project", "owner", "Versioned observations")
            first = upload(conn, store, "project", dataset, original)
            second = upload(conn, store, "project", dataset, b"value\n2\n")
            self.assertEqual(first["checksum"], checksum(original))
            self.assertEqual(second["version"], 2)
            self.assertEqual(download(conn, store, "project", dataset, 1), original)
            with self.assertRaises(LookupError):
                download(conn, store, "other", dataset, 1)
            with self.assertRaises(ValueError):
                store.read("../outside")
            with self.assertRaises(ValueError):
                upload(conn, store, "project", dataset, b"a,b\n1\n")


class AgingStatisticsTest(unittest.TestCase):
    def test_synthetic_associations_and_reproducibility(self):
        inputs = {"ages": [30, 45, 60, 75], "expression": {
            "SyntheticA": [1, 2, 3, 4], "SyntheticB": [2, 2, 2, 2],
        }}
        result = aging_associations(inputs)
        self.assertEqual(result, aging_associations(inputs))
        self.assertAlmostEqual(result["associations"][0]["spearman_rho"], 1.0)
        self.assertEqual(result["associations"][1]["fdr"], 1.0)


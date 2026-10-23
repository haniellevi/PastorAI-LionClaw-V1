import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci_test_shards import parse_collection, partition_files, verify_artifacts


class TestCollectionPartitioning(unittest.TestCase):
    def test_counts_nodeids_by_file_and_ignores_summary(self):
        counts = parse_collection(
            "tests/test_a.py::test_one\n"
            "tests/test_a.py::test_two[param]\n"
            "tests/test_b.py::test_three\n"
            "2 files, 3 tests collected\n"
        )
        self.assertEqual(counts, {"tests/test_a.py": 2, "tests/test_b.py": 1})

    def test_partition_is_deterministic_balanced_and_keeps_files_whole(self):
        counts = {
            "tests/a.py": 7,
            "tests/b.py": 6,
            "tests/c.py": 3,
            "tests/d.py": 2,
            "tests/e.py": 1,
        }
        shards = partition_files(counts, 3)
        self.assertEqual(shards, partition_files(dict(reversed(list(counts.items()))), 3))
        self.assertEqual([7, 6, 6], [sum(counts[path] for path in shard) for shard in shards])
        self.assertEqual(sorted(counts), sorted(path for shard in shards for path in shard))

    def test_artifact_verifier_rejects_duplicate_file_assignment(self):
        counts = {f"tests/test_{index}.py": 2 for index in range(4)}
        assignments = partition_files(counts, 4)
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_directory = Path(temporary_directory)
            for shard, assigned in enumerate(assignments):
                manifest = {
                    "schema_version": 1,
                    "shard": shard,
                    "shard_count": 4,
                    "collected_files": counts,
                    "collected_total": sum(counts.values()),
                    "assigned_files": assigned,
                    "assigned_total": sum(counts[path] for path in assigned),
                }
                (artifact_directory / f"rls-shard-{shard}.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                (artifact_directory / f"rls-results-{shard}.xml").write_text(
                    '<testsuites><testsuite tests="2" skipped="0" failures="0" errors="0"/></testsuites>',
                    encoding="utf-8",
                )

            output = io.StringIO()
            self.assertTrue(verify_artifacts(artifact_directory, 4, "success", output))
            self.assertIn("total=8 skipped=0 executed=8 failed=0 errors=0", output.getvalue())

            first_manifest_path = artifact_directory / "rls-shard-0.json"
            first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
            first_file = first_manifest["assigned_files"][0]
            second_manifest_path = artifact_directory / "rls-shard-1.json"
            second_manifest = json.loads(second_manifest_path.read_text(encoding="utf-8"))
            second_manifest["assigned_files"][0] = first_file
            second_manifest_path.write_text(json.dumps(second_manifest), encoding="utf-8")

            output = io.StringIO()
            self.assertFalse(verify_artifacts(artifact_directory, 4, "success", output))
            self.assertIn("arquivo atribuido aos shards", output.getvalue())
            self.assertIn("arquivos sem shard", output.getvalue())


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fetch_evaluation_tracks", ROOT / "scripts" / "fetch_evaluation_tracks.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class EvaluationTrackTests(unittest.TestCase):
    def test_public_manifest_is_complete_and_valid(self):
        manifest = json.loads((ROOT / "evaluation" / "tracks.json").read_text())
        self.assertGreaterEqual(len(manifest["tracks"]), 2)
        for track in manifest["tracks"]:
            self.assertIs(MODULE.validated_track(track), track)
            self.assertEqual(track["license"], "CC BY 4.0")

    def test_rejects_parent_traversal(self):
        manifest = json.loads((ROOT / "evaluation" / "tracks.json").read_text())
        track = dict(manifest["tracks"][0], filename="../outside.wav")
        with self.assertRaisesRegex(RuntimeError, "Unsafe"):
            MODULE.validated_track(track)

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample"
            path.write_bytes(b"abc")
            self.assertEqual(
                MODULE.sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )


if __name__ == "__main__":
    unittest.main()

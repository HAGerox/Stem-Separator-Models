from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def benchmark_rows(registry: dict) -> list[tuple[str, list[dict]]]:
    return [
        (model["id"], deepcopy(model.get("benchmarks", [])))
        for model in registry.get("models", [])
    ]


class SchemaFourValidationTests(unittest.TestCase):
    def test_schema_four_registry_validates_with_measured_rows(self) -> None:
        registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
        before_benchmarks = benchmark_rows(registry)
        self.assertEqual(registry.get("schema"), 4)
        self.assertFalse(any("semantic_evidence" in model for model in registry["models"]))
        self.assertEqual(benchmark_rows(registry), before_benchmarks)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8") as handle:
            json.dump(registry, handle)
            handle.flush()
            result = subprocess.run(
                ["python3", str(ROOT / "scripts" / "validate.py"), handle.name],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

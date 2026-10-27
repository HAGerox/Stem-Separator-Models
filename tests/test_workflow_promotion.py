"""Exercise the actual promotion shell against a local Git remote, without GitHub."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from smoke_audio_separator import promote
from smoke_policy import contract_sha256
from workflow_policy import OWNER_ID, REPOSITORY_ID


class WorkflowPromotionTests(unittest.TestCase):
    def test_promotion_writes_only_validated_json_without_checkout_or_filters(self):
        workflow = (ROOT / ".github/workflows/audio-separator-smoke.yml").read_text()
        step = workflow.split("      - name: Commit successful promotions to the PR\n", 1)[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1].split("      - name:", 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                       GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="file",
                       GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com",
                       GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")

            def git(*args, cwd=None):
                result = subprocess.run(["git", *args], cwd=cwd or root, env=env, check=True,
                                        capture_output=True, text=True)
                return result.stdout.strip()

            remote = root / "remote.git"
            seed = root / "seed"
            git("init", "--bare", str(remote))
            git("init", "-b", "main", str(seed))
            shutil.copytree(ROOT / "scripts", seed / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            for filename in ("registry.json", "product-catalog.json", "sources.json"):
                shutil.copy2(ROOT / filename, seed / filename)
            git("add", ".", cwd=seed)
            git("commit", "-m", "Trusted base", cwd=seed)
            base_sha = git("rev-parse", "HEAD", cwd=seed)
            git("remote", "add", "origin", str(remote), cwd=seed)
            git("push", "origin", "main", cwd=seed)
            git("switch", "-c", "owner-models", cwd=seed)
            registry = json.loads((seed / "registry.json").read_text())
            model = next(item for item in registry["models"] if item["backends"]["audio_separator"].get("smoke_validation"))
            backend = model["backends"]["audio_separator"]
            backend.update(state="compatible_unvalidated", validated=False)
            backend.pop("smoke_validation")
            (seed / "registry.json").write_text(json.dumps(registry))
            # A PR-controlled clean filter must never run in the write job.
            (seed / ".gitattributes").write_text("registry.json filter=untrusted\nproduct-catalog.json filter=untrusted\n")
            (seed / "unrelated.txt").write_text("Preserve this proposed file.\n")
            git("add", ".", cwd=seed)
            git("commit", "-m", "Owner proposal", cwd=seed)
            head_sha = git("rev-parse", "HEAD", cwd=seed)
            git("push", "origin", "owner-models", cwd=seed)
            git("clone", "--branch", "main", str(remote), str(root / "trusted"))
            sentinel = root / "filter-executed"
            git("config", "filter.untrusted.clean", f"touch '{sentinel}'; cat", cwd=root / "trusted")
            promoted = deepcopy(registry)
            promoted_model = next(item for item in promoted["models"] if item["id"] == model["id"])
            promote(promoted_model, {"contract_sha256": contract_sha256(model, backend)})
            temp = root / "runner-temp"
            package = temp / "audio-separator-package"
            package.mkdir(parents=True)
            (package / "registry.json").write_text(json.dumps(promoted))
            subprocess.run([sys.executable, str(ROOT / "scripts/product_catalog.py"),
                            "--registry", str(package / "registry.json"),
                            "--output", str(package / "product-catalog.json")], check=True, env=env)
            pr = {"number": 17, "state": "open", "draft": False, "user": {"id": OWNER_ID},
                  "base": {"ref": "main", "sha": base_sha, "repo": {"id": REPOSITORY_ID}},
                  "head": {"ref": "owner-models", "sha": head_sha, "repo": {"id": REPOSITORY_ID}}}
            api_response = root / "pr.json"
            api_response.write_text(json.dumps(pr))
            commands = root / "bin"
            commands.mkdir()
            fake_gh = commands / "gh"
            fake_gh.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
                import os, pathlib, sys
                if sys.argv[1:] == ["api", "repos/HAGerox/Stem-Separator-Models/pulls/17"]:
                    print(pathlib.Path(os.environ["TEST_PR_RESPONSE"]).read_text())
                elif sys.argv[1:] != ["auth", "setup-git"]:
                    raise SystemExit("Unexpected gh invocation")
                '''))
            fake_gh.chmod(0o755)
            env.update(PATH=str(commands) + os.pathsep + env["PATH"], TEST_PR_RESPONSE=str(api_response),
                       RUNNER_TEMP=str(temp), HEAD_REF="owner-models", HEAD_SHA=head_sha, BASE_SHA=base_sha,
                       PR_NUMBER="17", GIT_INDEX_FILE=str(temp / "promotion-index"))
            # The test's only push destination is the disposable local remote.
            script = script.replace("https://github.com/HAGerox/Stem-Separator-Models.git", str(remote))
            completed = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=root, env=env,
                                       capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result_sha = git("rev-parse", "refs/heads/owner-models", cwd=remote)
            self.assertNotEqual(result_sha, head_sha)
            self.assertEqual(git("rev-parse", f"{result_sha}^", cwd=remote), head_sha)
            changed = set(git("diff-tree", "--no-commit-id", "--name-only", "-r", result_sha, cwd=remote).splitlines())
            self.assertIn("registry.json", changed)
            self.assertLessEqual(changed, {"registry.json", "product-catalog.json"})
            self.assertEqual(json.loads(git("show", f"{result_sha}:registry.json", cwd=remote)), promoted)
            self.assertEqual(git("show", f"{result_sha}:unrelated.txt", cwd=remote), "Preserve this proposed file.")
            self.assertFalse((root / "trusted/.gitattributes").exists())
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()

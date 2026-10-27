from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from smoke_audio_separator import ArtifactRedirectHandler, download_verified, stage_model


class ArtifactSecurityTests(unittest.TestCase):
    def artifact(self, name="model.ckpt", data=b"checkpoint"):
        return {
            "name": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "url": "https://huggingface.co/owner/model/resolve/revision/model.ckpt",
        }

    def test_rejects_path_escape_before_any_network_request(self):
        for name in ("../escape.ckpt", "/tmp/escape.ckpt", "dir/model.ckpt", "..", "bad\\name.ckpt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with patch("urllib.request.build_opener") as opener:
                    with self.assertRaisesRegex(RuntimeError, "Unsafe artifact filename"):
                        download_verified(self.artifact(name), Path(directory))
                    opener.assert_not_called()

    def test_rejects_digest_path_escape(self):
        artifact = self.artifact()
        artifact["sha256"] = "../escape"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "Invalid artifact SHA"):
                download_verified(artifact, Path(directory))

    def test_rejects_symlinked_cache_files_and_directories(self):
        for kind in ("directory", "file", "partial"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cache = root / "cache"
                outside = root / "outside"
                outside.mkdir()
                artifact = self.artifact()
                digest_dir = cache / artifact["sha256"]
                if kind == "directory":
                    cache.mkdir()
                    digest_dir.symlink_to(outside, target_is_directory=True)
                else:
                    digest_dir.mkdir(parents=True)
                    name = artifact["name"] + (".part" if kind == "partial" else "")
                    (digest_dir / name).symlink_to(outside / "target")
                with self.assertRaisesRegex(RuntimeError, "symlinks"):
                    download_verified(artifact, cache)

    def test_only_hash_verified_cached_files_are_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = self.artifact()
            cached = root / artifact["sha256"] / artifact["name"]
            cached.parent.mkdir()
            cached.write_bytes(b"checkpoint")
            with patch("urllib.request.build_opener") as opener:
                self.assertEqual(download_verified(artifact, root), cached.resolve())
                opener.assert_not_called()

    def test_redirect_is_rejected_before_the_destination_is_contacted(self):
        for url in ("http://github.com/file", "https://127.0.0.1/file", "https://huggingface.co.evil.test/file",
                    "https://github.com:8080/file", "https://github.com:bad/file", "file:///tmp/file"):
            with self.subTest(url=url), patch("urllib.request.HTTPRedirectHandler.redirect_request") as redirect:
                with self.assertRaisesRegex(RuntimeError, "Untrusted artifact redirect"):
                    ArtifactRedirectHandler().redirect_request(None, None, 302, "", {}, url)
                redirect.assert_not_called()

    def test_config_download_has_a_size_limit(self):
        artifact = self.artifact("config.yaml")
        response = io.BytesIO(b"x" * (1024 * 1024 + 1))
        response.geturl = lambda: artifact["url"]
        opener = MagicMock()
        opener.open.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            with patch("urllib.request.build_opener", return_value=opener):
                with self.assertRaisesRegex(RuntimeError, "size limit"):
                    download_verified(artifact, Path(directory))
            self.assertFalse((Path(directory) / artifact["sha256"] / artifact["name"]).exists())

    def test_runtime_filename_cannot_escape_the_staging_directory(self):
        artifacts = [self.artifact("model.ckpt"), self.artifact("config.yaml")]
        model = {"availability": {"artifacts": artifacts}}
        backend = {"artifact_names": [item["name"] for item in artifacts], "model_filename": "../escape.ckpt"}
        with patch("smoke_audio_separator.download_verified") as download:
            with self.assertRaisesRegex(RuntimeError, "Unsafe runtime model filename"):
                stage_model(model, backend, Path("unused-cache"), Path("unused-staging"))
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()

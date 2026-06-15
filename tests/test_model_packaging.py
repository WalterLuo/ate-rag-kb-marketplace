"""Unit tests for model packaging and verification scripts."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.package_models import create_manifest, stage_models
from scripts.verify_models import verify_manifest, verify_structure


def _create_fake_model_cache(
    cache_dir: Path,
    model_name: str = "BAAI/bge-m3",
    weight_size: int = 100 * 1024 * 1024,
) -> Path:
    """Create a minimal fake model cache directory."""
    safe_name = model_name.replace("/", "--")
    model_dir = cache_dir / f"models--{safe_name}"
    snapshot = model_dir / "snapshots" / "abc1234"
    snapshot.mkdir(parents=True, exist_ok=True)

    (snapshot / "config.json").write_text('{"model_type": "bert"}')
    (snapshot / "tokenizer.json").write_text('{}')

    weight_file = snapshot / "model.safetensors"
    weight_file.write_bytes(b"\x00" * weight_size)

    return model_dir


class TestStageModels:
    def test_stages_real_files(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        staging_dir = tmp_path / "staging"
        cache_dir.mkdir()
        staging_dir.mkdir()

        _create_fake_model_cache(cache_dir, weight_size=20 * 1024 * 1024)

        manifest_entries, errors = stage_models(cache_dir, staging_dir)

        assert len(errors) == 0
        assert len(manifest_entries) > 0

    def test_rejects_small_weight_files(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        staging_dir = tmp_path / "staging"
        cache_dir.mkdir()
        staging_dir.mkdir()

        _create_fake_model_cache(cache_dir, weight_size=100)  # Very small

        _, errors = stage_models(cache_dir, staging_dir)

        assert len(errors) > 0
        assert any("Suspiciously small weight file" in e for e in errors)

    def test_excludes_patterns(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        staging_dir = tmp_path / "staging"
        cache_dir.mkdir()
        staging_dir.mkdir()

        safe_name = "BAAI--bge-m3"
        snapshot = cache_dir / f"models--{safe_name}" / "snapshots" / "abc1234"
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "config.json").write_text('{}')
        (snapshot / "model.safetensors").write_bytes(b"\x00" * 20 * 1024 * 1024)

        # Create files that should be excluded
        locks_dir = cache_dir / f"models--{safe_name}" / ".locks"
        locks_dir.mkdir()
        (locks_dir / "some.lock").write_text("lock")
        refs_dir = cache_dir / f"models--{safe_name}" / "refs"
        refs_dir.mkdir()
        (refs_dir / "main").write_text("abc1234")
        (snapshot / ".no_exist").write_text("")
        (snapshot / ".DS_Store").write_bytes(b"")

        _, errors = stage_models(cache_dir, staging_dir)

        # Check excluded files don't appear in staging
        staged_files = list(staging_dir.rglob("*"))
        staged_names = [f.name for f in staged_files if f.is_file()]
        assert ".no_exist" not in staged_names
        assert ".DS_Store" not in staged_names
        assert "some.lock" not in staged_names
        assert "main" not in staged_names

    def test_resolves_symlinks(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        staging_dir = tmp_path / "staging"
        cache_dir.mkdir()
        staging_dir.mkdir()

        safe_name = "BAAI--bge-m3"
        snapshot = cache_dir / f"models--{safe_name}" / "snapshots" / "abc1234"
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "config.json").write_text('{}')

        # Create a real file and a symlink pointing to it
        real_file = tmp_path / "real_weights.bin"
        real_file.write_bytes(b"\x00" * 20 * 1024 * 1024)
        link_file = snapshot / "model.safetensors"
        link_file.symlink_to(real_file)

        manifest_entries, errors = stage_models(cache_dir, staging_dir)

        # Should resolve symlink to regular file
        assert len(errors) == 0
        staged_weight = staging_dir / "embeddings" / "cache" / f"models--{safe_name}" / "snapshots" / "abc1234" / "model.safetensors"
        assert staged_weight.exists()
        assert not staged_weight.is_symlink()

    def test_reports_broken_symlinks(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        staging_dir = tmp_path / "staging"
        cache_dir.mkdir()
        staging_dir.mkdir()

        safe_name = "BAAI--bge-m3"
        snapshot = cache_dir / f"models--{safe_name}" / "snapshots" / "abc1234"
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "config.json").write_text('{}')

        # Create a symlink to a nonexistent target
        link_file = snapshot / "model.safetensors"
        link_file.symlink_to(tmp_path / "nonexistent_file")

        _, errors = stage_models(cache_dir, staging_dir)
        assert any("Broken symlink" in e or "Unresolved symlink" in e for e in errors)

    def test_missing_cache_dir(self, tmp_path: Path) -> None:
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()

        _, errors = stage_models(tmp_path / "nonexistent", staging_dir)
        assert any("does not exist" in e for e in errors)

    def test_no_model_dirs(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()

        _, errors = stage_models(cache_dir, staging_dir)
        assert any("No model directories" in e for e in errors)


class TestCreateManifest:
    def test_writes_manifest(self, tmp_path: Path) -> None:
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()

        entries = [
            {
                "model": "BAAI/bge-m3",
                "snapshot": "abc1234",
                "path": "embeddings/cache/models--BAAI--bge-m3/snapshots/abc1234/model.safetensors",
                "size": 20000000,
                "sha256": "abc123",
            }
        ]

        manifest_path = create_manifest(entries, staging_dir)

        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "models" in manifest
        assert "BAAI/bge-m3" in manifest["models"]


class TestVerifyStructure:
    def test_valid_cache(self, tmp_path: Path) -> None:
        _create_fake_model_cache(tmp_path, "BAAI/bge-m3", weight_size=20 * 1024 * 1024)
        _create_fake_model_cache(tmp_path, "BAAI/bge-reranker-v2-m3", weight_size=20 * 1024 * 1024)

        errors = verify_structure(tmp_path)
        assert len(errors) == 0

    def test_missing_model(self, tmp_path: Path) -> None:
        _create_fake_model_cache(tmp_path, "BAAI/bge-m3", weight_size=20 * 1024 * 1024)
        # Missing bge-reranker-v2-m3

        errors = verify_structure(tmp_path)
        assert any("Missing model directory" in e for e in errors)

    def test_small_weight_file(self, tmp_path: Path) -> None:
        _create_fake_model_cache(tmp_path, "BAAI/bge-m3", weight_size=100)
        _create_fake_model_cache(tmp_path, "BAAI/bge-reranker-v2-m3", weight_size=20 * 1024 * 1024)

        errors = verify_structure(tmp_path)
        assert any("Suspiciously small" in e for e in errors)

    def test_missing_cache_dir(self, tmp_path: Path) -> None:
        errors = verify_structure(tmp_path / "nonexistent")
        assert any("does not exist" in e for e in errors)


class TestVerifyManifest:
    def test_valid_manifest(self, tmp_path: Path) -> None:
        model_dir = _create_fake_model_cache(tmp_path, "BAAI/bge-m3", weight_size=20 * 1024 * 1024)
        weight_file = model_dir / "snapshots" / "abc1234" / "model.safetensors"
        weight_hash = _sha256(weight_file)

        manifest = {
            "version": 1,
            "models": {
                "BAAI/bge-m3": {
                    "name": "BAAI/bge-m3",
                    "snapshots": {
                        "abc1234": [
                            {
                                "path": "models--BAAI--bge-m3/snapshots/abc1234/model.safetensors",
                                "size": weight_file.stat().st_size,
                                "sha256": weight_hash,
                            }
                        ]
                    }
                }
            }
        }
        (tmp_path / "ate_kb_model_manifest.json").write_text(json.dumps(manifest))

        errors = verify_manifest(tmp_path)
        assert len(errors) == 0

    def test_hash_mismatch(self, tmp_path: Path) -> None:
        _create_fake_model_cache(tmp_path, "BAAI/bge-m3", weight_size=20 * 1024 * 1024)

        manifest = {
            "version": 1,
            "models": {
                "BAAI/bge-m3": {
                    "name": "BAAI/bge-m3",
                    "snapshots": {
                        "abc1234": [
                            {
                                "path": "models--BAAI--bge-m3/snapshots/abc1234/model.safetensors",
                                "size": 20 * 1024 * 1024,
                                "sha256": "wrong_hash",
                            }
                        ]
                    }
                }
            }
        }
        (tmp_path / "ate_kb_model_manifest.json").write_text(json.dumps(manifest))

        errors = verify_manifest(tmp_path)
        assert any("SHA-256 mismatch" in e for e in errors)

    def test_no_manifest_skips(self, tmp_path: Path) -> None:
        errors = verify_manifest(tmp_path)
        assert len(errors) == 0

    def test_missing_file_in_manifest(self, tmp_path: Path) -> None:
        manifest = {
            "version": 1,
            "models": {
                "BAAI/bge-m3": {
                    "name": "BAAI/bge-m3",
                    "snapshots": {
                        "abc1234": [
                            {
                                "path": "models--BAAI--bge-m3/snapshots/abc1234/nonexistent.safetensors",
                                "size": 100,
                            }
                        ]
                    }
                }
            }
        }
        (tmp_path / "ate_kb_model_manifest.json").write_text(json.dumps(manifest))

        errors = verify_manifest(tmp_path)
        assert any("missing file" in e for e in errors)


class TestEndToEndPackaging:
    """Regression test: stage_models -> create_manifest -> verify_manifest."""

    def test_full_pipeline_passes(self, tmp_path: Path) -> None:
        """A correctly staged and manifest-ed cache must pass verification."""
        cache_dir = tmp_path / "cache"
        staging_dir = tmp_path / "staging"
        cache_dir.mkdir()
        staging_dir.mkdir()

        # Build a fake cache with both required models
        for model in ("BAAI/bge-m3", "BAAI/bge-reranker-v2-m3"):
            _create_fake_model_cache(cache_dir, model, weight_size=20 * 1024 * 1024)

        # Stage models into the staging directory
        manifest_entries, stage_errors = stage_models(cache_dir, staging_dir)
        assert len(stage_errors) == 0, f"Stage errors: {stage_errors}"
        assert len(manifest_entries) > 0

        # Write manifest into staging directory
        manifest_path = create_manifest(manifest_entries, staging_dir)
        assert manifest_path.exists()

        # The staged cache root is staging_dir / "embeddings" / "cache"
        # create_manifest already wrote the manifest into this directory.
        staged_cache = staging_dir / "embeddings" / "cache"

        # Run verify_manifest on the staged cache
        errors = verify_manifest(staged_cache)
        assert len(errors) == 0, f"Verify errors: {errors}"

    def test_tampered_weight_fails_manifest_verify(self, tmp_path: Path) -> None:
        """Tampering with a staged weight file must fail manifest verification."""
        cache_dir = tmp_path / "cache"
        staging_dir = tmp_path / "staging"
        cache_dir.mkdir()
        staging_dir.mkdir()

        for model in ("BAAI/bge-m3", "BAAI/bge-reranker-v2-m3"):
            _create_fake_model_cache(cache_dir, model, weight_size=20 * 1024 * 1024)

        manifest_entries, stage_errors = stage_models(cache_dir, staging_dir)
        assert len(stage_errors) == 0
        create_manifest(manifest_entries, staging_dir)

        staged_cache = staging_dir / "embeddings" / "cache"

        # Tamper: overwrite a weight file with different content
        weight_files = list(staged_cache.rglob("*.safetensors"))
        assert len(weight_files) > 0
        weight_files[0].write_bytes(b"\xff" * 20 * 1024 * 1024)

        # create_manifest already wrote the manifest into staged_cache
        errors = verify_manifest(staged_cache)
        assert any("SHA-256 mismatch" in e for e in errors)


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

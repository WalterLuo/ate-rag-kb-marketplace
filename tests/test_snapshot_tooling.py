"""Unit tests for Qdrant snapshot tooling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.package_qdrant_snapshot import create_snapshot, restore_snapshot


class TestCreateSnapshot:
    def test_create_and_download(self, tmp_path: Path) -> None:
        mock_create_resp = MagicMock()
        mock_create_resp.status_code = 200
        mock_create_resp.json.return_value = {
            "result": {"name": "ate_kb-20260611.snapshot"}
        }

        mock_list_resp = MagicMock()
        mock_list_resp.status_code = 200
        mock_list_resp.json.return_value = {
            "result": [
                {"name": "ate_kb-20260611.snapshot", "status": "green", "size": 1024}
            ]
        }

        mock_download_resp = MagicMock()
        mock_download_resp.status_code = 200
        mock_download_resp.iter_bytes.return_value = [b"snapshot-data"]

        mock_client = MagicMock()
        mock_client.post.return_value = mock_create_resp
        mock_client.get.return_value = mock_list_resp
        mock_client.stream.return_value.__enter__ = MagicMock(return_value=mock_download_resp)
        mock_client.stream.return_value.__exit__ = MagicMock(return_value=False)

        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        def client_side_effect(*args, **kwargs):
            return mock_client

        with patch("scripts.package_qdrant_snapshot.httpx.Client", side_effect=client_side_effect):
            result = create_snapshot(
                url="http://localhost:6333",
                collection="ate_kb",
                output_dir=str(tmp_path),
                poll_interval=0.01,
                timeout=5.0,
            )

        assert result.exists()
        assert result.name == "ate_kb-20260611.snapshot"

    def test_create_snapshot_http_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("scripts.package_qdrant_snapshot.httpx.Client", return_value=mock_client), \
             pytest.raises(RuntimeError, match="HTTP 500"):
            create_snapshot(url="http://localhost:6333")


class TestRestoreSnapshot:
    def test_restore_uses_post_multipart(self, tmp_path: Path) -> None:
        """restore_snapshot must POST with multipart 'snapshot' field, wait=true, and priority=snapshot."""
        snapshot_file = tmp_path / "test.snapshot"
        snapshot_file.write_bytes(b"snapshot-data")

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("scripts.package_qdrant_snapshot.httpx.Client", return_value=mock_client):
            restore_snapshot(
                snapshot_path=str(snapshot_file),
                url="http://localhost:6333",
                collection="ate_kb",
            )

        # Must call post (not put)
        mock_client.post.assert_called_once()
        mock_client.put.assert_not_called()

        # Verify multipart 'snapshot' field and query params
        call_kwargs = mock_client.post.call_args.kwargs
        assert "files" in call_kwargs
        assert "snapshot" in call_kwargs["files"]
        assert "params" in call_kwargs
        assert call_kwargs["params"]["wait"] == "true"
        assert call_kwargs["params"]["priority"] == "snapshot"

    def test_restore_with_custom_priority(self, tmp_path: Path) -> None:
        """restore_snapshot with priority='replica' must pass it in query params."""
        snapshot_file = tmp_path / "test.snapshot"
        snapshot_file.write_bytes(b"snapshot-data")

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("scripts.package_qdrant_snapshot.httpx.Client", return_value=mock_client):
            restore_snapshot(
                snapshot_path=str(snapshot_file),
                url="http://localhost:6333",
                collection="ate_kb",
                priority="replica",
            )

        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["params"]["priority"] == "replica"

    def test_restore_invalid_priority_raises(self, tmp_path: Path) -> None:
        """restore_snapshot with an invalid priority must raise ValueError."""
        snapshot_file = tmp_path / "test.snapshot"
        snapshot_file.write_bytes(b"snapshot-data")

        with pytest.raises(ValueError, match="Invalid priority"):
            restore_snapshot(
                snapshot_path=str(snapshot_file),
                priority="invalid",
            )

    def test_restore_snapshot_field_contains_filename(self, tmp_path: Path) -> None:
        """The multipart snapshot field must carry the original filename."""
        snapshot_file = tmp_path / "ate_kb-20260611.snapshot"
        snapshot_file.write_bytes(b"snapshot-data")

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("scripts.package_qdrant_snapshot.httpx.Client", return_value=mock_client):
            restore_snapshot(
                snapshot_path=str(snapshot_file),
                url="http://localhost:6333",
                collection="ate_kb",
            )

        call_kwargs = mock_client.post.call_args.kwargs
        snapshot_tuple = call_kwargs["files"]["snapshot"]
        # httpx files format: (filename, file_obj, content_type)
        assert snapshot_tuple[0] == "ate_kb-20260611.snapshot"
        assert snapshot_tuple[2] == "application/octet-stream"

    def test_restore_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="Snapshot file not found"):
            restore_snapshot(snapshot_path="/nonexistent/file.snapshot")

    def test_restore_http_error(self, tmp_path: Path) -> None:
        snapshot_file = tmp_path / "test.snapshot"
        snapshot_file.write_bytes(b"snapshot-data")

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("scripts.package_qdrant_snapshot.httpx.Client", return_value=mock_client), \
             pytest.raises(RuntimeError, match="HTTP 503"):
            restore_snapshot(snapshot_path=str(snapshot_file))

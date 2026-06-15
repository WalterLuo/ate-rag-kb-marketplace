#!/usr/bin/env python3
"""Qdrant collection snapshot tooling.

Create/download and upload/restore Qdrant collection snapshots via HTTP APIs.

Usage:
    # Create and download a snapshot from a running Qdrant server
    uv run python scripts/package_qdrant_snapshot.py create \\
        --url http://localhost:6333 --collection ate_kb --output dist

    # Upload and restore a snapshot to a running Qdrant server
    uv run python scripts/package_qdrant_snapshot.py restore \\
        --url http://localhost:6333 --collection ate_kb --snapshot dist/ate_kb.snapshot
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:6333"
_DEFAULT_COLLECTION = "ate_kb"
_DEFAULT_OUTPUT_DIR = "dist"


def create_snapshot(
    url: str = _DEFAULT_URL,
    collection: str = _DEFAULT_COLLECTION,
    output_dir: str = _DEFAULT_OUTPUT_DIR,
    filename: str | None = None,
    poll_interval: float = 2.0,
    timeout: float = 300.0,
) -> Path:
    """Create a snapshot on the Qdrant server and download it.

    Returns the path to the downloaded snapshot file.
    """
    base_url = url.rstrip("/")
    snapshot_url = f"{base_url}/collections/{collection}/snapshots"

    # Trigger snapshot creation
    logger.info("Creating snapshot for collection '%s' at %s", collection, base_url)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(snapshot_url)
        _check_response(resp, "create snapshot")

        data = resp.json()
        snapshot_name = data.get("result", {}).get("name")
        if not snapshot_name:
            raise RuntimeError(
                f"Snapshot creation response missing 'result.name': {resp.text[:500]}"
            )

    # Poll until the snapshot is ready
    logger.info("Snapshot '%s' creation started, polling for completion...", snapshot_name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with httpx.Client(timeout=30.0) as client:
            list_resp = client.get(snapshot_url)
            _check_response(list_resp, "list snapshots")
            snapshots = list_resp.json().get("result", [])
            for snap in snapshots:
                if snap.get("name") == snapshot_name:
                    status = snap.get("status", "unknown")
                    if status == "green" or "size" in snap:
                        break
            else:
                time.sleep(poll_interval)
                continue
            break
    else:
        raise TimeoutError(f"Snapshot '{snapshot_name}' not ready within {timeout}s")

    # Download the snapshot file
    download_name = filename or snapshot_name
    output_path = Path(output_dir) / download_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    download_url = f"{snapshot_url}/{snapshot_name}"
    logger.info("Downloading snapshot from %s to %s", download_url, output_path)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client, \
         client.stream("GET", download_url) as stream, \
         open(output_path, "wb") as f:
        _check_stream_response(stream, "download snapshot")
        for chunk in stream.iter_bytes(chunk_size=8192):
            f.write(chunk)

    logger.info("Snapshot downloaded: %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


def restore_snapshot(
    snapshot_path: str,
    url: str = _DEFAULT_URL,
    collection: str = _DEFAULT_COLLECTION,
    timeout: float = 300.0,
    priority: str = "snapshot",
) -> None:
    """Upload and restore a snapshot to a running Qdrant server.

    Args:
        snapshot_path: Path to the snapshot file.
        url: Qdrant server URL.
        collection: Collection name.
        timeout: HTTP request timeout in seconds.
        priority: Snapshot restore priority (snapshot, replica, no_sync).
    """
    valid_priorities = ("snapshot", "replica", "no_sync")
    if priority not in valid_priorities:
        raise ValueError(
            f"Invalid priority '{priority}'. Must be one of: {', '.join(valid_priorities)}"
        )

    base_url = url.rstrip("/")
    snapshot_file = Path(snapshot_path)
    if not snapshot_file.exists():
        raise FileNotFoundError(f"Snapshot file not found: {snapshot_file}")

    upload_url = f"{base_url}/collections/{collection}/snapshots/upload"

    logger.info(
        "Uploading snapshot '%s' to collection '%s' at %s (priority=%s)",
        snapshot_file.name,
        collection,
        base_url,
        priority,
    )
    with open(snapshot_file, "rb") as f, httpx.Client(timeout=timeout) as client:
        resp = client.post(
            upload_url,
            files={"snapshot": (snapshot_file.name, f, "application/octet-stream")},
            params={"wait": "true", "priority": priority},
        )
        _check_response(resp, "upload snapshot")

    logger.info("Snapshot restored successfully to collection '%s'", collection)


def _check_response(resp: httpx.Response, action: str) -> None:
    """Raise on non-200 HTTP response."""
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Failed to {action}: HTTP {resp.status_code} — {resp.text[:500]}"
        )


def _check_stream_response(stream: httpx.Response, action: str) -> None:
    """Raise on non-200 streaming HTTP response."""
    if stream.status_code >= 400:
        raise RuntimeError(
            f"Failed to {action}: HTTP {stream.status_code}"
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Qdrant collection snapshot tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create subcommand
    create_parser = subparsers.add_parser("create", help="Create and download a snapshot")
    create_parser.add_argument("--url", default=_DEFAULT_URL, help="Qdrant server URL")
    create_parser.add_argument("--collection", default=_DEFAULT_COLLECTION, help="Collection name")
    create_parser.add_argument("--output", default=_DEFAULT_OUTPUT_DIR, help="Output directory")
    create_parser.add_argument("--filename", default=None, help="Custom snapshot filename")

    # restore subcommand
    restore_parser = subparsers.add_parser("restore", help="Upload and restore a snapshot")
    restore_parser.add_argument("--url", default=_DEFAULT_URL, help="Qdrant server URL")
    restore_parser.add_argument("--collection", default=_DEFAULT_COLLECTION, help="Collection name")
    restore_parser.add_argument("--snapshot", required=True, help="Path to snapshot file")
    restore_parser.add_argument(
        "--priority",
        choices=["snapshot", "replica", "no_sync"],
        default="snapshot",
        help="Restore priority (default: snapshot)",
    )

    args = parser.parse_args()

    if args.command == "create":
        path = create_snapshot(
            url=args.url,
            collection=args.collection,
            output_dir=args.output,
            filename=args.filename,
        )
        print(f"Snapshot saved to: {path}")
    elif args.command == "restore":
        restore_snapshot(
            snapshot_path=args.snapshot,
            url=args.url,
            collection=args.collection,
            priority=args.priority,
        )
        print("Snapshot restored successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

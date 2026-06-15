# Third-Party Notices

This repository contains the ATE RAG KB application code. It does not include
third-party ATE vendor documentation, converted Markdown copies of vendor
manuals, images extracted from vendor documentation, model weights, or Qdrant
database snapshots.

Users are responsible for ensuring they have the right to ingest, store, and
query any documentation they place under `data/raw/`.

## Runtime Dependencies

The project depends on Python packages declared in `pyproject.toml` and locked
in `uv.lock`, including FastAPI, Qdrant Client, Sentence Transformers,
Rank-BM25, NumPy, Pydantic, PyYAML, Markdown, Beautiful Soup, HTTPX,
Structlog, and MCP.

Before redistributing packaged builds, generate a dependency license report
from the exact locked environment and review it with your organization's
open-source compliance process.

## Models

The default configuration references the following Hugging Face model IDs:

- `BAAI/bge-m3`
- `BAAI/bge-reranker-v2-m3`

Model files are not committed to this repository. Review and comply with each
model's upstream license before downloading, caching, or redistributing model
artifacts.

## Infrastructure

The Docker Compose example uses the `qdrant/qdrant` container image. Review
Qdrant's upstream license and container image terms before redistribution.

## Excluded Vendor Content

Do not commit or publish:

- ATE vendor manuals, help systems, release notes, application notes, or other
  documentation unless you have explicit redistribution rights.
- Markdown, JSON, images, or other files converted from restricted vendor
  documentation.
- Qdrant collections or vector snapshots built from restricted documentation.
- Local model caches under `embeddings/cache/`.

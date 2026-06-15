# Multi-Platform Retrieval Coordinator Design

## Objective

Make ATE KB answers complete and platform-correct across the Teradyne J750
platform with IG-XL and the Advantest V93000 platform with SMT7 or SMT8.
Explicit platform or software queries must never mix documentation from another
platform. Neutral technical questions must support controlled comparison
answers without allowing one platform's documents to crowd out the other.

The existing SMT7 answer quality is the regression baseline. The design extends
that behavior to IG-XL while preserving the current broad-answer assembly,
citations, diagnostics, and source-hint-free retrieval policy.

## Domain Model

The current metadata model mixes platform names and software names. The target
model separates vendor, tester platform, software product, and release:

| Field | Examples | Meaning |
| --- | --- | --- |
| `vendor` | `advantest`, `teradyne` | Tester vendor |
| `platform` | `v93000`, `j750` | Tester platform |
| `software` | `smt7`, `smt8`, `igxl` | Software product used with the platform |
| `software_release` | `7.4.3`, `8.x`, `3.60.00` | Product release when known |
| `doc_family` | `smt_help`, `tdc`, `vbt`, `datatool`, `patternlanguage` | Documentation family |

The supported hierarchy is:

```text
Advantest
└── V93000
    ├── SMT7
    └── SMT8

Teradyne
└── J750
    └── IG-XL
```

The existing `ecosystem` and `software_version` payload fields remain readable
during migration so existing collections and tests can be diagnosed. New
ingestion writes the normalized fields. Retrieval routing uses the normalized
fields as the authoritative scope once the collection has been rebuilt.

`software_release` replaces the overloaded release meaning of
`software_version`. The new `software` field carries `igxl`, `smt7`, or `smt8`.

## Priority

The implementation order changes from the earlier two-phase proposal:

```text
P0  Preserve the usable SMT7 baseline with regression tests
P1  Phase 1.5: normalize metadata, repair IG-XL graph ingestion, rebuild indexes
P2  Introduce the Retrieval Coordinator and route every MCP entry through it
P3  Validate IG-XL completeness, cross-platform isolation, and comparison answers
```

The Retrieval Coordinator is higher priority than the previously deferred
architectural cleanup, but it must follow metadata normalization. Building the
coordinator on the current mixed model would preserve ambiguous routing rules
inside a cleaner wrapper.

## Retrieval Scopes

Introduce a `RetrievalScope` value object:

```python
RetrievalScope(
    vendor="teradyne",
    platform="j750",
    software="igxl",
)
```

or:

```python
RetrievalScope(
    vendor="advantest",
    platform="v93000",
    software="smt7",
)
```

Each scope becomes a Qdrant payload filter before dense and sparse retrieval.
Post-retrieval filtering remains as a defensive assertion and diagnostic, not
as the main isolation mechanism.

Graph expansion, reranking, parent-child enrichment, broad-context assembly,
and compression operate independently within each scope. A comparison answer
merges already-isolated context packages after each scope completes.

## Query Routing Rules

The planner resolves a query into one of three outcomes:

```text
resolved scopes
clarification request
corrected resolved scope
```

The routing rules are:

| Query condition | Required behavior |
| --- | --- |
| Mentions `IG-XL` or `J750` | Search only `teradyne / j750 / igxl` |
| Mentions `SMT7` | Search only `advantest / v93000 / smt7` |
| Mentions `SMT8` | Search only `advantest / v93000 / smt8` |
| Mentions only `V93000`, with only SMT7 enabled | Search only `advantest / v93000 / smt7` |
| Mentions only `V93000`, with SMT7 and SMT8 enabled | Ask whether the user wants SMT7 or SMT8 |
| Does not name a platform, but contains an exclusive symbol | Route directly to the symbol owner's software |
| Names a platform or software that conflicts with an exclusive symbol | Explain the correction and search only the symbol owner's software |
| Is neutral, with the current enabled set of IG-XL and SMT7 | Search both scopes and return a two-section comparison answer |
| Is neutral after SMT8 is enabled | Ask whether the user wants J750 or V93000; if V93000 is selected, ask SMT7 or SMT8 |
| Explicitly requests two or more platforms or software products | Search the requested scopes and return a comparison answer |
| Follow-up says only `I need the SMT7 answer` | Search only `advantest / v93000 / smt7` without asking again |

The current default comparison sections are:

```text
J750 / IG-XL
V93000 / SMT7
```

When a user explicitly requests multiple scopes, the answer contains one
section per requested scope. The coordinator does not silently add another
scope.

## Symbol Ownership Catalog

Exclusive API routing must not rely on a manually maintained source-hint table.
Build a symbol catalog during ingestion from documentation titles, API reference
pages, method format sections, and command headings.

Representative catalog entries:

```text
SelectFirst                  -> teradyne / j750 / igxl
SelectNext                   -> teradyne / j750 / igxl
ON_FIRST_INVOCATION_BEGIN    -> advantest / v93000 / smt7
FOR_EACH_SITE_BEGIN          -> advantest / v93000 / smt7
```

The catalog stores normalized symbols, their owning scopes, and supporting
`source_md` references for diagnostics. Query planning uses exact symbol
matches only when determining exclusive ownership. The catalog narrows the
search scope; it does not inject answer documents or bypass normal ranking.

If a symbol exists under more than one enabled scope, the symbol is not
exclusive and cannot force automatic narrowing.

Example:

```text
User: IG-XL 中 ON_FIRST_INVOCATION_BEGIN 怎么用？
System: ON_FIRST_INVOCATION_BEGIN belongs to V93000 / SMT7, not J750 / IG-XL.
        Answering from V93000 / SMT7 documentation.
```

## Unified Retrieval Coordinator

Introduce one coordinator used by MCP `search`, `retrieve`, and `ask`.
The coordinator owns planning, clarification, scoped execution, merging, and
stats. Existing retrieval components remain responsible for their specialized
stages.

```text
query
-> planner: infer explicit platform/software terms and symbol ownership
-> route: return clarification or one/more RetrievalScope values
-> for each scope:
     hybrid dense + sparse retrieval with scope filter
     -> scoped graph expansion
     -> rerank
     -> parent-child enrichment
     -> broad-context assembly when needed
     -> compression
     -> scoped context package and stats
-> merge isolated context packages
-> build answer contract
```

The coordinator prevents the current divergence where MCP handlers and
pipeline entry points apply overlapping but non-identical logic. It also makes
comparison behavior explicit instead of treating neutral queries as one shared
candidate pool.

## IG-XL Completeness Repairs

IG-XL cannot reach SMT7-level completeness until its documentation graph and
lexical retrieval are repaired.

### Markdown Link Graph

The current graph builder recognizes only `.htm` and `.html` links. IG-XL
markdown contains relative `.md` links such as:

```text
[SelectNext](execSites.39.09.md)
```

The graph parser must resolve local `.md`, `.htm`, and `.html` links relative to
the current source document. Graph nodes and edges retain normalized
`source_md` paths. Expansion rejects neighbors outside the active
`RetrievalScope`.

After rebuild, chains such as the following must be reachable:

```text
SelectFirst
-> SelectNext
-> Programming Examples
-> Looping Through Sites
```

### Sparse Retrieval

Full ingestion rebuilds the sparse vocabulary from the enabled corpus and
writes sparse vectors for every chunk. Runtime diagnostics must distinguish:

```text
sparse_search_used
sparse_candidate_count
legacy_bm25_fallback_used
```

The legacy BM25 fallback remains available for compatibility, but acceptance
requires corpus-wide sparse retrieval to be active for the production
collection.

### Glossary Expansion

Add concept-level multilingual expansions for IG-XL without adding source
hints. For example:

```text
多 site 串行处理
-> serial site loop
-> SelectFirst
-> SelectNext
-> LoopStatus
-> loopDone
```

Glossary entries may improve recall and title boosting. They must not point to
specific markdown paths.

## MCP Contract

MCP continues returning grounded context for agent synthesis. Extend processing
and answer contracts so agents can distinguish direct answers, comparisons,
clarifications, and corrected queries.

Representative response fields:

```json
{
  "answer_contract": {
    "answer_mode": "direct | platform_comparison | clarification",
    "resolved_scopes": [
      {
        "vendor": "teradyne",
        "platform": "j750",
        "software": "igxl"
      }
    ],
    "correction_notice": "",
    "clarification_prompt": "",
    "required_sections": [],
    "coverage_topics_by_scope": {}
  },
  "processing": {
    "processing_by_scope": {},
    "cross_scope_dropped_chunk_count": 0
  }
}
```

For comparison answers, source citations and coverage topics stay grouped by
scope. Agents must produce visibly separated answer sections and avoid
combining API names from different software products into one code example.

## Migration Strategy

Use a controlled rebuild:

1. Add normalized metadata fields and payload indexes.
2. Increment `ingestion.schema_version`.
3. Rebuild the document graph with `.md` support.
4. Rebuild sparse vocabulary.
5. Clear and fully reingest the Qdrant collection.
6. Validate chunk counts and metadata distribution.
7. Restart the MCP server so it loads the rebuilt graph and catalog.
8. Run isolation, comparison, and SMT7 baseline acceptance tests.

The rebuild is intentional. Updating only planner code would leave existing
Qdrant payloads and graph edges inconsistent with the new routing model.

## Diagnostics

Expose per-scope observability:

```text
resolved_scopes
scope_filters
dense_candidate_count
sparse_candidate_count
graph_expanded_source_count
post_rerank_source_count
final_context_source_count
coverage_topics
cross_scope_dropped_chunk_count
correction_notice
clarification_prompt
```

For explicit single-scope answers, `cross_scope_dropped_chunk_count` should
normally be zero because filtering happens before search. A nonzero value
indicates stale payloads, graph contamination, or a defensive post-filter
removal.

## Acceptance Matrix

The implementation is complete only when all rows pass through MCP without
manual source hints or raw markdown fallback.

| Query | Expected outcome |
| --- | --- |
| `IG-XL 多 site 串行处理` | IG-XL-only answer with `SelectFirst`, `SelectNext`, and example coverage |
| `J750 多 site 串行处理` | Same IG-XL-only behavior |
| `SMT7 多 site 串行处理` | SMT7-only answer without IG-XL citations |
| `V93000 多 site 串行处理`, only SMT7 enabled | SMT7-only answer |
| `多 site 串行处理`, current configuration | Two sections: J750 / IG-XL and V93000 / SMT7 |
| `SelectFirst 怎么用` | Automatically narrow to IG-XL |
| `ON_FIRST_INVOCATION_BEGIN 怎么用` | Automatically narrow to SMT7 |
| `IG-XL 中 ON_FIRST_INVOCATION_BEGIN 怎么用` | Return correction notice and SMT7-only answer |
| `V93000 多 site 怎么处理`, SMT7 and SMT8 enabled | Ask whether the user wants SMT7 or SMT8 |
| Neutral query after SMT8 is enabled | Ask whether the user wants J750 or V93000 |
| Follow-up `我需要 SMT7 的答案` | Direct SMT7-only answer |
| Explicit request for both J750 and SMT7 answers | Two isolated answer sections |

Retain the current SMT7 broad-concept, Site Control, and ARRAY acceptance cases
as regression tests. ARRAY answers must continue citing ARRAY-specific sources.

## Non-Goals

- Do not introduce hardcoded source markdown hints.
- Do not synthesize final natural-language answers inside the KB service.
- Do not silently combine SMT7 and SMT8 when a V93000 software version is
  ambiguous.
- Do not remove legacy metadata fields until the rebuilt collection and
  migration tests are stable.
- Do not optimize for additional tester platforms before J750 / IG-XL and
  V93000 / SMT7 isolation is proven.

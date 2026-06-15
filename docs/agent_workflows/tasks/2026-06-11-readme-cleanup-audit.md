# Codex Task Package

## Status

`ready_for_claude`

## Owner Handoff

- Planner and reviewer: Codex
- Implementer: Claude Code
- Integration owner: Codex

## Branch

`codex/readme-cleanup-audit`

Claude Code should create or switch to this branch from the current repository
state before editing:

```bash
git switch -c codex/readme-cleanup-audit
```

If the branch already exists, switch to it instead:

```bash
git switch codex/readme-cleanup-audit
```

## Objective

Audit and tighten the repository-facing documentation and cleanup guidance:

1. Decide whether `README.md` and `README_CN.md` still need updates after the
   recent cloud API, Qdrant snapshot, license, and handoff workflow changes.
2. Identify useless or redundant files under the project path that can be
   deleted, while protecting local ATE source data and user-specific
   configuration.
3. Fix small repository hygiene issues that make the README and handoff
   workflow inconsistent with the actual tracked files.

## Context

Codex performed a preliminary audit on 2026-06-11.

Current repository observations:

- `README.md` and `README_CN.md` are mostly current for server-mode Qdrant,
  cloud embedding/reranking providers, Qdrant snapshot packaging, agent
  integration, and license notes.
- `README.md` and `README_CN.md` link to `LICENSE` and `THIRD_PARTY.md`, but
  both files are currently untracked. They should be kept and committed, not
  deleted.
- `README.md` says private conversion scripts may live under `scripts/local/`,
  but `.gitignore` does not currently ignore `scripts/local/`.
- `README.md` says converted Markdown/JSON/assets and vector DB snapshots
  should not be committed. `.gitignore` ignores `data/raw/assets/`,
  `data/raw/json/`, and generated DB paths, but it does not ignore
  `data/raw/markdown/`; consequently local converted Markdown appears as
  untracked content.
- `docs/agent_workflows/codex_claude_handoff.md` exists but is untracked.
  It references `docs/agent_workflows/templates/claude_task.md` and
  `.claude/commands/execute-codex-task.md`; those files are missing.
- `.gitignore` currently ignores all of `.claude/`, which prevents a repository
  `.claude/commands/execute-codex-task.md` command from being tracked.
- `scripts/rebuild_sparse_vectors.py` is untracked. It may be a useful
  maintenance script, but it needs either documentation/tests or explicit
  removal.
- Large local/generated directories found during the audit:
  - `dist/` about 9.4 GB
  - `embeddings/cache/` about 6.4 GB
  - `data/qdrant_storage/` about 3.3 GB, deprecated local-mode data
  - `data/qdrant_server/` about 1.9 GB, active Docker server-mode volume
  - `.venv/` about 850 MB
  - `.mypy_cache/` about 112 MB
  - `data/processed/` about 20 MB
  - `data/raw/` about 526 MB, local source/converted ATE content

Important safety rule:

- Do not delete local ATE source docs or converted assets unless the task owner
  explicitly confirms they are backed up and no longer needed. In this repo
  that means treating `data/raw/markdown/`, `data/raw/json/`,
  `data/raw/assets/`, `data/raw/toc_tree.json`, and `data/raw/href_map.json`
  as local input artifacts, not disposable cache.

## Scope

Allowed changes:

- Update `README.md` and `README_CN.md` only where the audit shows drift or
  missing cleanup guidance.
- Update `.gitignore` to match the documented repository policy.
- Keep and stage `LICENSE` and `THIRD_PARTY.md` if the README links remain.
- Add the missing handoff support files if keeping
  `docs/agent_workflows/codex_claude_handoff.md`:
  - `docs/agent_workflows/templates/claude_task.md`
  - `.claude/commands/execute-codex-task.md`
- Commit or deliberately remove `docs/agent_workflows/codex_claude_handoff.md`
  based on whether the workflow should be retained. The user explicitly asked
  to use this workflow, so the expected path is to keep it and make it complete.
- Decide whether `scripts/rebuild_sparse_vectors.py` should be kept. If kept,
  document it in the development or maintenance section and add focused test
  coverage where practical. If removed, explain why in the report.
- Remove only clearly disposable generated files from the working tree after
  confirmation in this task package:
  - `.DS_Store` files
  - `.coverage`
  - Python `__pycache__/` directories outside `.venv/`
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `.mypy_cache/`
  - `htmlcov/`
  - `reports/`
  - `dist/`
  - `data/qdrant_storage/` because local Qdrant mode is deprecated

Outcomes may be either:

- Documentation-only, with a clear cleanup list and no deletions, or
- Documentation plus safe generated-file cleanup.

Use judgment, but do not delete source data or user configuration.

## Out Of Scope

- Do not change retrieval behavior, ingestion behavior, MCP behavior, or API
  contracts.
- Do not re-ingest data.
- Do not rebuild Qdrant collections.
- Do not modify `data/raw/markdown/`, `data/raw/json/`, or `data/raw/assets/`
  except removing nested `.DS_Store` files.
- Do not delete `.mcp.json`, `.claude/settings.local.json`, or other
  user-specific agent configuration.
- Do not commit generated data, converted vendor docs, model cache files,
  Qdrant volumes, snapshots, or packaged archives.
- Do not answer ATE technical documentation questions from raw files or memory;
  preserve the ATE KB MCP-first policy in `AGENTS.md` and `CLAUDE.md`.

## Implementation Requirements

1. Read `AGENTS.md`, `CLAUDE.md`, this task package, and
   `docs/agent_workflows/codex_claude_handoff.md` before editing.
2. Start from a clean understanding of current git state:

   ```bash
   git status --short
   git status --ignored --short -- .DS_Store .coverage .mypy_cache .pytest_cache .ruff_cache .venv dist htmlcov reports embeddings/cache data/processed data/qdrant_server data/qdrant_storage data/raw/markdown data/raw/assets data/raw/json docs/agent_workflows/codex_claude_handoff.md LICENSE THIRD_PARTY.md scripts/rebuild_sparse_vectors.py
   ```

3. If retaining the handoff workflow, make it internally consistent:
   - Add `docs/agent_workflows/templates/claude_task.md`.
   - Add `.claude/commands/execute-codex-task.md`.
   - Adjust `.gitignore` so repository commands under `.claude/commands/` can
     be tracked while local Claude settings remain ignored.
4. Align `.gitignore` with README policy:
   - Ignore `scripts/local/`.
   - Ignore local converted/vendor source artifacts that should not be committed
     unless there is an explicit redistribution decision. At minimum review
     whether `data/raw/markdown/` should be ignored because both READMEs state
     local source Markdown docs should not be committed.
5. Review `README.md` and `README_CN.md` for these exact questions:
   - Do they accurately describe what data is committed versus local-only?
   - Do they mention the large local/generated directories enough for users to
     know what can be deleted and regenerated?
   - Do they link only to files that will be tracked?
   - Do they need a short "Repository Cleanup" or equivalent section?
   - Are English and Chinese versions semantically aligned?
6. Treat `LICENSE` and `THIRD_PARTY.md` as useful repository files. Do not
   delete them unless also removing the README license section.
7. Decide what to do with `scripts/rebuild_sparse_vectors.py`:
   - Keep it only if it is documented and safe for server-mode Qdrant.
   - Otherwise remove it as an untracked maintenance experiment.
8. If deleting generated files, delete only the safe generated paths listed in
   Scope. Before deleting, run a dry run and include the output summary in the
   report:

   ```bash
   git clean -ndX
   ```

   Do not run broad `git clean -fdx` because it would remove local source data
   and configuration.
9. Keep the final diff focused. Do not modify unrelated docs or code.

## Acceptance Criteria

- `README.md` and `README_CN.md` are either unchanged with a justified report,
  or updated to reflect current repository cleanup and local-data policy.
- English and Chinese README content remains aligned for any changed sections.
- `LICENSE` and `THIRD_PARTY.md` are not left as broken README links.
- The Codex-Claude handoff workflow is either completed with its missing
  template/command files, or the report explains why the workflow file should
  not be retained.
- `.gitignore` no longer conflicts with README guidance for `scripts/local/`,
  `.claude/commands/`, and local converted documentation.
- The report clearly classifies cleanup candidates into:
  - safe to delete immediately,
  - delete only if regenerate/backed up,
  - do not delete.
- No local ATE source data, model cache, Qdrant server volume, or user-specific
  MCP/Claude configuration is deleted without explicit justification.
- `AGENTS.md` and `CLAUDE.md` ATE KB MCP-first instructions remain intact.
- Required verification commands are run and their results are reported.

## Required Verification Commands

Run:

```bash
uv run ruff check src/ tests/
uv run pytest tests/test_plugin_install.py tests/test_utils_paths.py tests/test_model_packaging.py -q
git status --short
git diff --stat
```

If README or workflow-only changes make Python tests unnecessary, still run
`uv run ruff check src/ tests/` and explain any skipped tests in the report.

If `.gitignore` changes affect ignored/generated files, also run:

```bash
git status --ignored --short -- data/raw/markdown data/raw/assets data/raw/json scripts/local .claude docs/agent_workflows LICENSE THIRD_PARTY.md
git clean -ndX
```

Do not run destructive cleanup commands unless the paths are limited to the
safe generated-file list in this task package.

## Expected Report Path

Write the completion report to:

```text
docs/agent_workflows/reports/2026-06-11-readme-cleanup-audit.md
```

Use `docs/agent_workflows/templates/claude_report.md` as the report structure.

## Integration Instructions For Codex

After Claude Code reports completion, Codex must:

1. Verify the branch is `codex/readme-cleanup-audit`.
2. Review `git diff` for scope control.
3. Confirm README links resolve to tracked files.
4. Confirm `.gitignore` does not hide files that should be committed.
5. Confirm no local source docs or user config were deleted.
6. Run or inspect the required verification evidence.
7. Request changes or approve for commit/merge.

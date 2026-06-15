# Codex-Claude Handoff Workflow

This workflow coordinates Codex and Claude Code for semi-automatic development
inside this repository.

Codex owns requirements, planning, review, commit, and merge. Claude Code owns
branch creation, implementation, local verification, and completion reporting.

The canonical flow is:

```text
Codex clarifies the task
-> Codex writes a task package
-> User runs Claude Code with the task package
-> Claude Code creates a branch, implements, tests, and reports
-> Codex reviews report, diff, and checks
-> Codex requests changes or commits and merges
```

## Files

| Path | Purpose |
|---|---|
| `docs/agent_workflows/tasks/` | Codex-authored task packages |
| `docs/agent_workflows/reports/` | Claude-authored completion reports |
| `docs/agent_workflows/templates/claude_task.md` | Task package template |
| `docs/agent_workflows/templates/claude_report.md` | Completion report template |
| `.claude/commands/execute-codex-task.md` | Claude Code slash command |

## Lifecycle States

| State | Owner | Meaning |
|---|---|---|
| `draft_task` | Codex | Requirements and implementation instructions are being written |
| `ready_for_claude` | Codex | The task package is ready for Claude Code |
| `claude_working` | Claude Code | Claude Code is implementing on the requested branch |
| `codex_review` | Codex | Claude Code has written a report and Codex is reviewing |
| `changes_requested` | Codex | Codex found issues and asks Claude Code to revise |
| `approved` | Codex | Review passed and the branch is ready for integration |
| `integrated` | Codex | Codex committed and merged the approved work |

## Codex Responsibilities

Codex must:

- Clarify the user's goal, constraints, and acceptance criteria.
- Write a task package under `docs/agent_workflows/tasks/`.
- Include the branch name, exact scope, likely files, required verification
  commands, and expected report path.
- Preserve the repository's ATE KB MCP-first policy.
- Review Claude Code's report, git diff, and verification evidence.
- Request follow-up changes when scope, tests, or behavior are incomplete.
- Commit and merge only after review passes.

Codex must not:

- Treat a Claude Code report as proof without checking the diff and evidence.
- Merge work that includes unrelated file changes.
- Bypass the review gate because tests were reported as passing.

## Claude Code Responsibilities

Claude Code must:

- Read `CLAUDE.md`, `AGENTS.md`, and the task package before editing.
- Create or switch to the branch named in the task package.
- Follow existing project structure and coding style.
- Keep changes inside the task scope.
- Run the required verification commands from the task package.
- Run additional focused checks when the changed code needs them.
- Write a report under `docs/agent_workflows/reports/`.

Claude Code must not:

- Commit, merge, push, or open a pull request unless the task package explicitly
  authorizes it.
- Revert unrelated user changes.
- Modify generated data, external dependencies, or broad project configuration
  unless requested.
- Answer ATE documentation questions from memory, web search, raw grep, or raw
  markdown before using the configured ATE KB MCP path.

## Task Package Rules

Task packages should be named:

```text
docs/agent_workflows/tasks/YYYY-MM-DD-<task-slug>.md
```

Each task package must include:

- Status.
- Owner handoff.
- Branch name.
- Objective.
- Context.
- Scope.
- Out-of-scope items.
- Implementation requirements.
- Acceptance criteria.
- Required verification commands.
- Expected report path.

## Report Rules

Reports should be named:

```text
docs/agent_workflows/reports/YYYY-MM-DD-<task-slug>.md
```

Each report must include:

- Branch name.
- Summary.
- Changed files.
- Verification commands and outcomes.
- Acceptance criteria checklist.
- Risks or skipped checks.
- Recommended next action.

## Claude Code Invocation

From Claude Code in this repository, run:

```text
/execute-codex-task docs/agent_workflows/tasks/YYYY-MM-DD-<task-slug>.md
```

The slash command tells Claude Code how to consume the task package and produce
the report.

## Codex Review Checklist

Before approving, Codex must verify:

- The current branch matches the task package.
- `git diff` matches the requested scope.
- No unrelated user changes were reverted or included.
- Required checks were run and reported.
- Any skipped checks are justified.
- The acceptance criteria are satisfied.
- The report path matches the task package.
- Existing ATE KB MCP-first instructions remain intact.

If any item fails, Codex sets the workflow state to `changes_requested` and
writes concrete follow-up instructions for Claude Code.

## Integration

After approval, Codex may:

1. Stage only the approved files.
2. Commit with a focused message.
3. Merge the branch according to the user's preferred git policy.
4. Report the final commit and merge status to the user.

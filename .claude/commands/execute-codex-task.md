# Execute a Codex task package

Read and execute the Codex task package at the given path.

## Arguments

- $TASK_PATH: Path to the task package markdown file (required)

## Instructions

1. Read the task package at `$TASK_PATH`.
2. Read `AGENTS.md` and `CLAUDE.md` for project context.
3. Confirm the task status is `ready_for_claude`. If not, ask the user before proceeding.
4. Create or switch to the branch named in the task package.
5. Follow the implementation requirements exactly.
6. Stay within the specified scope. Do not make changes listed as out of scope.
7. Run all required verification commands from the task package.
8. Write the completion report to the expected report path using the
   `docs/agent_workflows/templates/claude_report.md` template.
9. Set the task package status to `claude_working` while implementing.
10. Do not commit, merge, push, or open a pull request unless the task package
    explicitly authorizes it.

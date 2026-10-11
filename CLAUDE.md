# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- **Hooks** (`.claude/settings.json`): `SessionStart` prints the current branch, the branch's handoff doc and
  uncommitted files. `PreToolUse` blocks Edit/Write on `main`. If an edit gets blocked, don't work around
  it. Run `scripts/start-task.sh` (with `--worktree` on the Fable laptop) and continue there.
- **Start of session:** the SessionStart output is your handoff. Confirm it against `git log`, then work on its "Next steps".
- **Plan first** (plan mode) for anything touching more than two files, any `[contract]` change, and anything in
  `negotiation/` (gate, router, hash). Implement only after the plan matches the PRD section it cites.
- **Subagents:** use read-only explore or investigator agents to find code. Keep edits in the main thread so
  ownership rules stay visible. Don't spawn agents to edit other workstreams' files.
- **Codex interop:** to get a second opinion or hand a task to Codex, first update the handoff doc and commit.
  Codex reads `AGENTS.md` and the same handoff file. Don't depend on Claude chat history.
- **On Ali's Fable laptop:** use the Fable model for the work listed in AGENTS.md §5. Borrowed sessions run in
  a separate worktree under `../rotation-wt/` and commit with the borrower's `--author`.
- **Before ending:** update "Current state" in the handoff doc, run `scripts/handoff.sh claude-code "<status>"`, then commit and push.

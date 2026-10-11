# Handoff: chore/rohaan-agent-workflow

| Field | Value |
|---|---|
| Branch | `chore/rohaan-agent-workflow` |
| Owner | rohaan |
| Workstream / queue item | chore / <!-- e.g. B4, C2, D3, A3 --> |
| PRD sections | <!-- e.g. §6.7, §6.8, AC-006, AC-027 --> |
| Created | 2026-10-10T06:46Z |

## Goal

Team workflow: AGENTS.md/CLAUDE.md, enforced feature branches (git + Claude hooks), per-branch handoff docs for Claude Code ↔ Codex ↔ other tools.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR

**Done:**
- AGENTS.md, CLAUDE.md, .claude/settings.json hooks, .githooks/{pre-commit,pre-push}, scripts/{setup,start-task,handoff,check,lib}.sh, .gitignore, handoff TEMPLATE
- Tested in scratch clone: main commit/push blocked, Claude edit guard, worktree start, ownership warning, .env block, handoff snapshot

**In progress (exact file/function, what's half-finished):**
- 

**Next steps (ordered, concrete):**
1. Team reviews AGENTS.md §2 ownership + §5 Fable routing, merge PR
2. Everyone: pull main, run scripts/setup.sh
3. Tisha (repo owner): enable GitHub branch protection on main (require PR)

**Decisions and why:**
- 

**Gotchas / traps:**
- 

**How to verify:**
```bash

```

**Asks for other owners (file, owner, what, why):**
- 

**Open questions (with the PRD's provisional answer if any):**
- 

## Session log  (append-only; `scripts/handoff.sh` adds entries)

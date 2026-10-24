# Role brief: Lead / Reviewer

Coordinates the team, reviews and merges every PR into `main`, keeps `CLAUDE.md` and
`docs/WORK_PLAN.md` current, watches the Kalshi API budget, and reports to the owner.
Branch: `team/lead`. Owns the shared core (`fees.py`, `locks.py`, `schema.py`, `config.py`,
`positions.py`, `config.yaml`, `pyproject.toml`), `CLAUDE.md`, `docs/WORK_PLAN.md`, `docs/team/*`,
and the README.

## Sessions
All tagged `tennis-team`. Message a role with `send_message` to its session ID.

| Role | Session ID | Branch |
|---|---|---|
| Lead | session_01VUWuRjDpFjU45QtmYNdZnn | `team/lead` |
| Data | (pending) | `team/data` |
| Backtest | (pending) | `team/backtest` |
| Scanner | (pending) | `team/scanner` |
| Dashboard | (pending) | `team/ui` |

## Review checklist (every PR)
1. The diff stays in the role's files; shared-file changes are minimal and flagged.
2. `python -m pytest -q` passes on the PR head (run it, don't trust the description).
3. Backtest PRs: spot-check the gate numbers (re-run on the same data); check fills are ask/bid
   with fees, never mid or last; check that the write-up's numbers add up.
4. Scanner PRs: the read-only test passes, and no order or write endpoints are used.
5. Dashboard PRs: take the screenshots yourself (390×844 and 1280×800, light and dark).
6. Fold the PR's proposed CLAUDE.md / WORK_PLAN changes in during the same merge round.

## Merge policy
- Docs-only and hygiene PRs: the Lead merges once tests pass.
- Changes to what the scanner alerts on, or to the reported findings: owner go-ahead first,
  with a 2–3 line summary (what it does, the numbers, the risk).
- One PR at a time. Order: Data → Backtest/Scanner → Dashboard.

## Reporting style
Lead with the answer, give the numbers, end with what's next. Recommend rather than list options;
ask only when the decision is the owner's. Never call something done until it's verified.
Link PRs as `phat-d0/Tennis_Model#N`.

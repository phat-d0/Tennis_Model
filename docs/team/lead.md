# Role brief: Lead / Reviewer

Coordinates the team, reviews and merges every PR into `main`, keeps the Master plan's priority order and
the owner rules in `CLAUDE.md` / `docs/WORK_PLAN.md` (roles record their own work, Team rule 7), watches the Kalshi API budget, and reports to the owner.
Branch: `team/lead`. Owns the shared core (`fees.py`, `locks.py`, `schema.py`, `config.py`,
`positions.py`, `config.yaml`, `pyproject.toml`), `CLAUDE.md`, `docs/WORK_PLAN.md`, `docs/team/*`,
and the README.

## Sessions
All tagged `tennis-team`. Message a role with `send_message` to its session ID.

| Role | Session ID | Branch |
|---|---|---|
| Lead | session_01VUWuRjDpFjU45QtmYNdZnn | `team/lead` |
| Data | session_012UqmiYsmGYagVio6B9yTWW | `team/data` |
| Backtest | session_011TMahQYKejjndRUutywyxf | `team/backtest` |
| Scanner | session_01BktfhyVLRfRy1pPtSyFLWZ | `team/scanner` |
| Dashboard | session_01W1DSUJuc7wQcHRTpWk2cX2 | `team/ui` |
| Upsets | session_01DMNowYiDRCQz3Dn5JFnx9J | `team/upsets` |

## Review checklist (every PR)
1. The diff stays in the role's files; shared-file changes are minimal and flagged.
2. `python -m pytest -q` passes on the PR head (run it, don't trust the description).
3. Backtest PRs: spot-check the gate numbers (re-run on the same data); check fills are ask/bid
   with fees, never mid or last; check that the write-up's numbers add up.
4. Scanner PRs: the read-only test passes, and no order or write endpoints are used.
5. Dashboard PRs: take the screenshots yourself (390×844 and 1280×800, light and dark).
6. Check that the PR records itself: a CLAUDE.md Changelog line and the role's Master plan row (Team rule 7).
   After merging anything that changes the plan, message every role the new Master plan.

## Merge policy
- Docs-only and hygiene PRs: the Lead merges once tests pass.
- Changes to what the scanner alerts on, or to the reported findings: owner go-ahead first,
  with a 2–3 line summary (what it does, the numbers, the risk).
- One PR at a time. Order: Data → Backtest/Scanner → Dashboard.

## Reporting style
Lead with the answer, give the numbers, end with what's next. Recommend rather than list options;
ask only when the decision is the owner's. Never call something done until it's verified.
Link PRs as `phat-d0/Tennis_Model#N`.

# Proposal: record live score/state next to the order books

Data role, 2026-10-24. **Status: built into the recorder (`recorder.score_poll_s`, default 60 s),
approved by the Lead.** Sources: Kalshi docs (fetched as `.md`), our fixtures
`tests/fixtures/kalshi/{milestones_*,live_data_*}.json`, and **one** live
`GET /live_data/batch` call on 2026-10-24 10:43 UTC (10 milestones, HTTP 200), trimmed into
`live_data_batch_tennis_live_2026-10-24.json` to pin down the live formats.

## Why
Kalshi keeps no score history: `GET /live_data/milestone/{id}` is a current snapshot only
(docs/research/kalshi_api.md §3). If we want to know what the score was when a quote moved
(break of serve, set point, tiebreak), we have to log it ourselves while matches are live. Uses:
- swing-lock entry/lock rules conditioned on game state, not just price;
- explaining big quote jumps, and telling momentum moves from settlement noise;
- a real "live" phase start (first point), instead of milestone `start_date`.

## Endpoint: one call for up to 100 matches
`GET /live_data/batch?milestone_ids=<id>&milestone_ids=<id>…` ("Get Multiple Live Data",
https://docs.kalshi.com/api-reference/live-data/get-multiple-live-data.md):
- `milestone_ids`: array, **maxItems 100**, repeated query param (`style: form, explode: true`).
- Public (`security: []`), same as the other market-data endpoints.
- Response: `{live_datas: [{type, milestone_id, details}]}`, the same `details` as the
  single-milestone endpoint.
- Docs warning: `details.status` "is not guaranteed to be current: if the provider feed falls
  behind, a cached board may still be served, with `details.live_data_delayed` set to `true`
  only once it is significantly stale (some feeds never set it)".

Cost at today's ~90 open tennis matches: **1 request per poll**. At 60 s that is ~0.017 req/s, on
top of the recorder's ~0.2 req/s. The recorder's shared `max_rps` throttle covers it.

## Getting milestone IDs (free)
The recorder's discovery call already asks for `with_milestones=true`. Each milestone carries `id`,
`details.main_game_event_ticker` (our `match_id`), and `first_competitor_id` / `second_competitor_id`.
Each market carries `custom_strike.tennis_competitor`, which equals one of those competitor IDs,
so **side A/B maps to competitor1/2 without guessing** (confirmed on the Van Assche/Musetti
fixture: VAN = `f0e4…` = competitor1, MUS = `8fa1…` = competitor2).

## Fields (from the ended-match fixture)
`live_data.details` for `type: tennis_tournament_singles`:

| Field | Example (ended match) | Meaning |
|---|---|---|
| `status` | `not_started` → `started` → `live` → `closed` | game state (seen live) |
| `match_status` | `null`/`""` before and early on, `1st_set`, `2nd_set`, …, `ended` | set in progress |
| `widget_status` | `none`, `live`, `finished` | UI state |
| `competitor{1,2}_id` | UUID | maps to side A/B via `tennis_competitor` |
| `competitor{1,2}_overall_score` | 1 / 2 | sets won |
| `competitor{1,2}_round_scores[]` | `{score: 6, tiebreak_score: 5, outcome: "loser"}` | games per set (+ tiebreak points) |
| `competitor{1,2}_current_round_score` | 15 / 30, 40 / 40 | **points in the current game, literal 0/15/30/40** (live). Tiebreak values not yet seen |
| `completed_rounds`, `round_winners[]` | 3, [ids] | finished sets |
| `server` | competitor UUID (live); `''` before the start and after the end | who is serving |
| `advantage` | competitor UUID at deuce (seen at 40-40); `''` otherwise | player with AD |
| `winner` | UUID | match winner |
| `competitor{1,2}_statistics` | aces, breakpoints_won, points_won, … | cumulative match stats |
| `live_data_delayed` | (absent here) | staleness flag, not always set |

## Table: `data/recorded/kalshi/score/<day>.parquet`
One row per match per poll **only when something changed** since the last row (status, sets,
games, points, server), plus one row per match every 10 min as a heartbeat. That keeps it small,
and a timeline can be rebuilt with an as-of join on `ts`.

| Column | Type | From |
|---|---|---|
| ts | datetime UTC | our receive time |
| match_id | string | milestone `main_game_event_ticker` |
| milestone_id | string | `milestone_id` |
| status, match_status | string | `details.status`, `details.match_status` |
| delayed | bool | `details.live_data_delayed` (False if absent; see warning above) |
| sets_a, sets_b | int | `competitorN_overall_score`, mapped to A/B |
| games_a, games_b | int | last entry of `competitorN_round_scores[].score` (current set) |
| tb_a, tb_b | int/NA | that entry's `tiebreak_score` |
| points_a, points_b | int | `competitorN_current_round_score` (0/15/30/40 as given) |
| server | "A"/"B"/NA | `details.server` mapped via competitor IDs |
| advantage | "A"/"B"/NA | `details.advantage` mapped via competitor IDs |
| set_scores | string | compact "6-7(5) 7-6(9) 4-6" in A-B order, for humans |
| winner | "A"/"B"/NA | `details.winner` mapped |
| raw | string | the `details` JSON minus `statistics`, so nothing is lost while formats are unverified |

The `raw` column is the safety net: if a field's live format turns out different, we re-derive
the columns later from `raw` without having lost history. Statistics are dropped by default; they
are large and cumulative. A config flag could keep them.

## As built
- `kalshi_normalize.score_row(match_id, live, sides, at)` (pure) and `competitor_sides(market_a, market_b)`.
  If either competitor can't be mapped to A/B, it returns no row; we never guess the orientation.
- `recorder.py`: discovery keeps each match's singles milestone id and the competitor→side map.
  Every `score_poll_s` (default **60**; 0 = off) it calls `/live_data/batch` (100 ids per call) for
  matches from 30 min before their scheduled start (or always, if no start is known) until a
  `closed`/`ended` state has been recorded.
- A row is written when any of status, match_status, sets, games, tiebreak, points, server,
  advantage or winner changed, and otherwise every 10 min as a heartbeat. Rows go to
  `score/<day>/part-*.parquet`, compacted daily like quotes and depth.
- Tests: `score_row` on the ended VanMus fixture (real event + live data: A = Van Assche, the
  set scores and winner match the settled markets) and on the live batch fixture (deuce with
  advantage, flipped orientation, not started, unmapped → no row). Recorder: change-only rows,
  heartbeat logic, polling off (`0`) and not before the lead time.

## Open questions
1. ~~`current_round_score` format~~: points, literal 0/15/30/40 (live call 2026-10-24).
   In a tiebreak it is presumably tiebreak points; not seen yet. `raw` keeps it either way.
2. ~~`server` / `advantage` format~~: competitor UUIDs.
3. How far behind real time is the feed during play? Compare `ts` of score changes with quote jumps.
4. Doubles / team events use other milestone types; this design covers `tennis_tournament_singles` only.

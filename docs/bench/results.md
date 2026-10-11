# RescueMesh benchmark results

**Synthetic simulation.**

Recorded method runs only. Missing methods are absent, never treated as zero. Three seeds per preset do not support a significance claim.

Coverage: 19 of 36 planned preset × seed × method combinations. The paired comparison is incomplete.

## Realized outcomes

| Preset | Seed | Method | Exposure (person-steps) | Assisted sheltered / demand | Assisted completion | Evacuation step | Fire extent | Burning cell-steps | Crew risk-steps | Logistics risk | Invalid attempted / executed |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| normal | 1 | fixed_rule | 720 | 110 / 110 | 1.000 | 52 | 54 | 523 | 0 | 4 | 0 / 0 |
| normal | 1 | single_agent | 700 | 100 / 110 | 0.909 | N/A | 54 | 523 | 0 | 1 | 0 / 0 |
| normal | 1 | rescuemesh | 610 | 100 / 110 | 0.909 | N/A | 54 | 523 | 0 | 3 | 0 / 0 |
| normal | 2 | fixed_rule | 870 | 110 / 110 | 1.000 | 52 | 56 | 543 | 0 | 4 | 0 / 0 |
| normal | 2 | single_agent | 670 | 90 / 110 | 0.818 | N/A | 56 | 543 | 0 | 1 | 0 / 0 |
| normal | 2 | rescuemesh | 740 | 100 / 110 | 0.909 | N/A | 56 | 543 | 0 | 1 | 0 / 0 |
| normal | 3 | fixed_rule | 850 | 110 / 110 | 1.000 | 52 | 59 | 574 | 0 | 4 | 0 / 0 |
| normal | 3 | single_agent | 770 | 100 / 110 | 0.909 | N/A | 59 | 574 | 0 | 2 | 0 / 0 |
| normal | 3 | rescuemesh | 710 | 100 / 110 | 0.909 | N/A | 59 | 574 | 0 | 1 | 0 / 0 |
| wind_shift | 1 | fixed_rule | 710 | 30 / 110 | 0.273 | N/A | 49 | 476 | 0 | 2 | 0 / 0 |
| wind_shift | 1 | single_agent | 640 | 110 / 110 | 1.000 | 44 | 50 | 490 | 0 | 3 | 0 / 0 |
| wind_shift | 2 | fixed_rule | 1000 | 30 / 110 | 0.273 | N/A | 53 | 507 | 0 | 2 | 0 / 0 |
| wind_shift | 3 | fixed_rule | 1150 | 30 / 110 | 0.273 | N/A | 59 | 575 | 0 | 3 | 0 / 0 |
| road_closure | 1 | fixed_rule | 710 | 30 / 110 | 0.273 | N/A | 54 | 519 | 0 | 2 | 0 / 0 |
| road_closure | 2 | fixed_rule | 1000 | 30 / 110 | 0.273 | N/A | 56 | 536 | 0 | 2 | 0 / 0 |
| road_closure | 3 | fixed_rule | 950 | 30 / 110 | 0.273 | N/A | 59 | 575 | 0 | 3 | 0 / 0 |
| compound_failure | 1 | fixed_rule | 710 | 30 / 110 | 0.273 | N/A | 49 | 476 | 0 | 2 | 0 / 0 |
| compound_failure | 2 | fixed_rule | 1000 | 30 / 110 | 0.273 | N/A | 53 | 507 | 0 | 2 | 0 / 0 |
| compound_failure | 3 | fixed_rule | 1150 | 30 / 110 | 0.273 | N/A | 59 | 575 | 0 | 3 | 0 / 0 |

## Decisions, latency and cost

| Run ID | Preset | Seed | Method | DPs | Commits | Escalations | Inappropriate consensus | Justified escalations | Adaptation ms | Model calls | Tokens in / out | Wall ms | Estimated cost USD | Notes |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---|
| bench-20261011T115655Z-3ff42ddd-normal-s1-fixed_rule | normal | 1 | fixed_rule | 1 | 1 | 0 | 0 | 0 | N/A | 0 | N/A / N/A | 69 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T115655Z-3ff42ddd-normal-s1-single_agent | normal | 1 | single_agent | 1 | 1 | 0 | 0 | 0 | N/A | 3 | 51155 / 7318 | 46033 | N/A | single_agent: live provider anthropic/claude-sonnet-5-5 |
| bench-20261011T115655Z-3ff42ddd-normal-s1-rescuemesh | normal | 1 | rescuemesh | 1 | 1 | 0 | 0 | 0 | N/A | 19 | 299354 / 28410 | 83023 | N/A | rescuemesh: live provider anthropic/claude-sonnet-5-5 |
| bench-20261011T115655Z-3ff42ddd-normal-s2-fixed_rule | normal | 2 | fixed_rule | 1 | 1 | 0 | 0 | 0 | N/A | 0 | N/A / N/A | 47 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T115655Z-3ff42ddd-normal-s2-single_agent | normal | 2 | single_agent | 1 | 1 | 0 | 0 | 0 | N/A | 4 | 78220 / 7713 | 44061 | N/A | single_agent: live provider anthropic/claude-sonnet-5-5 |
| bench-20261011T115655Z-3ff42ddd-normal-s2-rescuemesh | normal | 2 | rescuemesh | 1 | 1 | 0 | 0 | 0 | N/A | 23 | 416570 / 38768 | 91376 | N/A | rescuemesh: live provider anthropic/claude-sonnet-5-5 |
| bench-20261011T115655Z-3ff42ddd-normal-s3-fixed_rule | normal | 3 | fixed_rule | 1 | 1 | 0 | 0 | 0 | N/A | 0 | N/A / N/A | 45 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T115655Z-3ff42ddd-normal-s3-single_agent | normal | 3 | single_agent | 1 | 1 | 0 | 0 | 0 | N/A | 4 | 74193 / 9310 | 57721 | N/A | single_agent: live provider anthropic/claude-sonnet-5-5 |
| bench-20261011T115655Z-3ff42ddd-normal-s3-rescuemesh | normal | 3 | rescuemesh | 1 | 1 | 0 | 0 | 0 | N/A | 25 | 403186 / 40544 | 149100 | N/A | rescuemesh: live provider anthropic/claude-sonnet-5-5 |
| bench-20261011T115655Z-3ff42ddd-wind_shift-s1-fixed_rule | wind_shift | 1 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 8 | 0 | N/A / N/A | 69 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T115655Z-3ff42ddd-wind_shift-s1-single_agent | wind_shift | 1 | single_agent | 2 | 2 | 0 | 0 | 0 | 38174 | 7 | 128387 / 11077 | 66940 | N/A | single_agent: live provider anthropic/claude-sonnet-5-5 |
| bench-20261011T145134Z-3767818e-wind_shift-s2-fixed_rule | wind_shift | 2 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 12 | 0 | N/A / N/A | 82 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T145134Z-3767818e-wind_shift-s3-fixed_rule | wind_shift | 3 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 19 | 0 | N/A / N/A | 137 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T145151Z-ad66c1bd-road_closure-s1-fixed_rule | road_closure | 1 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 10 | 0 | N/A / N/A | 78 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T145151Z-ad66c1bd-road_closure-s2-fixed_rule | road_closure | 2 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 10 | 0 | N/A / N/A | 66 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T145151Z-ad66c1bd-road_closure-s3-fixed_rule | road_closure | 3 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 9 | 0 | N/A / N/A | 56 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T145151Z-ad66c1bd-compound_failure-s1-fixed_rule | compound_failure | 1 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 7 | 0 | N/A / N/A | 55 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T145151Z-ad66c1bd-compound_failure-s2-fixed_rule | compound_failure | 2 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 7 | 0 | N/A / N/A | 55 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |
| bench-20261011T145151Z-ad66c1bd-compound_failure-s3-fixed_rule | compound_failure | 3 | fixed_rule | 2 | 2 | 0 | 0 | 0 | 8 | 0 | N/A / N/A | 54 | N/A | fixed_rule: deterministic §11.2 policy, no model calls |

Cost is N/A when model pricing has not been verified. Evacuation step N/A means unfinished at the horizon.
Forecast-versus-realized differences require commit-time Evaluation records; the results CSV contains realized metrics only.

# CausalTrace — final ChatGPT-side source handoff

**Date:** 27 October 2026  
**Artifact:** `CausalTrace_Final_Local_Verification_Handoff.zip`  
**Classification:** engineering source candidate for local verification, **not full-stack or production certified**.

## Baseline vs this turn

The provided existing source had a previously audited baseline of **52 passing Python tests and 3 PostgreSQL skips**, OTel SDK HTTP ingestion, cross-process trace propagation, and synthetic benchmarks. Those are **prior-run claims**, not checks that should be silently attributed to this revision.

### Real verification performed during this source pass

| Gate | Observed outcome | Status |
|---|---|---|
| Known live CI authentication defect | Browser step now independently loads, validates, exports and checks the exact ephemeral operator key before executing Playwright | SOURCE FIXED; live run unverified |
| PostgreSQL test isolation | Dedicated ephemeral `postgres-test` and migrated `postgres-check` instead of application `postgres` | SOURCE FIXED; Docker run unverified |
| Static CI regression checks | Both functions in `tests/test_ci_release_contract.py` executed successfully using system Python | VERIFIED PASS (static tests only) |
| Python compilation | `/usr/bin/python3 -m compileall -q causaltrace demo benchmarks scripts tests` | VERIFIED PASS (syntax only) |
| Shell script syntax | `bash -n scripts/verify.sh scripts/run_lab.sh` | VERIFIED PASS |
| YAML parsing | Ruby Psych parsed both Compose files, collector config, and both workflows without syntax errors | VERIFIED PASS (parsing only) |
| TS/TSX syntax | Installed global TypeScript `transpileModule` checked eight frontend source/config/test files without syntactic diagnostics | VERIFIED PASS (syntax only) |
| Full Python regression suite | Attempted using `pytest -q`; did not complete. One run reached 12 passes then failed when `test_database_fault_reservation.py` spawned a child process whose 25-second timeout expired under this constrained runner. A separate attempt timed out before completion. | NOT VERIFIED IN THIS TURN |
| npm registry lockfile generation | `npm install --package-lock-only` attempted, but registry resolution did not complete; `getent hosts registry.npmjs.org` yielded no address. No existing npm cache. | BLOCKED; lockfile absent |
| `npm ci` | Attempted, failed with npm `EUSAGE`: missing `web/package-lock.json` | VERIFIED FAIL (missing prerequisite) |
| TypeScript strict, ESLint, Prettier, Vitest, Vite, Playwright | Application dependencies unavailable; no end-to-end frontend execution | UNVERIFIED |
| Ruff/mypy/Python security audit | Tools unavailable in this runner; no checks counted as passed | UNVERIFIED |
| Docker Compose runtime, Collector and PostgreSQL | Docker CLI not installed | UNVERIFIED |
| Three actual fault experiments and live root-cause evaluation | No running full lab | UNVERIFIED |

The earlier 52-pass baseline is preserved as historical context. The 25-second subprocess deadline during the current run is an **execution-environment result**, not evidence that the database fault behavior is correct or incorrect. A clean Python test pass remains mandatory on the user's host and in CI.

## Exact changes

See `LOCAL_VERIFICATION_HANDOFF.md` for the six source/test changes and Windows commands. No ML or observability algorithms were replaced. No ground-truth labels were added to inference. The synthetic evaluation remains a regression baseline and is **not** represented as live detection/root-cause accuracy.

## Release decision

**NOT CERTIFIED.** The required npm lockfile, frontend production/browser gates, PostgreSQL integration, Collector and full fault-lab tests must pass before declaring the application final. The archive is a reproducible source handoff for running those gates, not a guarantee they pass.

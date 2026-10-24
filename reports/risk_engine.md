# Independent paper risk engine

Implemented as an independent, deterministic module in `src/alphacouncil/risk/`. It never calls a network order endpoint, reads trading credentials, or modifies the existing forward and forced-paper sessions. Live execution always returns `live_execution_unsupported`.

## Interface

```python
from alphacouncil.risk import assess, assess_payload, RiskConfig

decision = assess(context, RiskConfig())  # frozen typed contracts
review = decision.to_dict()              # JSON safe; exact decimals serialized as strings
review = assess_payload(payload)         # malformed inputs return an explicit refusal
```

The JSON payload has `now`, `clock_offset_seconds`, `quote`, `account`, `venue`, optional `forecast`, and `permissions`. The exact contract fields are in `src/alphacouncil/risk/contracts.py`. Missing quote, account, venue rules, clock measurement, or signal evidence cannot produce an authorized proposal.

`Forecast.expected_return_fraction` is a **simple return**. Convert the existing committee's log return using `expm1(mu)` when constructing a contract. An expert's disagreement/dispersion is not a calibrated error distribution. The current models have not supplied independently validated uncertainty or downside estimates, so their signal proposals deliberately fail closed.

## Deterministic checks

- Paper permission, kill switch, BUY spot only, 1x leverage, and no existing position.
- Aware timestamps; measured clock offset at most 5 seconds; quote age and request latency at most 3 seconds; no future observation; consistent latency measurement; identifiable raw receipt.
- Published, unexpired forecast; quote requested after publication; matching symbol; positive prices/depth; crossed markets refused; spread at most 25 basis points.
- Explicit uncertainty estimate with validation identifier, bounded at 5%; a separate downside scenario and distinct validation identifier. Identifiers record caller-supplied provenance; this module does not itself prove that a research calibration is valid.
- Decimal arithmetic, common lot-size multiple for both lot filters, quantity and notional limits, displayed liquidity, available cash after reservations, and independent planned-loss budget after reservations.
- At a 50 USDT equity, default loss budget is `min(0.50, equity * 0.01) = 0.50 USDT`. Entry debit including fees is capped at 10 USDT.

Defaults assume 10 basis points of fees and 2 basis points of slippage **on each side**. These are simulation assumptions, not verified account-specific fee rates. Fees, slippage, observed spread, and change since the forecast's reference price all enter the net-edge calculation. The lower forecast estimate after uncertainty must clear another 2 basis points.

For quantity `q`, the sizing constraint is:

```text
entry debit = q * ask * (1 + entry slippage) * (1 + entry fee)
scenario exit proceeds = q * bid * (1 - downside fraction)
                         * (1 - exit slippage) * (1 - exit fee)
planned loss = entry debit - scenario exit proceeds
```

The downside scenario is an independently validated planning input, **not a guaranteed maximum loss or a resting stop order**. Gaps, outages, and liquidity changes can exceed this estimate. The configuration and provenance should be owned by the trusted local application; a future HTTP adapter must not let an untrusted caller invent calibrated evidence or loosen policy.

## Forced paper diagnostic

`Permissions(forced_paper_diagnostic=True)` is marked separately from signal trading and cannot authorize live execution. It bypasses forecast/uncertainty evidence, while retaining cash, freshness, clock, venue, permission, kill, and size rules. Without a validated downside scenario it assumes a complete loss of the position. At the default 0.50 USDT loss budget this is smaller than a 5 USDT venue minimum, and the engine refuses that proposal explicitly. It does not silently weaken the budget to produce a forced fill. The previously running forced 20-second experiment remains independent and unchanged.

## Local human review and paper submission

`PaperReviewLedger(path)` stores immutable proposal snapshots plus append-only review/fill events in its own SQLite database. A proposal expires after at most 20 seconds and cannot outlive its forecast. A named, explicit `approve(proposal_id, reviewer=..., now=...)` action is required before `submit_paper(...)`. Review is caller-attested local interaction, not authenticated remote identity.

```python
ledger.initialize_account(context.account)   # cannot refill/reset an existing account
decision = ledger.propose(context)
# A UI renders decision.proposal.to_dict() before the user's explicit approval.
ledger.approve(decision.proposal.proposal_id, reviewer="local-user", now=current_time)
receipt = ledger.submit_paper(decision.proposal.proposal_id, fresh_context)
```

At submission the ledger reassesses fresh inputs, kills, account state, all risk rules, and the pinned configuration. Reviewed identity and quantity cannot change; a higher entry cost or higher planned loss requires a new review. Approval before creation, after expiry, repeated approval, future-dated approval at submission, or an account snapshot inconsistent with the stored cash/position count is refused. `BEGIN IMMEDIATE` makes debit and fill recording atomic. Repeated submission of a filled proposal returns the identical receipt without another debit, even if the old quote has since expired. Replaying that receipt is a read of the prior fill, not a new execution.

This new local ledger implements entry review and paper fills. It does not yet manage position exits, reconcile a venue account, authenticate reviewers, guarantee public quote event-time freshness, or support real orders. The application must supply server-owned current time; caller-supplied timestamps alone are not a security boundary. Existing forward-session ledgers remain the source for those sessions' closing trades and P&L.

## Local command-line workflow

`scripts/paper_review.py` makes the review contract usable without a mutable API or dashboard. Every result is marked `paper_only: true`. It has no network client. Input JSON paths are explicit; the default independent ledger is `.context/data/risk/paper_review.sqlite3`, and policy defaults come from `configs/risk.json`. Each command accepts `--ledger PATH`; review/propose/submit also accept `--risk-config PATH` (alias `--riskconfig`).

```sh
# Use a genuine, freshly captured context JSON with documented research evidence.
uv run scripts/paper_review.py review --context .context/data/risk/current_context.json
uv run scripts/paper_review.py propose --context .context/data/risk/current_context.json

# Replace FULL_PROPOSAL_ID_FROM_REVIEW with the exact 64-character emitted ID.
uv run scripts/paper_review.py approve --proposal-id FULL_PROPOSAL_ID_FROM_REVIEW --reviewer 'Your name'

# Refresh the context's quote/account inputs before submitting the reviewed proposal.
uv run scripts/paper_review.py submit --proposal-id FULL_PROPOSAL_ID_FROM_REVIEW --context .context/data/risk/current_context.json
uv run scripts/paper_review.py status
uv run scripts/paper_review.py status --proposal-id FULL_PROPOSAL_ID_FROM_REVIEW
```

`review` is read-only and never creates a ledger. `propose` creates an allowed immutable proposal and initializes an independent paper account; it never approves or submits. `approve` requires an exact proposal ID, a nonblank named reviewer, and an existing unexpired proposal. There is no automatic approval option and no command-line approval timestamp override. `submit` requires a fresh explicit context file, reruns all rules, requires the pinned policy and prior approval, and records only a simulated fill. `status` opens an existing ledger read-only and reports proposal state, reviewer, receipts, cash, and position count; absent ledgers are not created.

For review/propose/submit the CLI replaces the payload's `now` with the process's actual UTC clock. An old JSON file cannot make an expired quote fresh by retaining an old assessment timestamp. Missing risk evidence is refused rather than filled with artificial calibration. This workflow deliberately does not generate a successful context example with made-up validation identifiers; the identifiers used by unit tests are test fixtures only. Today's uncalibrated model output should therefore produce a transparent refusal.

Allowed operations exit with code 0; malformed input, risk refusal, expired review, missing ledger, or invalid transition exits with code 2. `status` can retrieve an already-recorded receipt independently of current eligibility. Repeating `submit` is idempotent when its supplied fresh context still passes assessment; a stale repeated submit is refused before it reaches the paper ledger. No command resets an account that has already spent cash.

## Validation

Focused tests cover cost and loss sizing, independent calibration requirements, reserved budgets, exact precision across non-nested grids, stale/future/expired data, net edge after uncertainty and costs, forced-diagnostic separation, malformed JSON, kill and leverage refusal, immutable review, future/duplicate/expired approvals, account mismatch, adverse price movement, and idempotent atomic paper submission. CLI tests exercise real argument parsing, read-only review/status, explicit propose/approve/submit transitions, no automatic approval, named/exact-ID requirements, current-clock expiry, stale/live refusal, missing calibration, pinned configuration, and duplicate submission. Run `uv run --group training --group analysis pytest -q tests/test_risk.py tests/test_paper_review_cli.py`.

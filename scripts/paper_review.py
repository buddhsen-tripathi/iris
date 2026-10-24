#!/usr/bin/env python3
"""Review, explicitly approve, and submit local PAPER-ONLY proposals. No network orders."""

import argparse
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from alphacouncil.risk import PaperReviewLedger, ReviewError, RiskConfig, assess, context_from_payload
from alphacouncil.risk.adapters import decode_contract

DEFAULT_LEDGER = Path(".context/data/risk/paper_review.sqlite3")
DEFAULT_CONFIG = Path("configs/risk.json")


def utc_now():
    return datetime.now(timezone.utc)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def read_json(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Input JSON exceeds 1 MiB")
    def reject_constant(value):
        raise ValueError("Nonfinite JSON number")
    return json.loads(path.read_text(), object_pairs_hook=_unique_object, parse_constant=reject_constant)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("review", "Read-only PAPER risk assessment; never creates or approves a proposal"),
        ("propose", "Persist an allowed PAPER proposal without approving or submitting it"),
        ("approve", "Record an explicit named human approval of one exact PAPER proposal"),
        ("submit", "Reassess fresh inputs and submit an already-approved PAPER proposal"),
        ("status", "Read local PAPER ledger state without creating a ledger"),
    ]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        if name in {"review", "propose", "submit"}:
            command.add_argument("--context", type=Path, required=True,
                                 help="Explicit fresh risk context JSON; current process UTC overrides context.now")
            command.add_argument("--risk-config", "--riskconfig", type=Path, default=DEFAULT_CONFIG)
        if name in {"approve", "submit", "status"}:
            command.add_argument("--proposal-id", required=name != "status",
                                 help="Full 64-character immutable proposal ID; prefixes are refused")
        if name == "approve":
            command.add_argument("--reviewer", required=True, help="Name of the human explicitly approving this proposal")
    return root


def output(payload):
    print(json.dumps({"paper_only": True, **payload}, indent=2, sort_keys=True, allow_nan=False))


def _proposal_id(value):
    if value is not None and (len(value) != 64 or any(character not in "0123456789abcdef" for character in value)):
        raise ReviewError("Full lowercase 64-character proposal ID required")


def status(path, proposal_id=None):
    if not path.exists():
        if proposal_id is not None:
            raise ReviewError("Unknown proposal; ledger does not exist")
        return {"status": "ledger_not_created", "ledger": str(path), "accounts": [], "proposals": []}
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        query = "SELECT * FROM risk_proposals"
        rows = db.execute(query + (" WHERE proposal_id=?" if proposal_id else " ORDER BY rowid DESC LIMIT 50"),
                          (proposal_id,) if proposal_id else ()).fetchall()
        if proposal_id and not rows:
            raise ReviewError("Unknown proposal")
        now = utc_now()
        proposals = []
        for row in rows:
            proposal = json.loads(row["proposal_json"])
            state = "submitted" if row["submitted_at"] else (
                "expired" if datetime.fromisoformat(proposal["expires_at"]) <= now else
                "approved" if row["approved_at"] else "awaiting_human_approval")
            proposals.append({"state": state, "proposal": proposal, "approved_at": row["approved_at"],
                              "approved_by": row["approved_by"], "submitted_at": row["submitted_at"],
                              "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None})
        return {"status": "paper_ledger", "ledger": str(path),
                "accounts": [dict(row) for row in db.execute("SELECT * FROM risk_accounts ORDER BY account_id")],
                "proposals": proposals, "proposal_display_limit": 50 if not proposal_id else 1,
                "proposal_count": db.execute("SELECT COUNT(*) FROM risk_proposals").fetchone()[0]}
    finally:
        db.close()


def main(argv=None):
    args = parser().parse_args(argv)
    ledger = None
    try:
        _proposal_id(getattr(args, "proposal_id", None))
        if args.command == "status":
            output(status(args.ledger, args.proposal_id))
            return 0
        now = utc_now()
        if args.command in {"review", "propose", "submit"}:
            # A historical or caller-invented 'now' cannot make an old quote fresh.
            context = replace(context_from_payload(read_json(args.context)), now=now)
            config = decode_contract(RiskConfig, read_json(args.risk_config))
            decision = assess(context, config)
            if not decision.allowed:
                output({"status": "risk_refused", "command": args.command, "review": decision.to_dict()})
                return 2
            if args.command == "review":
                output({"status": "review_only", "persisted": False, "approved": False, "review": decision.to_dict()})
                return 0
        if args.command in {"approve", "submit"} and not args.ledger.exists():
            raise ReviewError("Existing proposal ledger required")
        if args.command == "propose":
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger = PaperReviewLedger(args.ledger)
        if args.command == "propose":
            ledger.initialize_account(context.account)
            decision = ledger.propose(context, config)
            output({"status": "awaiting_human_approval", "approved": False, "submitted": False,
                    "ledger": str(args.ledger), "review": decision.to_dict()})
        elif args.command == "approve":
            ledger.approve(args.proposal_id, reviewer=args.reviewer, now=now)
            output({"status": "human_approved", "proposal_id": args.proposal_id,
                    "reviewer": args.reviewer, "approved_at": now.isoformat(), "submitted": False})
        elif args.command == "submit":
            receipt = ledger.submit_paper(args.proposal_id, context, config)
            output({"status": "paper_filled", "receipt": receipt})
        return 0
    except (ReviewError, OSError, ValueError, TypeError, KeyError, ArithmeticError, AttributeError, sqlite3.Error) as error:
        output({"status": "refused", "command": args.command, "error": str(error)})
        return 2
    finally:
        if ledger is not None:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())

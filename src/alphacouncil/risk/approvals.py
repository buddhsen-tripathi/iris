"""Local paper-only review ledger with atomic approval and submission transitions.

Human approval is a caller-attested local action, not remote identity authentication.
This module deliberately has no HTTP client, credentials or live order adapter.
"""

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .contracts import RiskConfig, RiskContext
from .engine import assess, fingerprint


class ReviewError(ValueError):
    pass


class PaperReviewLedger:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS risk_accounts(
                account_id TEXT PRIMARY KEY, cash TEXT NOT NULL, open_positions INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS risk_proposals(
                proposal_id TEXT PRIMARY KEY, proposal_json TEXT NOT NULL, config_hash TEXT NOT NULL,
                approved_at TEXT, approved_by TEXT, submitted_at TEXT, receipt_json TEXT);
            CREATE TABLE IF NOT EXISTS risk_events(
                id INTEGER PRIMARY KEY, proposal_id TEXT, time_utc TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def initialize_account(self, account):
        if not account.cash.is_finite() or account.cash < 0 or account.open_positions < 0:
            raise ReviewError("Invalid paper account")
        existing = self.db.execute("SELECT * FROM risk_accounts WHERE account_id=?", (account.account_id,)).fetchone()
        if existing is not None:
            # Reinitialization cannot refill an account that has already spent cash.
            if Decimal(existing["cash"]) != account.cash or existing["open_positions"] != account.open_positions:
                raise ReviewError("Existing paper account cannot be reset")
            return
        self.db.execute("INSERT INTO risk_accounts VALUES (?,?,?)", (account.account_id, str(account.cash), account.open_positions))

    def propose(self, context: RiskContext, config: RiskConfig = RiskConfig()):
        decision = assess(context, config)
        if not decision.allowed:
            return decision
        proposal = decision.proposal
        payload = json.dumps(proposal.to_dict(), sort_keys=True)
        self.db.execute("INSERT OR IGNORE INTO risk_proposals(proposal_id,proposal_json,config_hash) VALUES (?,?,?)",
                        (proposal.proposal_id, payload, fingerprint(config)))
        existing = self.db.execute("SELECT proposal_json FROM risk_proposals WHERE proposal_id=?", (proposal.proposal_id,)).fetchone()
        if existing[0] != payload:
            raise ReviewError("Immutable proposal conflict")
        return decision

    def approve(self, proposal_id: str, *, reviewer: str, now: datetime):
        """Record an explicit local human decision; repeated approval is rejected."""
        if not reviewer.strip() or now.tzinfo is None or now.utcoffset() is None:
            raise ReviewError("Named reviewer and aware approval time required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM risk_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None:
                raise ReviewError("Unknown proposal")
            proposal = json.loads(row["proposal_json"])
            if not datetime.fromisoformat(proposal["created_at"]) <= now < datetime.fromisoformat(proposal["expires_at"]):
                raise ReviewError("Approval is before proposal creation or after expiry")
            if row["approved_at"] or row["submitted_at"]:
                raise ReviewError("Proposal already approved or submitted")
            self.db.execute("UPDATE risk_proposals SET approved_at=?,approved_by=? WHERE proposal_id=?",
                            (now.isoformat(), reviewer, proposal_id))
            self.db.execute("INSERT INTO risk_events(proposal_id,time_utc,kind,detail) VALUES (?,?,?,?)",
                            (proposal_id, now.isoformat(), "human_approved", reviewer))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def submit_paper(self, proposal_id: str, context: RiskContext, config: RiskConfig = RiskConfig()):
        """Reassess current state and atomically debit one simulated fill exactly once."""
        # Even idempotent retries cannot route through this interface as live orders.
        if context.permissions.mode != "paper":
            raise ReviewError("Live execution is unsupported")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM risk_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None or row["approved_at"] is None:
                raise ReviewError("Existing approved proposal required")
            if row["receipt_json"]:
                receipt = json.loads(row["receipt_json"])
                self.db.execute("COMMIT")
                return receipt
            proposal = json.loads(row["proposal_json"])
            if not datetime.fromisoformat(row["approved_at"]) <= context.now < datetime.fromisoformat(proposal["expires_at"]):
                raise ReviewError("Approval is future dated or proposal expired")
            if fingerprint(config) != row["config_hash"]:
                raise ReviewError("Risk configuration changed; new review required")
            decision = assess(context, config)
            if not decision.allowed:
                raise ReviewError("Current risk refusal: " + ", ".join(decision.reasons))
            current = decision.proposal
            for field in ("mode", "strategy", "account_id", "symbol", "side", "forecast_id", "planned_loss_basis"):
                if str(getattr(current, field)) != str(proposal[field]):
                    raise ReviewError("Reviewed proposal identity changed")
            quantity = Decimal(proposal["quantity"])
            if current.quantity < quantity:
                raise ReviewError("Current size cap is below approved quantity")
            entry_cost = current.entry_cost_including_fee / current.quantity * quantity
            planned_loss = current.planned_loss_including_costs / current.quantity * quantity
            if entry_cost > Decimal(proposal["entry_cost_including_fee"]) or planned_loss > Decimal(proposal["planned_loss_including_costs"]):
                raise ReviewError("Cost or planned loss increased; new review required")
            stored = self.db.execute("SELECT * FROM risk_accounts WHERE account_id=?", (current.account_id,)).fetchone()
            if stored is None or Decimal(stored["cash"]) != context.account.cash or stored["open_positions"] != context.account.open_positions:
                raise ReviewError("Paper account missing or context differs from ledger")
            if stored["open_positions"] != 0 or Decimal(stored["cash"]) < entry_cost:
                raise ReviewError("Paper account position or cash limit")
            receipt = {"proposal_id": proposal_id, "paper_only": True, "status": "paper_filled",
                       "submitted_at": context.now.isoformat(), "account_id": current.account_id,
                       "symbol": current.symbol, "side": "BUY", "quantity": str(quantity),
                       "entry_cost_including_fee": str(entry_cost), "planned_loss_including_costs": str(planned_loss),
                       "quote_receipt_sha256": current.quote_receipt_sha256,
                       "reviewer": row["approved_by"]}
            self.db.execute("UPDATE risk_accounts SET cash=?,open_positions=1 WHERE account_id=?",
                            (str(Decimal(stored["cash"]) - entry_cost), current.account_id))
            self.db.execute("UPDATE risk_proposals SET submitted_at=?,receipt_json=? WHERE proposal_id=?",
                            (context.now.isoformat(), json.dumps(receipt, sort_keys=True), proposal_id))
            self.db.execute("INSERT INTO risk_events(proposal_id,time_utc,kind,detail) VALUES (?,?,?,?)",
                            (proposal_id, context.now.isoformat(), "paper_filled", json.dumps(receipt, sort_keys=True)))
            self.db.execute("COMMIT")
            return receipt
        except Exception:
            self.db.execute("ROLLBACK")
            raise

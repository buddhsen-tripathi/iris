"""Five-minute long-only spot round trips under explicit next-open proxy assumptions."""

import math

import numpy as np
import pandas as pd

TRADE_COLUMNS = [
    "entry_time_utc", "exit_time_utc", "side", "entry_open_proxy", "exit_open_proxy",
    "assumed_entry_fill", "assumed_exit_fill", "quantity_btc", "cash_allocated_usdt",
    "entry_fee_usdt", "exit_fee_usdt", "execution_impact_usdt", "gross_mid_pnl_usdt",
    "net_pnl_usdt", "equity_after_exit_usdt",
]
DECISION_COLUMNS = ["decision_time_utc", "reason", "committee_5m", "committee_15m", "committee_30m", "required_log_edge"]


def edge_threshold_log(fee_bps: float, impact_bps: float, buffer_bps: float) -> float:
    fee, impact = fee_bps / 10000, impact_bps / 10000
    if min(fee, impact, buffer_bps) < 0 or max(fee, impact) >= 1:
        raise ValueError("Invalid cost assumptions")
    break_even = (1 + impact) * (1 + fee) / ((1 - impact) * (1 - fee)) - 1
    return math.log1p(break_even + buffer_bps / 10000)


def simulate_policy(predictions: pd.DataFrame, candles: pd.DataFrame, start: pd.Timestamp,
                    end: pd.Timestamp, policy: str, scenario: dict, settings: dict) -> dict:
    if policy not in {"five_minute_only", "with_15m_30m_confirmation"}:
        raise ValueError("Unknown paper policy")
    if settings["mode"] != "SIMULATED_SPOT_LONG_ONLY" or settings["holding_minutes"] != 5:
        raise ValueError("Only simulated long-only spot with five-minute holding is supported")
    if not start < end:
        raise ValueError("Evaluation end must be after start")
    times = predictions["decision_time_utc"]
    if times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError("Predictions must be chronological with unique decisions")
    bars = candles.set_index("open_time_utc")["open"].astype(float)
    if bars.index.has_duplicates or not bars.gt(0).all() or not np.isfinite(bars).all():
        raise ValueError("Invalid executable-price proxy series")
    fee = scenario["fee_bps_per_side"] / 10000
    impact = scenario["impact_bps_per_side"] / 10000
    threshold = edge_threshold_log(scenario["fee_bps_per_side"], scenario["impact_bps_per_side"], settings["extra_edge_buffer_bps"])
    cash = float(settings["initial_cash_usdt"])
    allocation_cap = float(settings["maximum_cash_per_position_usdt"])
    if cash <= 0 or allocation_cap <= 0:
        raise ValueError("Invalid simulated capital limits")
    trades, decisions = [], []
    equity = [{"time_utc": start, "equity_usdt": cash}]
    occupied_until = start
    for row in predictions.itertuples(index=False):
        time = row.decision_time_utc
        if time < start or time >= end:
            continue
        exit_time = time + pd.Timedelta(minutes=5)
        reason = "PROPOSE_SIMULATED_LONG"
        if time < occupied_until:
            reason = "POSITION_ALREADY_OPEN"
        elif not np.isfinite(row.committee_5m):
            reason = "MISSING_FORECAST"
        elif row.committee_5m <= threshold:
            reason = "NO_EDGE_AFTER_ASSUMED_COSTS"
        elif policy == "with_15m_30m_confirmation" and not (
            np.isfinite(row.committee_15m) and np.isfinite(row.committee_30m)
            and row.committee_15m > 0 and row.committee_30m > 0
        ):
            reason = "LONGER_HORIZON_DISAGREEMENT"
        elif exit_time >= end:
            reason = "END_OF_REPLAY"
        elif time not in bars.index:
            reason = "MISSING_ENTRY_PROXY"
        elif cash <= 0:
            reason = "NO_SIMULATED_CASH"
        decisions.append({"decision_time_utc": time, "reason": reason, "committee_5m": row.committee_5m,
                          "committee_15m": row.committee_15m, "committee_30m": row.committee_30m,
                          "required_log_edge": threshold})
        if reason != "PROPOSE_SIMULATED_LONG":
            continue
        if exit_time not in bars.index:
            # Do not pretend the entry policy foresaw a later data outage and abstained.
            raise ValueError("Missing future exit proxy; cannot settle this simulation")
        entry_open, exit_open = float(bars.loc[time]), float(bars.loc[exit_time])
        entry_fill = entry_open * (1 + impact)
        exit_fill = exit_open * (1 - impact)
        cash_allocated = min(allocation_cap, cash)
        quantity = cash_allocated / (entry_fill * (1 + fee))
        entry_fee = quantity * entry_fill * fee
        exit_fee = quantity * exit_fill * fee
        proceeds = quantity * exit_fill - exit_fee
        pnl = proceeds - cash_allocated
        gross_mid_pnl = quantity * (exit_open - entry_open)
        execution_impact = quantity * (entry_open + exit_open) * impact
        cash += pnl
        occupied_until = exit_time
        trades.append({"entry_time_utc": time, "exit_time_utc": exit_time, "side": "LONG",
            "entry_open_proxy": entry_open, "exit_open_proxy": exit_open,
            "assumed_entry_fill": entry_fill, "assumed_exit_fill": exit_fill,
            "quantity_btc": quantity, "cash_allocated_usdt": cash_allocated,
            "entry_fee_usdt": entry_fee, "exit_fee_usdt": exit_fee,
            "execution_impact_usdt": execution_impact, "gross_mid_pnl_usdt": gross_mid_pnl,
            "net_pnl_usdt": pnl, "equity_after_exit_usdt": cash})
        equity.append({"time_utc": exit_time, "equity_usdt": cash})
    equity.append({"time_utc": end, "equity_usdt": cash})
    trades = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    decisions = pd.DataFrame(decisions, columns=DECISION_COLUMNS)
    equity = pd.DataFrame(equity)
    hours = (end - start).total_seconds() / 3600
    counts = trades["entry_time_utc"].dt.floor("h").value_counts().sort_index() if not trades.empty else pd.Series(dtype=int)
    balances = equity["equity_usdt"]
    drawdowns = balances / balances.cummax() - 1
    summary = {
        "mode": settings["mode"], "policy": policy, "cost_scenario": scenario["name"],
        "decision_checks": len(decisions), "completed_trades": len(trades),
        "evaluation_hours": hours, "average_trades_per_hour": len(trades) / hours,
        "maximum_entries_in_utc_hour": int(counts.max()) if len(counts) else 0,
        "active_hours": len(counts), "initial_cash_usdt": settings["initial_cash_usdt"],
        "final_equity_usdt": cash, "net_pnl_usdt": cash - settings["initial_cash_usdt"],
        "return_fraction": cash / settings["initial_cash_usdt"] - 1,
        "entry_and_exit_fees_usdt": float((trades["entry_fee_usdt"] + trades["exit_fee_usdt"]).sum()) if not trades.empty else 0.0,
        "execution_impact_usdt": float(trades["execution_impact_usdt"].sum()) if not trades.empty else 0.0,
        "gross_mid_pnl_usdt": float(trades["gross_mid_pnl_usdt"].sum()) if not trades.empty else 0.0,
        "maximum_exit_mark_drawdown": float(drawdowns.min()),
        "win_rate": float(trades["net_pnl_usdt"].gt(0).mean()) if not trades.empty else None,
        "turnover_usdt": float((trades["quantity_btc"] * (trades["assumed_entry_fill"] + trades["assumed_exit_fill"])).sum()) if not trades.empty else 0.0,
        "required_log_edge": threshold,
        "reason_counts": decisions["reason"].value_counts().to_dict() if not decisions.empty else {},
    }
    hourly = counts.rename_axis("entry_hour_utc").rename("completed_round_trips_entered").reset_index()
    return {"summary": summary, "trades": trades, "decisions": decisions, "equity": equity, "hourly": hourly}

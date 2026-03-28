# PUT UP — Reputation & Outcome Resolution
# Karma scoring rules + the main orchestrator that combines escrow + karma

import config
from escrow_engine import send_payment, calculate_distribution
from karma_engine import issue_karma, burn_karma, get_karma_score


def resolve_outcome(outcome, user_role):
    """
    Map a Put Up outcome to karma delta for a specific user.

    Args:
        outcome: "both_show", "a_ghosted", "b_ghosted", "both_ghost", "late_cancel"
        user_role: "A" or "B"

    Returns:
        dict with karma_delta, reason, is_penalty
    """
    if outcome == "both_show":
        return {
            "karma_delta": config.KARMA_BOTH_SHOW,
            "reason": "Both showed up — commitment honored!",
            "is_penalty": False,
        }

    elif outcome == "a_ghosted":
        if user_role == "A":
            return {
                "karma_delta": -config.KARMA_GHOST_PENALTY,
                "reason": "Ghosted — didn't show up after committing",
                "is_penalty": True,
            }
        else:
            return {
                "karma_delta": config.KARMA_WINNER_BONUS,
                "reason": "Showed up when the other person ghosted — respect!",
                "is_penalty": False,
            }

    elif outcome == "b_ghosted":
        if user_role == "B":
            return {
                "karma_delta": -config.KARMA_GHOST_PENALTY,
                "reason": "Ghosted — didn't show up after committing",
                "is_penalty": True,
            }
        else:
            return {
                "karma_delta": config.KARMA_WINNER_BONUS,
                "reason": "Showed up when the other person ghosted — respect!",
                "is_penalty": False,
            }

    elif outcome == "both_ghost":
        return {
            "karma_delta": -config.KARMA_BOTH_GHOST_PENALTY,
            "reason": "Nobody showed up — everyone flaked",
            "is_penalty": True,
        }

    elif outcome == "late_cancel":
        return {
            "karma_delta": -config.KARMA_LATE_CANCEL_PENALTY,
            "reason": "Bailed last minute (<6 hours before event)",
            "is_penalty": True,
        }

    return {"karma_delta": 0, "reason": "Unknown outcome", "is_penalty": False}


def get_reputation_tier(karma_score):
    """Get the reputation tier for a given karma score."""
    for tier in config.TIERS:
        if tier["min"] <= karma_score <= tier["max"]:
            return tier
    return config.TIERS[0]


def check_badge_eligibility(show_count, ghost_bust_count):
    """Check which badges a user has earned."""
    earned = []
    for badge in config.BADGES:
        if badge["type"] == "show_count" and show_count >= badge["threshold"]:
            earned.append(badge)
        elif badge["type"] == "ghost_bust" and ghost_bust_count >= badge["threshold"]:
            earned.append(badge)
    return earned


def resolve_full_putup(
    client,
    platform_wallet,
    user_a_wallet,
    user_b_wallet,
    deposit_a,
    deposit_b,
    bag_a_xrp,
    bag_b_xrp,
    checkin_a,
    checkin_b,
    event_name="Social Event",
):
    """
    The main orchestrator — resolves a Put Up by combining escrow + karma.

    1. Determine outcome from check-in booleans
    2. Calculate XRP distribution based on outcome
    3. Distribute XRP payouts from platform wallet
    4. Issue or burn KRM tokens based on outcome
    5. Return full resolution report

    Args:
        deposit_a, deposit_b: dicts with "tx_hash" and "owner" from deposit_bag
        checkin_a, checkin_b: booleans — did they show up?
    """
    # 1. Determine outcome
    if checkin_a and checkin_b:
        outcome = "both_show"
    elif checkin_a and not checkin_b:
        outcome = "b_ghosted"
    elif not checkin_a and checkin_b:
        outcome = "a_ghosted"
    else:
        outcome = "both_ghost"

    print(f"\n  ── Resolving: {event_name} ──")
    print(f"  Outcome: {outcome.upper().replace('_', ' ')}")

    tx_hashes = {
        "deposits": [deposit_a.get("tx_hash", ""), deposit_b.get("tx_hash", "")],
        "payments": [],
        "karma": [],
    }
    timestamps = {
        "deposits": [
            {"who": "User A", "timestamp": deposit_a.get("timestamp", ""), "tx_hash": deposit_a.get("tx_hash", "")},
            {"who": "User B", "timestamp": deposit_b.get("timestamp", ""), "tx_hash": deposit_b.get("tx_hash", "")},
        ],
        "payments": [],
        "karma": [],
    }

    # 2. Calculate and distribute XRP
    dist = calculate_distribution(bag_a_xrp, bag_b_xrp, outcome)
    print(f"\n  [Distributing funds...]")

    if dist["user_a"] > 0:
        pay_result = send_payment(
            client, platform_wallet, user_a_wallet.address,
            dist["user_a"], f"Put Up resolved: {outcome} | {event_name}"
        )
        tx_hashes["payments"].append(pay_result["tx_hash"])
        timestamps["payments"].append({"who": "User A", "amount": dist["user_a"], "timestamp": pay_result["timestamp"], "tx_hash": pay_result["tx_hash"]})

    if dist["user_b"] > 0:
        pay_result = send_payment(
            client, platform_wallet, user_b_wallet.address,
            dist["user_b"], f"Put Up resolved: {outcome} | {event_name}"
        )
        tx_hashes["payments"].append(pay_result["tx_hash"])
        timestamps["payments"].append({"who": "User B", "amount": dist["user_b"], "timestamp": pay_result["timestamp"], "tx_hash": pay_result["tx_hash"]})

    # 4. Issue or burn KRM tokens
    print(f"\n  [Updating karma...]")
    result_a = resolve_outcome(outcome, "A")
    result_b = resolve_outcome(outcome, "B")

    # User A karma
    if result_a["karma_delta"] > 0:
        k_result = issue_karma(
            client, platform_wallet, user_a_wallet.address,
            result_a["karma_delta"], f"{event_name}: {result_a['reason']}"
        )
        tx_hashes["karma"].append(k_result["tx_hash"])
        timestamps["karma"].append({"who": "User A", "delta": f"+{result_a['karma_delta']}", "timestamp": k_result["timestamp"], "tx_hash": k_result["tx_hash"]})
    elif result_a["karma_delta"] < 0:
        current_karma = get_karma_score(client, user_a_wallet.address, platform_wallet.address)
        burn_amount = min(abs(result_a["karma_delta"]), current_karma)
        if burn_amount > 0:
            k_result = burn_karma(
                client, user_a_wallet, platform_wallet.address,
                burn_amount, f"{event_name}: {result_a['reason']}"
            )
            tx_hashes["karma"].append(k_result["tx_hash"])
            timestamps["karma"].append({"who": "User A", "delta": f"-{burn_amount}", "timestamp": k_result["timestamp"], "tx_hash": k_result["tx_hash"]})

    # User B karma
    if result_b["karma_delta"] > 0:
        k_result = issue_karma(
            client, platform_wallet, user_b_wallet.address,
            result_b["karma_delta"], f"{event_name}: {result_b['reason']}"
        )
        tx_hashes["karma"].append(k_result["tx_hash"])
        timestamps["karma"].append({"who": "User B", "delta": f"+{result_b['karma_delta']}", "timestamp": k_result["timestamp"], "tx_hash": k_result["tx_hash"]})
    elif result_b["karma_delta"] < 0:
        current_karma = get_karma_score(client, user_b_wallet.address, platform_wallet.address)
        burn_amount = min(abs(result_b["karma_delta"]), current_karma)
        if burn_amount > 0:
            k_result = burn_karma(
                client, user_b_wallet, platform_wallet.address,
                burn_amount, f"{event_name}: {result_b['reason']}"
            )
            tx_hashes["karma"].append(k_result["tx_hash"])
            timestamps["karma"].append({"who": "User B", "delta": f"-{burn_amount}", "timestamp": k_result["timestamp"], "tx_hash": k_result["tx_hash"]})

    # 5. Build resolution report
    report = {
        "event": event_name,
        "outcome": outcome,
        "xrp_distribution": dist,
        "karma_changes": {
            "user_a": result_a,
            "user_b": result_b,
        },
        "tx_hashes": tx_hashes,
        "timestamps": timestamps,
    }

    print(f"\n  ✓ Resolution complete: {outcome}")
    return report

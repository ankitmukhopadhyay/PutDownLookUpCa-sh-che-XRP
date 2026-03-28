# PUT UP — XRPL Escrow Engine
# On-chain XRP fund management: deposit bags, distribute on resolution
#
# Uses Payment-based escrow flow:
#   1. Users deposit their "Bag" (XRP) to the platform wallet via Payment
#   2. After GPS check-in resolves the outcome, platform distributes funds
#   3. Every transaction is on-chain with memos — fully verifiable

import math
from datetime import datetime, timezone, timedelta

from xrpl.models.transactions import Payment
from xrpl.models import Memo
from xrpl.transaction import submit_and_wait
from xrpl.utils import xrp_to_drops, str_to_hex

import config

# Ripple Epoch starts Jan 1, 2000 — offset from Unix Epoch (Jan 1, 1970)
RIPPLE_EPOCH_OFFSET = 946684800
PST = timezone(timedelta(hours=-8))


def _get_tx_timestamp(result):
    """Extract human-readable timestamp from XRPL transaction result."""
    date = result.get("date")
    if date:
        unix_ts = date + RIPPLE_EPOCH_OFFSET
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone(PST).strftime("%Y-%m-%d %H:%M:%S PST")
    return datetime.now(PST).strftime("%Y-%m-%d %H:%M:%S PST")


def deposit_bag(client, sender_wallet, platform_address, amount_xrp, event_name=""):
    """
    User deposits their Bag (XRP) to the platform wallet.
    This locks their stake for the Put Up — recorded on-chain with a memo.
    """
    memo_text = f"PUT UP Bag Deposit | Event: {event_name}" if event_name else "PUT UP Bag Deposit"
    memos = [
        Memo(
            memo_data=str_to_hex(memo_text),
            memo_type=str_to_hex("text/plain"),
        )
    ]

    payment = Payment(
        account=sender_wallet.address,
        amount=xrp_to_drops(amount_xrp),
        destination=platform_address,
        memos=memos,
    )

    response = submit_and_wait(payment, client, sender_wallet)
    result = response.result
    tx_hash = result.get("hash", "")
    meta_result = result.get("meta", {}).get("TransactionResult", "unknown")
    timestamp = _get_tx_timestamp(result)
    print(f"  ✓ Bag Deposit: {meta_result} | {amount_xrp} XRP locked | {timestamp} | tx: {tx_hash[:16]}...")

    return {
        "tx_hash": tx_hash,
        "owner": sender_wallet.address,
        "amount_xrp": amount_xrp,
        "timestamp": timestamp,
    }


def send_payment(client, sender_wallet, destination, amount_xrp, memo_data=None):
    """
    Send XRP payment with optional memo. Used for fund distribution after resolution.
    """
    memos = None
    if memo_data:
        memos = [
            Memo(
                memo_data=str_to_hex(memo_data),
                memo_type=str_to_hex("text/plain"),
            )
        ]

    payment = Payment(
        account=sender_wallet.address,
        amount=xrp_to_drops(amount_xrp),
        destination=destination,
        memos=memos,
    )

    response = submit_and_wait(payment, client, sender_wallet)
    result = response.result
    tx_hash = result.get("hash", "")
    meta_result = result.get("meta", {}).get("TransactionResult", "unknown")
    timestamp = _get_tx_timestamp(result)
    print(f"  ✓ Payment: {meta_result} | {amount_xrp} XRP → {destination[:12]}... | {timestamp} | tx: {tx_hash[:16]}...")

    return {"tx_hash": tx_hash, "timestamp": timestamp}


def calculate_distribution(bag_a_xrp, bag_b_xrp, outcome):
    """
    Calculate XRP distribution based on Put Up outcome.
    All math in XRP (float), rounded to 6 decimal places.
    Returns dict with payouts for user_a, user_b, and platform.
    """
    if outcome == "both_show":
        fee_a = math.ceil(bag_a_xrp * config.FEE_BOTH_SHOW * 1e6) / 1e6
        fee_b = math.ceil(bag_b_xrp * config.FEE_BOTH_SHOW * 1e6) / 1e6
        return {
            "user_a": round(bag_a_xrp - fee_a, 6),
            "user_b": round(bag_b_xrp - fee_b, 6),
            "platform": round(fee_a + fee_b, 6),
        }

    elif outcome == "a_ghosted":
        platform_cut = math.ceil(bag_a_xrp * config.GHOST_PLATFORM_SHARE * 1e6) / 1e6
        winner_bonus = round(bag_a_xrp - platform_cut, 6)
        return {
            "user_a": 0,
            "user_b": round(bag_b_xrp + winner_bonus, 6),
            "platform": platform_cut,
        }

    elif outcome == "b_ghosted":
        platform_cut = math.ceil(bag_b_xrp * config.GHOST_PLATFORM_SHARE * 1e6) / 1e6
        winner_bonus = round(bag_b_xrp - platform_cut, 6)
        return {
            "user_a": round(bag_a_xrp + winner_bonus, 6),
            "user_b": 0,
            "platform": platform_cut,
        }

    else:  # both_ghost
        return {
            "user_a": 0,
            "user_b": 0,
            "platform": round(bag_a_xrp + bag_b_xrp, 6),
        }

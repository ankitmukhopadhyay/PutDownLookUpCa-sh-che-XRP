# PUT UP — XRPL Karma Engine
# Issue, burn, and query KRM reputation tokens on-chain

import json
from datetime import datetime, timezone, timedelta

from xrpl.models.transactions import Payment
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountLines, AccountTx
from xrpl.models import Memo
from xrpl.transaction import submit_and_wait
from xrpl.utils import str_to_hex, hex_to_str

import config

RIPPLE_EPOCH_OFFSET = 946684800
PST = timezone(timedelta(hours=-8))


def _get_tx_timestamp(result):
    """Extract human-readable timestamp from XRPL transaction result."""
    date = result.get("date")
    if date:
        unix_ts = date + RIPPLE_EPOCH_OFFSET
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone(PST).strftime("%Y-%m-%d %H:%M:%S PST")
    return datetime.now(PST).strftime("%Y-%m-%d %H:%M:%S PST")


def issue_karma(client, issuer_wallet, user_address, amount, memo_data=""):
    """
    Award KARMA: platform issues KRM tokens to user.
    Attaches a memo with the reason for the award.
    """
    payment = Payment(
        account=issuer_wallet.address,
        amount=IssuedCurrencyAmount(
            currency=config.CURRENCY_CODE,
            issuer=issuer_wallet.address,
            value=str(amount),
        ),
        destination=user_address,
        memos=[
            Memo(
                memo_data=str_to_hex(memo_data or f"+{amount} KRM"),
                memo_type=str_to_hex("text/plain"),
            )
        ],
    )

    response = submit_and_wait(payment, client, issuer_wallet)
    result = response.result
    tx_hash = result.get("hash", "")
    meta_result = result.get("meta", {}).get("TransactionResult", "unknown")
    timestamp = _get_tx_timestamp(result)
    print(f"  ✓ Karma +{amount}: {meta_result} → {user_address[:12]}... | {timestamp} | tx: {tx_hash[:16]}...")

    return {"tx_hash": tx_hash, "timestamp": timestamp}


def burn_karma(client, user_wallet, issuer_address, amount, memo_data=""):
    """
    Penalize KARMA: user sends KRM back to issuer (effectively burning it).
    For demo purposes, we control the user wallets so we can execute this directly.
    """
    payment = Payment(
        account=user_wallet.address,
        amount=IssuedCurrencyAmount(
            currency=config.CURRENCY_CODE,
            issuer=issuer_address,
            value=str(amount),
        ),
        destination=issuer_address,
        memos=[
            Memo(
                memo_data=str_to_hex(memo_data or f"-{amount} KRM penalty"),
                memo_type=str_to_hex("text/plain"),
            )
        ],
    )

    response = submit_and_wait(payment, client, user_wallet)
    result = response.result
    tx_hash = result.get("hash", "")
    meta_result = result.get("meta", {}).get("TransactionResult", "unknown")
    timestamp = _get_tx_timestamp(result)
    print(f"  ✓ Karma -{amount}: {meta_result} ← {user_wallet.address[:12]}... | {timestamp} | tx: {tx_hash[:16]}...")

    return {"tx_hash": tx_hash, "timestamp": timestamp}


def get_karma_score(client, address, issuer_address):
    """Read current KRM balance from the user's trust line."""
    try:
        response = client.request(AccountLines(account=address))
        for line in response.result.get("lines", []):
            if line["currency"] == config.CURRENCY_CODE and line["account"] == issuer_address:
                return float(line["balance"])
        return 0.0
    except Exception:
        return 0.0


def get_karma_history(client, address, issuer_address):
    """
    Query on-chain transaction history for KRM token movements.
    Returns a list of karma events with decoded memos.
    """
    events = []
    try:
        response = client.request(AccountTx(account=address))
        transactions = response.result.get("transactions", [])

        for tx_entry in transactions:
            tx = tx_entry.get("tx_json", tx_entry.get("tx", {}))
            meta = tx_entry.get("meta", {})

            if tx.get("TransactionType") != "Payment":
                continue

            # Check if this is a KRM transaction
            # XRPL v4+ uses "DeliverMax" instead of "Amount" for payments
            amount = tx.get("DeliverMax", tx.get("Amount", {}))
            if not isinstance(amount, dict):
                continue
            if amount.get("currency") != config.CURRENCY_CODE:
                continue
            if amount.get("issuer") != issuer_address:
                continue

            # Decode memo
            memo_text = ""
            memos = tx.get("Memos", [])
            if memos:
                memo_data_hex = memos[0].get("Memo", {}).get("MemoData", "")
                if memo_data_hex:
                    try:
                        memo_text = hex_to_str(memo_data_hex)
                    except Exception:
                        memo_text = ""

            # Determine if award or penalty
            is_incoming = tx.get("Destination") == address
            karma_amount = float(amount.get("value", "0"))

            events.append({
                "tx_hash": tx_entry.get("hash", tx.get("hash", "")),
                "amount": karma_amount,
                "type": "award" if is_incoming else "penalty",
                "reason": memo_text,
                "date": tx.get("date", tx_entry.get("close_time_iso", "")),
                "result": meta.get("TransactionResult", ""),
            })

    except Exception as e:
        print(f"  Warning: Could not fetch karma history: {e}")

    return events

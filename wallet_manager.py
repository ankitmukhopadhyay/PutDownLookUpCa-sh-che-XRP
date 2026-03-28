# PUT UP — XRPL Wallet Manager
# Creates and manages wallets for the platform and users

import json
import time
from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet
from xrpl.models.transactions import TrustSet
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountLines
from xrpl.transaction import submit_and_wait
from xrpl.account import get_balance

import config


def create_client():
    """Connect to XRPL Testnet."""
    return JsonRpcClient(config.TESTNET_URL)


def create_funded_wallet(client, label="User"):
    """Create a new wallet funded by the testnet faucet."""
    print(f"  Creating wallet for {label}...")
    wallet = generate_faucet_wallet(client, debug=True)
    print(f"  ✓ {label}: {wallet.address}")
    return wallet


def get_xrp_balance(client, address):
    """Get XRP balance for an address (in XRP, not drops)."""
    try:
        balance_drops = get_balance(address, client)
        return int(balance_drops) / 1_000_000
    except Exception:
        return 0.0


def get_karma_balance(client, address, issuer_address):
    """Get KRM token balance for a user via their trust line."""
    try:
        response = client.request(AccountLines(account=address))
        for line in response.result.get("lines", []):
            if line["currency"] == config.CURRENCY_CODE and line["account"] == issuer_address:
                return float(line["balance"])
        return 0.0
    except Exception:
        return 0.0


def setup_trust_line(client, user_wallet, issuer_address):
    """Create a trust line so the user can hold KRM tokens."""
    trust_set = TrustSet(
        account=user_wallet.address,
        limit_amount=IssuedCurrencyAmount(
            currency=config.CURRENCY_CODE,
            issuer=issuer_address,
            value=config.KARMA_TRUST_LIMIT,
        ),
    )
    response = submit_and_wait(trust_set, client, user_wallet)
    result = response.result["meta"]["TransactionResult"]
    print(f"  ✓ Trust line for KRM: {result}")
    return result == "tesSUCCESS"


def print_balances(client, wallets, issuer_address):
    """Print a formatted balance table for all wallets."""
    print("\n  ┌──────────────┬────────────────┬──────────────┐")
    print("  │ User         │ XRP Balance    │ KRM (Karma)  │")
    print("  ├──────────────┼────────────────┼──────────────┤")
    for label, wallet in wallets.items():
        xrp = get_xrp_balance(client, wallet.address)
        krm = get_karma_balance(client, wallet.address, issuer_address)
        print(f"  │ {label:<12} │ {xrp:>12.2f}  │ {krm:>10.0f}   │")
    print("  └──────────────┴────────────────┴──────────────┘\n")


def save_wallets(wallets, filename=None):
    """Save wallet addresses and seeds to JSON for the web app."""
    filename = filename or config.WALLETS_FILE
    data = {}
    for label, wallet in wallets.items():
        data[label] = {
            "address": wallet.address,
            "seed": wallet.seed,
        }
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✓ Wallets saved to {filename}")


def load_wallets(filename=None):
    """Load wallet data from JSON."""
    filename = filename or config.WALLETS_FILE
    with open(filename, "r") as f:
        return json.load(f)

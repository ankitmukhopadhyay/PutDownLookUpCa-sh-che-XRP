# PUT UP — XRPL Wallet Manager
# Creates and manages wallets for the platform and users

import json
import time
import traceback
from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet, Wallet
from xrpl.models.transactions import TrustSet, Payment
from xrpl.utils import xrp_to_drops
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountLines
from xrpl.transaction import submit_and_wait
from xrpl.account import get_balance

import config


def create_client():
    """Connect to XRPL Testnet."""
    return JsonRpcClient(config.TESTNET_URL)


def create_funded_wallet(client, label="User"):
    """Create a new wallet funded by the testnet faucet (used for platform wallet init only)."""
    print(f"  Creating wallet for {label}...")
    wallet = generate_faucet_wallet(client, debug=True)
    print(f"  ✓ {label}: {wallet.address}")
    return wallet


def create_user_wallet(client, platform_wallet, label="User"):
    """
    Create a new user wallet funded by the platform wallet (not the faucet).
    Platform sends exactly the XRPL reserve needed to activate the wallet.
    This replicates the mainnet flow where the platform covers activation.
    """
    RESERVE_XRP = 22  # 20 base + 2 for trust line object
    print(f"  Creating wallet for {label} (funded by platform)...")
    new_wallet = Wallet.create()
    tx = Payment(
        account=platform_wallet.address,
        destination=new_wallet.address,
        amount=xrp_to_drops(RESERVE_XRP),
    )
    submit_and_wait(tx, client, platform_wallet)
    # Give the testnet a moment to fully index the new account
    time.sleep(3)
    print(f"  ✓ {label}: {new_wallet.address} (activated with {RESERVE_XRP} XRP reserve)")
    return new_wallet


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

"""
PUT UP — Demo Setup Script
===========================
Creates 4 demo accounts in PostgreSQL + XRPL testnet, then simulates a full
Put Up event (one person shows up, one ghosts) to demonstrate karma/XRP flow.

Run with:
    railway run python demo_setup.py      # against Railway DB
    python demo_setup.py                  # against local DB / wallets.json

Demo accounts created:
    alice@demo.putup    password: demo1234
    bob@demo.putup      password: demo1234
    carlos@demo.putup   password: demo1234
    diana@demo.putup    password: demo1234
"""

import os
import sys
import json
import time
from dotenv import load_dotenv

load_dotenv()

from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from werkzeug.security import generate_password_hash

import config
import db
from wallet_manager import (
    create_funded_wallet, create_user_wallet,
    setup_trust_line, get_xrp_balance,
)
from karma_engine import get_karma_score, issue_karma, burn_karma
from escrow_engine import send_payment

# ── Demo user definitions ────────────────────────────────────────

DEMO_USERS = [
    {"name": "Alice",  "email": "alice@demo.putup",  "password": "demo1234"},
    {"name": "Bob",    "email": "bob@demo.putup",    "password": "demo1234"},
    {"name": "Carlos", "email": "carlos@demo.putup", "password": "demo1234"},
    {"name": "Diana",  "email": "diana@demo.putup",  "password": "demo1234"},
]

DEMO_BALANCE = 20  # XRP starting balance for each demo user (from platform)


def log(msg):
    print(f"  {msg}")


def setup_demo():
    print("\n╔══════════════════════════════════════════════╗")
    print("║          PUT UP — Demo Setup                 ║")
    print("╚══════════════════════════════════════════════╝\n")

    # Init DB
    db.init_db()
    log("DB initialized")

    # Connect to XRPL testnet
    client = JsonRpcClient(config.TESTNET_URL)
    log(f"Connected to XRPL testnet: {config.TESTNET_URL}")

    # Load or create Platform wallet
    existing = db.load_wallets()

    if "Platform" not in existing:
        log("Creating Platform wallet from testnet faucet...")
        pw = create_funded_wallet(client, "Platform")
        existing["Platform"] = {"address": pw.address, "seed": pw.seed}
        db.save_wallet("Platform", existing["Platform"])
        log(f"Platform wallet: {pw.address}")
        time.sleep(3)
    else:
        log(f"Platform wallet already exists: {existing['Platform']['address']}")

    platform_wallet = Wallet.from_seed(existing["Platform"]["seed"])

    print()
    print("── Creating demo users ─────────────────────────")

    created = []
    for user in DEMO_USERS:
        name  = user["name"]
        email = user["email"]

        if name in existing:
            log(f"✓ {name} already exists — skipping")
            continue

        # Check email
        already = any(d.get("email", "").lower() == email for n, d in existing.items() if n != "Platform")
        if already:
            log(f"✓ {name} email already registered — skipping")
            continue

        log(f"Creating {name}...")
        try:
            new_wallet = create_user_wallet(client, platform_wallet, name)
            time.sleep(4)
            setup_trust_line(client, new_wallet, platform_wallet.address)

            # Seed starting balance — send XRP from platform
            send_payment(client, platform_wallet, new_wallet.address, DEMO_BALANCE,
                         f"Demo balance for {name}")

            entry = {
                "address":       new_wallet.address,
                "seed":          new_wallet.seed,
                "email":         email,
                "password_hash": generate_password_hash(user["password"]),
                "balance":       float(DEMO_BALANCE),
                "deposit_xrp":   float(DEMO_BALANCE),
                "stripe_paid":   False,
            }
            existing[name] = entry
            db.save_wallet(name, entry)
            log(f"✓ {name}: {new_wallet.address}  (balance: {DEMO_BALANCE} XRP)")
            created.append(name)
        except Exception as e:
            log(f"✗ Failed to create {name}: {e}")
            import traceback; traceback.print_exc()

    print()
    print("── Simulating a Put Up event ───────────────────")
    print("   Alice SHOWS UP.  Bob GHOSTS.")
    print()

    # Need at least Alice and Bob
    existing = db.load_wallets()
    if "Alice" not in existing or "Bob" not in existing:
        log("Alice and Bob must both exist to simulate — skipping simulation.")
    else:
        alice_wallet = Wallet.from_seed(existing["Alice"]["seed"])
        bob_wallet   = Wallet.from_seed(existing["Bob"]["seed"])

        stake = 5  # XRP each

        try:
            # Deduct stake from both at "commit" time
            log("Alice commits 5 XRP...")
            log("Bob commits 5 XRP...")
            for name in ["Alice", "Bob"]:
                existing[name]["balance"] = round(existing[name].get("balance", 0) - stake, 6)
            db.save_all_wallets(existing)

            # Alice shows up → gets her stake back + Bob's stake (minus platform cut)
            ghost_pot    = stake  # only Bob ghosted
            platform_cut = round(ghost_pot * config.GHOST_PLATFORM_SHARE, 6)
            winner_pool  = round(ghost_pot - platform_cut, 6)
            alice_payout = round(stake + winner_pool, 6)

            log(f"Paying Alice {alice_payout} XRP (stake back + ghost bonus)...")
            send_payment(client, platform_wallet, existing["Alice"]["address"],
                         alice_payout, "Put Up resolved: Alice showed up")
            existing["Alice"]["balance"] = round(existing["Alice"].get("balance", 0) + alice_payout, 6)

            # Issue karma
            log("Issuing karma to Alice (+15 KRM: winner)...")
            issue_karma(client, platform_wallet, existing["Alice"]["address"],
                        config.KARMA_WINNER_BONUS, "Demo event: showed up")

            log("Burning karma from Bob (-20 KRM: ghosted)...")
            current_krm = get_karma_score(client, existing["Bob"]["address"], platform_wallet.address)
            burn_amount = min(config.KARMA_GHOST_PENALTY, current_krm)
            if burn_amount > 0:
                burn_karma(client, bob_wallet, platform_wallet.address,
                           burn_amount, "Demo event: ghosted")

            db.save_all_wallets(existing)

            # Print final scores
            print()
            print("── Results ─────────────────────────────────────")
            alice_krm = get_karma_score(client, existing["Alice"]["address"], platform_wallet.address)
            bob_krm   = get_karma_score(client, existing["Bob"]["address"],   platform_wallet.address)
            log(f"Alice → {alice_krm} KRM  |  balance: {existing['Alice']['balance']} XRP")
            log(f"Bob   → {bob_krm} KRM    |  balance: {existing['Bob']['balance']} XRP  (lost stake)")

        except Exception as e:
            log(f"Simulation failed: {e}")
            import traceback; traceback.print_exc()

    print()
    print("── Demo accounts ───────────────────────────────")
    for u in DEMO_USERS:
        print(f"   {u['name']:8}  {u['email']:25}  password: {u['password']}")
    print()
    print("  Done! Visit the app and log in with any demo account.")
    print()


if __name__ == "__main__":
    setup_demo()

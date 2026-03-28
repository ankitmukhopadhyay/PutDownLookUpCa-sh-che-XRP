#!/usr/bin/env python3
"""
PUT UP — Demo Seed Script
Creates wallets, simulates 5 social events with escrow + karma on XRPL Testnet.
Run this before starting the Flask web app.
"""

import time
import json

from wallet_manager import (
    create_client, create_funded_wallet, setup_trust_line,
    print_balances, save_wallets,
)
from escrow_engine import deposit_bag
from reputation import resolve_full_putup
from karma_engine import get_karma_score
import config


def main():
    print("=" * 60)
    print("  PUT UP — XRPL Blockchain Social Accountability Demo")
    print("  Seeding wallets and simulating events on Testnet...")
    print("=" * 60)

    # ── Step 1: Connect ─────────────────────────────────────────
    print("\n[1/7] Connecting to XRPL Testnet...")
    client = create_client()
    print(f"  ✓ Connected to {config.TESTNET_URL}")

    # ── Step 2: Create Wallets ──────────────────────────────────
    print("\n[2/7] Creating funded wallets (this takes ~15 seconds)...")
    platform = create_funded_wallet(client, "Platform")
    time.sleep(3)  # Faucet rate limiting
    alice = create_funded_wallet(client, "Alice")
    time.sleep(3)
    bob = create_funded_wallet(client, "Bob")
    time.sleep(2)

    wallets = {"Platform": platform, "Alice": alice, "Bob": bob}

    # ── Step 3: Trust Lines ─────────────────────────────────────
    print("\n[3/7] Setting up KRM trust lines...")
    setup_trust_line(client, alice, platform.address)
    setup_trust_line(client, bob, platform.address)

    # ── Step 4: Initial Balances ────────────────────────────────
    print("\n[4/7] Initial balances:")
    print_balances(client, wallets, platform.address)

    # ── Step 5: Simulate Events ─────────────────────────────────
    bag_xrp = config.DEFAULT_BAG_XRP  # 100 XRP per bag

    events = [
        {
            "name": "Friday Game Night",
            "checkin_a": True,
            "checkin_b": True,
            "description": "Both Alice and Bob showed up to game night!",
        },
        {
            "name": "Saturday Study Session",
            "checkin_a": True,
            "checkin_b": True,
            "description": "Both showed up to study together.",
        },
        {
            "name": "Sunday Group Hangout",
            "checkin_a": True,
            "checkin_b": False,
            "description": "Bob ghosted the group hangout. Alice was there.",
        },
        {
            "name": "Wednesday Party",
            "checkin_a": True,
            "checkin_b": True,
            "description": "Both pulled up to the party!",
        },
        {
            "name": "Friday Concert",
            "checkin_a": True,
            "checkin_b": False,
            "description": "Bob bailed on the concert. Alice showed up solo.",
        },
    ]

    print(f"\n[5/7] Simulating {len(events)} social events on XRPL...")
    print("  (Each event creates escrow + resolves + updates karma)")
    print("  This will take a few minutes — real blockchain transactions!\n")

    all_reports = []

    for i, event in enumerate(events):
        print(f"\n{'─' * 60}")
        print(f"  EVENT {i+1}/{len(events)}: {event['name']}")
        print(f"  {event['description']}")
        print(f"{'─' * 60}")

        # Deposit bags on-chain
        print("\n  [Depositing bags on-chain...]")
        deposit_a = deposit_bag(client, alice, platform.address, bag_xrp, event["name"])
        deposit_b = deposit_bag(client, bob, platform.address, bag_xrp, event["name"])

        # Resolve
        report = resolve_full_putup(
            client, platform, alice, bob,
            deposit_a, deposit_b,
            bag_xrp, bag_xrp,
            event["checkin_a"], event["checkin_b"],
            event["name"],
        )
        all_reports.append(report)

        # Show current karma
        karma_a = get_karma_score(client, alice.address, platform.address)
        karma_b = get_karma_score(client, bob.address, platform.address)
        print(f"\n  Current Karma → Alice: {karma_a:.0f} KRM | Bob: {karma_b:.0f} KRM")

        # Show transaction timestamps
        ts = report.get("timestamps", {})
        print(f"\n  ┌─── Transaction Timeline: {event['name']} ───")
        for dep in ts.get("deposits", []):
            who = "Alice" if dep["who"] == "User A" else "Bob"
            print(f"  │ {dep['timestamp']}  {who} deposited bag     tx: {dep['tx_hash'][:16]}...")
        for pay in ts.get("payments", []):
            who = "Alice" if pay["who"] == "User A" else "Bob"
            print(f"  │ {pay['timestamp']}  {who} received {pay['amount']:.4f} XRP  tx: {pay['tx_hash'][:16]}...")
        for krm in ts.get("karma", []):
            who = "Alice" if krm["who"] == "User A" else "Bob"
            print(f"  │ {krm['timestamp']}  {who} karma {krm['delta']} KRM      tx: {krm['tx_hash'][:16]}...")
        print(f"  └───────────────────────────────────────────")

        if i < len(events) - 1:
            print("\n  Waiting before next event...")
            time.sleep(2)

    # ── Step 6: Final Balances ──────────────────────────────────
    print(f"\n\n{'=' * 60}")
    print("[6/7] Final balances after all events:")
    print_balances(client, wallets, platform.address)

    # ── Step 7: Save Wallets ────────────────────────────────────
    print("[7/7] Saving wallet data...")
    save_wallets(wallets)

    # ── Full Transaction Timeline ──────────────────────────────
    print(f"\n\n{'=' * 70}")
    print("  COMPLETE TRANSACTION TIMELINE (All Events)")
    print(f"{'=' * 70}")
    tx_count = 0
    for report in all_reports:
        ts = report.get("timestamps", {})
        print(f"\n  ┌─── {report['event']} ({report['outcome'].upper().replace('_', ' ')}) ───")
        for dep in ts.get("deposits", []):
            who = "Alice" if dep["who"] == "User A" else "Bob  "
            print(f"  │ [{dep['timestamp']}]  DEPOSIT   {who}  tx: {dep['tx_hash'][:20]}...")
            tx_count += 1
        for pay in ts.get("payments", []):
            who = "Alice" if pay["who"] == "User A" else "Bob  "
            print(f"  │ [{pay['timestamp']}]  PAYOUT    {who}  {pay['amount']:>10.4f} XRP  tx: {pay['tx_hash'][:20]}...")
            tx_count += 1
        for krm in ts.get("karma", []):
            who = "Alice" if krm["who"] == "User A" else "Bob  "
            print(f"  │ [{krm['timestamp']}]  KARMA     {who}  {krm['delta']:>6} KRM  tx: {krm['tx_hash'][:20]}...")
            tx_count += 1
        print(f"  └───────────────────────────────────────────────────────────────")

    # ── Summary ─────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  DEMO SEED COMPLETE!")
    print(f"{'=' * 70}")
    print(f"\n  Platform: {platform.address}")
    print(f"  Alice:    {alice.address}")
    print(f"  Bob:      {bob.address}")
    print(f"\n  Total on-chain transactions: {tx_count}")
    print(f"\n  Verify any transaction at:")
    print(f"  https://testnet.xrpl.org/accounts/{alice.address}")
    print(f"\n  Now run: python app.py")
    print(f"  Then open: http://localhost:5000")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()

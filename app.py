# PUT UP — Flask Web Application
# Karma dashboard + escrow status website

import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet

import config
from wallet_manager import get_xrp_balance, get_karma_balance, load_wallets
from karma_engine import get_karma_score, get_karma_history, issue_karma, burn_karma
from escrow_engine import deposit_bag, send_payment, calculate_distribution
from reputation import (
    resolve_outcome, get_reputation_tier, resolve_full_putup, check_badge_eligibility
)

app = Flask(__name__)

# Global XRPL client and wallet references
client = None
wallets_data = None
platform_wallet = None
user_wallets = {}


def init_xrpl():
    """Initialize XRPL client and load wallet data."""
    global client, wallets_data, platform_wallet, user_wallets

    client = JsonRpcClient(config.TESTNET_URL)

    if os.path.exists(config.WALLETS_FILE):
        wallets_data = load_wallets()
        platform_wallet = Wallet.from_seed(wallets_data["Platform"]["seed"])
        for label, data in wallets_data.items():
            if label != "Platform":
                user_wallets[label] = {
                    "wallet": Wallet.from_seed(data["seed"]),
                    "address": data["address"],
                    "label": label,
                }


# ── Routes ──────────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page."""
    users = []
    if wallets_data:
        for label, data in wallets_data.items():
            if label != "Platform":
                users.append({"label": label, "address": data["address"]})
    return render_template("index.html", users=users)


@app.route("/profile/<address>")
def profile(address):
    """User karma profile page."""
    if not client or not wallets_data:
        return "Run demo_seed.py first to create wallets.", 500

    issuer_address = wallets_data["Platform"]["address"]

    # Find user label
    label = address[:12] + "..."
    for name, data in wallets_data.items():
        if data["address"] == address:
            label = name
            break

    # Read from XRPL
    karma = get_karma_score(client, address, issuer_address)
    xrp = get_xrp_balance(client, address)
    tier = get_reputation_tier(karma)
    history = get_karma_history(client, address, issuer_address)

    # Calculate stats from history
    show_count = sum(1 for e in history if e["type"] == "award")
    ghost_count = sum(1 for e in history if e["type"] == "penalty")
    total = show_count + ghost_count
    show_rate = round((show_count / total * 100) if total > 0 else 0)

    badges = check_badge_eligibility(show_count, 0)

    return render_template(
        "profile.html",
        address=address,
        label=label,
        karma=karma,
        xrp=xrp,
        tier=tier,
        history=history,
        show_count=show_count,
        ghost_count=ghost_count,
        show_rate=show_rate,
        total=total,
        badges=badges,
        explorer_url=f"https://testnet.xrpl.org/accounts/{address}",
    )


@app.route("/leaderboard")
def leaderboard():
    """Leaderboard — ranked by karma score."""
    if not client or not wallets_data:
        return "Run demo_seed.py first.", 500

    issuer_address = wallets_data["Platform"]["address"]
    users = []

    for label, data in wallets_data.items():
        if label == "Platform":
            continue
        karma = get_karma_score(client, data["address"], issuer_address)
        tier = get_reputation_tier(karma)
        users.append({
            "label": label,
            "address": data["address"],
            "karma": karma,
            "tier": tier,
        })

    users.sort(key=lambda u: u["karma"], reverse=True)
    return render_template("leaderboard.html", users=users)


# ── API Endpoints ───────────────────────────────────────────────

@app.route("/api/karma/<address>")
def api_karma(address):
    """JSON API: karma score + history."""
    if not client or not wallets_data:
        return jsonify({"error": "Not initialized"}), 500

    issuer_address = wallets_data["Platform"]["address"]
    karma = get_karma_score(client, address, issuer_address)
    tier = get_reputation_tier(karma)
    history = get_karma_history(client, address, issuer_address)

    return jsonify({
        "address": address,
        "karma": karma,
        "tier": tier,
        "history": history,
    })


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """Trigger a simulated Put Up scenario on XRPL."""
    if not client or not platform_wallet:
        return jsonify({"error": "Not initialized. Run demo_seed.py first."}), 500

    data = request.get_json()
    scenario = data.get("scenario", "both_show")
    event_name = data.get("event_name", "Demo Event")

    # Get the two demo users
    user_labels = [l for l in user_wallets.keys()]
    if len(user_labels) < 2:
        return jsonify({"error": "Need at least 2 users. Run demo_seed.py."}), 500

    user_a = user_wallets[user_labels[0]]
    user_b = user_wallets[user_labels[1]]

    bag_xrp = config.DEFAULT_BAG_XRP

    try:
        # Deposit bags on-chain
        print(f"\n=== Simulating: {scenario} ({event_name}) ===")
        deposit_a = deposit_bag(client, user_a["wallet"], platform_wallet.address, bag_xrp, event_name)
        deposit_b = deposit_bag(client, user_b["wallet"], platform_wallet.address, bag_xrp, event_name)

        # Determine check-ins
        checkin_a = scenario in ("both_show", "b_ghosts", "b_ghosted")
        checkin_b = scenario in ("both_show", "a_ghosts", "a_ghosted")

        # Resolve
        report = resolve_full_putup(
            client, platform_wallet,
            user_a["wallet"], user_b["wallet"],
            deposit_a, deposit_b,
            bag_xrp, bag_xrp,
            checkin_a, checkin_b,
            event_name,
        )

        # Get updated scores
        issuer_address = platform_wallet.address
        report["new_scores"] = {
            user_labels[0]: get_karma_score(client, user_a["address"], issuer_address),
            user_labels[1]: get_karma_score(client, user_b["address"], issuer_address),
        }

        return jsonify(report)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_xrpl()
    if not wallets_data:
        print("⚠ No wallets.json found. Run 'python demo_seed.py' first!")
        print("  Starting server anyway — simulation won't work until wallets exist.\n")
    else:
        print(f"✓ Loaded {len(wallets_data)} wallets from {config.WALLETS_FILE}")
        print(f"  Platform: {wallets_data['Platform']['address']}")

    app.run(debug=True, port=5000)

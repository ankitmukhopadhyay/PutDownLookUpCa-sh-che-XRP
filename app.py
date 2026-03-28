# PUT UP — Flask Web Application
# Karma dashboard + escrow status website

import os
import json
import time
import socket
from flask import Flask, render_template, request, jsonify, redirect, url_for
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet

import config
from wallet_manager import (
    get_xrp_balance, get_karma_balance, load_wallets,
    create_funded_wallet, setup_trust_line,
)
from karma_engine import get_karma_score, get_karma_history, issue_karma, burn_karma
from escrow_engine import deposit_bag, send_payment, calculate_distribution
from reputation import (
    resolve_outcome, get_reputation_tier, resolve_full_putup, check_badge_eligibility
)
from gps_engine import validate_checkin

app = Flask(__name__)


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

# Global XRPL client and wallet references
client = None
wallets_data = None
platform_wallet = None
user_wallets = {}

# In-memory active event (resets on server restart)
active_event = {}


def init_xrpl():
    """Initialize XRPL client. Auto-creates Platform wallet if needed."""
    global client, wallets_data, platform_wallet, user_wallets

    client = JsonRpcClient(config.TESTNET_URL)

    existing = load_wallets() if os.path.exists(config.WALLETS_FILE) else {}

    # Auto-create Platform wallet on first run — no demo_seed.py needed
    if "Platform" not in existing:
        print("  No Platform wallet found — creating one from testnet faucet...")
        pw = create_funded_wallet(client, "Platform")
        existing["Platform"] = {"address": pw.address, "seed": pw.seed}
        with open(config.WALLETS_FILE, "w") as f:
            json.dump(existing, f, indent=2)
        print(f"  ✓ Platform wallet created: {pw.address}")

    wallets_data = existing
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


# ── Registration ────────────────────────────────────────────────

@app.route("/register")
def register():
    return render_template("register.html")


@app.route("/api/register", methods=["POST"])
def api_register():
    global wallets_data, user_wallets
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    existing = load_wallets() if os.path.exists(config.WALLETS_FILE) else {}
    if name in existing:
        return jsonify({"error": f"'{name}' is already registered. Choose a different name."}), 400

    try:
        new_wallet = create_funded_wallet(client, name)
        setup_trust_line(client, new_wallet, platform_wallet.address)

        existing[name] = {"address": new_wallet.address, "seed": new_wallet.seed}
        with open(config.WALLETS_FILE, "w") as f:
            json.dump(existing, f, indent=2)

        wallets_data = existing
        user_wallets[name] = {
            "wallet": new_wallet,
            "address": new_wallet.address,
            "label": name,
        }

        xrp = get_xrp_balance(client, new_wallet.address)
        return jsonify({
            "name": name,
            "address": new_wallet.address,
            "xrp": round(xrp, 2),
            "profile_url": f"/profile/{new_wallet.address}",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Event Creation ───────────────────────────────────────────────

@app.route("/event/create")
def event_create():
    users = []
    if wallets_data:
        for label, data in wallets_data.items():
            if label != "Platform":
                users.append({"label": label, "address": data["address"]})
    return render_template("event_create.html", users=users)


@app.route("/api/event/create", methods=["POST"])
def api_event_create():
    global active_event, wallets_data, user_wallets
    data = request.get_json()

    name = data.get("name", "").strip()
    lat = data.get("lat")
    lon = data.get("lon")
    scheduled_time = data.get("scheduled_time")
    name_a = data.get("participant_a_name", "").strip()
    name_b = data.get("participant_b_name", "").strip()
    deposit_xrp = float(data.get("deposit_xrp", config.DEFAULT_BAG_XRP))

    if not all([name, lat is not None, lon is not None, scheduled_time, name_a, name_b]):
        return jsonify({"error": "Missing required fields"}), 400
    if name_a.lower() == name_b.lower():
        return jsonify({"error": "Participants must have different names"}), 400

    existing = load_wallets() if os.path.exists(config.WALLETS_FILE) else {}

    try:
        # Create wallet for participant A
        wallet_a = create_funded_wallet(client, name_a)
        setup_trust_line(client, wallet_a, platform_wallet.address)
        existing[name_a] = {"address": wallet_a.address, "seed": wallet_a.seed}
        user_wallets[name_a] = {"wallet": wallet_a, "address": wallet_a.address, "label": name_a}

        # Create wallet for participant B
        wallet_b = create_funded_wallet(client, name_b)
        setup_trust_line(client, wallet_b, platform_wallet.address)
        existing[name_b] = {"address": wallet_b.address, "seed": wallet_b.seed}
        user_wallets[name_b] = {"wallet": wallet_b, "address": wallet_b.address, "label": name_b}

        with open(config.WALLETS_FILE, "w") as f:
            json.dump(existing, f, indent=2)
        wallets_data = existing

        active_event = {
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
            "scheduled_time": float(scheduled_time),
            "deposit_xrp": deposit_xrp,
            "participant_a": wallet_a.address,
            "participant_b": wallet_b.address,
            "participant_a_name": name_a,
            "participant_b_name": name_b,
            "checkins": {},
        }
        return jsonify({
            "success": True,
            "participant_a": {"name": name_a, "address": wallet_a.address},
            "participant_b": {"name": name_b, "address": wallet_b.address},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Event Status ─────────────────────────────────────────────────

@app.route("/event")
def event_status():
    if not active_event:
        return render_template("event_status.html", event=None, participants=[])

    participants = []
    for addr in [active_event["participant_a"], active_event["participant_b"]]:
        label = addr[:12] + "..."
        for n, d in (wallets_data or {}).items():
            if d["address"] == addr:
                label = n
                break
        info = active_event["checkins"].get(addr, {})
        participants.append({
            "address": addr,
            "label": label,
            "checked_in": addr in active_event["checkins"],
            "distance_ft": info.get("distance_ft"),
            "elapsed_min": info.get("elapsed_min"),
        })

    window_end_ms = int((active_event["scheduled_time"] + config.GPS_WINDOW_MINUTES * 60) * 1000)
    scheduled_ms = int(active_event["scheduled_time"] * 1000)

    base_url = f"http://{request.host}"

    return render_template(
        "event_status.html",
        event=active_event,
        participants=participants,
        scheduled_ms=scheduled_ms,
        window_end_ms=window_end_ms,
        base_url=base_url,
    )


# ── GPS Check-In ─────────────────────────────────────────────────

@app.route("/checkin/<address>")
def checkin_page(address):
    label = address[:12] + "..."
    for n, d in (wallets_data or {}).items():
        if d["address"] == address:
            label = n
            break

    if not active_event:
        return render_template("checkin.html", event=None, address=address, label=label)

    checked_in = address in active_event["checkins"]
    checkin_info = active_event["checkins"].get(address, {})
    scheduled_ms = int(active_event["scheduled_time"] * 1000)
    window_end_ms = int((active_event["scheduled_time"] + config.GPS_WINDOW_MINUTES * 60) * 1000)

    return render_template(
        "checkin.html",
        event=active_event,
        address=address,
        label=label,
        checked_in=checked_in,
        checkin_info=checkin_info,
        scheduled_ms=scheduled_ms,
        window_end_ms=window_end_ms,
        gps_radius=config.GPS_RADIUS_FEET,
        gps_window=config.GPS_WINDOW_MINUTES,
    )


@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    if not active_event:
        return jsonify({"error": "No active event"}), 400

    data = request.get_json()
    address = data.get("address")
    user_lat = data.get("lat")
    user_lon = data.get("lon")

    if not all([address, user_lat is not None, user_lon is not None]):
        return jsonify({"error": "Missing address or GPS coordinates"}), 400

    if address not in (active_event["participant_a"], active_event["participant_b"]):
        return jsonify({"error": "You are not a participant in this event"}), 400

    if address in active_event["checkins"]:
        return jsonify({"error": "Already checked in", "already_checked_in": True}), 400

    valid, reason, distance_ft, elapsed_min = validate_checkin(
        float(user_lat), float(user_lon),
        active_event["lat"], active_event["lon"],
        active_event["scheduled_time"],
        config.GPS_RADIUS_FEET,
        config.GPS_WINDOW_MINUTES,
    )

    if valid:
        active_event["checkins"][address] = {
            "distance_ft": distance_ft,
            "elapsed_min": elapsed_min,
        }

    return jsonify({"valid": valid, "reason": reason, "distance_ft": distance_ft, "elapsed_min": elapsed_min})


@app.route("/api/event/status")
def api_event_status():
    if not active_event:
        return jsonify({"active": False})
    return jsonify({
        "active": True,
        "name": active_event["name"],
        "scheduled_time": active_event["scheduled_time"],
        "participant_a": active_event["participant_a"],
        "participant_b": active_event["participant_b"],
        "checkins": list(active_event["checkins"].keys()),
    })


@app.route("/api/event/resolve", methods=["POST"])
def api_event_resolve():
    global active_event
    if not active_event:
        return jsonify({"error": "No active event"}), 400
    if not client or not platform_wallet:
        return jsonify({"error": "Not initialized"}), 500

    addr_a = active_event["participant_a"]
    addr_b = active_event["participant_b"]

    wallet_a = next((uw["wallet"] for uw in user_wallets.values() if uw["address"] == addr_a), None)
    wallet_b = next((uw["wallet"] for uw in user_wallets.values() if uw["address"] == addr_b), None)

    if not wallet_a or not wallet_b:
        return jsonify({"error": "Could not find participant wallets. Were they registered on this server?"}), 500

    checkin_a = addr_a in active_event["checkins"]
    checkin_b = addr_b in active_event["checkins"]
    event_name = active_event["name"]

    try:
        deposit_xrp = active_event.get("deposit_xrp", config.DEFAULT_BAG_XRP)
        deposit_a = deposit_bag(client, wallet_a, platform_wallet.address, deposit_xrp, event_name)
        deposit_b = deposit_bag(client, wallet_b, platform_wallet.address, deposit_xrp, event_name)

        report = resolve_full_putup(
            client, platform_wallet,
            wallet_a, wallet_b,
            deposit_a, deposit_b,
            deposit_xrp, deposit_xrp,
            checkin_a, checkin_b,
            event_name,
        )

        issuer_address = platform_wallet.address
        report["new_scores"] = {
            addr_a: get_karma_score(client, addr_a, issuer_address),
            addr_b: get_karma_score(client, addr_b, issuer_address),
        }

        active_event = {}
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_xrpl()
    lan_ip = get_lan_ip()
    print(f"\n  PUT UP is running!")
    print(f"  Local:   http://localhost:8080")
    print(f"  Network: http://{lan_ip}:8080  ← share this with participants\n")
    app.run(host="0.0.0.0", port=8080, debug=True)

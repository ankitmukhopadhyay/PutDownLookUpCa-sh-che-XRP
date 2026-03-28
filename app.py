# PUT UP — Flask Web Application
# Karma dashboard + escrow status website

import os
import json
import time
import socket
import uuid
import traceback
import stripe
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, jsonify, redirect, url_for, session as flask_session
from werkzeug.security import generate_password_hash, check_password_hash
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AccountTx

import config
import db
from wallet_manager import (
    get_xrp_balance, get_karma_balance, load_wallets,
    create_funded_wallet, create_user_wallet, setup_trust_line,
)
from karma_engine import get_karma_score, get_karma_history, issue_karma, burn_karma
from escrow_engine import deposit_bag, send_payment, calculate_distribution
from reputation import (
    resolve_outcome, get_reputation_tier, resolve_full_putup, check_badge_eligibility
)
from gps_engine import validate_checkin

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "putup-dev-secret-2024")
stripe.api_key = config.STRIPE_SECRET_KEY


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

# In-memory active events keyed by event ID (resets on server restart)
active_events = {}

# Pending registrations: token → {name, email, password_hash, deposit_xrp}
pending_registrations = {}


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


# ── Context Processor ───────────────────────────────────────────

@app.context_processor
def inject_user():
    address = flask_session.get("address")
    current_user = None
    if address and wallets_data:
        for name, data in wallets_data.items():
            if data.get("address") == address:
                current_user = {"name": name, "address": address}
                break
    return {"current_user": current_user}


# ── Routes ──────────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page — auth gate if not logged in, dashboard if logged in."""
    address = flask_session.get("address")
    if not address:
        return render_template("index.html", logged_in=False, users=[], current_wallet=None)

    # Build user list with karma for dashboard
    users = []
    current_wallet = None
    issuer_address = wallets_data["Platform"]["address"] if wallets_data else None

    if wallets_data and issuer_address:
        for label, data in wallets_data.items():
            if label == "Platform":
                continue
            karma = get_karma_score(client, data["address"], issuer_address) if client else 0
            tier = get_reputation_tier(karma)
            entry = {
                "label": label,
                "address": data["address"],
                "karma": karma,
                "tier": tier,
                "balance": data.get("balance", 0),
            }
            users.append(entry)
            if data["address"] == address:
                current_wallet = entry

        users.sort(key=lambda u: u["karma"], reverse=True)

    return render_template("index.html", logged_in=True, users=users, current_wallet=current_wallet)


@app.route("/profile/<address>")
def profile(address):
    """User karma profile page."""
    if not client or not wallets_data:
        return "Run demo_seed.py first to create wallets.", 500

    issuer_address = wallets_data["Platform"]["address"]

    # Find user label and balance
    label = address[:12] + "..."
    balance = 0
    for name, data in wallets_data.items():
        if data.get("address") == address:
            label = name
            balance = data.get("balance", 0)
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
        balance=balance,
        tier=tier,
        history=history,
        show_count=show_count,
        ghost_count=ghost_count,
        show_rate=show_rate,
        total=total,
        badges=badges,
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
    if flask_session.get("address"):
        return redirect(f"/profile/{flask_session['address']}")
    return render_template("register.html", stripe_pub_key=config.STRIPE_PUBLISHABLE_KEY)


@app.route("/api/stripe/checkout", methods=["POST"])
def stripe_checkout():
    data = request.get_json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    deposit_xrp = float(data.get("deposit_xrp", 0))

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    existing = load_wallets() if os.path.exists(config.WALLETS_FILE) else {}
    if name in existing:
        return jsonify({"error": f"'{name}' is already registered."}), 400
    # Check email uniqueness
    for n, d in existing.items():
        if d.get("email", "").lower() == email:
            return jsonify({"error": f"An account with that email already exists."}), 400

    if deposit_xrp <= 0:
        return jsonify({"error": "Deposit must be greater than 0 to pay via Stripe."}), 400

    usd_amount = round(deposit_xrp * config.USD_PER_XRP, 2)
    if usd_amount < 0.50:
        return jsonify({"error": "Minimum deposit is 0.25 XRP ($0.50)."}), 400

    # Store pending registration so we can retrieve after Stripe redirect
    token = str(uuid.uuid4())
    pending_registrations[token] = {
        "name": name,
        "email": email,
        "password_hash": generate_password_hash(password),
        "deposit_xrp": deposit_xrp,
    }

    try:
        base_url = request.host_url.rstrip("/")
        stripe_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"PUT UP Balance Deposit — {name}",
                        "description": f"{deposit_xrp} XRP credited to your PUT UP account",
                    },
                    "unit_amount": int(usd_amount * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base_url}/register/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/register",
            metadata={"token": token},
        )
        return jsonify({"url": stripe_session.url})
    except Exception as e:
        pending_registrations.pop(token, None)
        return jsonify({"error": str(e)}), 500


@app.route("/register/success")
def register_success():
    session_id = request.args.get("session_id")
    if not session_id:
        return redirect("/register")

    try:
        stripe_session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        return render_template("register_success.html",
            error=f"Could not verify payment ({type(e).__name__}: {e}). Contact support.")

    if stripe_session.payment_status != "paid":
        return render_template("register_success.html",
            error="Payment not completed. Please try again.")

    try:
        metadata = dict(stripe_session.metadata or {})
        token = metadata.get("token")
        pending = pending_registrations.pop(token, None) if token else None

        if not pending:
            # Session expired or server restarted — we can't recover without re-registering
            return render_template("register_success.html",
                error="Your session expired. Payment went through but wallet was not created — please contact support with your Stripe receipt.")

        return _create_wallet_and_respond(
            pending["name"], pending["deposit_xrp"], stripe_paid=True,
            email=pending["email"], password_hash=pending["password_hash"],
        )
    except Exception as e:
        print(f"\n[ERROR] register_success outer exception:")
        traceback.print_exc()
        return render_template("register_success.html",
            error=f"Wallet creation failed ({type(e).__name__}: {e}). Please try again.")


@app.route("/api/stripe/topup", methods=["POST"])
def stripe_topup():
    global wallets_data
    data = request.get_json()
    address = data.get("address", "").strip()
    topup_xrp = float(data.get("topup_xrp", 0))

    if not address:
        return jsonify({"error": "Address required"}), 400
    if topup_xrp <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400

    usd_amount = round(topup_xrp * config.USD_PER_XRP, 2)
    if usd_amount < 0.50:
        return jsonify({"error": "Minimum top-up is 0.25 XRP ($0.50)."}), 400

    # Find the name for this address
    name = None
    for n, d in (wallets_data or {}).items():
        if d.get("address") == address:
            name = n
            break
    if not name:
        return jsonify({"error": "Address not found"}), 404

    try:
        base_url = request.host_url.rstrip("/")
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"PUT UP Top-Up — {name}",
                        "description": f"Adding {topup_xrp} XRP to your PUT UP balance",
                    },
                    "unit_amount": int(usd_amount * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base_url}/topup/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/profile/{address}",
            metadata={"address": address, "topup_xrp": str(topup_xrp)},
        )
        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/topup/success")
def topup_success():
    global wallets_data
    session_id = request.args.get("session_id")
    if not session_id:
        return redirect("/")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status != "paid":
            return redirect("/")

        address = session.metadata["address"]
        topup_xrp = float(session.metadata["topup_xrp"])

        # Update balance in wallets_data and wallets.json
        for name, d in wallets_data.items():
            if d.get("address") == address:
                d["balance"] = round(d.get("balance", 0) + topup_xrp, 6)
                break
        with open(config.WALLETS_FILE, "w") as f:
            json.dump(wallets_data, f, indent=2)

        return redirect(f"/profile/{address}?topped_up={topup_xrp}")
    except Exception as e:
        return redirect("/")


def _create_wallet_and_respond(name, deposit_xrp, stripe_paid=False, email=None, password_hash=None):
    """Shared wallet creation logic used by both Stripe and direct registration."""
    global wallets_data, user_wallets

    existing = load_wallets() if os.path.exists(config.WALLETS_FILE) else {}

    # Guard 1: name already taken
    if name in existing:
        err = f"'{name}' is already registered."
        if stripe_paid:
            return render_template("register_success.html", error=err)
        return jsonify({"error": err}), 400

    # Guard 2: email already used (one wallet per email)
    if email:
        for n, d in existing.items():
            if n != "Platform" and d.get("email", "").lower() == email.lower():
                err = f"An account already exists for {email}. Please log in instead."
                if stripe_paid:
                    return render_template("register_success.html", error=err)
                return jsonify({"error": err}), 400

    try:
        fresh_client = JsonRpcClient(config.TESTNET_URL)
        # Platform funds the reserve — no faucet (replicates mainnet flow)
        new_wallet = create_user_wallet(fresh_client, platform_wallet, name)

        # Wait for the testnet to fully index the new account before sending more txs
        time.sleep(4)

        setup_trust_line(fresh_client, new_wallet, platform_wallet.address)

        # Send user deposit to platform
        deposit_tx_hash = None
        if deposit_xrp > 0:
            dep = deposit_bag(fresh_client, new_wallet, platform_wallet.address, deposit_xrp, "Registration Deposit")
            deposit_tx_hash = dep["tx_hash"]

        entry = {
            "address": new_wallet.address,
            "seed": new_wallet.seed,
            "deposit_xrp": deposit_xrp,
            "balance": deposit_xrp,
            "stripe_paid": stripe_paid,
        }
        if email:
            entry["email"] = email
        if password_hash:
            entry["password_hash"] = password_hash

        existing[name] = entry
        with open(config.WALLETS_FILE, "w") as f:
            json.dump(existing, f, indent=2)

        wallets_data = existing
        user_wallets[name] = {
            "wallet": new_wallet,
            "address": new_wallet.address,
            "label": name,
            "deposit_xrp": deposit_xrp,
        }

        # Log the user in immediately after registration
        flask_session["address"] = new_wallet.address

        result = {
            "name": name,
            "address": new_wallet.address,
            "deposit_xrp": deposit_xrp,
            "balance": deposit_xrp,
            "deposit_tx_hash": deposit_tx_hash,
            "profile_url": f"/profile/{new_wallet.address}",
            "stripe_paid": stripe_paid,
        }

        if stripe_paid:
            return render_template("register_success.html", result=result)
        return jsonify(result)

    except Exception as e:
        print(f"\n[ERROR] _create_wallet_and_respond failed:")
        traceback.print_exc()
        err_msg = f"{type(e).__name__}: {e}"
        if stripe_paid:
            return render_template("register_success.html", error=err_msg)
        return jsonify({"error": err_msg}), 500


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    deposit_xrp = float(data.get("deposit_xrp", 0))
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    password_hash = generate_password_hash(password)
    return _create_wallet_and_respond(name, deposit_xrp, stripe_paid=False,
                                      email=email, password_hash=password_hash)


# ── Auth ─────────────────────────────────────────────────────────

@app.route("/login")
def login():
    if flask_session.get("address"):
        return redirect("/")
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    global wallets_data, user_wallets
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    # Always read fresh from DB so users seeded after server start are found
    existing = db.load_wallets()
    for name, d in existing.items():
        if name == "Platform":
            continue
        if d.get("email", "").lower() == email:
            ph = d.get("password_hash", "")
            if ph and check_password_hash(ph, password):
                flask_session["address"] = d["address"]
                # Refresh in-memory state so the rest of the app knows this user
                wallets_data = existing
                if name not in user_wallets and d.get("seed"):
                    user_wallets[name] = {
                        "wallet": Wallet.from_seed(d["seed"]),
                        "address": d["address"],
                        "label": name,
                    }
                return jsonify({"success": True, "address": d["address"], "name": name,
                                "profile_url": f"/profile/{d['address']}"})
            else:
                return jsonify({"error": "Incorrect password"}), 401

    return jsonify({"error": "No account found with that email"}), 404


@app.route("/logout")
def logout():
    flask_session.clear()
    return redirect("/")



# ── Event Creation ───────────────────────────────────────────────

@app.route("/event/create")
def event_create():
    users = []
    if wallets_data:
        for label, data in wallets_data.items():
            if label != "Platform":
                bal = data.get("balance", 0)
                users.append({
                    "label": label,
                    "address": data["address"],
                    "balance": bal,
                    "display": f"{label} ({bal} XRP)",
                })
    return render_template("event_create.html", users=users)


@app.route("/api/event/create", methods=["POST"])
def api_event_create():
    global active_events, wallets_data, user_wallets
    data = request.get_json()

    name = data.get("name", "").strip()
    lat = data.get("lat")
    lon = data.get("lon")
    scheduled_time = data.get("scheduled_time")
    participant_addresses = data.get("participant_addresses", [])
    deposit_xrp = float(data.get("deposit_xrp", 0))

    if not all([name, lat is not None, lon is not None, scheduled_time]):
        return jsonify({"error": "Missing required fields"}), 400
    if len(participant_addresses) < 2:
        return jsonify({"error": "At least 2 participants required"}), 400
    if len(participant_addresses) != len(set(participant_addresses)):
        return jsonify({"error": "Duplicate participants selected"}), 400

    # Look up names and balances
    participants = []
    for addr in participant_addresses:
        label = addr[:12] + "..."
        balance = 0
        for n, d in (wallets_data or {}).items():
            if d.get("address") == addr:
                label = n
                balance = d.get("balance", 0)
                break
        participants.append({"name": label, "address": addr, "balance": balance})

    # Validate balance
    if deposit_xrp > 0:
        for p in participants:
            if p["balance"] < deposit_xrp:
                return jsonify({
                    "error": f"{p['name']} only has {p['balance']} XRP (need {deposit_xrp} XRP)."
                }), 400

    # Lock stake — deduct from balance immediately at event creation
    if deposit_xrp > 0 and wallets_data:
        for p in participants:
            for n, d in wallets_data.items():
                if d.get("address") == p["address"]:
                    d["balance"] = round(d.get("balance", 0) - deposit_xrp, 6)
                    break
        with open(config.WALLETS_FILE, "w") as f:
            json.dump(wallets_data, f, indent=2)

    event_id = f"evt_{int(time.time() * 1000)}"
    active_events[event_id] = {
        "id": event_id,
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "scheduled_time": float(scheduled_time),
        "deposit_xrp": deposit_xrp,
        "participants": participants,
        "checkins": {},
    }
    return jsonify({"success": True, "event_id": event_id, "participants": participants})


# ── Event Status ─────────────────────────────────────────────────

@app.route("/event")
def event_status():
    base_url = f"http://{request.host}"
    events = []
    for ev in active_events.values():
        ps = []
        for p in ev["participants"]:
            addr = p["address"]
            info = ev["checkins"].get(addr, {})
            ps.append({
                "address": addr,
                "label": p["name"],
                "checked_in": addr in ev["checkins"],
                "distance_ft": info.get("distance_ft"),
                "elapsed_min": info.get("elapsed_min"),
            })
        events.append({
            "id": ev["id"],
            "name": ev["name"],
            "lat": ev["lat"],
            "lon": ev["lon"],
            "deposit_xrp": ev["deposit_xrp"],
            "participants": ps,
            "scheduled_ms": int(ev["scheduled_time"] * 1000),
            "window_end_ms": int((ev["scheduled_time"] + config.GPS_WINDOW_MINUTES * 60) * 1000),
        })
    return render_template("event_status.html", events=events, base_url=base_url)


# ── GPS Check-In ─────────────────────────────────────────────────

@app.route("/checkin/<address>")
def checkin_page(address):
    label = address[:12] + "..."
    for n, d in (wallets_data or {}).items():
        if d.get("address") == address:
            label = n
            break

    # Find all events this address is part of
    user_events = [ev for ev in active_events.values()
                   if any(p["address"] == address for p in ev["participants"])]

    if not user_events:
        return render_template("checkin.html", event=None, address=address, label=label)

    # If specific event requested via query param, use that
    event_id = request.args.get("event_id")
    ev = None
    if event_id and event_id in active_events:
        ev = active_events[event_id]
    elif len(user_events) == 1:
        ev = user_events[0]
    else:
        # Multiple events — let user pick
        return render_template("checkin.html", select_event=True,
                               user_events=user_events, address=address, label=label)

    checked_in = address in ev["checkins"]
    checkin_info = ev["checkins"].get(address, {})
    return render_template(
        "checkin.html",
        event=ev,
        address=address,
        label=label,
        checked_in=checked_in,
        checkin_info=checkin_info,
        scheduled_ms=int(ev["scheduled_time"] * 1000),
        window_end_ms=int((ev["scheduled_time"] + config.GPS_WINDOW_MINUTES * 60) * 1000),
        gps_radius=config.GPS_RADIUS_FEET,
        gps_window=config.GPS_WINDOW_MINUTES,
    )


@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    data = request.get_json()
    address = data.get("address")
    event_id = data.get("event_id")
    user_lat = data.get("lat")
    user_lon = data.get("lon")

    if not event_id or event_id not in active_events:
        return jsonify({"error": "Event not found"}), 400
    if not all([address, user_lat is not None, user_lon is not None]):
        return jsonify({"error": "Missing address or GPS coordinates"}), 400

    ev = active_events[event_id]
    if address not in [p["address"] for p in ev["participants"]]:
        return jsonify({"error": "You are not a participant in this event"}), 400
    if address in ev["checkins"]:
        return jsonify({"valid": True, "already_checked_in": True,
                        "distance_ft": ev["checkins"][address]["distance_ft"],
                        "elapsed_min": ev["checkins"][address]["elapsed_min"]})

    valid, reason, distance_ft, elapsed_min = validate_checkin(
        float(user_lat), float(user_lon),
        ev["lat"], ev["lon"],
        ev["scheduled_time"],
        config.GPS_RADIUS_FEET,
        config.GPS_WINDOW_MINUTES,
    )
    if valid:
        ev["checkins"][address] = {"distance_ft": distance_ft, "elapsed_min": elapsed_min}

    return jsonify({"valid": valid, "reason": reason, "distance_ft": distance_ft, "elapsed_min": elapsed_min})


@app.route("/api/event/status")
def api_event_status():
    return jsonify({"active": len(active_events) > 0, "count": len(active_events)})


@app.route("/api/event/resolve", methods=["POST"])
def api_event_resolve():
    global active_events
    if not client or not platform_wallet:
        return jsonify({"error": "Not initialized"}), 500

    data = request.get_json() or {}
    event_id = data.get("event_id")
    if not event_id or event_id not in active_events:
        return jsonify({"error": "Event not found"}), 400

    ev = active_events[event_id]
    participants = ev["participants"]
    deposit_xrp = ev.get("deposit_xrp", 0)
    event_name = ev["name"]
    checkins = ev["checkins"]

    showups = [p for p in participants if p["address"] in checkins]
    ghosts  = [p for p in participants if p["address"] not in checkins]

    wallets = {}
    for p in participants:
        w = next((uw["wallet"] for uw in user_wallets.values() if uw["address"] == p["address"]), None)
        if not w:
            return jsonify({"error": f"Wallet not found for {p['name']}."}), 500
        wallets[p["address"]] = w

    try:
        tx_hashes = {"payments": [], "karma": []}

        ghost_pot       = round(deposit_xrp * len(ghosts), 6)
        platform_cut    = round(ghost_pot * config.GHOST_PLATFORM_SHARE, 6) if ghost_pot > 0 else 0
        winner_pool     = round(ghost_pot - platform_cut, 6)
        bonus_per_show  = round(winner_pool / len(showups), 6) if showups else 0
        payout_per_show = round(deposit_xrp + bonus_per_show, 6)

        # Pay show-ups: return stake + ghost pot bonus
        for p in showups:
            if deposit_xrp > 0:
                pay = send_payment(client, platform_wallet, p["address"], payout_per_show,
                                   f"Put Up resolved | {event_name}")
                tx_hashes["payments"].append(pay["tx_hash"])
            karma_delta = config.KARMA_WINNER_BONUS if ghosts else config.KARMA_BOTH_SHOW
            k = issue_karma(client, platform_wallet, p["address"], karma_delta,
                            f"{event_name}: showed up")
            tx_hashes["karma"].append(k["tx_hash"])

        # Penalise ghosts (stake already deducted at creation)
        for p in ghosts:
            penalty = config.KARMA_BOTH_GHOST_PENALTY if not showups else config.KARMA_GHOST_PENALTY
            current = get_karma_score(client, p["address"], platform_wallet.address)
            burn_amount = min(penalty, current)
            if burn_amount > 0:
                k = burn_karma(client, wallets[p["address"]], platform_wallet.address,
                               burn_amount, f"{event_name}: ghosted")
                tx_hashes["karma"].append(k["tx_hash"])

        # Update balances: showups get back payout, ghosts already lost stake at creation
        if deposit_xrp > 0 and wallets_data:
            for p in showups:
                for n, d in wallets_data.items():
                    if d.get("address") == p["address"]:
                        d["balance"] = round(d.get("balance", 0) + payout_per_show, 6)
                        break
            with open(config.WALLETS_FILE, "w") as f:
                json.dump(wallets_data, f, indent=2)

        issuer = platform_wallet.address
        outcome = "all_show" if not ghosts else ("all_ghost" if not showups else "mixed")

        report = {
            "event": event_name,
            "outcome": outcome,
            "showups": [p["name"] for p in showups],
            "ghosts":  [p["name"] for p in ghosts],
            "deposit_xrp": deposit_xrp,
            "payout_per_showup": payout_per_show if showups else 0,
            "platform_cut": platform_cut,
            "tx_hashes": tx_hashes,
            "new_scores": {p["name"]: get_karma_score(client, p["address"], issuer) for p in participants},
        }

        del active_events[event_id]
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Explorer ────────────────────────────────────────────────────

@app.route("/explorer")
def explorer():
    if not client or not wallets_data:
        return "XRPL not initialized.", 500

    issuer_address = wallets_data["Platform"]["address"]

    # Platform wallet info
    platform_xrp = get_xrp_balance(client, issuer_address)

    # User wallets with balances
    users = []
    for label, data in wallets_data.items():
        if label == "Platform":
            continue
        xrp = get_xrp_balance(client, data["address"])
        krm = get_karma_balance(client, data["address"], issuer_address)
        users.append({
            "label": label,
            "address": data["address"],
            "xrp": round(xrp, 4),
            "krm": int(krm),
            "balance": data.get("balance", 0),
        })

    # Recent transactions on platform wallet (last 20)
    transactions = []
    try:
        resp = client.request(AccountTx(account=issuer_address, limit=20))
        for item in resp.result.get("transactions", []):
            tx = item.get("tx", {})
            meta = item.get("meta", {})
            tx_type = tx.get("TransactionType", "")
            tx_hash = tx.get("hash", "")
            amount_raw = tx.get("Amount", 0)
            amount_xrp = None
            if isinstance(amount_raw, str):
                amount_xrp = round(int(amount_raw) / 1_000_000, 4)

            # Decode memo if present
            memo_text = ""
            memos = tx.get("Memos", [])
            if memos:
                try:
                    memo_hex = memos[0].get("Memo", {}).get("MemoData", "")
                    memo_text = bytes.fromhex(memo_hex).decode("utf-8", errors="ignore")
                except Exception:
                    pass

            # Resolve label for sender/destination
            def addr_label(addr):
                for n, d in wallets_data.items():
                    if d.get("address") == addr:
                        return n
                return addr[:10] + "..."

            account = tx.get("Account", "")
            destination = tx.get("Destination", "")
            result_code = meta.get("TransactionResult", "")

            # Ripple epoch offset
            date_raw = tx.get("date")
            date_str = ""
            if date_raw:
                from datetime import datetime, timezone, timedelta
                unix_ts = date_raw + 946684800
                date_str = datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

            # Tag the tx type for display
            if memo_text.startswith("PUT UP Bag Deposit"):
                display_type = "Deposit"
                tag_class = "tag-deposit"
            elif memo_text.startswith("Put Up resolved") or "showed up" in memo_text:
                display_type = "Payout"
                tag_class = "tag-payout"
            elif tx_type == "TrustSet":
                display_type = "Trust Line"
                tag_class = "tag-trust"
            elif tx_type == "Payment" and amount_xrp is None:
                display_type = "KRM Token"
                tag_class = "tag-karma"
            else:
                display_type = tx_type
                tag_class = "tag-other"

            transactions.append({
                "hash": tx_hash,
                "hash_short": tx_hash[:10] + "..." if tx_hash else "",
                "type": display_type,
                "tag_class": tag_class,
                "from": addr_label(account),
                "to": addr_label(destination) if destination else "",
                "amount_xrp": amount_xrp,
                "memo": memo_text[:60] + ("..." if len(memo_text) > 60 else ""),
                "result": result_code,
                "date": date_str,
            })
    except Exception as e:
        transactions = []

    return render_template(
        "explorer.html",
        platform_address=issuer_address,
        platform_xrp=round(platform_xrp, 4),
        users=users,
        transactions=transactions,
        network="XRPL Testnet",
    )


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_xrpl()
    lan_ip = get_lan_ip()
    print(f"\n  PUT UP is running!")
    print(f"  Local:   http://localhost:8080")
    print(f"  Network: http://{lan_ip}:8080  (share this with participants)\n")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

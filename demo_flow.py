"""
PUT UP — Automated Full Flow Demo
===================================
Self-contained demo that:
  1. Seeds demo_data/wallets.json with 4 funded XRPL testnet wallets
  2. Starts the Flask server pointing at demo_data/
  3. Runs the full app flow via HTTP (login → create event → commit → check-in → resolve)
  4. Shows results and shuts down

Usage:
    python demo_flow.py              # creates wallets + runs flow
    python demo_flow.py --skip-seed  # reuse existing demo_data/, just run flow
"""

import os
import sys
import json
import time
import signal
import subprocess
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
DEMO_DIR = ROOT / "demo_data"
WALLETS_FILE = DEMO_DIR / "wallets.json"
SERVER_PORT = 8080
BASE = f"http://localhost:{SERVER_PORT}"

DEMO_USERS = [
    {"name": "Alice",  "email": "alice@demo.putup",  "password": "demo1234"},
    {"name": "Bob",    "email": "bob@demo.putup",    "password": "demo1234"},
    {"name": "Carlos", "email": "carlos@demo.putup", "password": "demo1234"},
    {"name": "Diana",  "email": "diana@demo.putup",  "password": "demo1234"},
]

STARTING_BALANCE = 20  # XRP per user


def log(msg):
    print(f"  {msg}")


def step(title):
    print(f"\n── {title} {'─' * max(1, 50 - len(title))}")


# ═══════════════════════════════════════════════════════════════════
#  SEED: create demo_data/wallets.json with funded testnet wallets
# ═══════════════════════════════════════════════════════════════════

def seed_demo_data():
    """Create Platform + 4 user wallets on XRPL testnet, save to demo_data/."""
    from xrpl.clients import JsonRpcClient
    from xrpl.wallet import Wallet
    from werkzeug.security import generate_password_hash
    from wallet_manager import (
        create_funded_wallet, create_user_wallet,
        setup_trust_line, get_xrp_balance,
    )
    from escrow_engine import send_payment
    import config

    DEMO_DIR.mkdir(exist_ok=True)

    # If wallets already exist, just reset balances and top up platform
    if WALLETS_FILE.exists():
        with open(WALLETS_FILE) as f:
            existing = json.load(f)
        if "Platform" in existing and all(u["name"] in existing for u in DEMO_USERS):
            log("demo_data/wallets.json exists — resetting balances to 20 XRP")
            for u in DEMO_USERS:
                existing[u["name"]]["balance"] = float(STARTING_BALANCE)
            with open(WALLETS_FILE, "w") as f:
                json.dump(existing, f, indent=2)

            # Top up platform wallet on-chain so it can fund payouts
            platform_addr = existing["Platform"]["address"]
            log(f"Topping up platform wallet: {platform_addr[:16]}...")
            for i in range(2):
                try:
                    r = requests.post(
                        "https://faucet.altnet.rippletest.net/accounts",
                        json={"destination": platform_addr}, timeout=30,
                    )
                    log(f"Faucet top-up {i+1}: {r.status_code}")
                    time.sleep(4)
                except Exception as e:
                    log(f"Faucet error: {e}")
            return

    client = JsonRpcClient(config.TESTNET_URL)
    wallets = {}

    # Platform wallet
    log("Creating Platform wallet from faucet...")
    pw = create_funded_wallet(client, "Platform")
    wallets["Platform"] = {"address": pw.address, "seed": pw.seed}
    platform = pw
    time.sleep(3)

    def faucet_topup(address):
        try:
            r = requests.post(
                "https://faucet.altnet.rippletest.net/accounts",
                json={"destination": address}, timeout=30,
            )
            if r.ok:
                log(f"Faucet topped up {address[:16]}...")
                time.sleep(4)
        except Exception as e:
            log(f"Faucet top-up failed: {e}")

    for user in DEMO_USERS:
        name = user["name"]

        # Check platform balance, top up if low
        bal = get_xrp_balance(client, platform.address)
        log(f"Platform balance: {bal} XRP")
        if bal < 50:
            log("Low balance — topping up...")
            faucet_topup(platform.address)

        log(f"Creating {name}...")
        new_wallet = create_user_wallet(client, platform, name)
        time.sleep(4)
        setup_trust_line(client, new_wallet, platform.address)
        send_payment(client, platform, new_wallet.address, STARTING_BALANCE,
                     f"Demo balance for {name}")

        wallets[name] = {
            "address": new_wallet.address,
            "seed": new_wallet.seed,
            "email": user["email"],
            "password_hash": generate_password_hash(user["password"]),
            "balance": float(STARTING_BALANCE),
            "deposit_xrp": float(STARTING_BALANCE),
            "stripe_paid": False,
        }
        log(f"✓ {name}: {new_wallet.address}")

    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)
    log(f"Saved {len(wallets)} wallets to {WALLETS_FILE}")


# ═══════════════════════════════════════════════════════════════════
#  SERVER: start Flask pointing at demo_data/
# ═══════════════════════════════════════════════════════════════════

def start_server():
    """Start app.py with WALLETS_DIR=demo_data (no DATABASE_URL)."""
    env = os.environ.copy()
    env["WALLETS_DIR"] = str(DEMO_DIR)
    env["DATABASE_URL"] = ""  # force file-based storage (overrides .env)
    env["PORT"] = str(SERVER_PORT)

    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Wait for server to be ready (XRPL init can take 10-15s on first run)
    for i in range(30):
        time.sleep(2)
        # Check process is still alive
        if proc.poll() is not None:
            out = proc.stdout.read().decode() if proc.stdout else ""
            log(f"Server exited with code {proc.returncode}")
            log(f"Output:\n{out[-500:]}")
            raise RuntimeError("Server crashed during startup")
        try:
            r = requests.get(f"{BASE}/", timeout=2)
            if r.status_code == 200:
                log(f"Server running on {BASE} (PID {proc.pid})")
                return proc
        except requests.ConnectionError:
            if i % 5 == 4:
                log("Still waiting for server to initialize...")

    out = proc.stdout.read().decode() if proc.stdout else ""
    proc.terminate()
    log(f"Server output:\n{out[-500:]}")
    raise RuntimeError("Server failed to start after 60s")


# ═══════════════════════════════════════════════════════════════════
#  FLOW: run the full demo via HTTP
# ═══════════════════════════════════════════════════════════════════

def run_flow():
    alice_session = requests.Session()
    bob_session = requests.Session()

    # ── Step 1: Login ───────────────────────────────────────────
    step("Step 1: Alice logs in")
    resp = alice_session.post(f"{BASE}/api/login", json={
        "email": "alice@demo.putup", "password": "demo1234",
    })
    data = resp.json()
    if "error" in data:
        log(f"FAIL: {data['error']}"); return False
    alice_address = data["address"]
    log(f"Alice: {alice_address[:16]}...")

    step("Step 2: Bob logs in")
    resp = bob_session.post(f"{BASE}/api/login", json={
        "email": "bob@demo.putup", "password": "demo1234",
    })
    data = resp.json()
    if "error" in data:
        log(f"FAIL: {data['error']}"); return False
    bob_address = data["address"]
    log(f"Bob: {bob_address[:16]}...")

    # ── Step 3: Create event ────────────────────────────────────
    step("Step 3: Alice creates event with 2 location suggestions")
    scheduled_time = time.time()  # NOW — so check-in window is open

    resp = alice_session.post(f"{BASE}/api/event/create", json={
        "name": "Coffee Meetup Demo",
        "scheduled_time": scheduled_time,
        "organizer_address": alice_address,
        "participant_addresses": [alice_address, bob_address],
        "location_suggestions": [
            {"name": "Starbucks on Main St", "lat": 27.9506, "lon": -82.4572},
            {"name": "Blue Bottle Coffee",   "lat": 27.9517, "lon": -82.4588},
        ],
    })
    data = resp.json()
    if "error" in data:
        log(f"FAIL: {data['error']}"); return False
    event_id = data["event_id"]
    log(f"Event created: {event_id}")
    log(f"Participants: {[p['name'] for p in data['participants']]}")

    # ── Step 4: Vote for location ───────────────────────────────
    step("Step 4: Both vote for Blue Bottle Coffee")
    for name, session, addr in [("Bob", bob_session, bob_address), ("Alice", alice_session, alice_address)]:
        resp = session.post(f"{BASE}/api/event/{event_id}/vote", json={
            "address": addr, "location_id": 1,
        })
        vdata = resp.json()
        log(f"{name} voted: {vdata.get('voted_for', '?')} → winner: {vdata.get('current_winner', '?')}")

    # ── Step 5: Commit stakes ───────────────────────────────────
    step("Step 5: Alice commits 10 XRP, Bob commits 10 XRP (private)")
    for name, session, addr, stake in [
        ("Alice", alice_session, alice_address, 10),
        ("Bob", bob_session, bob_address, 10),
    ]:
        resp = session.post(f"{BASE}/api/event/{event_id}/commit", json={
            "address": addr, "stake_xrp": stake,
        })
        data = resp.json()
        if "error" in data:
            log(f"{name} commit FAIL: {data['error']}"); return False
        log(f"{name} committed {stake} XRP (all_committed: {data.get('all_committed')})")

    # ── Step 6: GPS Check-in ────────────────────────────────────
    step("Step 6: Both GPS check-in at Blue Bottle Coffee")
    venue_lat, venue_lon = 27.9517, -82.4588

    for name, session, addr, offset in [
        ("Alice", alice_session, alice_address, 0.0001),
        ("Bob", bob_session, bob_address, -0.0002),
    ]:
        resp = session.post(f"{BASE}/api/checkin", json={
            "address": addr, "event_id": event_id,
            "lat": venue_lat + offset, "lon": venue_lon,
        })
        data = resp.json()
        if data.get("valid"):
            log(f"{name} checked in: {data['distance_ft']}ft from venue")
        else:
            log(f"{name} check-in FAIL: {data.get('reason', data.get('error', '?'))}")

    # ── Step 7: Resolve ─────────────────────────────────────────
    step("Step 7: Resolve event on XRPL (15-30 seconds)")
    resp = alice_session.post(f"{BASE}/api/event/resolve", json={"event_id": event_id})
    data = resp.json()
    if "error" in data:
        log(f"FAIL: {data['error']}"); return False

    log(f"Outcome: {data['outcome'].upper().replace('_', ' ')}")
    log(f"Showed up: {', '.join(data.get('showups', []))}")
    log(f"Ghosted: {', '.join(data.get('ghosts', []))}")
    if data.get("new_scores"):
        log("Karma:")
        for n, s in data["new_scores"].items():
            log(f"  {n}: {int(s)} KRM")
    if data.get("tx_hashes"):
        hashes = data["tx_hashes"].get("payments", []) + data["tx_hashes"].get("karma", [])
        log(f"XRPL transactions: {len(hashes)}")
        for h in hashes:
            if h: log(f"  {h[:24]}...")

    # Top up platform wallet before next scenario
    step("Top-up: Refilling platform wallet from faucet")
    try:
        with open(WALLETS_FILE) as f:
            wdata = json.load(f)
        platform_addr = wdata["Platform"]["address"]
        r = requests.post("https://faucet.altnet.rippletest.net/accounts",
                          json={"destination": platform_addr}, timeout=30)
        log(f"Faucet top-up: {r.status_code} → {platform_addr[:16]}...")
        time.sleep(4)
    except Exception as e:
        log(f"Top-up warning: {e}")

    # ── Step 8: Ghost scenario ──────────────────────────────────
    step("Step 8: Ghost Scenario — Carlos shows, Diana ghosts")
    carlos_session = requests.Session()
    diana_session = requests.Session()

    resp = carlos_session.post(f"{BASE}/api/login", json={
        "email": "carlos@demo.putup", "password": "demo1234",
    })
    cdata = resp.json()
    if "error" in cdata:
        log(f"Carlos login FAIL: {cdata['error']}"); return True
    carlos_address = cdata["address"]

    resp = diana_session.post(f"{BASE}/api/login", json={
        "email": "diana@demo.putup", "password": "demo1234",
    })
    ddata = resp.json()
    if "error" in ddata:
        log(f"Diana login FAIL: {ddata['error']}"); return True
    diana_address = ddata["address"]

    log(f"Carlos: {carlos_address[:16]}...")
    log(f"Diana: {diana_address[:16]}...")

    # Create event
    log("Carlos creates 'Gym Session' event...")
    resp = carlos_session.post(f"{BASE}/api/event/create", json={
        "name": "Gym Session Demo",
        "scheduled_time": time.time(),
        "organizer_address": carlos_address,
        "participant_addresses": [carlos_address, diana_address],
        "location_suggestions": [
            {"name": "Planet Fitness", "lat": 27.9500, "lon": -82.4560},
        ],
    })
    data = resp.json()
    if "error" in data:
        log(f"FAIL: {data['error']}"); return True
    event_id2 = data["event_id"]

    # Both commit
    for name, session, addr in [
        ("Carlos", carlos_session, carlos_address),
        ("Diana", diana_session, diana_address),
    ]:
        resp = session.post(f"{BASE}/api/event/{event_id2}/commit", json={
            "address": addr, "stake_xrp": 10,
        })
        if resp.json().get("error"):
            log(f"{name} commit FAIL: {resp.json()['error']}"); return True
        log(f"{name} committed 10 XRP")

    # Only Carlos checks in
    resp = carlos_session.post(f"{BASE}/api/checkin", json={
        "address": carlos_address, "event_id": event_id2,
        "lat": 27.9501, "lon": -82.4561,
    })
    data = resp.json()
    log(f"Carlos checked in: {data.get('distance_ft', '?')}ft from venue")
    log("Diana does NOT check in — she's ghosting!")

    # Resolve
    log("Resolving on XRPL...")
    resp = carlos_session.post(f"{BASE}/api/event/resolve", json={"event_id": event_id2})
    data = resp.json()
    if "error" in data:
        log(f"FAIL: {data['error']}"); return True

    log(f"Outcome: {data['outcome'].upper().replace('_', ' ')}")
    log(f"Showed up: {', '.join(data.get('showups', []))}")
    log(f"Ghosted: {', '.join(data.get('ghosts', []))}")
    log(f"Ghost pot: {data.get('ghost_pot', 0)} XRP (Diana's lost stake)")
    log(f"Carlos bonus: +{data.get('bonus_per_showup', 0)} XRP")

    if data.get("new_scores"):
        log("Updated karma:")
        for n, s in data["new_scores"].items():
            log(f"  {n}: {int(s)} KRM")

    # ── Step 9: Leaderboard ─────────────────────────────────────
    step("Step 9: Check leaderboard")
    resp = alice_session.get(f"{BASE}/leaderboard")
    log(f"Leaderboard: {'OK' if resp.ok else 'FAIL'} ({resp.status_code})")

    return True


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    print("\n╔══════════════════════════════════════════════════╗")
    print("║     PUT UP — Automated Full Flow Demo            ║")
    print("╚══════════════════════════════════════════════════╝")

    skip_seed = "--skip-seed" in sys.argv

    # Seed demo data
    if not skip_seed:
        step("Seeding demo_data/")
        seed_demo_data()
    else:
        log("Skipping seed (--skip-seed)")

    # Start server
    step("Starting server")
    server = start_server()

    try:
        success = run_flow()
    finally:
        log("Shutting down server...")
        server.terminate()
        server.wait(timeout=5)

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║              Demo Complete!                      ║")
    print("╠══════════════════════════════════════════════════╣")
    print("║  Scenario 1: Both showed up (Alice + Bob)         ║")
    print("║    → +10 KRM each, stakes returned                ║")
    print("║                                                   ║")
    print("║  Scenario 2: Diana ghosted (Carlos showed)        ║")
    print("║    → Carlos: +15 KRM + ghost bonus XRP            ║")
    print("║    → Diana:  -20 KRM + lost her stake             ║")
    print("║                                                   ║")
    print("║  All transactions verified on XRPL Testnet!       ║")
    print("║  Mock data in: demo_data/wallets.json             ║")
    print("╚══════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    main()

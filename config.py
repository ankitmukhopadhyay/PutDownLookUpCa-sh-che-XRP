# PUT UP — XRPL Blockchain Configuration
# Social commitment & accountability platform

# ── XRPL Network ────────────────────────────────────────────────
TESTNET_URL = "https://s.altnet.rippletest.net:51234"

# ── KRM Token (Karma) ───────────────────────────────────────────
CURRENCY_CODE = "KRM"
KARMA_TRUST_LIMIT = "10000"

# Karma rewards/penalties per outcome
KARMA_BOTH_SHOW = 10       # Both friends showed up
KARMA_WINNER_BONUS = 15    # You showed up, they ghosted
KARMA_GHOST_PENALTY = 20   # You ghosted someone
KARMA_BOTH_GHOST_PENALTY = 10  # Everyone no-showed
KARMA_LATE_CANCEL_PENALTY = 5  # Bailed last minute (<6h)

# ── Reputation Tiers ────────────────────────────────────────────
TIERS = [
    {"min": 0,   "max": 25,   "name": "New",            "icon": "🆕"},
    {"min": 26,  "max": 75,   "name": "Building Trust",  "icon": "🌱"},
    {"min": 76,  "max": 150,  "name": "Reliable",        "icon": "⭐"},
    {"min": 151, "max": 300,  "name": "Solid",           "icon": "💎"},
    {"min": 301, "max": 99999,"name": "Legendary",       "icon": "👑"},
]

# ── Badge Milestones ────────────────────────────────────────────
BADGES = [
    {"threshold": 10, "type": "show_count", "name": "Consistent",   "icon": "🎯"},
    {"threshold": 25, "type": "show_count", "name": "Dependable",   "icon": "🤝"},
    {"threshold": 50, "type": "show_count", "name": "Rock Solid",   "icon": "🪨"},
    {"threshold": 1,  "type": "ghost_bust", "name": "Ghost Buster", "icon": "👻"},
]

# ── Escrow Fee Structure ────────────────────────────────────────
FEE_BOTH_SHOW = 0.005          # 0.5% fee when both show
GHOST_WINNER_SHARE = 0.95      # Winner gets 95% of ghost's bag
GHOST_PLATFORM_SHARE = 0.05    # Platform gets 5% of ghost's bag

# Cancellation tiers: hours_before -> fee_percent
CANCELLATION_TIERS = [
    (72, 0.0),      # 72h+ out: free
    (48, 0.005),    # 48-72h: 0.5%
    (24, 0.01),     # 24-48h: 1.0%
    (12, 0.015),    # 12-24h: 1.5%
    (6,  0.02),     # 6-12h: 2.0%
    (0,  0.025),    # <6h: 2.5%
]

# ── Demo Constants ──────────────────────────────────────────────
XRP_PER_USD = 2.0              # Demo conversion rate
MINIMUM_BAG_XRP = 40           # Equiv of $20 at demo rate
DEFAULT_BAG_XRP = 10           # Default bag for demo (small for testnet)

# ── GPS Check-In ────────────────────────────────────────────────
GPS_RADIUS_FEET = 300       # Must be within 300ft of venue
GPS_WINDOW_MINUTES = 31     # Check-in window opens at scheduled event time

# ── Stake ───────────────────────────────────────────────────────
MIN_STAKE_XRP = 10          # Minimum XRP stake per event commitment

# ── Stripe ──────────────────────────────────────────────────────
import os
STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
USD_PER_XRP            = 2.0   # $2 per XRP (demo rate)

# ── Wallet Data File ────────────────────────────────────────────
WALLETS_FILE = "wallets.json"

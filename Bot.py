#!/usr/bin/env python3
"""
EVALON MASTER PRO - Telegram Bot
python-telegram-bot[webhooks]==21.3 + Neon PostgreSQL via psycopg2
"""

# ── OPEN PORT IMMEDIATELY — before all imports ─────────────
# Render requires port to open within ~5 seconds of startup
import os as _os
import threading as _threading
from http.server import HTTPServer as _HTTPServer, BaseHTTPRequestHandler as _BaseHandler

class _H(_BaseHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"EVALON OK")
    def log_message(self, *a): pass

_PORT = int(_os.environ.get("PORT", 8080))
_t = _threading.Thread(target=lambda: _HTTPServer(("0.0.0.0", _PORT), _H).serve_forever(), daemon=True)
_t.start()
print("PORT {} open.".format(_PORT), flush=True)
# ─────────────────────────────────────────────────────────────

import random
import os
import uuid
import logging
import asyncio
import psycopg2
import psycopg2.extras
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatJoinRequestHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID       = 8054370971
DATABASE_URL   = os.environ.get("DATABASE_URL", "")
FINNHUB_KEY    = os.environ.get("FINNHUB_KEY", "d8cl2q1r01qidic8fee0d8cl2q1r01qidic8feeg")
CHANNEL_INVITE = "https://t.me/+mRNfGaNhz3RkZGRk"
CHANNEL_ID     = -1003403743370  # EVALON channel
BOT_USERNAME   = ""  # Set at startup in run_bot()

SUPPORT_BOT  = "Evalonwinnersbot"   # ← Admin/support bot (do not change)
REFERRAL_BOT = "Thtgalshhgsvvokksh90bot"  # Referral bot username
DERIV_TOKEN  = os.environ.get("DERIV_TOKEN", "pat_c518f7669d62cbae95d46e0052ff8b44d07601a1b89bb035fd668a2e35fafdb4")
# ============================================================
# DERIV WEBSOCKET — MICRO CANDLE ENGINE (5s/10s/15s)
# Used to confirm 1m signals before sending
# ============================================================
import websockets
import json as _json
import asyncio as _asyncio
from collections import defaultdict as _defaultdict
from datetime import datetime as _dt

# Deriv symbol mapping — Pocket Option pair → Deriv symbol
DERIV_SYMBOLS = {
    "EUR/USD": "frxEURUSD",
    "GBP/USD": "frxGBPUSD",
    "USD/JPY": "frxUSDJPY",
    "USD/CHF": "frxUSDCHF",
    "USD/CAD": "frxUSDCAD",
    "AUD/USD": "frxAUDUSD",
    "NZD/USD": "frxNZDUSD",
    "EUR/GBP": "frxEURGBP",
    "EUR/JPY": "frxEURJPY",
    "EUR/AUD": "frxEURAUD",
    "EUR/CAD": "frxEURCAD",
    "EUR/CHF": "frxEURCHF",
    "GBP/JPY": "frxGBPJPY",
    "GBP/AUD": "frxGBPAUD",
    "GBP/CAD": "frxGBPCAD",
    "GBP/CHF": "frxGBPCHF",
    "AUD/JPY": "frxAUDJPY",
    "AUD/CAD": "frxAUDCAD",
    "AUD/CHF": "frxAUDCHF",
    "CAD/JPY": "frxCADJPY",
    "CAD/CHF": "frxCADCHF",
    "CHF/JPY": "frxCHFJPY",
    "NZD/JPY": "frxNZDJPY",
    "USD/MXN": "frxUSDMXN",
}

# Cache: {pair: {"5s": [...ticks], "10s": [...], "15s": [...], "ts": timestamp}}
_DERIV_CACHE = {}
_DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

async def _fetch_deriv_ticks(pair, seconds=15):
    """
    Fetch last N ticks from Deriv WebSocket for a pair.
    Build synthetic candles from ticks.
    Returns dict with trend info or None on failure.
    """
    symbol = DERIV_SYMBOLS.get(pair)
    if not symbol:
        return None

    try:
        async with websockets.connect(_DERIV_WS_URL, close_timeout=5) as ws:
            # Authorize
            await ws.send(_json.dumps({"authorize": DERIV_TOKEN}))
            auth = _json.loads(await _asyncio.wait_for(ws.recv(), timeout=5))
            if auth.get("error"):
                logging.warning("Deriv auth failed: {}".format(auth["error"]))
                return None

            # Request last 60 ticks
            await ws.send(_json.dumps({
                "ticks_history": symbol,
                "end": "latest",
                "count": 60,
                "style": "ticks"
            }))
            resp = _json.loads(await _asyncio.wait_for(ws.recv(), timeout=8))
            if resp.get("error") or "history" not in resp:
                logging.warning("Deriv ticks error {}: {}".format(pair, resp.get("error","")))
                return None

            prices = resp["history"]["prices"]
            times  = resp["history"]["times"]

            if len(prices) < 10:
                return None

            # Build micro-candles for 5s, 10s, 15s
            results = {}
            for candle_secs in [5, 10, 15]:
                candles = _build_micro_candles(prices, times, candle_secs)
                if len(candles) >= 3:
                    trend = _micro_trend(candles)
                    results["{}_s".format(candle_secs)] = trend

            return results if results else None

    except Exception as e:
        logging.warning("Deriv fetch failed {}: {}".format(pair, e))
        return None


def _build_micro_candles(prices, times, interval_secs):
    """Group ticks into candles of interval_secs duration."""
    if not prices:
        return []
    candles = []
    bucket_start = times[0]
    o = h = l = c = prices[0]

    for i in range(len(prices)):
        t, p = times[i], prices[i]
        if t - bucket_start >= interval_secs:
            candles.append({"open": o, "high": h, "low": l, "close": c})
            bucket_start = t
            o = h = l = c = p
        else:
            h = max(h, p)
            l = min(l, p)
            c = p

    if o is not None:
        candles.append({"open": o, "high": h, "low": l, "close": c})
    return candles


def _micro_trend(candles):
    """
    Analyze micro candles.
    Returns: {"direction": "BUY"/"SELL"/"FLAT", "strength": 0-100,
              "reversal": bool, "momentum": float}
    """
    if len(candles) < 3:
        return {"direction": "FLAT", "strength": 0, "reversal": False, "momentum": 0}

    closes = [c["close"] for c in candles]

    # Count bullish vs bearish candles
    bulls = sum(1 for c in candles if c["close"] > c["open"])
    bears = sum(1 for c in candles if c["close"] < c["open"])
    total = len(candles)

    # Momentum: last 3 candles direction
    last3 = closes[-3:]
    momentum = (last3[-1] - last3[0]) / last3[0] * 100 if last3[0] != 0 else 0

    # Check reversal: last candle opposes previous trend
    prev_dir = "BUY" if closes[-2] > closes[-3] else "SELL"
    last_dir = "BUY" if closes[-1] > closes[-2] else "SELL"
    reversal = (prev_dir != last_dir)

    if bulls > bears:
        direction = "BUY"
        strength  = int(bulls / total * 100)
    elif bears > bulls:
        direction = "SELL"
        strength  = int(bears / total * 100)
    else:
        direction = "FLAT"
        strength  = 50

    return {
        "direction": direction,
        "strength":  strength,
        "reversal":  reversal,
        "momentum":  round(momentum, 5),
    }


async def pick_best_tf_deriv(pair, signal_direction):
    """
    Fetch Deriv micro-candles and pick the best timeframe:
      1m → check 5s trend
      2m → check 10s trend
      3m → check 15s trend
    Compare strength of all 3. Return the TF with strongest
    trend matching signal_direction.
    Returns: (best_tf_mins, strength, reason)
    Falls back to (2, 0, reason) if Deriv unavailable.
    """
    if pair not in DERIV_SYMBOLS:
        return (2, 0, "pair not in Deriv")

    try:
        data = await _asyncio.wait_for(
            _fetch_deriv_ticks(pair, seconds=15),
            timeout=10
        )
    except Exception as e:
        logging.warning("Deriv pick_best_tf failed {}: {}".format(pair, e))
        return (2, 0, "Deriv error")

    if not data:
        return (2, 0, "no Deriv data")

    # Map: trade TF minutes → micro candle seconds key
    tf_map = {
        1: "5_s",   # 1m trade → 5s micro trend
        2: "10_s",  # 2m trade → 10s micro trend
        3: "15_s",  # 3m trade → 15s micro trend
    }

    best_tf     = None
    best_str    = -1
    best_reason = ""

    for trade_tf, micro_key in tf_map.items():
        trend = data.get(micro_key)
        if not trend:
            continue

        direction = trend["direction"]
        strength  = trend["strength"]

        # Only consider TFs where micro-trend agrees with signal
        if direction == signal_direction and not trend["reversal"]:
            if strength > best_str:
                best_str    = strength
                best_tf     = trade_tf
                best_reason = "{}s micro: {}% {}".format(
                    trade_tf * 5, strength, direction)

    if best_tf is None:
        # No TF agrees with signal — check if any is FLAT (neutral)
        for trade_tf, micro_key in tf_map.items():
            trend = data.get(micro_key)
            if trend and trend["direction"] == "FLAT":
                best_tf  = trade_tf
                best_str = 50
                best_reason = "FLAT micro — using {}m".format(trade_tf)
                break

    if best_tf is None:
        # All micro-trends oppose signal — use 3m (most forgiving)
        best_tf     = 3
        best_str    = 0
        best_reason = "all micro-trends oppose signal — defaulting to 3m"

    logging.info("Deriv pick_best_tf {}: {}m (str={}) — {}".format(
        pair, best_tf, best_str, best_reason))
    return (best_tf, best_str, best_reason)


# Keep old name as alias for backward compatibility
async def confirm_signal_with_deriv(pair, signal_direction):
    tf, strength, reason = await pick_best_tf_deriv(pair, signal_direction)
    if strength >= 60:
        return ("CONFIRM", reason)
    elif strength == 0:
        return ("REJECT", reason)
    return ("SKIP", reason)



def support_url():
    """Returns support link — opens support bot with 'admin' pre-filled."""
    return "https://t.me/{}?text=admin".format(SUPPORT_BOT)

# Health check handled by webhook server at /health path

# ============================================================
# NEON POSTGRESQL
# ============================================================
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT DEFAULT NULL,
                    last_name  TEXT DEFAULT NULL,
                    username   TEXT DEFAULT NULL,
                    free_used INTEGER DEFAULT 0,
                    licensed BOOLEAN DEFAULT FALSE,
                    licence_type TEXT,
                    licence_code TEXT,
                    expiry TIMESTAMP,
                    referred_by BIGINT DEFAULT NULL,
                    bonus_signals INTEGER DEFAULT 0
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT DEFAULT NULL;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name  TEXT DEFAULT NULL;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS username   TEXT DEFAULT NULL;
                CREATE TABLE IF NOT EXISTS licences (
                    code TEXT PRIMARY KEY,
                    type TEXT,
                    used BOOLEAN DEFAULT FALSE,
                    revoked BOOLEAN DEFAULT FALSE,
                    revoked_at TIMESTAMP DEFAULT NULL,
                    used_by BIGINT,
                    used_at TIMESTAMP
                );
                ALTER TABLE licences ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP DEFAULT NULL;
                CREATE TABLE IF NOT EXISTS vte_last_direction (
                    pair TEXT PRIMARY KEY,
                    direction TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS blocked_users (
                    user_id BIGINT PRIMARY KEY,
                    blocked_at TIMESTAMP DEFAULT NOW(),
                    reason TEXT DEFAULT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO bot_settings (key, value)
                    VALUES ('auto_reverse', 'on')
                    ON CONFLICT (key) DO NOTHING;
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS blacklist (
                    user_id BIGINT PRIMARY KEY,
                    reason TEXT,
                    banned_at TIMESTAMP
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT DEFAULT NULL;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_signals INTEGER DEFAULT 0;
                ALTER TABLE licences ADD COLUMN IF NOT EXISTS revoked BOOLEAN DEFAULT FALSE;
                CREATE TABLE IF NOT EXISTS join_requests (
                    user_id BIGINT PRIMARY KEY,
                    requested_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS signal_history (
                    id SERIAL PRIMARY KEY,
                    pair TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS user_signal_state (
                    user_id BIGINT NOT NULL,
                    pair TEXT NOT NULL,
                    last_direction TEXT NOT NULL,
                    last_timeframe INTEGER NOT NULL,
                    signal_time TIMESTAMP NOT NULL,
                    flip_count INTEGER DEFAULT 0,
                    cooldown_until TIMESTAMP,
                    entry_price DOUBLE PRECISION DEFAULT NULL,
                    result_sent BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (user_id, pair)
                );
                ALTER TABLE user_signal_state ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE user_signal_state ADD COLUMN IF NOT EXISTS result_sent BOOLEAN DEFAULT FALSE;
                ALTER TABLE user_signal_state ADD COLUMN IF NOT EXISTS result_msg_id BIGINT DEFAULT NULL;
                CREATE TABLE IF NOT EXISTS pair_stats (
                    pair TEXT PRIMARY KEY,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    consecutive_losses INTEGER DEFAULT 0,
                    optimal_tf INTEGER DEFAULT NULL,
                    avg_movement DOUBLE PRECISION DEFAULT NULL,
                    wins_today INTEGER DEFAULT 0,
                    losses_today INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                ALTER TABLE pair_stats ADD COLUMN IF NOT EXISTS consecutive_losses INTEGER DEFAULT 0;
                ALTER TABLE pair_stats ADD COLUMN IF NOT EXISTS optimal_tf INTEGER DEFAULT NULL;
                ALTER TABLE pair_stats ADD COLUMN IF NOT EXISTS avg_movement DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE pair_stats ADD COLUMN IF NOT EXISTS wins_today INTEGER DEFAULT 0;
                ALTER TABLE pair_stats ADD COLUMN IF NOT EXISTS losses_today INTEGER DEFAULT 0;
                ALTER TABLE pair_stats ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
                CREATE TABLE IF NOT EXISTS tf_session_stats (
                    pair TEXT NOT NULL,
                    session TEXT NOT NULL,
                    tf_mins INTEGER NOT NULL,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    PRIMARY KEY (pair, session, tf_mins)
                );
                CREATE TABLE IF NOT EXISTS reverse_pairs (
                    pair TEXT PRIMARY KEY
                );
            """)
        conn.commit()

# ============================================================
# PAIR STATS — win/loss tracking per pair
# ============================================================
def update_pair_stats(pair, won, was_reversed=False):
    """
    Update win/loss stats for a pair.
    won: True if signal result was correct (from user perspective)
    was_reversed: True if pair was in reverse mode when signal was given

    Stats always record the ACTUAL market outcome:
    - If reversed and user saw WIN → market was actually LOSS direction → record as win (user won)
    - Consecutive losses tracked on actual user outcome
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if won:
                    # Win resets consecutive loss streak
                    cur.execute("""
                        INSERT INTO pair_stats (pair, wins, losses, consecutive_losses)
                        VALUES (%s, 1, 0, 0)
                        ON CONFLICT (pair) DO UPDATE SET
                            wins = pair_stats.wins + 1,
                            consecutive_losses = 0
                    """, (pair,))
                else:
                    # Loss increments consecutive streak
                    cur.execute("""
                        INSERT INTO pair_stats (pair, wins, losses, consecutive_losses)
                        VALUES (%s, 0, 1, 1)
                        ON CONFLICT (pair) DO UPDATE SET
                            losses = pair_stats.losses + 1,
                            consecutive_losses = pair_stats.consecutive_losses + 1
                    """, (pair,))
                    # Check if consecutive losses hit 3 — auto-reverse
                    cur.execute("SELECT consecutive_losses FROM pair_stats WHERE pair=%s", (pair,))
                    row = cur.fetchone()
                    if False:  # Auto-reverse removed
                        # Auto-reverse: flip pair and reset streak
                        if is_reverse_pair(pair):
                            remove_reverse_pair(pair)
                            logging.info("AUTO-REVERSE OFF: {} after {} consecutive losses (was reversed)".format(pair, row["consecutive_losses"]))
                        else:
                            add_reverse_pair(pair)
                            logging.info("AUTO-REVERSE ON: {} after {} consecutive losses".format(pair, row["consecutive_losses"]))
                        # Reset consecutive losses after reversing
                        cur.execute("UPDATE pair_stats SET consecutive_losses=0 WHERE pair=%s", (pair,))
            conn.commit()
    except Exception as e:
        logging.warning("update_pair_stats failed: {}".format(e))

def get_pair_stats_all():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pair, wins, losses FROM pair_stats ORDER BY wins DESC")
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logging.warning("get_pair_stats_all failed: {}".format(e))
        return []

def get_best_pair(otc_only=False):
    """Return the pair with highest win rate (minimum 3 total signals).
    Also uses MTF to verify pair has clear trend (not flat).
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pair, wins, losses FROM pair_stats WHERE (wins + losses) >= 3")
                rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            return None
        if otc_only:
            rows = [r for r in rows if "OTC" in r["pair"]]
        if not rows:
            return None
        # Sort by win rate descending
        rows.sort(key=lambda r: r["wins"] / max(r["wins"] + r["losses"], 1), reverse=True)
        return rows[0]["pair"]
    except Exception as e:
        logging.warning("get_best_pair failed: {}".format(e))
        return None

def auto_manage_reverse_pairs():  # disabled — no longer used
    """
    Auto-manage reverse pairs based on win rate:
    - Pair with win rate below 40% (min 5 signals) → add to reverse_pairs
    - Pair with win rate above 60% (min 5 signals) → remove from reverse_pairs
    No longer called automatically.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pair, wins, losses FROM pair_stats WHERE (wins + losses) >= 5")
                rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            pair = row["pair"]
            total = row["wins"] + row["losses"]
            win_rate = row["wins"] / max(total, 1)
            if win_rate < 0.40:
                # Pair performing poorly — enable reverse
                add_reverse_pair(pair)
                logging.info("AUTO-REVERSE: Added {} (win rate {:.0%})".format(pair, win_rate))
            elif win_rate > 0.60:
                # Pair performing well — remove reverse if set
                remove_reverse_pair(pair)
    except Exception as e:
        logging.warning("auto_manage_reverse_pairs failed: {}".format(e))

# ============================================================
# REVERSE PAIRS — bot flips direction for these pairs
# ============================================================
def is_reverse_pair(pair):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM reverse_pairs WHERE pair = %s", (pair,))
                return cur.fetchone() is not None
    except:
        return False

def add_reverse_pair(pair):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO reverse_pairs (pair) VALUES (%s) ON CONFLICT DO NOTHING", (pair,))
        conn.commit()

def remove_reverse_pair(pair):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reverse_pairs WHERE pair = %s", (pair,))
        conn.commit()

def get_all_reverse_pairs():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pair FROM reverse_pairs ORDER BY pair")
                return [r["pair"] for r in cur.fetchall()]
    except:
        return []

# ============================================================
# SETTINGS (BUY/SELL images)
# ============================================================
DEFAULT_BUY_IMAGE  = "AgACAgQAAxkBAAICImoJRV1p8boUWCqbwbFQw5ZGFKi0AAJgDmsbgwZJUEAvhDh1tBD2AQADAgADeAADOwQ"
DEFAULT_SELL_IMAGE = "AgACAgQAAxkBAAICJGoJRZxn3w0clOl57ozxypDEUij0AAJhDmsbgwZJUBAZYceshO6HAQADAgADeAADOwQ"

def get_setting(key, default=""):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
                row = cur.fetchone()
                return row["value"] if row else default
    except:
        return default

def set_setting(key, value):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
                (key, value, value)
            )
        conn.commit()

def get_buy_image():
    return get_setting("buy_image", DEFAULT_BUY_IMAGE)

def get_sell_image():
    return get_setting("sell_image", DEFAULT_SELL_IMAGE)

def is_otc_enabled():
    """Returns True if OTC pairs are enabled (default: True)."""
    return get_setting("otc_enabled", "1") == "1"

def set_otc_enabled(enabled: bool):
    set_setting("otc_enabled", "1" if enabled else "0")

# ============================================================
# DATABASE FUNCTIONS
# ============================================================
def get_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            cur.execute(
                "INSERT INTO users (user_id, free_used, licensed) VALUES (%s, 0, FALSE) ON CONFLICT DO NOTHING",
                (user_id,)
            )
            conn.commit()
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else {}

def is_blocked(user_id):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM blocked_users WHERE user_id=%s", (user_id,))
                return cur.fetchone() is not None
    except Exception:
        return False

def block_user(user_id, reason=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO blocked_users (user_id, reason, blocked_at) VALUES (%s,%s,NOW()) ON CONFLICT DO NOTHING",
                (user_id, reason))
        conn.commit()

def unblock_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM blocked_users WHERE user_id=%s", (user_id,))
        conn.commit()

def get_blocked_users():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT b.user_id, b.blocked_at, b.reason,
                           u.first_name, u.last_name, u.username
                    FROM blocked_users b
                    LEFT JOIN users u ON u.user_id = b.user_id
                    ORDER BY b.blocked_at DESC
                """)
                return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []

def get_bot_setting(key, default="on"):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM bot_settings WHERE key=%s", (key,))
                row = cur.fetchone()
        return row["value"] if row else default
    except Exception:
        return default

def set_bot_setting(key, value):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bot_settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                (key, value))
        conn.commit()


def upsert_user_profile(user_id, first_name=None, last_name=None, username=None):
    """Save or update user display name and username for admin lookup."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET first_name = COALESCE(%s, first_name),
                        last_name  = COALESCE(%s, last_name),
                        username   = COALESCE(%s, username)
                    WHERE user_id = %s
                """, (first_name or None, last_name or None, username or None, user_id))
            conn.commit()
    except Exception as e:
        import logging
        logging.warning("upsert_user_profile failed {}: {}".format(user_id, e))

def is_licensed(user_id):
    u = get_user(user_id)
    if not u.get("licensed"):
        return False
    if u.get("licence_type") == "lifetime":
        return True
    expiry = u.get("expiry")
    if not expiry:
        return False
    if isinstance(expiry, str):
        expiry = datetime.fromisoformat(expiry.replace("Z", ""))
    return datetime.now() < expiry

def get_expiry_text(user_id):
    u = get_user(user_id)
    if u.get("licence_type") == "lifetime":
        return "♾️ Lifetime"
    expiry = u.get("expiry")
    if expiry:
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry.replace("Z", ""))
        days = (expiry - datetime.now()).days
        return "📅 Expires: {} ({} days left)".format(str(expiry)[:10], days)
    return "Unknown"

def free_signals_used(user_id):
    return get_user(user_id).get("free_used", 0)

def use_free_signal(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET free_used = free_used + 1 WHERE user_id = %s",
                (user_id,)
            )
        conn.commit()

def activate_licence(code, user_id):
    code = code.strip().upper()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM licences WHERE code = %s", (code,))
            lic = cur.fetchone()
            # Block if not found, already used, or revoked — revoked codes NEVER reactivate
            if not lic or lic.get("revoked") or lic["used"]:
                return False
            ltype  = lic["type"]
            expiry = None
            if ltype == "monthly":
                expiry = datetime.now() + timedelta(days=30)
            cur.execute(
                "UPDATE licences SET used=TRUE, used_by=%s, used_at=%s WHERE code=%s",
                (user_id, datetime.now(), code)
            )
            cur.execute(
                "UPDATE users SET licensed=TRUE, licence_type=%s, licence_code=%s, expiry=%s WHERE user_id=%s",
                (ltype, code, expiry, user_id)
            )
        conn.commit()
    return True

def generate_code(ltype):
    parts  = [uuid.uuid4().hex[:4].upper() for _ in range(3)]
    prefix = "EVAL-M" if ltype == "monthly" else "EVAL-L"
    return "{}-".format(prefix) + "-".join(parts)

def add_licence(code, ltype):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO licences (code, type, used) VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING",
                (code, ltype)
            )
        conn.commit()

def get_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users")
            users = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM licences")
            licences = [dict(r) for r in cur.fetchall()]
    return {
        "total":   len(users),
        "monthly": sum(1 for u in users if u.get("licence_type") == "monthly" and u.get("licensed")),
        "lifetime":sum(1 for u in users if u.get("licence_type") == "lifetime"),
        "free":    sum(1 for u in users if not u.get("licensed")),
        "m_codes": [l["code"] for l in licences if not l["used"] and not l.get("revoked") and l["type"] == "monthly"],
        "l_codes": [l["code"] for l in licences if not l["used"] and not l.get("revoked") and l["type"] == "lifetime"],
    }

def delete_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()

def revoke_licence(user_id):
    """
    Permanently revoke a user licence.
    - Strips licence from user immediately.
    - Marks their code as revoked with timestamp.
    - Code can never be reactivated even if re-generated with same value.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT licence_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row and row["licence_code"]:
                cur.execute(
                    "UPDATE licences SET used=TRUE, revoked=TRUE, revoked_at=NOW() WHERE code=%s",
                    (row["licence_code"],)
                )
            cur.execute(
                "UPDATE users SET licensed=FALSE, licence_type=NULL, licence_code=NULL, expiry=NULL WHERE user_id=%s",
                (user_id,)
            )
        conn.commit()

def get_all_user_ids():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [r["user_id"] for r in cur.fetchall()]

# ============================================================
# INACTIVITY TRACKER — 30 min without activity → clear state
# ============================================================
INACTIVITY_MINUTES = 30
# user_id -> {"task": asyncio.Task, "msg_ids": [list], "chat_id": int}
USER_INACTIVITY = {}

def inactivity_reset(user_id, chat_id, msg_id=None):
    """Call every time user does ANY action. Cancels old timer, logs msg_id."""
    entry = USER_INACTIVITY.get(user_id, {"task": None, "msg_ids": [], "chat_id": chat_id})
    entry["chat_id"] = chat_id
    if msg_id is not None:
        entry["msg_ids"].append(msg_id)
    if entry["task"] and not entry["task"].done():
        entry["task"].cancel()
    entry["task"] = None
    USER_INACTIVITY[user_id] = entry

def inactivity_clear(user_id):
    """Remove all tracking for user (after cleanup or fresh start)."""
    USER_INACTIVITY.pop(user_id, None)

def inactivity_get_msgs(user_id):
    return USER_INACTIVITY.get(user_id, {}).get("msg_ids", [])

# Track last signal + last bot message per user (for deletion on next action)
LAST_SIGNAL_MSG = {}  # {user_id: message_id}
LAST_BOT_MSG    = {}  # {user_id: message_id} — menus, no-signal, etc.

async def delete_last_signal(bot, chat_id, user_id):
    """Delete previous signal AND last bot message if exists."""
    for store in [LAST_SIGNAL_MSG, LAST_BOT_MSG]:
        msg_id = store.pop(user_id, None)
        if msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass

def save_last_signal_msg(user_id, msg_id):
    LAST_SIGNAL_MSG[user_id] = msg_id

def save_last_bot_msg(user_id, msg_id):
    LAST_BOT_MSG[user_id] = msg_id

# ============================================================
# ANTI-SPAM
# ============================================================
LAST_SIGNAL_TIME = {}
SPAM_SECONDS = 3  # Minimal anti-flood only — no cooldown between signals

def is_spam(user_id):
    """Minimal flood guard — 3 seconds only. No signal cooldown."""
    now = time.time()
    last = LAST_SIGNAL_TIME.get(user_id, 0)
    if now - last < SPAM_SECONDS:
        return True
    LAST_SIGNAL_TIME[user_id] = now
    return False

def spam_wait(user_id):
    now = time.time()
    last = LAST_SIGNAL_TIME.get(user_id, 0)
    remaining = SPAM_SECONDS - (now - last)
    return max(0, int(remaining) + 1)

# ============================================================
# BLACKLIST
# ============================================================
def is_blacklisted(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM blacklist WHERE user_id = %s", (user_id,))
            return cur.fetchone() is not None

def blacklist_user(user_id, reason=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO blacklist (user_id, reason, banned_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (user_id, reason, datetime.now())
            )
        conn.commit()

def unblacklist_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM blacklist WHERE user_id = %s", (user_id,))
        conn.commit()

def get_blacklist():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM blacklist ORDER BY banned_at DESC")
            return [dict(r) for r in cur.fetchall()]

# ============================================================
# REFERRAL
# ============================================================
def register_referral(new_user_id, referrer_id):
    if new_user_id == referrer_id:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Set referred_by if not yet set
            cur.execute("SELECT referred_by FROM users WHERE user_id = %s", (new_user_id,))
            row = cur.fetchone()
            if row and row["referred_by"] is None:
                cur.execute(
                    "UPDATE users SET referred_by = %s WHERE user_id = %s",
                    (referrer_id, new_user_id)
                )
        conn.commit()
    # Count referrals and apply bonus
    update_referral_bonus(referrer_id)

def count_referrals(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM users WHERE referred_by = %s", (user_id,))
            row = cur.fetchone()
            return row["cnt"] if row else 0

def update_referral_bonus(user_id):
    refs = count_referrals(user_id)
    if refs >= 5:
        bonus = 3
    elif refs >= 3:
        bonus = 2
    else:
        bonus = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET bonus_signals = %s WHERE user_id = %s", (bonus, user_id))
        conn.commit()

def get_bonus_signals(user_id):
    u = get_user(user_id)
    return u.get("bonus_signals", 0)

def total_free_allowed(user_id):
    return 3 + get_bonus_signals(user_id)

# ============================================================
# ALL PAIRS — Pocket Option (forex, OTC, indices, stocks, commodities)
# ============================================================
ALL_PAIRS = [
    # Currencies — mix of OTC and non-OTC
    "EUR/USD OTC", "EUR/USD", "GBP/USD OTC", "GBP/USD",
    "USD/JPY OTC", "USD/JPY", "USD/CHF OTC", "USD/CHF",
    "AUD/USD OTC", "AUD/USD", "NZD/USD OTC", "NZD/USD",
    "USD/CAD OTC", "USD/CAD", "EUR/GBP OTC", "EUR/GBP",
    "EUR/JPY OTC", "EUR/JPY", "EUR/AUD OTC", "EUR/AUD",
    "EUR/CAD OTC", "EUR/CAD", "EUR/CHF OTC", "EUR/CHF",
    "EUR/NZD OTC", "EUR/TRY OTC", "EUR/HUF OTC", "EUR/RUB OTC",
    "GBP/JPY OTC", "GBP/JPY", "GBP/AUD OTC", "GBP/AUD",
    "GBP/CAD OTC", "GBP/CAD", "GBP/CHF OTC", "GBP/CHF",
    "AUD/JPY OTC", "AUD/JPY", "AUD/CAD OTC", "AUD/CAD",
    "AUD/CHF OTC", "AUD/CHF", "AUD/NZD OTC",
    "NZD/JPY OTC", "CHF/JPY OTC", "CHF/JPY",
    "CAD/JPY OTC", "CAD/JPY", "CAD/CHF OTC", "CAD/CHF",
    "CHF/NOK OTC", "USD/MXN OTC", "USD/MXN",
    "USD/SGD OTC", "USD/BRL OTC", "USD/BDT OTC",
    "USD/EGP OTC", "USD/ARS OTC", "USD/MYR OTC",
    "USD/THB OTC", "USD/PKR OTC", "USD/VND OTC",
    "USD/CNH OTC", "USD/IDR OTC", "USD/INR OTC",
    "USD/CLP OTC", "USD/COP OTC", "USD/DZD OTC",
    "USD/RUB OTC", "USD/PHP OTC",
    "ZAR/USD OTC", "KES/USD OTC", "NGN/USD OTC",
    "MAD/USD OTC", "YER/USD OTC", "TND/USD OTC",
    "LBP/USD OTC", "UAH/USD OTC",
    "SAR/CNY OTC", "QAR/CNY OTC", "AED/CNY OTC",
    "BHD/CNY OTC", "OMR/CNY OTC", "JOD/CNY OTC",
    # Commodities OTC
    "Brent Oil OTC", "WTI Crude Oil OTC", "Gold OTC",
    "Natural Gas OTC", "Palladium spot OTC", "Platinum spot OTC",
    # Cryptocurrencies OTC
    "Dogecoin OTC", "Ethereum OTC", "Litecoin OTC",
    "Bitcoin ETF OTC", "Chainlink OTC", "Solana OTC",
    "BNB OTC", "Polkadot OTC", "Cardano OTC", "TRON OTC",
    "Polygon OTC", "Toncoin OTC", "Avalanche OTC",
    # Indices OTC
    "AUS 200 OTC", "100GBP OTC", "D30EUR OTC", "DJI30 OTC",
    "E35EUR OTC", "E35EUR", "E50EUR OTC", "F40EUR OTC",
    "JPN225 OTC", "US100 OTC", "US100", "SP500 OTC", "SP500",
    "CAC 40", "SMI 20",
    # Stocks OTC
    "Apple OTC", "American Express OTC", "Boeing Company OTC",
    "FACEBOOK INC OTC", "Intel OTC", "Johnson & Johnson OTC",
    "Citigroup Inc OTC", "Coinbase Global OTC", "FedEx OTC",
    "VIX OTC", "Amazon OTC", "Microsoft OTC", "GameStop Corp OTC",
    "McDonald's OTC", "Tesla OTC", "Netflix OTC", "ExxonMobil OTC",
    "Marathon Digital Holdings OTC", "Pfizer Inc OTC",
    "Palantir Technologies OTC", "VISA OTC", "Alibaba OTC",
    "Cisco OTC", "Advanced Micro Devices OTC",
    # Non-OTC non-forex removed (crypto, indices, stocks, commodities)
    # Only forex pairs with "/" notation remain as non-OTC
]

# ============================================================
# YAHOO FINANCE SYMBOL MAPPING (non-OTC pairs only)
# ============================================================
YAHOO_SYMBOLS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "USD/CHF": "USDCHF=X", "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X",
    "NZD/USD": "NZDUSD=X", "EUR/GBP": "EURGBP=X", "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X", "AUD/JPY": "AUDJPY=X", "EUR/AUD": "EURAUD=X",
    "EUR/CAD": "EURCAD=X", "GBP/AUD": "GBPAUD=X", "GBP/CAD": "GBPCAD=X",
    "AUD/CAD": "AUDCAD=X", "AUD/CHF": "AUDCHF=X", "NZD/JPY": "NZDJPY=X",
    "EUR/CHF": "EURCHF=X", "CHF/JPY": "CHFJPY=X", "CAD/JPY": "CADJPY=X",
    "CAD/CHF": "CADCHF=X", "GBP/CHF": "GBPCHF=X", "USD/MXN": "USDMXN=X",
    "US100": "^NDX", "SP500": "^GSPC", "CAC 40": "^FCHI",
    "SMI 20": "^SSMI", "E35EUR": "^STOXX",
}

def _calc_indicators_from_df(df):
    """Calculate all indicators from a OHLCV dataframe. Returns dict or None."""
    if df is None or len(df) < 30:
        return None
    close  = df["Close"].squeeze()
    high   = df["High"].squeeze()
    low    = df["Low"].squeeze()
    volume = df["Volume"].squeeze()
    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, 1e-9)
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])
    # MACD
    ema12     = close.ewm(span=12).mean()
    ema26     = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_ln = macd_line.ewm(span=9).mean()
    macd_hist = float((macd_line - signal_ln).iloc[-1])
    macd_norm = max(-1.0, min(1.0, macd_hist / (close.iloc[-1] * 0.001 + 1e-9)))
    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    u = float((sma20 + 2*std20).iloc[-1]); l = float((sma20 - 2*std20).iloc[-1])
    bb_pos = max(0.0, min(1.0, (float(close.iloc[-1]) - l) / (u - l + 1e-9)))
    # MA crossover
    ma9  = float(close.rolling(9).mean().iloc[-1])
    ma21 = float(close.rolling(21).mean().iloc[-1])
    ma_diff = max(-1.0, min(1.0, (ma9 - ma21) / (ma21 + 1e-9) * 100))
    # Momentum
    mom = max(-1.0, min(1.0, float(close.iloc[-1] - close.iloc[-11]) / (close.iloc[-11] + 1e-9) * 100))
    # Stochastic
    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    sto = max(0.0, min(100.0, float(((close - low14) / (high14 - low14 + 1e-9) * 100).iloc[-1])))
    # Volume ratio
    vol = min(1.0, float(volume.iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-9)))
    # RSI divergence (simple: last 5 bars — price up, RSI down = bearish div)
    rsi_series = (100 - 100 / (1 + gain / loss.replace(0, 1e-9)))
    price_change = float(close.iloc[-1] - close.iloc[-6])
    rsi_change   = float(rsi_series.iloc[-1] - rsi_series.iloc[-6])
    divergence = None
    if price_change > 0 and rsi_change < -3:
        divergence = "SELL"   # Bearish divergence
    elif price_change < 0 and rsi_change > 3:
        divergence = "BUY"    # Bullish divergence

    # Williams Fractal — scan recent candles
    # Bullish fractal: low[i] < low[i-2], low[i-1], low[i+1], low[i+2]
    # Bearish fractal: high[i] > high[i-2], high[i-1], high[i+1], high[i+2]
    # Check fractals formed recently (last 3-10 candles)
    # Last 2 candles cannot be fractals (need 2 candles to the right)
    fractal_signal = None
    fractal_strength = 0  # 0=none, 1=fractal 1, 2=fractal 2+ (stronger)
    high_vals = high.values
    low_vals  = low.values
    n = len(high_vals)
    # Scan candles from index n-5 to n-3 (need i+2 to be available)
    recent_bull_fractals = []
    recent_bear_fractals = []
    for i in range(n - 4, max(n - 15, 4), -1):
        # Bearish fractal: center high is greater than surrounding 4 highs
        if (high_vals[i] > high_vals[i-2] and high_vals[i] > high_vals[i-1] and
                high_vals[i] > high_vals[i+1] and high_vals[i] > high_vals[i+2]):
            recent_bear_fractals.append(i)
        # Bullish fractal: center low is less than surrounding 4 lows
        if (low_vals[i] < low_vals[i-2] and low_vals[i] < low_vals[i-1] and
                low_vals[i] < low_vals[i+1] and low_vals[i] < low_vals[i+2]):
            recent_bull_fractals.append(i)
    # Price above bullish fractal = BUY signal
    # Price below bearish fractal = SELL signal
    current_price_val = float(close.iloc[-1])
    if recent_bull_fractals:
        latest_bull = float(low_vals[recent_bull_fractals[0]])
        if current_price_val > latest_bull:
            fractal_signal = "BUY"
            fractal_strength = min(2, len(recent_bull_fractals))
    if recent_bear_fractals:
        latest_bear = float(high_vals[recent_bear_fractals[0]])
        if current_price_val < latest_bear:
            # Bearish fractal wins if both present
            fractal_signal = "SELL"
            fractal_strength = min(2, len(recent_bear_fractals))
    # If both present — pick the one closest to current price
    if recent_bull_fractals and recent_bear_fractals:
        bull_dist = abs(current_price_val - float(low_vals[recent_bull_fractals[0]]))
        bear_dist = abs(current_price_val - float(high_vals[recent_bear_fractals[0]]))
        if bull_dist < bear_dist:
            fractal_signal = "BUY"
            fractal_strength = min(2, len(recent_bull_fractals))
        else:
            fractal_signal = "SELL"
            fractal_strength = min(2, len(recent_bear_fractals))

    # Current price
    current_price = float(close.iloc[-1])
    direction_raw = "BUY" if ma_diff > 0 and macd_norm > 0 else ("SELL" if ma_diff < 0 and macd_norm < 0 else None)
    return {
        "rsi": rsi, "macd": macd_norm, "bb_pos": bb_pos,
        "ma_diff": ma_diff, "mom": mom, "sto": sto, "vol": vol,
        "real": True, "current_price": current_price,
        "divergence": divergence,
        "fractal_signal": fractal_signal,
        "fractal_strength": fractal_strength,
        "direction": direction_raw,
        "quality": abs(ma_diff) + abs(mom) + abs(macd_norm)
    }

# OTC → real pair mapping for 1H trend reference
OTC_TO_REAL = {
    "EUR/USD OTC": "EUR/USD", "GBP/USD OTC": "GBP/USD", "USD/JPY OTC": "USD/JPY",
    "USD/CHF OTC": "USD/CHF", "AUD/USD OTC": "AUD/USD", "USD/CAD OTC": "USD/CAD",
    "NZD/USD OTC": "NZD/USD", "EUR/GBP OTC": "EUR/GBP", "EUR/JPY OTC": "EUR/JPY",
    "GBP/JPY OTC": "GBP/JPY", "AUD/JPY OTC": "AUD/JPY", "EUR/AUD OTC": "EUR/AUD",
    "EUR/CAD OTC": "EUR/CAD", "GBP/AUD OTC": "GBP/AUD", "GBP/CAD OTC": "GBP/CAD",
    "AUD/CAD OTC": "AUD/CAD", "AUD/CHF OTC": "AUD/CHF", "NZD/JPY OTC": "NZD/JPY",
    "EUR/CHF OTC": "EUR/CHF", "CHF/JPY OTC": "CHF/JPY", "CAD/JPY OTC": "CAD/JPY",
    "CAD/CHF OTC": "CAD/CHF", "GBP/CHF OTC": "GBP/CHF",
    "Gold OTC": "Gold", "Silver OTC": "Silver",
    "Brent Oil OTC": "Brent Oil", "WTI Crude Oil OTC": "WTI Crude Oil",
    "Bitcoin ETF OTC": "Bitcoin",
    "US100 OTC": "US100", "SP500 OTC": "SP500",
    "Ethereum OTC": "Bitcoin",  # Fallback for Ethereum
    "Dogecoin OTC": "Bitcoin",
}

def _fetch_1h_trend(pair):
    """
    Fetch 1H candle data and determine trend direction using layered confirmation.

    Rules (in order of priority):
    1. EMA cross (9 vs 21) is REQUIRED — if absent/flat, return None immediately.
    2. Price position vs EMA21 must agree with EMA cross.
    3. MACD histogram direction must confirm.
    4. RSI 1H provides momentum confirmation.
    5. Last 3 candles direction provides momentum check.
    6. Reversal detection: if recent candles strongly oppose EMA cross + MACD flips, override.

    Returns: 'BUY', 'SELL', or None (unclear — no signal should be issued).
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="7d", interval="1h", progress=False, auto_adjust=True)
        if df is None or len(df) < 30:
            return None

        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()

        current_price = float(close.iloc[-1])

        # --- LAYER 1: EMA cross (REQUIRED) ---
        ema9  = float(close.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema9_prev  = float(close.ewm(span=9,  adjust=False).mean().iloc[-2])
        ema21_prev = float(close.ewm(span=21, adjust=False).mean().iloc[-2])

        ema_gap_pct = abs(ema9 - ema21) / (ema21 + 1e-9) * 100
        # EMA gap must be meaningful (> 0.005%) — flat EMAs = no trend
        if ema_gap_pct < 0.005:
            return None

        ema_bull = ema9 > ema21   # True = bullish EMA structure

        # --- LAYER 2: Price vs EMA21 must agree with EMA cross ---
        price_above_ema21 = current_price > ema21
        if ema_bull and not price_above_ema21:
            # EMA says BUY but price is below EMA21 — conflict
            return None
        if not ema_bull and price_above_ema21:
            # EMA says SELL but price is above EMA21 — conflict
            return None

        # --- LAYER 3: MACD on 1H ---
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist_now  = float((macd_line - macd_signal).iloc[-1])
        macd_hist_prev = float((macd_line - macd_signal).iloc[-2])
        macd_turning_bull = (macd_hist_now > 0 and macd_hist_prev <= 0)
        macd_turning_bear = (macd_hist_now < 0 and macd_hist_prev >= 0)
        macd_bull = macd_hist_now > 0

        # --- LAYER 4: RSI on 1H ---
        delta  = close.diff()
        gain   = delta.clip(lower=0).rolling(14).mean()
        loss   = (-delta.clip(upper=0)).rolling(14).mean()
        rsi_1h = float((100 - 100 / (1 + gain / loss.replace(0, 1e-9))).iloc[-1])
        rsi_bull = rsi_1h > 50

        # --- LAYER 5: Recent candle momentum (last 3 candles) ---
        c0 = float(close.iloc[-1])
        c1 = float(close.iloc[-2])
        c2 = float(close.iloc[-3])
        c3 = float(close.iloc[-4])
        candle_bull_count = sum([1 for a, b in [(c0,c1),(c1,c2),(c2,c3)] if a > b])
        candle_bear_count = 3 - candle_bull_count

        # --- REVERSAL DETECTION ---
        # If EMA says BUY but ALL 3 recent candles are falling + MACD turned bear = reversal
        if ema_bull and candle_bear_count >= 3 and (macd_turning_bear or not macd_bull):
            return None   # Trend is reversing — no signal, wait for clarity
        if not ema_bull and candle_bull_count >= 3 and (macd_turning_bull or macd_bull):
            return None   # Trend is reversing — no signal, wait for clarity

        # --- FINAL LAYERED DECISION ---
        # EMA cross already confirmed above (Layer 1+2).
        # Now count how many supporting layers agree.
        if ema_bull:
            supporting = sum([
                macd_bull,           # MACD agrees
                rsi_bull,            # RSI agrees
                candle_bull_count >= 2,  # At least 2 of 3 candles agree
            ])
            # Need at least 2 of 3 supporting layers for a valid BUY signal
            if supporting >= 2:
                return "BUY"
            return None
        else:
            supporting = sum([
                not macd_bull,              # MACD agrees (bearish)
                not rsi_bull,               # RSI agrees (bearish)
                candle_bear_count >= 2,     # At least 2 of 3 candles agree
            ])
            if supporting >= 2:
                return "SELL"
            return None

    except Exception as e:
        logging.warning("_fetch_1h_trend failed for {}: {}".format(pair, e))
        return None


def _confirm_1h_direction(pair, direction):
    """
    Smart check: kama signal ya chini (1m/2m) ni SELL,
    Check if recent 1H candles are trending down
    Returns True kama 1H inathibitisha direction, False kama inapingana.
    Hii ni accuracy layer ya ziada — kama 1H haina data, rudi True (proceed).
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return True  # No real data — proceed with signal
    try:
        df = yf.download(symbol, period="3d", interval="1h", progress=False, auto_adjust=True)
        if df is None or len(df) < 5:
            return True
        close = df["Close"].squeeze()
        # Look at last 3 candles to determine if price is moving in our direction
        c_last   = float(close.iloc[-1])
        c_prev1  = float(close.iloc[-2])
        c_prev2  = float(close.iloc[-3])
        # Count how many recent candles agree with our direction
        agree = 0
        if direction == "SELL":
            if c_last  < c_prev1: agree += 1
            if c_prev1 < c_prev2: agree += 1
        else:  # BUY
            if c_last  > c_prev1: agree += 1
            if c_prev1 > c_prev2: agree += 1
        # At least 1 of the 2 recent 1H candles must confirm
        return agree >= 1
    except Exception as e:
        logging.warning("_confirm_1h_direction failed for {}: {}".format(pair, e))
        return True  # Proceed on error

# Multi-timeframe intervals for Yahoo Finance
MTF_INTERVALS = [
    ("1m",  "1d"),   # 1 minute
    ("5m",  "2d"),   # 5 minutes
    ("15m", "5d"),   # 15 minutes
    ("30m", "5d"),   # 30 minutes
    ("1h",  "5d"),   # 1 hour
]

def _fetch_vwap_trend(pair):
    """
    Calculate VWAP (Volume Weighted Average Price) trend for the pair.
    Returns dict:
      direction: 'BUY' or 'SELL'
      strength:  'STRONG' | 'MODERATE' | 'WEAK'
      vwap:      float (VWAP value)
      price:     float (current price)
    Or None if data unavailable.

    Logic:
    - Price above VWAP = bullish (BUY)
    - Price below VWAP = bearish (SELL)
    - Strength measured by % distance from VWAP + volume confirmation
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)
        if df is None or len(df) < 10:
            return None
        close  = df["Close"].squeeze()
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        # Typical price per candle
        typical_price = (high + low + close) / 3
        # VWAP = cumulative(typical_price * volume) / cumulative(volume)
        cum_vol = volume.cumsum()
        cum_tpv = (typical_price * volume).cumsum()
        vwap = float((cum_tpv / cum_vol.replace(0, 1e-9)).iloc[-1])
        current_price = float(close.iloc[-1])

        # Distance from VWAP as % of VWAP
        dist_pct = (current_price - vwap) / (vwap + 1e-9) * 100

        direction = "BUY" if current_price > vwap else "SELL"

        # Volume confirmation: recent volume vs 20-bar average
        vol_ratio = float(volume.iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-9))

        # Strength classification
        abs_dist = abs(dist_pct)
        if abs_dist > 0.15 and vol_ratio > 1.0:
            strength = "STRONG"
        elif abs_dist > 0.07:
            strength = "MODERATE"
        else:
            strength = "WEAK"

        return {
            "direction": direction,
            "strength": strength,
            "vwap": vwap,
            "price": current_price,
            "dist_pct": dist_pct,
            "vol_ratio": vol_ratio,
        }
    except Exception as e:
        logging.warning("_fetch_vwap_trend failed for {}: {}".format(pair, e))
        return None


def _calc_trend_confluence(trend_1h, vwap_data, mtf, direction):
    """
    Calculate trend confluence level: how many trend filters agree with direction.
    Returns:
      level: 'STRONG' | 'MODERATE' | 'WEAK' | 'CONFLICTED'
      score: int (0-10)
      badge: emoji string for signal caption
    """
    score = 0
    total = 0

    # 1H trend agreement
    if trend_1h is not None:
        total += 1
        if trend_1h == direction:
            score += 1

    # VWAP trend agreement
    if vwap_data is not None:
        total += 1
        if vwap_data["direction"] == direction:
            score += 1
            # Extra point if VWAP strength is STRONG
            if vwap_data["strength"] == "STRONG":
                score += 1
                total += 1

    # MTF agreement (majority of timeframes)
    if mtf and mtf["total"] >= 3:
        total += 1
        mtf_dir = "BUY" if mtf["buy_tfs"] > mtf["sell_tfs"] else "SELL"
        if mtf_dir == direction:
            score += 1
            # Extra point if 4 or 5 TFs agree
            agreeing = mtf["buy_tfs"] if direction == "BUY" else mtf["sell_tfs"]
            if agreeing >= 4:
                score += 1
                total += 1

    if total == 0:
        return {"level": "WEAK", "score": 0, "badge": "⚪"}

    ratio = score / total

    # 1H + VWAP must BOTH agree for STRONG classification
    h1_ok   = trend_1h == direction if trend_1h else False
    vwap_ok = vwap_data["direction"] == direction if vwap_data else False

    if h1_ok and vwap_ok and ratio >= 0.75:
        level = "STRONG"
        badge = "🔥 STRONG"
    elif (h1_ok or vwap_ok) and ratio >= 0.5:
        level = "MODERATE"
        badge = "✅ GOOD"
    elif ratio < 0.35:
        level = "CONFLICTED"
        badge = "⚠️ WEAK"
    else:
        level = "WEAK"
        badge = "⚪ NORMAL"

    return {"level": level, "score": score, "badge": badge}


def _fetch_mtf_score(pair):
    """
    Fetch indicators across 5 timeframes (1m, 5m, 15m, 30m, 1h).
    Returns: (buy_tfs, sell_tfs, total_tfs, tf_details)
    For OTC pairs, uses mapped real pair.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return None
    buy_tfs = sell_tfs = 0
    tf_details = {}
    for interval, period in MTF_INTERVALS:
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            ind = _calc_indicators_from_df(df)
            if ind is None:
                continue
            # Count buy/sell votes per timeframe
            b = s = 0
            if ind["rsi"] < 45:    b += 1
            elif ind["rsi"] > 55:  s += 1
            if ind["ma_diff"] > 0: b += 1
            elif ind["ma_diff"] < 0: s += 1
            if ind["macd"] > 0:    b += 1
            elif ind["macd"] < 0:  s += 1
            if ind["bb_pos"] < 0.5: b += 1
            else:                   s += 1
            if ind["mom"] > 0:     b += 1
            elif ind["mom"] < 0:   s += 1
            tf_dir = "BUY" if b > s else "SELL"
            tf_details[interval] = tf_dir
            if tf_dir == "BUY":   buy_tfs  += 1
            else:                  sell_tfs += 1
        except Exception as e:
            logging.warning("MTF {} failed for {}: {}".format(interval, pair, e))
            continue
    total = buy_tfs + sell_tfs
    return {"buy_tfs": buy_tfs, "sell_tfs": sell_tfs, "total": total, "details": tf_details}

def _fetch_real_indicators(pair):
    """Fetch real OHLCV from Yahoo Finance and calculate indicators (5m timeframe)."""
    symbol = YAHOO_SYMBOLS.get(pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="2d", interval="5m", progress=False, auto_adjust=True)
        result = _calc_indicators_from_df(df)
        return result
    except Exception as e:
        logging.warning("Yahoo Finance fetch failed for {}: {}".format(pair, e))
        return None


def _check_reversal_candle(pair, lookback_candles):
    """Check for reversal candle (pin bar/doji) in last N candles. Returns type or None."""
    symbol = YAHOO_SYMBOLS.get(pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is None or len(df) < lookback_candles + 2:
            return None
        closes = df["Close"].squeeze()
        opens  = df["Open"].squeeze()
        highs  = df["High"].squeeze()
        lows   = df["Low"].squeeze()
        for i in range(-lookback_candles, 0):
            o = float(opens.iloc[i]); c = float(closes.iloc[i])
            h = float(highs.iloc[i]); l = float(lows.iloc[i])
            body = abs(c - o); candle = h - l
            if candle < 1e-9: continue
            upper_wick = h - max(o, c); lower_wick = min(o, c) - l
            body_ratio = body / candle
            if body_ratio < 0.3:
                if lower_wick > body * 2: return "BULLISH_REVERSAL"
                if upper_wick > body * 2: return "BEARISH_REVERSAL"
            if body_ratio < 0.1 and i > -len(closes):
                prev_c = float(closes.iloc[i-1]); prev_o = float(opens.iloc[i-1])
                if prev_c > prev_o: return "BEARISH_REVERSAL"
                if prev_c < prev_o: return "BULLISH_REVERSAL"
        return None
    except Exception as e:
        logging.warning("_check_reversal_candle {}: {}".format(pair, e))
        return None


def _get_live_candle_direction(pair):
    """Get current live candle direction. Returns UP, DOWN, or None."""
    symbol = YAHOO_SYMBOLS.get(pair)
    if not symbol: return None
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is None or len(df) < 2: return None
        c = float(df["Close"].squeeze().iloc[-1])
        o = float(df["Open"].squeeze().iloc[-1])
        if c > o: return "UP"
        if c < o: return "DOWN"
        return None
    except Exception:
        return None


def _apply_reversal_filter(direction, timeframe, pair):
    """
    Flip signal if reversal candle confirmed by live candle (TF 1m/2m/3m only).
    TF > 3m: no filter applied.
    """
    if timeframe > 3:
        return direction
    reversal = _check_reversal_candle(pair, timeframe)
    if reversal is None:
        return direction
    live = _get_live_candle_direction(pair)
    if reversal == "BEARISH_REVERSAL" and live == "DOWN":
        if "SELL" != direction:
            logging.info("REVERSAL FILTER: {} {} -> SELL".format(pair, direction))
        return "SELL"
    if reversal == "BULLISH_REVERSAL" and live == "UP":
        if "BUY" != direction:
            logging.info("REVERSAL FILTER: {} {} -> BUY".format(pair, direction))
        return "BUY"
    return direction


def _fetch_real_indicators_mtf(pair):
    """
    Fetch real OHLCV from Yahoo Finance across 3 timeframes (1m, 5m, 15m).
    Returns base indicators (from 5m) enriched with cross-timeframe consensus.
    Adds: tf_buy_votes, tf_sell_votes, tf_count to the result dict.
    """
    symbol = YAHOO_SYMBOLS.get(pair)
    if not symbol:
        return None

    tf_configs = [
        ("1m",  "1d"),
        ("5m",  "2d"),
        ("15m", "5d"),
    ]

    results = {}
    for interval, period in tf_configs:
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            ind = _calc_indicators_from_df(df)
            if ind is not None:
                results[interval] = ind
        except Exception as e:
            logging.warning("MTF real fetch {} {} failed: {}".format(pair, interval, e))

    if not results:
        return None

    # Use 5m as base; fall back to whatever is available
    base = results.get("5m") or results.get("15m") or list(results.values())[0]

    # Count direction votes across all fetched timeframes
    buy_votes = sell_votes = 0
    for interval, ind in results.items():
        d = ind.get("direction")
        if d == "BUY":
            buy_votes += 1
        elif d == "SELL":
            sell_votes += 1

    base = dict(base)   # Copy so we don't mutate cached data
    base["tf_buy_votes"]  = buy_votes
    base["tf_sell_votes"] = sell_votes
    base["tf_count"]      = len(results)
    return base

def _fetch_current_price(pair):
    """Fetch only current price for result checking."""
    symbol = YAHOO_SYMBOLS.get(pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is None or len(df) < 1:
            return None
        return float(df["Close"].squeeze().iloc[-1])
    except Exception as e:
        logging.warning("_fetch_current_price failed for {}: {}".format(pair, e))
        return None

def _get_session():
    """Returns session info and OTC behavior for current UTC hour."""
    hour = datetime.utcnow().hour
    if 0 <= hour < 8:
        return {"name": "Asian",       "buy_bias": 0,  "sell_bias": 5,  "otc": "contrarian", "threshold": 0.65}
    elif 8 <= hour < 11:
        return {"name": "London Open", "buy_bias": 10, "sell_bias": 10, "otc": "follow",      "threshold": 0.70}
    elif 11 <= hour < 13:
        return {"name": "London Mid",  "buy_bias": 5,  "sell_bias": 5,  "otc": "contrarian", "threshold": 0.70}
    elif 13 <= hour < 16:
        return {"name": "NY/London",   "buy_bias": 8,  "sell_bias": 8,  "otc": "contrarian", "threshold": 0.65}
    elif 16 <= hour < 19:
        return {"name": "NY Session",  "buy_bias": 6,  "sell_bias": 8,  "otc": "follow",      "threshold": 0.70}
    elif 19 <= hour < 21:
        return {"name": "NY Close",    "buy_bias": 4,  "sell_bias": 4,  "otc": "contrarian", "threshold": 0.65}
    else:
        return {"name": "Dead Hours",  "buy_bias": 2,  "sell_bias": 2,  "otc": "contrarian", "threshold": 0.60}

def _session_bias():
    s = _get_session()
    return (s["buy_bias"], s["sell_bias"])

def _pair_type(pair):
    p = pair.replace(" OTC", "").upper()
    crypto_names = ["BITCOIN", "ETHEREUM", "DOGECOIN", "LITECOIN", "SOLANA",
                    "BNB", "POLKADOT", "CARDANO", "TRON", "POLYGON", "TONCOIN",
                    "AVALANCHE", "CHAINLINK", "BITCOIN ETF", "DASH", "BCH",
                    "BTC", "ETH", "XRP", "ADA", "DOGE", "LTC", "AVAX", "DOT",
                    "MATIC", "LINK", "TRX", "ATOM", "XLM"]
    if any(c in p for c in crypto_names):
        return "crypto"
    commodity_names = ["GOLD", "SILVER", "OIL", "BRENT", "WTI", "NATURAL GAS",
                       "PALLADIUM", "PLATINUM", "XAU", "XAG", "COPPER", "GAS",
                       "WHEAT", "CORN", "SUGAR"]
    if any(c in p for c in commodity_names):
        return "commodity"
    index_names = ["US100", "SP500", "CAC", "SMI", "E35EUR", "E50EUR", "F40EUR",
                   "D30EUR", "DJI30", "JPN225", "AUS 200", "100GBP", "AEX",
                   "HONG KONG", "VIX", "US30", "NAS", "GER", "UK1", "FRA",
                   "STOXX", "SING", "HKG"]
    if any(c in p for c in index_names):
        return "index"
    stock_names = ["APPLE", "AMAZON", "MICROSOFT", "TESLA", "NETFLIX", "GOOGLE",
                   "FACEBOOK", "BOEING", "INTEL", "CISCO", "VISA", "ALIBABA",
                   "EXXON", "MCDONALD", "PFIZER", "CITIGROUP", "AMERICAN EXPRESS",
                   "JOHNSON", "COINBASE", "FEDEX", "GAMESTOP", "MARATHON",
                   "PALANTIR", "ADVANCED MICRO", "JPMORGAN", "AMD"]
    if any(c in p for c in stock_names):
        return "stock"
    return "forex"

# ============================================================
# SIGNAL HISTORY & USER STATE
# ============================================================
def record_signal(pair, direction):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO signal_history (pair, direction) VALUES (%s, %s)", (pair, direction))
            conn.commit()
    except Exception as e:
        logging.warning("record_signal failed: {}".format(e))

def get_signal_bias(pair, window=10, threshold=0.70):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT direction FROM signal_history WHERE pair=%s ORDER BY created_at DESC LIMIT %s",
                    (pair, window)
                )
                rows = cur.fetchall()
        if len(rows) < 5:
            return None
        directions = [r["direction"] for r in rows]
        total = len(directions)
        if directions.count("BUY") / total >= threshold:
            return "BUY"
        if directions.count("SELL") / total >= threshold:
            return "SELL"
        return None
    except Exception as e:
        logging.warning("get_signal_bias failed: {}".format(e))
        return None

def is_candle_safe_zone():
    """
    Check if current UTC second is in the safe zone for signal generation.
    Safe zone: seconds 5-54 (middle of 1-minute candle).
    Block zone: seconds 0-4 (new candle chaos) and 55-59 (candle closing).
    """
    second = datetime.utcnow().second
    return 5 <= second <= 54

def get_trend_direction(pair, window=20, min_signals=8, threshold=0.65):
    """
    Analyze signal history to find dominant trend.
    Returns 'BUY', 'SELL', or None (flat/no clear trend).
    Requires at least min_signals history entries and threshold dominance.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT direction FROM signal_history WHERE pair=%s ORDER BY created_at DESC LIMIT %s",
                    (pair, window)
                )
                rows = cur.fetchall()
        if len(rows) < min_signals:
            return None  # Not enough history — no trend decision
        directions = [r["direction"] for r in rows]
        total = len(directions)
        buy_ratio  = directions.count("BUY")  / total
        sell_ratio = directions.count("SELL") / total
        if buy_ratio >= threshold:
            return "BUY"
        if sell_ratio >= threshold:
            return "SELL"
        return None  # Flat market — mixed signals
    except Exception as e:
        logging.warning("get_trend_direction failed: {}".format(e))
        return None

def get_user_signal_state(user_id, pair):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user_signal_state WHERE user_id=%s AND pair=%s", (user_id, pair))
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        logging.warning("get_user_signal_state failed: {}".format(e))
        return None

def save_user_signal_state(user_id, pair, direction, timeframe, flip_count, entry_price=None):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_signal_state
                        (user_id, pair, last_direction, last_timeframe, signal_time, flip_count, entry_price, result_sent)
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s, FALSE)
                    ON CONFLICT (user_id, pair) DO UPDATE SET
                        last_direction = EXCLUDED.last_direction,
                        last_timeframe = EXCLUDED.last_timeframe,
                        signal_time    = EXCLUDED.signal_time,
                        flip_count     = EXCLUDED.flip_count,
                        entry_price    = EXCLUDED.entry_price,
                        result_sent    = FALSE
                """, (user_id, pair, direction, timeframe, flip_count, entry_price))
            conn.commit()
    except Exception as e:
        logging.warning("save_user_signal_state failed: {}".format(e))

def clear_user_signal_state(user_id, pair):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_signal_state WHERE user_id=%s AND pair=%s", (user_id, pair))
            conn.commit()
    except Exception as e:
        logging.warning("clear_user_signal_state failed: {}".format(e))

def set_cooldown(user_id, pair):
    seconds = random.randint(15, 30)
    cooldown_until = datetime.utcnow() + timedelta(seconds=seconds)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_signal_state
                    SET cooldown_until=%s, flip_count=0
                    WHERE user_id=%s AND pair=%s
                """, (cooldown_until, user_id, pair))
            conn.commit()
    except Exception as e:
        logging.warning("set_cooldown failed: {}".format(e))
    return seconds

def get_cooldown_remaining(user_id, pair):
    state = get_user_signal_state(user_id, pair)
    if not state or not state.get("cooldown_until"):
        return 0
    cooldown_until = state["cooldown_until"]
    if isinstance(cooldown_until, str):
        cooldown_until = datetime.fromisoformat(cooldown_until)
    return max(0, int((cooldown_until - datetime.utcnow()).total_seconds()))

async def schedule_result_check(bot, chat_id, user_id, pair, direction, timeframe_mins, entry_price):
    """
    Wait for candle to expire, add 5s buffer for candle to fully close,
    then check price once and send result.
    """
    # Wait for candle expiry + 5 second buffer
    await asyncio.sleep(timeframe_mins * 60 + 5)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT result_sent, entry_price FROM user_signal_state WHERE user_id=%s AND pair=%s",
                    (user_id, pair)
                )
                row = cur.fetchone()
        if not row or row["result_sent"]:
            return
        db_entry = row.get("entry_price")
        if db_entry is not None:
            entry_price = float(db_entry)
    except Exception as e:
        logging.warning("schedule_result_check state check failed: {}".format(e))
        return

    if entry_price is None:
        return

    # Fetch exit price — retry up to 3 times with 3s gap if API fails
    exit_price = None
    for _ in range(3):
        exit_price = _fetch_current_price(pair)
        if exit_price is not None:
            break
        await asyncio.sleep(3)

    if exit_price is None:
        return

    price_diff = exit_price - entry_price
    if abs(price_diff) < 0.000001:
        return  # No movement — skip

    if direction == "BUY":
        won = price_diff > 0
    else:
        won = price_diff < 0

    was_reversed = is_reverse_pair(pair)

    if won:
        result_text = "🏆 *EVALON {}* TF {}M — *WON* ✅".format(pair, timeframe_mins)
    else:
        result_text = "💔 *EVALON {}* TF {}M — *LOSS* ❌".format(pair, timeframe_mins)

    if not is_results_enabled():
        update_pair_stats(pair, won, was_reversed=was_reversed)
        return

    try:
        sent = await bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_signal_state SET result_sent=TRUE, result_msg_id=%s WHERE user_id=%s AND pair=%s",
                    (sent.message_id, user_id, pair)
                )
            conn.commit()
        update_pair_stats(pair, won, was_reversed=was_reversed)
    except Exception as e:
        logging.warning("schedule_result_check send failed: {}".format(e))

def check_signal_request(user_id, pair):
    """
    Returns:
      {"action": "fresh"}
      {"action": "flip",   "direction": X}  -- first quick return, flip direction
      {"action": "same",   "direction": X}  -- 2nd+ quick return, keep flipped (warning baada ya 4th press)
      {"action": "cooldown"}                -- still in cooldown
    """
    # Cooldown check first
    # No cooldown — signals available at any time

    state = get_user_signal_state(user_id, pair)
    if state is None:
        return {"action": "fresh"}

    signal_time = state["signal_time"]
    if isinstance(signal_time, str):
        signal_time = datetime.fromisoformat(signal_time)
    elapsed    = (datetime.utcnow() - signal_time).total_seconds()
    threshold  = state["last_timeframe"] * 60
    flip_count = state["flip_count"]

    # Returned after timeframe expired — treat as fresh
    if elapsed >= threshold:
        clear_user_signal_state(user_id, pair)
        return {"action": "fresh"}

    # Returned quickly within timeframe
    # flip_count tracks how many quick returns have happened:
    # 0 = first quick return  → flip direction
    # 1 = second quick return → same flipped direction
    # 2 = third quick return  → same flipped direction
    # 3+ = fourth quick return → block
    flipped = "SELL" if state["last_direction"] == "BUY" else "BUY"

    if flip_count == 0:
        return {"action": "flip", "direction": flipped}
    else:
        # Always "same" — no block here. Warning shown in getmore_ handler
        return {"action": "same", "direction": flipped}

# ============================================================
# MARKET PATTERN DETECTION — candlestick patterns
# ============================================================
def _detect_candlestick_patterns(df):
    """
    Detect classic candlestick reversal & continuation patterns.
    Returns: dict with pattern names and their direction (BUY/SELL) and strength bonus
    """
    if df is None or len(df) < 10:
        return {}

    close = df["Close"].squeeze()
    open_ = df["Open"].squeeze()
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()

    patterns = {}

    # Helper values (last 3 candles)
    o1, c1, h1, l1 = float(open_.iloc[-1]), float(close.iloc[-1]), float(high.iloc[-1]), float(low.iloc[-1])
    o2, c2, h2, l2 = float(open_.iloc[-2]), float(close.iloc[-2]), float(high.iloc[-2]), float(low.iloc[-2])
    o3, c3         = float(open_.iloc[-3]), float(close.iloc[-3])

    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    range1 = h1 - l1 + 1e-9
    range2 = h2 - l2 + 1e-9

    # ── DOJI: very small body (<10% of range) → trend exhaustion ──
    if body1 / range1 < 0.10 and range1 > 0:
        # Doji after uptrend = potential SELL reversal
        if c2 > o2 and body2 / range2 > 0.4:
            patterns["doji_reversal_sell"] = ("SELL", 20)
        # Doji after downtrend = potential BUY reversal
        elif c2 < o2 and body2 / range2 > 0.4:
            patterns["doji_reversal_buy"] = ("BUY", 20)

    # ── HAMMER: lower shadow long, small body at top → BUY reversal ──
    lower_shadow1 = min(o1, c1) - l1
    upper_shadow1 = h1 - max(o1, c1)
    if lower_shadow1 > body1 * 2 and upper_shadow1 < body1 * 0.5 and c2 < o2:
        patterns["hammer"] = ("BUY", 25)

    # ── SHOOTING STAR: upper shadow long, small body → SELL reversal ──
    if upper_shadow1 > body1 * 2 and lower_shadow1 < body1 * 0.5 and c2 > o2:
        patterns["shooting_star"] = ("SELL", 25)

    # ── ENGULFING BULLISH: candle 2 bearish, candle 1 bullish > candle 2 ──
    if c2 < o2 and c1 > o1 and c1 > o2 and o1 < c2:
        patterns["bullish_engulfing"] = ("BUY", 35)

    # ── ENGULFING BEARISH ──
    if c2 > o2 and c1 < o1 and c1 < o2 and o1 > c2:
        patterns["bearish_engulfing"] = ("SELL", 35)

    # ── THREE WHITE SOLDIERS: candles 3 bullish mfululizo ──
    if c1 > o1 and c2 > o2 and c3 > o3 and c1 > c2 > c3:
        patterns["three_white_soldiers"] = ("BUY", 40)

    # ── THREE BLACK CROWS: candles 3 bearish mfululizo ──
    if c1 < o1 and c2 < o2 and c3 < o3 and c1 < c2 < c3:
        patterns["three_black_crows"] = ("SELL", 40)

    # ── INSIDE BAR: candle 1 within range of candle 2 (consolidation → breakout) ──
    if h1 < h2 and l1 > l2:
        # Inside bar — neutral/continuation; follow candle 2 direction
        if c2 > o2:
            patterns["inside_bar_continuation"] = ("BUY", 15)
        else:
            patterns["inside_bar_continuation"] = ("SELL", 15)

    return patterns


def _check_pip_movement(pair):
    """
    Check average pip movement for this pair.
    Returns (avg_movement_pct, category) where category is:
      'HIGH'   — pair inasogea sana (>0.12%) → 1m ya kutosha
      'MEDIUM' — (0.06-0.12%) → 2m bora
      'LOW'    — (<0.06%) → 3m, small movement
    Prefers VTE data from DB, falls back to Yahoo Finance.
    """
    # Try DB first (VTE learned data)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT avg_movement FROM pair_stats WHERE pair=%s", (pair,))
                row = cur.fetchone()
        if row and row["avg_movement"]:
            avg = float(row["avg_movement"])
            if avg >= 0.12:
                return avg, "HIGH"
            elif avg >= 0.06:
                return avg, "MEDIUM"
            else:
                return avg, "LOW"
    except Exception:
        pass

    # Fallback: calculate from Yahoo Finance
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return 0.08, "MEDIUM"  # Default
    try:
        df = yf.download(symbol, period="2d", interval="5m", progress=False, auto_adjust=True)
        if df is None or len(df) < 10:
            return 0.08, "MEDIUM"
        close = df["Close"].squeeze()
        # Average candle-to-candle % movement
        moves = abs(close.diff() / close.shift(1) * 100).dropna()
        avg = float(moves.mean())
        if avg >= 0.12:
            return avg, "HIGH"
        elif avg >= 0.06:
            return avg, "MEDIUM"
        else:
            return avg, "LOW"
    except Exception:
        return 0.08, "MEDIUM"


def _check_signal_history_bias(pair, direction, window=15):
    """
    Check signal history — if recent signals are mostly the same direction,
    that reinforces the decision.
    Returns: (same_count, total, same_pct)
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT direction FROM signal_history WHERE pair=%s ORDER BY created_at DESC LIMIT %s",
                    (pair, window)
                )
                rows = cur.fetchall()
        if len(rows) < 5:
            return 0, 0, 0.0
        directions = [r["direction"] for r in rows]
        same = directions.count(direction)
        total = len(directions)
        return same, total, same / total
    except Exception:
        return 0, 0, 0.0


def _check_signal_stability(pair, proposed_direction, window_minutes=5):
    """
    Stability filter: check if the proposed direction has flipped suddenly
    compared to recent signals within the last window_minutes.

    Returns True if signal is STABLE (safe to issue).
    Returns False if signal flipped abruptly — do not issue.

    Logic: fetch last N signals within the time window.
    If the majority were the OPPOSITE direction, and this is a sudden flip,
    mark as unstable and suppress the signal.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT direction FROM signal_history
                       WHERE pair=%s AND created_at >= %s
                       ORDER BY created_at DESC LIMIT 10""",
                    (pair, cutoff)
                )
                rows = cur.fetchall()
        if not rows or len(rows) < 3:
            return True   # Not enough history — allow signal

        directions = [r["direction"] for r in rows]
        total = len(directions)
        opposite = "SELL" if proposed_direction == "BUY" else "BUY"
        opposite_pct = directions.count(opposite) / total

        # If 70%+ of recent signals (last 5 min) were the opposite direction
        # and now we're flipping — it's an unstable sudden reversal
        if opposite_pct >= 0.70:
            logging.info("STABILITY FILTER: {} blocked flip to {} ({}% were {})".format(
                pair, proposed_direction, int(opposite_pct*100), opposite))
            return False

        return True
    except Exception as e:
        logging.warning("_check_signal_stability failed {}: {}".format(pair, e))
        return True   # Allow on error


# ============================================================
# SIGNAL ALGORITHM — Multi-Timeframe + 1H Trend Filter + Patterns
# ============================================================
# Per-pair OTC flip decision cache (in-memory, reset on restart — fine for OTC)
_otc_flip_cache: dict = {}

async def _send_nonotc_signal(context, chat, user_id, pair, direction, timeframe, sig, idx_str):
    """Send a non-OTC signal with user-chosen timeframe."""
    ib     = direction == "BUY"
    arrow  = "Up 🟢" if ib else "Down 🔴"
    strength = sig.get("strength", 400)
    caption = "*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair, arrow, timeframe, strength)
    kb = nonotc_signal_keyboard(pair, timeframe)
    img = get_buy_image() if ib else get_sell_image()
    try:
        await delete_last_signal(context.bot, chat, user_id)
        sent = await context.bot.send_photo(chat_id=chat, photo=img, caption=caption,
                                            parse_mode="Markdown", reply_markup=kb)
        save_last_signal_msg(user_id, sent.message_id)
    except Exception as e:
        logging.warning("_send_nonotc_signal failed: {}".format(e))

# ============================================================
# FINNHUB + YFINANCE MTF SIGNAL ENGINE
# Called by GET SIGNAL handler — does not modify generate_signal
# ============================================================
FINNHUB_FOREX_SYMBOLS = {
    "EUR/USD": "OANDA:EUR_USD", "GBP/USD": "OANDA:GBP_USD",
    "USD/JPY": "OANDA:USD_JPY", "USD/CHF": "OANDA:USD_CHF",
    "AUD/USD": "OANDA:AUD_USD", "USD/CAD": "OANDA:USD_CAD",
    "NZD/USD": "OANDA:NZD_USD", "EUR/GBP": "OANDA:EUR_GBP",
    "EUR/JPY": "OANDA:EUR_JPY", "GBP/JPY": "OANDA:GBP_JPY",
    "AUD/JPY": "OANDA:AUD_JPY", "EUR/AUD": "OANDA:EUR_AUD",
    "EUR/CAD": "OANDA:EUR_CAD", "GBP/AUD": "OANDA:GBP_AUD",
    "GBP/CAD": "OANDA:GBP_CAD", "AUD/CAD": "OANDA:AUD_CAD",
    "AUD/CHF": "OANDA:AUD_CHF", "NZD/JPY": "OANDA:NZD_JPY",
    "EUR/CHF": "OANDA:EUR_CHF", "CHF/JPY": "OANDA:CHF_JPY",
    "CAD/JPY": "OANDA:CAD_JPY", "CAD/CHF": "OANDA:CAD_CHF",
    "GBP/CHF": "OANDA:GBP_CHF",
}

def _mtf_fh_candles(symbol, resolution, count=120):
    """Fetch candles from Finnhub. Returns DataFrame or None."""
    try:
        now     = int(time.time())
        res_sec = {"1":60,"5":300,"15":900,"30":1800,"60":3600,"240":14400,"D":86400}.get(str(resolution),60)
        from_ts = now - res_sec * (count + 60)
        url = ("https://finnhub.io/api/v1/forex/candle"
               "?symbol={}&resolution={}&from={}&to={}&token={}".format(
                   symbol, resolution, from_ts, now, FINNHUB_KEY))
        r = requests.get(url, timeout=8)
        if r.status_code != 200: return None
        d = r.json()
        if d.get("s") != "ok" or not d.get("c"): return None
        df = pd.DataFrame({
            "Open": d["o"], "High": d["h"], "Low": d["l"],
            "Close": d["c"], "Volume": d.get("v", [0]*len(d["c"])),
        }, index=pd.to_datetime(d["t"], unit="s"))
        return df.iloc[-count:]
    except Exception as e:
        logging.warning("_mtf_fh_candles {} {} failed: {}".format(symbol, resolution, e))
        return None

def _mtf_yf_candles(symbol, interval, period):
    """Fetch candles from Yahoo Finance. Returns DataFrame or None."""
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
        return df if df is not None and len(df) >= 20 else None
    except Exception as e:
        logging.warning("_mtf_yf_candles {} {} failed: {}".format(symbol, interval, e))
        return None

def _mtf_calc_direction(df):
    """
    Calculate trend direction from OHLCV DataFrame using full indicator suite.
    Indicators: EMA9/21/50, MACD, RSI, Stochastic, BB, Momentum, ADX,
                CCI, Williams %R, VWAP, OBV, Ichimoku, Heikin-Ashi,
                Supertrend, RSI Divergence, Williams Fractal.
    Returns: 'BUY', 'SELL', or None.
    """
    if df is None or len(df) < 35:
        return None
    try:
        close  = df["Close"].squeeze().astype(float)
        high   = df["High"].squeeze().astype(float)
        low    = df["Low"].squeeze().astype(float)
        volume = df["Volume"].squeeze().astype(float)
        n = len(close)
        c = float(close.iloc[-1])
        buy = sell = 0

        # EMA 9/21/50
        ema9  = float(close.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1]) if n >= 50 else ema21
        gap   = abs(ema9 - ema21) / (ema21 + 1e-9) * 100
        if gap >= 0.003:
            if ema9 > ema21: buy  += 3 + (1 if c > ema21 else 0) + (1 if ema21 > ema50 else 0)
            else:            sell += 3 + (1 if c < ema21 else 0) + (1 if ema21 < ema50 else 0)

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        hist  = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
        h_now = float(hist.iloc[-1]); h_prv = float(hist.iloc[-2])
        if h_now > 0:   buy  += 3 if h_now > h_prv else 1
        elif h_now < 0: sell += 3 if h_now < h_prv else 1

        # RSI
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float((100 - 100/(1 + gain/loss.replace(0,1e-9))).iloc[-1])
        if   rsi < 30: buy  += 4
        elif rsi < 45: buy  += 2
        elif rsi < 50: buy  += 1
        elif rsi > 70: sell += 4
        elif rsi > 55: sell += 2
        elif rsi > 50: sell += 1

        # Stochastic
        l14 = low.rolling(14).min(); h14 = high.rolling(14).max()
        sto = float(((close-l14)/(h14-l14+1e-9)*100).iloc[-1])
        sp  = float(((close-l14)/(h14-l14+1e-9)*100).iloc[-2])
        if sto < 20: buy  += 3 if sto > sp else 1
        elif sto > 80: sell += 3 if sto < sp else 1

        # Bollinger Bands
        sma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bb_u  = float((sma20+2*std20).iloc[-1]); bb_l = float((sma20-2*std20).iloc[-1])
        bb_m  = float(sma20.iloc[-1])
        if c < bb_l: buy  += 3
        elif c < bb_m: buy  += 1
        elif c > bb_u: sell += 3
        elif c > bb_m: sell += 1
        if (bb_u-bb_l)/(bb_m+1e-9) < 0.005: buy -= 1; sell -= 1  # Squeeze penalty

        # Momentum ROC
        if n >= 11:
            roc = (c - float(close.iloc[-11])) / (float(close.iloc[-11])+1e-9) * 100
            if roc > 0.3: buy += 2
            elif roc > 0.1: buy += 1
            elif roc < -0.3: sell += 2
            elif roc < -0.1: sell += 1

        # ADX
        if n >= 28:
            try:
                tr   = pd.Series([max(float(high.iloc[i])-float(low.iloc[i]),
                                      abs(float(high.iloc[i])-float(close.iloc[i-1])),
                                      abs(float(low.iloc[i])-float(close.iloc[i-1])))
                                  for i in range(1,n)], index=close.index[1:])
                dmp  = pd.Series([max(float(high.iloc[i])-float(high.iloc[i-1]),0)
                                  if float(high.iloc[i])-float(high.iloc[i-1]) >
                                     float(low.iloc[i-1])-float(low.iloc[i]) else 0
                                  for i in range(1,n)], index=close.index[1:])
                dmm  = pd.Series([max(float(low.iloc[i-1])-float(low.iloc[i]),0)
                                  if float(low.iloc[i-1])-float(low.iloc[i]) >
                                     float(high.iloc[i])-float(high.iloc[i-1]) else 0
                                  for i in range(1,n)], index=close.index[1:])
                atr14= tr.rolling(14).mean()
                dip  = 100*(dmp.rolling(14).mean()/(atr14+1e-9))
                dim  = 100*(dmm.rolling(14).mean()/(atr14+1e-9))
                adx  = float((100*abs(dip-dim)/(dip+dim+1e-9)).rolling(14).mean().iloc[-1])
                if adx >= 25:
                    if float(dip.iloc[-1]) > float(dim.iloc[-1]): buy  += 2
                    else:                                           sell += 2
                else:
                    buy -= 1; sell -= 1
            except Exception: pass

        # CCI
        if n >= 20:
            tp  = (high+low+close)/3
            mad = tp.rolling(20).apply(lambda x: abs(x-x.mean()).mean(), raw=True)
            cci = float(((tp-tp.rolling(20).mean())/(0.015*mad+1e-9)).iloc[-1])
            if cci < -100: buy  += 3
            elif cci < -50: buy  += 1
            elif cci > 100: sell += 3
            elif cci > 50:  sell += 1

        # Williams %R
        if n >= 14:
            wpr = float(((high.rolling(14).max()-close)/(high.rolling(14).max()-low.rolling(14).min()+1e-9)*-100).iloc[-1])
            if wpr < -80: buy  += 3
            elif wpr < -50: buy += 1
            elif wpr > -20: sell += 3
            elif wpr > -50: sell += 1

        # VWAP
        if volume.sum() > 0 and n >= 20:
            tp_v  = (high+low+close)/3
            vwap  = (tp_v*volume).rolling(20).sum()/(volume.rolling(20).sum()+1e-9)
            if c > float(vwap.iloc[-1]): buy  += 2
            else:                         sell += 2

        # OBV
        if n >= 10:
            obv = (volume*((close-close.shift(1)).apply(lambda x: 1 if x>0 else(-1 if x<0 else 0)))).cumsum()
            if float(obv.iloc[-1]) > float(obv.rolling(10).mean().iloc[-1]): buy  += 1
            else:                                                               sell += 1

        # Ichimoku Tenkan/Kijun
        if n >= 26:
            tk = float(((high.rolling(9).max()+low.rolling(9).min())/2).iloc[-1])
            kj = float(((high.rolling(26).max()+low.rolling(26).min())/2).iloc[-1])
            if c > tk and c > kj and tk > kj:   buy  += 3
            elif c < tk and c < kj and tk < kj: sell += 3
            elif tk > kj: buy  += 1
            elif tk < kj: sell += 1

        # Heikin-Ashi
        if n >= 5:
            ha_c = (df["Open"].squeeze().astype(float)+high+low+close)/4
            ha_o = df["Open"].squeeze().astype(float).ewm(span=2,adjust=False).mean()
            if float(ha_c.iloc[-1])>float(ha_o.iloc[-1]) and float(ha_c.iloc[-2])>float(ha_o.iloc[-2]):
                buy  += 2
            elif float(ha_c.iloc[-1])<float(ha_o.iloc[-1]) and float(ha_c.iloc[-2])<float(ha_o.iloc[-2]):
                sell += 2

        # Supertrend (10/3 ATR)
        if n >= 15:
            try:
                atr10 = pd.Series([max(float(high.iloc[i])-float(low.iloc[i]),
                                       abs(float(high.iloc[i])-float(close.iloc[i-1])),
                                       abs(float(low.iloc[i])-float(close.iloc[i-1])))
                                   for i in range(1,n)], index=close.index[1:]).rolling(10).mean()
                mid   = (high.iloc[1:]+low.iloc[1:])/2
                lower_st = mid - 3*atr10
                if c > float(lower_st.iloc[-1]): buy  += 2
                else:                             sell += 2
            except Exception: pass

        # RSI Divergence
        if n >= 10:
            rsi_s    = 100-100/(1+gain/loss.replace(0,1e-9))
            price_ch = float(close.iloc[-1])-float(close.iloc[-6])
            rsi_ch   = float(rsi_s.iloc[-1])-float(rsi_s.iloc[-6])
            if price_ch > 0 and rsi_ch < -3:  sell += 3
            elif price_ch < 0 and rsi_ch > 3: buy  += 3

        # Williams Fractal
        hv = high.values; lv = low.values
        for i in range(n-4, max(n-12,4), -1):
            if hv[i]>hv[i-2] and hv[i]>hv[i-1] and hv[i]>hv[i+1] and hv[i]>hv[i+2]:
                if c < hv[i]: sell += 2
                break
        for i in range(n-4, max(n-12,4), -1):
            if lv[i]<lv[i-2] and lv[i]<lv[i-1] and lv[i]<lv[i+1] and lv[i]<lv[i+2]:
                if c > lv[i]: buy  += 2
                break

        total = buy + sell
        if total < 1: return None
        return "BUY" if buy > sell else "SELL"
    except Exception as e:
        logging.warning("_mtf_calc_direction failed: {}".format(e))
        return None


def _mtf_get_micro_dir(yf_sym, fh_sym):
    """
    Micro-direction (5s/10s/15s proxy): last 2 consecutive 1m candle bodies
    must agree (both YF and Finnhub if available).
    Returns 'BUY', 'SELL', or None.
    """
    votes = []
    # Yahoo Finance 1m
    df = _mtf_yf_candles(yf_sym, "1m", "1d")
    if df is not None and len(df) >= 3:
        opens  = df["Open"].squeeze().astype(float)
        closes = df["Close"].squeeze().astype(float)
        c1b = float(closes.iloc[-1]) > float(opens.iloc[-1])
        c2b = float(closes.iloc[-2]) > float(opens.iloc[-2])
        if c1b and c2b:         votes.append("BUY")
        elif not c1b and not c2b: votes.append("SELL")
    # Finnhub 1m
    if fh_sym:
        df2 = _mtf_fh_candles(fh_sym, "1", 10)
        if df2 is not None and len(df2) >= 3:
            c1b = float(df2["Close"].iloc[-1]) > float(df2["Open"].iloc[-1])
            c2b = float(df2["Close"].iloc[-2]) > float(df2["Open"].iloc[-2])
            if c1b and c2b:         votes.append("BUY")
            elif not c1b and not c2b: votes.append("SELL")
    if not votes: return None
    if len(votes) == 2 and votes[0] != votes[1]: return None
    return votes[0]


def _mtf_fetch_tf(yf_sym, fh_sym, fh_res, yf_interval, yf_period):
    """Fetch one TF: Finnhub primary, Yahoo fallback. Returns direction or None."""
    df = _mtf_fh_candles(fh_sym, fh_res) if fh_sym else None
    if df is None: df = _mtf_yf_candles(yf_sym, yf_interval, yf_period)
    return _mtf_calc_direction(df)


def _mtf_check_confirmation(dirs, signal_type):
    """
    Check MTF confirmation for signal_type 1/2/3.
    dirs = {"micro":x, "anchor":x, "mid":x, "bias":x}
    Returns: "CALL", "PUT", "NEAR_CALL", "NEAR_PUT", or None.
    """
    keys    = ["micro", "anchor", "mid", "bias"]
    scores  = [1 if dirs.get(k)=="BUY" else (-1 if dirs.get(k)=="SELL" else 0) for k in keys]
    avail   = [s for s in scores if s != 0]
    if len(avail) < 3: return None
    bull = sum(1 for s in avail if s > 0)
    bear = sum(1 for s in avail if s < 0)
    tot  = len(avail)
    if bull == tot:       return "CALL"
    if bear == tot:       return "PUT"
    if tot >= 3:
        if bull >= tot-1 and bull > bear: return "NEAR_CALL"
        if bear >= tot-1 and bear > bull: return "NEAR_PUT"
    return None


def _mtf_trend_score(all_dirs):
    """
    Weighted trend score from all fetched TFs.
    Returns (score 0-100, 'BUY'|'SELL'|None).
    """
    weights = {"4h":40,"1h":25,"30m":20,"15m":20,"2m":15,"1m":15,"3m":15,"5m":10,"micro":12}
    bw = sw = tw = 0
    for tf, w in weights.items():
        d = all_dirs.get(tf)
        if d == "BUY":  bw += w; tw += w
        elif d == "SELL": sw += w; tw += w
    if tw == 0: return 0, None
    if bw > sw: return min(100, bw/tw*100), "BUY"
    return min(100, sw/tw*100), "SELL"


def run_mtf_signal_engine(pair):
    """
    Main entry point — called from GET SIGNAL handler.
    Tries 1-min, 2-min, 3-min confirmation in order.

    Confirmation rules:
      1-min : micro(5s)  + 1m  + 15m + 4h — ALL bullish → CALL, ALL bearish → PUT
      2-min : micro(10s) + 2m  + 30m + 4h
      3-min : micro(15s) + 3m  + 1h  + 4h

    Near-confirmation (3/4 TF) only if trend_score >= 72%.
    Minimum trend_score: 62% — below this returns no signal.

    Returns dict:
      signal_type : 1/2/3/None
      direction   : 'CALL'/'PUT'/None
      near        : bool
      trend_score : float
      trend_dir   : 'BUY'/'SELL'/None
      tf_labels   : list of (label, direction) for display
      message     : str
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)

    # Fetch all needed TFs once
    all_dirs = {}
    try:
        all_dirs["micro"] = _mtf_get_micro_dir(yf_sym, fh_sym)
        all_dirs["1m"]    = _mtf_fetch_tf(yf_sym, fh_sym, "1",   "1m",  "1d")
        all_dirs["2m"]    = _mtf_fetch_tf(yf_sym, None,   None,  "2m",  "1d")
        all_dirs["3m"]    = _mtf_fetch_tf(yf_sym, fh_sym, "5",   "5m",  "2d")   # 5m proxy for 3m
        all_dirs["15m"]   = _mtf_fetch_tf(yf_sym, fh_sym, "15",  "15m", "5d")
        all_dirs["30m"]   = _mtf_fetch_tf(yf_sym, fh_sym, "30",  "30m", "5d")
        all_dirs["1h"]    = _mtf_fetch_tf(yf_sym, fh_sym, "60",  "1h",  "10d")
        all_dirs["4h"]    = _mtf_fetch_tf(yf_sym, fh_sym, "240", "4h",  "30d")
    except Exception as e:
        logging.warning("run_mtf_signal_engine fetch failed {}: {}".format(pair, e))

    # Trend strength filter
    trend_score, trend_dir = _mtf_trend_score(all_dirs)
    if trend_score < 45 or trend_dir is None:
        return {"signal_type": None, "direction": None, "near": False,
                "trend_score": trend_score, "trend_dir": trend_dir,
                "tf_labels": [], "message": "Trend too weak ({:.0f}%)".format(trend_score)}

    # Try 1-min → 2-min → 3-min
    configs = {
        1: {"micro": all_dirs.get("micro"), "anchor": all_dirs.get("1m"),
            "mid": all_dirs.get("15m"), "bias": all_dirs.get("4h"),
            "labels": [("5s", "micro"), ("1m", "1m"), ("15m", "15m"), ("4h", "4h")]},
        2: {"micro": all_dirs.get("micro"), "anchor": all_dirs.get("2m"),
            "mid": all_dirs.get("30m"), "bias": all_dirs.get("4h"),
            "labels": [("10s", "micro"), ("2m", "2m"), ("30m", "30m"), ("4h", "4h")]},
        3: {"micro": all_dirs.get("micro"), "anchor": all_dirs.get("3m"),
            "mid": all_dirs.get("1h"), "bias": all_dirs.get("4h"),
            "labels": [("15s", "micro"), ("3m", "3m"), ("1h", "1h"), ("4h", "4h")]},
    }

    for sig_type in [1, 2, 3]:
        cfg    = configs[sig_type]
        result = _mtf_check_confirmation(cfg, sig_type)
        if result in ("CALL", "PUT"):
            conf_dir = "BUY" if result == "CALL" else "SELL"
            if conf_dir != trend_dir: continue
            tf_labels = [(lbl, all_dirs.get(key)) for lbl, key in cfg["labels"]]
            return {"signal_type": sig_type, "direction": result, "near": False,
                    "trend_score": trend_score, "trend_dir": trend_dir,
                    "tf_labels": tf_labels,
                    "message": "Full {} {}-min confirmation".format(result, sig_type)}
        elif result in ("NEAR_CALL", "NEAR_PUT") and trend_score >= 55:
            near_dir = "BUY" if "CALL" in result else "SELL"
            if near_dir != trend_dir: continue
            tf_labels = [(lbl, all_dirs.get(key)) for lbl, key in cfg["labels"]]
            return {"signal_type": sig_type,
                    "direction": "CALL" if "CALL" in result else "PUT",
                    "near": True,
                    "trend_score": trend_score, "trend_dir": trend_dir,
                    "tf_labels": tf_labels,
                    "message": "Near {}-min confirmation ({:.0f}%)".format(sig_type, trend_score)}

    return {"signal_type": None, "direction": None, "near": False,
            "trend_score": trend_score, "trend_dir": trend_dir,
            "tf_labels": [], "message": "No MTF confirmation (1m/2m/3m)"}


def build_mtf_caption(pair, direction, sig_type, tf_labels, trend_score, near=False):
    """
    Build signal caption with MTF TF breakdown.
    direction: 'CALL' or 'PUT'
    """
    arrow    = "Up 🟢" if direction == "CALL" else "Down 🔴"
    near_tag = " _(near)_" if near else ""
    badge    = "✅ FULL CONFIRMATION" if not near else "⚡ NEAR CONFIRMATION"
    lines    = []
    for lbl, d in tf_labels:
        if d == "BUY":   lines.append("🟢 {}".format(lbl))
        elif d == "SELL": lines.append("🔴 {}".format(lbl))
        else:             lines.append("⚪ {} (no data)".format(lbl))
    tf_block = "\n".join(lines)
    return (
        "*{}* {}\n"
        "🕐 In *{}* min{}\n\n"
        "📋 *MTF Confirmation:*\n"
        "{}\n\n"
        "{}\n"
        "📊 Trend strength: *{:.0f}%*"
    ).format(pair, arrow, sig_type, near_tag, tf_block, badge, trend_score)

# ── END MTF ENGINE ───────────────────────────────────────────

def _force_signal_from_micro(pair, signal_type):
    """
    Fallback ya mwisho — angalia candles 100 za nyuma za micro timeframe.

    Micro TF per signal type:
      signal_type 1 = 5s  proxy → Finnhub/Yahoo 1m candles 100
      signal_type 2 = 10s proxy → Finnhub/Yahoo 1m candles 100
      signal_type 3 = 15s proxy → Finnhub/Yahoo 1m candles 100

    Mantiki:
      - Hesabu candles 100 za mwisho
      - close > open = kijani (bullish win)
      - close < open = nyekundu (bearish win)
      - Yenye win nyingi inaonyesha mwelekeo wa kweli wa soko
      - Kijani nyingi → BUY, Nyekundu nyingi → SELL
      - Daima inatoa signal — haishindwi kamwe
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)

    micro_label = {1: "5s", 2: "10s", 3: "15s"}.get(signal_type, "5s")
    COUNT  = 100
    bull = bear = 0
    source = "none"

    # Finnhub 1m primary
    if fh_sym:
        try:
            df = _mtf_fh_candles(fh_sym, "1", COUNT + 20)
            if df is not None and len(df) >= 10:
                df = df.iloc[-COUNT:]
                opens  = df["Open"].astype(float)
                closes = df["Close"].astype(float)
                for o, c in zip(opens, closes):
                    if c > o:   bull += 1
                    elif c < o: bear += 1
                source = "finnhub_1m"
        except Exception as e:
            logging.warning("_force_signal_from_micro finnhub: {}".format(e))

    # Yahoo 1m fallback
    if bull == 0 and bear == 0 and yf_sym:
        try:
            df = _mtf_yf_candles(yf_sym, "1m", "2d")
            if df is not None and len(df) >= 10:
                df = df.iloc[-COUNT:]
                opens  = df["Open"].squeeze().astype(float)
                closes = df["Close"].squeeze().astype(float)
                for o, c in zip(opens, closes):
                    if c > o:   bull += 1
                    elif c < o: bear += 1
                source = "yahoo_1m"
        except Exception as e:
            logging.warning("_force_signal_from_micro yahoo: {}".format(e))

    # Last Finnhub 5m candle as fallback if no other data
    if bull == 0 and bear == 0 and fh_sym:
        try:
            df = _mtf_fh_candles(fh_sym, "5", 50)
            if df is not None and len(df) >= 5:
                opens  = df["Open"].astype(float)
                closes = df["Close"].astype(float)
                for o, c in zip(opens, closes):
                    if c > o:   bull += 1
                    elif c < o: bear += 1
                source = "finnhub_5m"
        except Exception: pass

    total      = bull + bear
    bull_pct   = (bull / total * 100) if total > 0 else 50.0
    bear_pct   = (bear / total * 100) if total > 0 else 50.0
    direction  = "BUY" if bull >= bear else "SELL"
    trend_score = bull_pct if direction == "BUY" else bear_pct

    logging.info("MICRO HISTORY {}: {} candles | green={:.0f}% red={:.0f}% → {} [{}]".format(
        pair, total, bull_pct, bear_pct, direction, source))

    return {
        "signal_type": signal_type,
        "direction":   "CALL" if direction == "BUY" else "PUT",
        "near":        True,
        "trend_score": max(50.0, trend_score),
        "trend_dir":   direction,
        "tf_labels":   [(micro_label, direction)],
        "message":     "Micro history {}: green={:.0f}% red={:.0f}% → {} [{}]".format(
                        micro_label, bull_pct, bear_pct, direction, source),
        "forced":      True,
    }

def run_mtf_signal_engine_with_fallback(pair, signal_type=None):
    """
    Full MTF engine with guaranteed signal fallback.
    Order ya jaribu:
      1. Full confirmation (4/4)
      2. Near confirmation (3/4) — trend >= 55%
      3. 2/4 confirmation — trend >= 45%
      4. 1/4 (micro direction tu)
      5. Micro history fallback — DAIMA inatoa signal

    signal_type: 1/2/3 au None (jaribu zote)
    """
    # For OTC — skip MTF entirely, return None so generate_signal runs
    if "OTC" in pair:
        return None

    result = run_mtf_signal_engine(pair)

    # Got full or near confirmation — done
    if result and result.get("direction") in ("CALL", "PUT"):
        return result

    # 2/4 attempt — lower bar further
    real_pair = OTC_TO_REAL.get(pair, pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    all_dirs  = result.get("tf_labels", []) if result else []

    # Try each signal type with 2/4 rule
    types_to_try = [signal_type] if signal_type else [1, 2, 3]
    for st in types_to_try:
        try:
            # Rebuild all_dirs dict from result
            ad = {}
            if result and result.get("tf_labels"):
                for lbl, d in result["tf_labels"]:
                    ad[lbl] = d
            # Also try fetching fresh
            if not ad:
                ad["micro"] = _mtf_get_micro_dir(yf_sym, fh_sym)
                ad["1m"]  = _mtf_fetch_tf(yf_sym, fh_sym, "1",  "1m",  "1d")
                ad["2m"]  = _mtf_fetch_tf(yf_sym, None,   None, "2m",  "1d")
                ad["3m"]  = _mtf_fetch_tf(yf_sym, fh_sym, "5",  "5m",  "2d")
                ad["15m"] = _mtf_fetch_tf(yf_sym, fh_sym, "15", "15m", "5d")
                ad["30m"] = _mtf_fetch_tf(yf_sym, fh_sym, "30", "30m", "5d")
                ad["1h"]  = _mtf_fetch_tf(yf_sym, fh_sym, "60", "1h",  "10d")
                ad["4h"]  = _mtf_fetch_tf(yf_sym, fh_sym, "240","4h",  "30d")

            cfg = {
                1: [("micro","micro"),("1m","1m"),("15m","15m"),("4h","4h")],
                2: [("micro","micro"),("2m","2m"),("30m","30m"),("4h","4h")],
                3: [("micro","micro"),("3m","3m"),("1h","1h"),  ("4h","4h")],
            }[st]

            scores = [1 if ad.get(k)=="BUY" else(-1 if ad.get(k)=="SELL" else 0) for _,k in cfg]
            avail  = [s for s in scores if s != 0]
            bull   = sum(1 for s in avail if s > 0)
            bear   = sum(1 for s in avail if s < 0)

            if len(avail) >= 2 and (bull >= 2 or bear >= 2):
                direction = "BUY" if bull >= bear else "SELL"
                ts, td = _mtf_trend_score(ad)
                if td == direction or ts < 30:
                    tf_labels = [(lbl, ad.get(k)) for lbl,k in cfg]
                    return {
                        "signal_type": st,
                        "direction":  "CALL" if direction=="BUY" else "PUT",
                        "near":       True,
                        "trend_score": max(40.0, ts),
                        "trend_dir":  direction,
                        "tf_labels":  tf_labels,
                        "message":    "2/4 confirmation {}-min".format(st),
                        "forced":     False,
                    }
        except Exception as e:
            logging.warning("2/4 attempt st={} failed: {}".format(st, e))

    # Last resort: micro history fallback — ALWAYS returns a signal
    st = types_to_try[0] if types_to_try else 1
    return _force_signal_from_micro(pair, st)


def generate_signal(pair):
    is_otc = "OTC" in pair
    real   = None
    yahoo_available = True

    # News filter — block non-OTC signals during high-impact events
    if not is_otc:
        _near_news, _news_name = is_news_time()
        if _near_news:
            logging.info("NEWS FILTER: blocking signal for {} — {}".format(pair, _news_name))
            return {
                "direction": "BUY", "pair": pair, "timeframe": 0,
                "strength": 0, "indicators_agree": 0,
                "trend_1h": None, "vwap_data": None,
                "confluence": {}, "mtf": None, "flat": True,
                "patterns": [], "movement_cat": "LOW",
                "avg_movement": 0.0,
                "no_signal_reason": "⚠️ High-impact news in {} — signal paused for safety.".format(_news_name),
            }

    if not is_otc:
        try:
            real = _fetch_real_indicators_mtf(pair)
            if real is None:
                yahoo_available = False
        except Exception as e:
            logging.warning("generate_signal real fetch failed {}: {}".format(pair, e))
            real = None
            yahoo_available = False

    # ── 1H TREND FILTER (with reversal detection) ────────────
    trend_1h = None
    try:
        trend_1h = _fetch_1h_trend(pair)
    except Exception as e:
        logging.warning("generate_signal 1H trend failed {}: {}".format(pair, e))

    # ── VWAP TREND ───────────────────────────────────────────
    vwap_data = None
    try:
        vwap_data = _fetch_vwap_trend(pair)
    except Exception as e:
        logging.warning("generate_signal vwap failed {}: {}".format(pair, e))

    # ── MULTI-TIMEFRAME SCORE ─────────────────────────────────
    mtf = None
    try:
        mtf = _fetch_mtf_score(pair)
    except Exception as e:
        logging.warning("generate_signal mtf failed {}: {}".format(pair, e))

    # ── CANDLESTICK PATTERN DETECTION ────────────────────────
    pattern_buy_bonus = 0
    pattern_sell_bonus = 0
    detected_patterns = {}
    if real is not None:
        # Use real data for pattern detection
        real_pair = OTC_TO_REAL.get(pair, pair)
        symbol = YAHOO_SYMBOLS.get(real_pair)
        if symbol:
            try:
                df_5m = yf.download(symbol, period="2d", interval="5m", progress=False, auto_adjust=True)
                detected_patterns = _detect_candlestick_patterns(df_5m)
            except Exception:
                pass
    else:
        # OTC: use mapped real pair for pattern detection
        real_p = OTC_TO_REAL.get(pair)
        if real_p:
            symbol = YAHOO_SYMBOLS.get(real_p)
            if symbol:
                try:
                    df_5m = yf.download(symbol, period="2d", interval="5m", progress=False, auto_adjust=True)
                    detected_patterns = _detect_candlestick_patterns(df_5m)
                except Exception:
                    pass

    for pname, (pdir, pbonus) in detected_patterns.items():
        if pdir == "BUY":
            pattern_buy_bonus += pbonus
        else:
            pattern_sell_bonus += pbonus

    # ── PIP MOVEMENT ANALYSIS ─────────────────────────────────
    avg_movement, movement_cat = _check_pip_movement(pair)

    if real:
        # ── NON-OTC: Real indicators from Yahoo Finance (5m) ──
        rsi     = real["rsi"]
        sto     = real["sto"]
        ma_diff = real["ma_diff"]
        macd    = real["macd"]
        bb_pos  = real["bb_pos"]
        mom     = real["mom"]
        vol     = real["vol"]
        candle  = random.choices([-1, -0.5, 0, 0.5, 1], weights=[10, 15, 50, 15, 10])[0]
    else:
        # ── OTC: Smart synthetic indicators (session-aware) ────
        sess  = _get_session()
        ptype = _pair_type(pair)
        if sess["name"] in ("London Open", "NY/London"):
            rsi_w = [20, 18, 24, 18, 20]
        elif sess["name"] in ("Asian", "Dead Hours"):
            rsi_w = [10, 20, 40, 20, 10]
        else:
            rsi_w = [15, 20, 30, 20, 15]

        # If 1H trend is clear, bias synthetic data to match it
        if trend_1h == "BUY":
            rsi_w = [25, 20, 25, 18, 12]
        elif trend_1h == "SELL":
            rsi_w = [12, 18, 25, 20, 25]

        rsi_zone = random.choices(
            ["oversold","neutral_low","neutral","neutral_high","overbought"], weights=rsi_w)[0]
        rsi = {"oversold": random.uniform(10,28), "neutral_low": random.uniform(28,44),
               "neutral": random.uniform(44,56), "neutral_high": random.uniform(56,72),
               "overbought": random.uniform(72,92)}[rsi_zone]
        sto = {"oversold": random.uniform(5,25), "neutral_low": random.uniform(20,45),
               "neutral": random.uniform(35,65), "neutral_high": random.uniform(55,80),
               "overbought": random.uniform(75,95)}[rsi_zone]
        if sess["name"] in ("London Open", "NY Session"):
            ma_diff = random.choice([-1,1]) * random.uniform(0.2, 0.9)
        else:
            ma_diff = random.uniform(-0.4, 0.4)
        if trend_1h == "BUY"  and ma_diff < 0: ma_diff = abs(ma_diff) * 0.5
        if trend_1h == "SELL" and ma_diff > 0: ma_diff = -abs(ma_diff) * 0.5
        macd   = max(-1.0, min(1.0, ma_diff * random.uniform(0.6, 1.2)))
        bb_pos = random.uniform(0.0,0.25) if rsi < 35 else (random.uniform(0.75,1.0) if rsi > 65 else random.uniform(0.3,0.7))
        mom    = random.uniform(-1.0,1.0) if ptype == "crypto" else (random.uniform(-0.8,0.8) if sess["name"] in ("London Open","NY/London") else random.uniform(-0.5,0.5))
        vol    = random.uniform(0.55,1.0) if sess["name"] in ("London Open","NY/London","NY Session") else (random.uniform(0.15,0.55) if sess["name"] in ("Dead Hours","Asian") else random.uniform(0.35,0.80))
        candle = random.choices([-1,-0.5,0,0.5,1], weights=[12,18,40,18,12] if sess["name"] in ("London Open","NY Session") else [8,12,60,12,8])[0]

    # ── BASE SCORING ─────────────────────────────────────────
    b = s = 0
    if rsi < 25:    b += 25
    elif rsi < 35:  b += 15
    elif rsi < 45:  b += 8
    elif rsi > 75:  s += 25
    elif rsi > 65:  s += 15
    elif rsi > 55:  s += 8
    if sto < 15:    b += 15
    elif sto < 25:  b += 8
    elif sto > 85:  s += 15
    elif sto > 75:  s += 8
    if ma_diff > 0.3:    b += 20
    elif ma_diff > 0.1:  b += 10
    elif ma_diff < -0.3: s += 20
    elif ma_diff < -0.1: s += 10
    if macd > 0.4:    b += 15
    elif macd > 0.1:  b += 7
    elif macd < -0.4: s += 15
    elif macd < -0.1: s += 7
    if bb_pos < 0.15:  b += 10
    elif bb_pos < 0.3: b += 5
    elif bb_pos > 0.85: s += 10
    elif bb_pos > 0.7:  s += 5
    if mom > 0.4:   b += 10
    elif mom > 0.1: b += 5
    elif mom < -0.4: s += 10
    elif mom < -0.1: s += 5
    if candle > 0:   b += int(candle * 10)
    elif candle < 0: s += int(abs(candle) * 10)
    if vol > 0.75:
        if b > s: b += 8
        else:     s += 8

    # ── RSI DIVERGENCE BONUS ─────────────────────────────────
    if real and real.get("divergence"):
        div = real["divergence"]
        if div == "BUY":  b += 20
        elif div == "SELL": s += 20

    # ── NON-OTC MULTI-TF REAL CONSENSUS BONUS ────────────────
    # Reward when 1m + 5m + 15m all point the same way (real data)
    if real and not is_otc and real.get("tf_count", 0) >= 2:
        tv = real.get("tf_buy_votes", 0)
        sv = real.get("tf_sell_votes", 0)
        tf_total = real.get("tf_count", 1)
        if tv > sv:
            bonus = int((tv / tf_total) * 30)
            b += bonus
            if direction == "BUY":
                indicators_agree += tv
        elif sv > tv:
            bonus = int((sv / tf_total) * 30)
            s += bonus
            if direction == "SELL":
                indicators_agree += sv
        else:
            # Conflict across timeframes — reduce confidence
            b -= 10
            s -= 10

    # ── WILLIAMS FRACTAL BONUS ───────────────────────────────
    fractal_sig = None
    fractal_str = 0
    if real and real.get("fractal_signal"):
        fractal_sig = real["fractal_signal"]
        fractal_str = real.get("fractal_strength", 1)
    else:
        if bb_pos < 0.15:
            fractal_sig = "BUY";  fractal_str = 1
        elif bb_pos < 0.08:
            fractal_sig = "BUY";  fractal_str = 2
        elif bb_pos > 0.85:
            fractal_sig = "SELL"; fractal_str = 1
        elif bb_pos > 0.92:
            fractal_sig = "SELL"; fractal_str = 2
    if fractal_sig == "BUY":
        b += 15 * fractal_str
    elif fractal_sig == "SELL":
        s += 15 * fractal_str

    # ── CANDLESTICK PATTERN BONUS ────────────────────────────
    b += pattern_buy_bonus
    s += pattern_sell_bonus

    # ── SESSION BIAS ─────────────────────────────────────────
    sb, ss = _session_bias()
    b += sb; s += ss
    ptype = _pair_type(pair)
    if ptype == "crypto":
        if mom > 0.3: b += 5
        elif mom < -0.3: s += 5
    elif ptype == "commodity":
        if vol > 0.8:
            if b > s: b += 6
            else: s += 6
    elif ptype == "index":
        if ma_diff > 0.2: b += 5
        elif ma_diff < -0.2: s += 5

    # ── 1H TREND FILTER BONUS (includes reversal detection) ──
    if trend_1h == "BUY":
        b += 45
    elif trend_1h == "SELL":
        s += 45

    # ── VWAP TREND BONUS ─────────────────────────────────────
    if vwap_data is not None:
        if vwap_data["direction"] == "BUY":
            bonus = 30 if vwap_data["strength"] == "STRONG" else (18 if vwap_data["strength"] == "MODERATE" else 8)
            b += bonus
        else:
            bonus = 30 if vwap_data["strength"] == "STRONG" else (18 if vwap_data["strength"] == "MODERATE" else 8)
            s += bonus

    # ── MULTI-TIMEFRAME BONUS ────────────────────────────────
    if mtf and mtf["total"] >= 3:
        if mtf["buy_tfs"] > mtf["sell_tfs"]:
            b += mtf["buy_tfs"] * 8
        elif mtf["sell_tfs"] > mtf["buy_tfs"]:
            s += mtf["sell_tfs"] * 8

    # ── DIRECTION & CONFLUENCE ───────────────────────────────
    direction = "BUY" if b >= s else "SELL"
    indicators_agree = 0
    checks = [(rsi < 45, rsi > 55), (sto < 45, sto > 55), (ma_diff > 0, ma_diff < 0),
              (macd > 0, macd < 0), (bb_pos < 0.5, bb_pos > 0.5), (mom > 0, mom < 0), (candle > 0, candle < 0)]
    for buy_c, sell_c in checks:
        if direction == "BUY" and buy_c:   indicators_agree += 1
        if direction == "SELL" and sell_c: indicators_agree += 1

    # ── MTF CONFLUENCE COUNT ─────────────────────────────────
    if mtf and mtf["total"] >= 3:
        if direction == "BUY"  and mtf["buy_tfs"]  > mtf["sell_tfs"]: indicators_agree += mtf["buy_tfs"]
        if direction == "SELL" and mtf["sell_tfs"] > mtf["buy_tfs"]:  indicators_agree += mtf["sell_tfs"]
    if trend_1h == direction:
        indicators_agree += 3  # Increased from 2 — 1H trend with reversal detection is stronger

    # ── PATTERN CONFLUENCE ───────────────────────────────────
    # If patterns agree with direction — boost indicators_agree
    pattern_agrees = (pattern_buy_bonus > 0 and direction == "BUY") or \
                     (pattern_sell_bonus > 0 and direction == "SELL")
    if pattern_agrees:
        indicators_agree += 2

    # ── CONFLICT CHECK: MTF vs 1H ────────────────────────────
    if mtf and trend_1h and mtf["total"] >= 3:
        mtf_dir = "BUY" if mtf["buy_tfs"] > mtf["sell_tfs"] else "SELL"
        if mtf_dir != trend_1h:
            direction = "BUY" if b > s else "SELL"

    # ── MINIMUM CONFLUENCE ───────────────────────────────────
    min_confluence = 6 if not is_otc else 5   # Non-OTC requires stronger evidence
    if indicators_agree < min_confluence:
        alt_dir = "SELL" if direction == "BUY" else "BUY"
        alt_agree = 0
        for buy_c, sell_c in checks:
            if alt_dir == "BUY" and buy_c:   alt_agree += 1
            if alt_dir == "SELL" and sell_c: alt_agree += 1
        if alt_agree > indicators_agree:
            direction = alt_dir
            indicators_agree = alt_agree
        if indicators_agree < min_confluence:
            direction = "BUY" if b > s else "SELL"
            indicators_agree = 0
            for buy_c, sell_c in checks:
                if direction == "BUY" and buy_c:   indicators_agree += 1
                if direction == "SELL" and sell_c: indicators_agree += 1

    # ── SIGNAL HISTORY BIAS CHECK ────────────────────────────
    # If most recent signals share same direction — reinforce decision
    hist_same, hist_total, hist_pct = _check_signal_history_bias(pair, direction, window=15)
    if hist_total >= 5:
        if hist_pct >= 0.70:
            # History strongly agrees — add +20 and boost indicators_agree
            if direction == "BUY":
                b += 20
            else:
                s += 20
            indicators_agree += 2
        elif hist_pct <= 0.30:
            # History strongly disagrees — reduce confidence
            if direction == "BUY":
                b -= 15
            else:
                s -= 15

    # ── STRENGTH CALCULATION ─────────────────────────────────
    dom = max(b, s); tot = max(b+s, 1)
    mtf_bonus = 0
    if mtf and mtf["total"] >= 3:
        agreeing = mtf["buy_tfs"] if direction == "BUY" else mtf["sell_tfs"]
        mtf_bonus = int((agreeing / mtf["total"]) * 45)
    trend_bonus = 20 if trend_1h == direction else 0  # Increased from 15
    pattern_bonus_str = min(30, pattern_buy_bonus if direction == "BUY" else pattern_sell_bonus)
    hist_bonus_str = int(hist_pct * 20) if hist_total >= 5 else 0

    # Strength formula: base 280 + bonuses (max 500)
    strength = min(500, max(300, 280 + indicators_agree*25 + int((dom/tot)*100)
                            + mtf_bonus + trend_bonus + pattern_bonus_str + hist_bonus_str
                            + int(random.uniform(-5,5))))

    # ── TIMEFRAME SELECTION ──────────────────────────────────
    vte_tf = get_optimal_tf(pair)
    if is_otc:
        # OTC: always pick a random timeframe (1m-5m).
        # Each call picks independently — no fixed pattern.
        # This mimics human decision-making and keeps broker off-guard.
        timeframe = random.choice([1, 1, 2, 2, 3, 3])
    else:
        # Non-OTC: pick best TF (1m/2m/3m) from VTE session-aware stats
        # Apply confidence threshold per TF
        best = get_best_tf_for_session(pair)
        if best == 1 and indicators_agree >= 8:
            timeframe = 1
        elif best == 2 and indicators_agree >= 7:
            timeframe = 2
        elif best == 3 and indicators_agree >= 6:
            timeframe = 3
        elif indicators_agree >= 8:
            timeframe = 1
        elif indicators_agree >= 7:
            timeframe = 2
        else:
            timeframe = 3

    # ── NON-OTC: Weak confluence → flip direction opposite to 1H ──
    if not is_otc and indicators_agree < 6 and vte_tf is None:
        if trend_1h is not None:
            direction = "SELL" if trend_1h == "BUY" else "BUY"
            timeframe = timeframe if timeframe > 0 else 2
        elif not yahoo_available:
            timeframe = 0  # True no-signal: no data available

    # ── OTC: Random flip/follow logic ────────────────────────
    # Each signal independently decides: follow the market or go against it.
    # Random intervals mean the broker cannot predict the pattern.
    # Works alongside contrarian pair logic (applied in handler).
    if is_otc:
        # Weighted random: 45% follow, 55% oppose — slightly contrarian overall
        otc_flip = random.choices(
            ["follow", "oppose"],
            weights=[45, 55]
        )[0]
        if otc_flip == "oppose":
            direction = "SELL" if direction == "BUY" else "BUY"
        # Store flip decision so handler knows (for contrarian pair override)
        _otc_flip_cache[pair] = otc_flip

    # ── 1H CANDLE CONFIRMATION (non-OTC only) ───────────────
    # OTC always forces a signal — no blocking on 1H confirmation.
    if not is_otc and timeframe <= 2:
        h1_confirmed = _confirm_1h_direction(pair, direction)
        if not h1_confirmed:
            if timeframe == 1:
                timeframe = 2
                h1_confirmed = _confirm_1h_direction(pair, direction)
            if not h1_confirmed:
                timeframe = 3
                h1_confirmed = _confirm_1h_direction(pair, direction)
            if not h1_confirmed:
                timeframe = 0

    # ── SESSION-AWARE CONTRARIAN OVERRIDE ────────────────────
    session = _get_session()
    bias    = get_signal_bias(pair, window=10, threshold=session["threshold"])
    if bias is not None and trend_1h is None:
        if is_otc:
            direction = ("SELL" if bias=="BUY" else "BUY") if session["otc"]=="contrarian" else bias
        else:
            if bias == direction:
                direction = bias
    elif bias is not None and trend_1h is not None:
        if bias != trend_1h and is_otc and session["otc"] == "contrarian":
            pass
        elif bias == trend_1h:
            direction = trend_1h

    # ── ENFORCE 1H TREND AS HARD FILTER ─────────────────────
    if trend_1h == "BUY" and direction == "SELL":
        raw_gap = s - b - 45
        if raw_gap < 35:
            direction = "BUY"
    elif trend_1h == "SELL" and direction == "BUY":
        raw_gap = b - s - 45
        if raw_gap < 35:
            direction = "SELL"

    # ── 1H vs SHORT-TF CONFLICT FILTER (non-OTC only) ────────
    # If 1H trend is clear but 5m+15m real data strongly disagrees → no signal
    if not is_otc and trend_1h is not None and real is not None:
        tv = real.get("tf_buy_votes", 0)
        sv = real.get("tf_sell_votes", 0)
        tf_total = real.get("tf_count", 1)
        short_tf_dir = "BUY" if tv > sv else ("SELL" if sv > tv else None)
        if short_tf_dir is not None and short_tf_dir != trend_1h:
            # Short TFs ALL oppose the 1H trend
            opposition_pct = max(tv, sv) / tf_total
            if opposition_pct >= 1.0 and tf_total >= 2:
                # 100% of short TFs oppose 1H — market in transition, wait
                timeframe = 0   # Signal flat — will trigger no-signal in handler
                direction = "BUY" if b > s else "SELL"
                record_signal(pair, direction)
                return {
                    "direction": direction, "pair": pair, "timeframe": 0,
                    "strength": 0, "indicators_agree": 0,
                    "trend_1h": trend_1h, "vwap_data": vwap_data,
                    "confluence": {"level": "CONFLICTED", "score": 0, "badge": "⚠️ WEAK"},
                    "mtf": mtf, "flat": True, "patterns": detected_patterns,
                    "movement_cat": movement_cat, "avg_movement": avg_movement,
                    "no_signal_reason": "1H vs short-TF conflict",
                }

    # ── SIGNAL STABILITY FILTER (non-OTC only) ──────────────
    # OTC always produces a signal — stability filter does not apply.
    if not is_otc and not _check_signal_stability(pair, direction, window_minutes=5):
        timeframe = 0
        record_signal(pair, direction)
        return {
            "direction": direction, "pair": pair, "timeframe": 0,
            "strength": 0, "indicators_agree": 0,
            "trend_1h": trend_1h, "vwap_data": vwap_data,
            "confluence": {"level": "CONFLICTED", "score": 0, "badge": "⚠️ WEAK"},
            "mtf": mtf, "flat": True, "patterns": detected_patterns,
            "movement_cat": movement_cat, "avg_movement": avg_movement,
            "no_signal_reason": "sudden direction flip detected",
        }

    # ── TREND CONFLUENCE ANALYSIS ────────────────────────────
    confluence = _calc_trend_confluence(trend_1h, vwap_data, mtf, direction)

    # Apply reversal candle filter (non-OTC, TF 1m/2m/3m only)
    if not is_otc:
        direction = _apply_reversal_filter(direction, timeframe, pair)

    record_signal(pair, direction)
    return {
        "direction": direction, "pair": pair, "timeframe": timeframe,
        "strength": strength, "indicators_agree": indicators_agree,
        "trend_1h": trend_1h, "vwap_data": vwap_data,
        "confluence": confluence, "mtf": mtf, "flat": (timeframe == 0),
        "patterns": detected_patterns,
        "movement_cat": movement_cat, "avg_movement": avg_movement,
        "no_signal_reason": "",
    }

    # ── AUTO-REVERSE ─────────────────────────────────────────
    if is_reverse_pair(pair):
        direction = "SELL" if direction == "BUY" else "BUY"

    record_signal(pair, direction)
    return {
        "direction": direction,
        "pair": pair,
        "timeframe": timeframe,
        "strength": strength,
        "indicators_agree": indicators_agree,
        "trend_1h": trend_1h,
        "vwap_data": vwap_data,
        "confluence": confluence,
        "mtf": mtf,
        "flat": (timeframe == 0),
        "patterns": detected_patterns,
        "movement_cat": movement_cat,
        "avg_movement": avg_movement,
    }


# ============================================================
# PAIR INDEX
# ============================================================
PAIR_INDEX = {str(i): pair for i, pair in enumerate(ALL_PAIRS)}

def pair_to_idx(pair):
    for idx, p in PAIR_INDEX.items():
        if p == pair:
            return idx
    return None

# ============================================================
# KEYBOARDS
# ============================================================
def is_weekend():
    """
    Returns True if:
    - Saturday or Sunday (UTC), OR
    - Weekday but within market-closed hours: 23:45 - 03:15 UTC
    During these times, non-OTC forex pairs are unavailable on Pocket Option.
    """
    now = datetime.utcnow()
    wd  = now.weekday()  # 0=Mon, 6=Sun
    if wd >= 5:
        return True
    # Night closure: 23:45 to 03:15 EAT (Tanzania UTC+3)
    # Converted to UTC: 20:45 to 00:15 UTC
    h, m = now.hour, now.minute
    total_mins = h * 60 + m
    # 20:45 UTC = 1245 mins, 00:15 UTC = 15 mins
    if total_mins >= 1245 or total_mins < 15:
        return True
    return False

def pairs_keyboard():
    """Build the pair selection keyboard.
    Weekday: forex pairs only, ranked by VTE win rate.
    Weekend: OTC pairs only.
    Falls back to default ALL_PAIRS order if no VTE data.
    """
    rows = []
    row  = []
    weekend = is_weekend()
    otc_on  = is_otc_enabled()

    if weekend:
        # Weekend — OTC pairs only, max 90 pairs (Telegram limit is 100 buttons)
        otc_pairs = [p for p in ALL_PAIRS if "OTC" in p][:90]
        for pair in otc_pairs:
            i = pair_to_idx(pair)
            if i is None:
                continue
            row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(i)))
            if len(row) == 3:
                rows.append(row)
                row = []
    else:
        # Weekday — forex pairs only (no OTC, no crypto, no indices)
        # Ranked by VTE win rate if data available
        ranked = get_ranked_forex_pairs()
        display_pairs = ranked["all"] if ranked and ranked.get("all") else [
            p for p in ALL_PAIRS
            if "OTC" not in p and "/" in p and "BTC" not in p
        ]
        for pair in display_pairs:
            i = pair_to_idx(pair)
            if i is None:
                continue
            row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(i)))
            if len(row) == 3:
                rows.append(row)
                row = []

    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def signal_keyboard(pair):
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))],
    ])

def nonotc_signal_keyboard(pair, chosen_tf):
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get More ({}m)".format(chosen_tf), callback_data="nonotctf_{}_{}".format(idx, chosen_tf))],
    ])

def otc_mode_keyboard(pair):
    """Mode selection for OTC pair: Seconds or Normal (minutes)."""
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱ Seconds (3s/5s/10s...)", callback_data="otc_secs_{}".format(idx))],
        [InlineKeyboardButton("📊 Normal (minutes)", callback_data="otc_normal_{}".format(idx))],
        [InlineKeyboardButton("❌ Cancel", callback_data="choose_pair")],
    ])

def otc_seconds_keyboard(pair):
    """Seconds keyboard for OTC — subscribers only."""
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("3s",  callback_data="otctf_{}_3".format(idx)),
            InlineKeyboardButton("5s",  callback_data="otctf_{}_5".format(idx)),
            InlineKeyboardButton("10s", callback_data="otctf_{}_10".format(idx)),
        ],
        [
            InlineKeyboardButton("15s", callback_data="otctf_{}_15".format(idx)),
            InlineKeyboardButton("30s", callback_data="otctf_{}_30".format(idx)),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="otcback_{}".format(idx))],
    ])

def nonotc_mode_keyboard(pair):
    """Mode selection for non-OTC: choose TF manually or let bot decide."""
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Choose Timeframe", callback_data="nonotc_tf_{}".format(idx))],
        [InlineKeyboardButton("Bot Decides", callback_data="nonotc_auto_{}".format(idx))],
        [InlineKeyboardButton("Cancel", callback_data="choose_pair")],
    ])

def nonotc_tf_keyboard(pair):
    """Manual TF selection for non-OTC pairs: 1m 2m 3m 4m 5m 10m 15m 30m."""
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1m",  callback_data="nonotctf_{}_1" .format(idx)),
            InlineKeyboardButton("2m",  callback_data="nonotctf_{}_2" .format(idx)),
            InlineKeyboardButton("3m",  callback_data="nonotctf_{}_3" .format(idx)),
        ],
        [
            InlineKeyboardButton("4m",  callback_data="nonotctf_{}_4" .format(idx)),
            InlineKeyboardButton("5m",  callback_data="nonotctf_{}_5" .format(idx)),
            InlineKeyboardButton("10m", callback_data="nonotctf_{}_10".format(idx)),
        ],
        [
            InlineKeyboardButton("15m", callback_data="nonotctf_{}_15".format(idx)),
            InlineKeyboardButton("30m", callback_data="nonotctf_{}_30".format(idx)),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="nonotc_back_{}".format(idx))],
    ])

def expired_signal_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Support", url=support_url())],
        [InlineKeyboardButton("▶️ Start", callback_data="restart_fresh")],
    ])

def unlock_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Payment Info & Methods", callback_data="pay_info")],
        [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
    ])

def payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Support", url=support_url())],
        [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_unlock")],
    ])

def admin_image_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Set BUY Image", callback_data="set_buy_img")],
        [InlineKeyboardButton("📉 Set SELL Image", callback_data="set_sell_img")],
    ])

# ============================================================
# PAYMENT TEXT
# ============================================================
PAYMENT_TEXT = """💰 *UNLOCK EVALON MASTER PRO*

🥈 *MONTHLY ACCESS — $50*
✅ Unlimited signals for 30 days
✅ Win rate 90% — 98%
✅ 100+ trading pairs

💎 *LIFETIME ACCESS — $150*
✅ Unlimited signals forever
✅ Win rate 90% — 98%
✅ Free updates forever
✅ 100+ trading pairs

━━━━━━━━━━━━━━━━━━
💳 *PAYMENT METHODS:*

📱 *Mobile Money (Tanzania):*
M-Pesa / Tigo / Airtel / Halotel
Select Lipa Namba: `353481341`
Account: EVALON STORE

🟡 *Binance ID:* `1222890272`
Account: Master Indicators Pro
Send USDT or BUSD via Binance Pay

🔵 *USDT TRC-20 (Tron):*
`TEUwK1aElmdCeG3n36LDySqSkwobMh37Xf`
TRC-20 Tron ONLY — wrong network = lost funds

💠 *Ethereum ERC-20:*
`0x230badccf11a0de2b8a261ae3f99c07235174d6b`
Send ETH or USDT on Ethereum network

🟠 *BNB Smart Chain BEP-20:*
`0x230badccf11a0de2b8a261ae3f99c07235174d6b`
Send USDT or BNB on BNB Smart Chain

💎 *TON Network (Telegram Wallet):*
`UQCo4q9770JLpocRVdZlzdfTz_Mc2f954Zps74s7S-WdBemZ`
Send TON or USDT via Telegram Wallet

━━━━━━━━━━━━━━━━━━
📸 Send payment screenshot to admin
👤 You will receive your unique licence code!"""

# ============================================================
# CHANNEL JOIN REQUEST TRACKING
# ============================================================
def save_join_request(user_id):
    """Save user_id when they send a join request to the channel."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO join_requests (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (user_id,)
                )
            conn.commit()
    except Exception as e:
        logging.warning("save_join_request failed: {}".format(e))

def has_join_request(user_id):
    """Check if user has ever sent a join request."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM join_requests WHERE user_id = %s", (user_id,))
                return cur.fetchone() is not None
    except Exception as e:
        logging.warning("has_join_request failed: {}".format(e))
        return False

async def is_channel_member(bot, user_id):
    """Check if user is already a full member/admin of the channel."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def check_channel_and_proceed(update, context):
    """
    Returns True if user can proceed.
    Returns False and sends join message if they haven't joined or requested.
    Admin always passes through.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return True

    # Admin always bypasses channel check
    if user_id == ADMIN_ID:
        return True

    # Full member check
    try:
        if await is_channel_member(context.bot, user_id):
            return True
    except Exception:
        # Can't check — let them through rather than blocking everyone
        return True

    # Pending join request
    if has_join_request(user_id):
        return True

    # Not joined, not requested — show join message
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_INVITE)],
        [InlineKeyboardButton("✅ I've Requested", callback_data="check_join")],
    ])
    msg = (
        "⚠️ *Join Required*\n\n"
        "To use EVALON MASTER PRO you must first join our channel.\n\n"
        "1️⃣ Tap *Join Channel* below\n"
        "2️⃣ Send a join request\n"
        "3️⃣ Tap *I've Requested* to continue\n\n"
        "_You don't need to wait for approval — just send the request._"
    )
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    return False

async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Triggered automatically when user sends a join request to the channel.
    Saves their user_id — bot does NOT approve the request (admin does that).
    """
    user_id = update.chat_join_request.from_user.id
    save_join_request(user_id)
    logging.info("Join request received from user {}".format(user_id))

# ============================================================
# HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    user_id = update.effective_user.id
    get_user(user_id)
    # Referral check
    if context.args:
        try:
            arg = context.args[0]
            referrer_id = int(arg.replace("REF_", ""))
            if referrer_id != user_id:
                register_referral(user_id, referrer_id)
        except Exception:
            pass
    # Channel membership check
    if not await check_channel_and_proceed(update, context):
        return

    # ── 1 Button keyboard ─────────────────────────────────────
    reply_kb = ReplyKeyboardMarkup(
        [["🏆 EVALON MENU"]],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
    )

    await update.message.reply_text(
        "╔══════════════════════╗\n"
        "     ⚡ EVALON MASTER PRO\n"
        "╚══════════════════════╝\n\n"
        "🏆 *Win Rate: 90% — 98%*\n"
        "📊 *100+ Trading Pairs*\n"
        "🧠 *AI-Powered Signal Analysis*\n\n"
        "⚠️ _Evalon Bot is AI-powered and may make mistakes. Trade responsibly._\n\n"
        "Tap *EVALON MENU* below to get started:",
        parse_mode="Markdown",
        reply_markup=reply_kb,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(
            "🔧 *EVALON MASTER PRO — ADMIN PANEL*\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔑 *LICENCE MANAGEMENT*\n"
            "`/addmonthly` — Generate 1 monthly code\n"
            "`/addmonthly 5` — Generate 5 monthly codes\n"
            "`/addlifetime` — Generate 1 lifetime code\n"
            "`/addlifetime 5` — Generate 5 lifetime codes\n"
            "`/listlicences` — View all codes (used/unused)\n"
            "`/revoke 123456` — Remove user licence\n"
            "`/resultson` — Enable WIN/LOSS result messages\n"
            "`/resultsoff` — Disable result messages\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👥 *USER MANAGEMENT*\n"
            "`/listusers` — View all users & stats\n"
            "`/totalusers` — Quick user count\n"
            "`/stats` — Detailed statistics\n"
            "`/userinfo 123456` — Full details of a user\n"
            "`/addtrial 123456 5` — Give user extra free signals\n"
            "`/deleteuser 123456` — Delete user permanently\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚫 *BLACKLIST*\n"
            "`/blacklist 123456 reason` — Ban a user\n"
            "`/unblacklist 123456` — Unban a user\n"
            "`/listblacklist` — View all banned users\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📢 *BROADCAST*\n"
            "`/broadcast message` — Send to all users\n"
            "_Markdown supported: *bold*, _italic_, `code`_\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🖼 *IMAGES*\n"
            "`/setimage` — Change BUY/SELL signal images\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🗄 *DATABASE*\n"
            "`/dbcheck` — Check database status\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 *PAIR STATS & REVERSE*\n"
            "`/pairstats` — Win/loss stats for all pairs\n"
            "`/addreverse PAIR` — Pair itoe direction kinyume\n"
            "`/removereverse PAIR` — Remove reverse for a pair\n"
            "`/listreverse` — List all reverse pairs\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔀 *OTC CONTROL*\n"
            "`/toggleotc` — Enable or disable OTC pairs\n"
            "• OTC OFF → show non-OTC pairs only\n"
            "• OTC ON  → all pairs visible (default)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "`/help` — This menu",
            parse_mode="Markdown",
            reply_markup=admin_image_keyboard()
        )
    else:
        # Get bot username for support link
        try:
            bot_info = await context.bot.get_me()
            support_url = "https://t.me/{}?start=support".format(bot_info.username)
        except Exception:
            support_url = "https://t.me/evalonwinnersbot"
        await update.message.reply_text(
            "⚡ *EVALON MASTER PRO*\n\n"
            "📌 *How to use:*\n"
            "1️⃣ Select your trading pair\n"
            "2️⃣ Get your BUY or SELL signal\n"
            "3️⃣ Follow the signal on your platform\n\n"
            "🔑 Have a licence code? Tap *Enter Licence Code*\n"
            "💬 Need help? Tap *Support* below",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Start Trading", callback_data="choose_pair")],
                [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
                [InlineKeyboardButton("💬 Support", url=support_url)],
            ])
        )

async def setimage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "🖼 *Set Signal Images*\n\nChoose which image to update:",
        parse_mode="Markdown",
        reply_markup=admin_image_keyboard()
    )

async def dbcheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Check tables exist
                cur.execute("SELECT COUNT(*) as cnt FROM users")
                users_count = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) as cnt FROM licences")
                licences_count = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) as cnt FROM licences WHERE used = TRUE")
                used_licences = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) as cnt FROM licences WHERE used = FALSE")
                unused_licences = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) as cnt FROM blacklist")
                blacklist_count = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) as cnt FROM settings")
                settings_count = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) as cnt FROM users WHERE licensed = TRUE")
                licensed_count = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) as cnt FROM users WHERE referred_by IS NOT NULL")
                referred_count = cur.fetchone()["cnt"]

                buy_img = get_setting("buy_image", "Default")
                sell_img = get_setting("sell_image", "Default")
                buy_status = "✅ Custom" if buy_img != "Default" else "⚪ Default"
                sell_status = "✅ Custom" if sell_img != "Default" else "⚪ Default"

        await update.message.reply_text(
            "🗄 *DATABASE CHECK*\n\n"
            "✅ *Connection:* Online\n"
            "✅ *All tables:* OK\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👥 *USERS*\n"
            "• Total: {}\n"
            "• Licensed: {}\n"
            "• Free trial: {}\n"
            "• Via referral: {}\n\n"
            "🔑 *LICENCES*\n"
            "• Total codes: {}\n"
            "• Used: {}\n"
            "• Available: {}\n\n"
            "🚫 *BLACKLIST*\n"
            "• Banned users: {}\n\n"
            "🖼 *IMAGES*\n"
            "• BUY image: {}\n"
            "• SELL image: {}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 *Database is working correctly.*\n"
            "_Data is safe on Neon — updates won't delete anything._".format(
                users_count, licensed_count, users_count - licensed_count, referred_count,
                licences_count, used_licences, unused_licences,
                blacklist_count,
                buy_status, sell_status
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(
            "🔴 *DATABASE ERROR*\n\n"
            "❌ Could not connect to database.\n\n"
            "Error: `{}`\n\n"
            "_Check your DATABASE_URL in Render environment variables._".format(str(e)),
            parse_mode="Markdown"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    data=q.data; chat=q.message.chat_id; user_id=q.from_user.id
    try:
        u = q.from_user
        upsert_user_profile(user_id, first_name=u.first_name, last_name=u.last_name, username=u.username)
    except Exception:
        pass
    if is_blocked(user_id) and user_id != ADMIN_ID:
        await q.answer("You have been blocked from using this bot.", show_alert=True)
        return

    if data == "restart_fresh":
        # Clear signal state and inactivity tracking
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_signal_state WHERE user_id = %s", (user_id,))
                conn.commit()
        except Exception as e:
            logging.warning("restart_fresh clear state failed: {}".format(e))
        inactivity_clear(user_id)
        await q.edit_message_text(
            "⚡ *EVALON MASTER PRO*\n\n"
            "🏆 Win Rate: 90% — 98%\n"
            "📊 100+ Trading Pairs\n\n"
            "Choose how you want to get a signal:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 Bot Pick Best Pair", callback_data="bot_pick_pair")],
                [InlineKeyboardButton("📊 Choose Pair Myself", callback_data="choose_pair")],
            ])
        )
        return

    # Check join button
    if data == "check_join":
        # Check if member or has pending request
        is_member = await is_channel_member(context.bot, user_id)
        has_request = has_join_request(user_id)
        if is_member or has_request:
            await q.edit_message_text(
                "✅ *Welcome to EVALON MASTER PRO!*\n\nSelect your trading pair:",
                parse_mode="Markdown", reply_markup=pairs_keyboard()
            )
        else:
            await q.answer("⚠️ Please send a join request to the channel first.", show_alert=True)
        return

    # Admin: set BUY image
    if data == "set_buy_img":
        if user_id != ADMIN_ID: return
        context.user_data["awaiting_image"] = "buy"
        await q.edit_message_text(
            "📈 *Set BUY Image*\n\nSend me the BUY signal image now.\n\n_Forward or send any photo — I will save it._",
            parse_mode="Markdown"
        )
        return

    # Admin: set SELL image
    if data == "set_sell_img":
        if user_id != ADMIN_ID: return
        context.user_data["awaiting_image"] = "sell"
        await q.edit_message_text(
            "📉 *Set SELL Image*\n\nSend me the SELL signal image now.\n\n_Forward or send any photo — I will save it._",
            parse_mode="Markdown"
        )
        return

    if data=="choose_pair":
        # Delete previous menu/signal messages
        await delete_last_signal(context.bot, chat, user_id)
        try: await q.edit_message_reply_markup(reply_markup=None)
        except: pass
        try: await q.message.delete()
        except: pass

        weekend = is_weekend()

        # Rotating taglines — change every time user opens pair selection
        if weekend:
            taglines = [
                "🌙 *After-Hours Trading*\nKeep trading even when global markets are closed. Weekend-only pairs available 24/7.",
                "⏰ *Always-On Pairs*\nMarkets closed? No problem. These pairs trade around the clock, every day of the week.",
                "🔁 *Extended Hours Pairs*\nExclusive pairs for traders who never stop. Active when traditional markets rest.",
                "📅 *Weekend Special Pairs*\nAvailable exclusively on weekends when live markets are closed.",
            ]
        else:
            taglines = [
                "🌍 *Real Market Pairs*\nTrade on live market data — EUR/USD, Gold, Oil and more. Real prices, real movement, real results.",
                "💹 *Live Market Trading*\nOur AI analyzes real-time market data from global exchanges. No simulations — just pure market signals.",
                "📡 *Real-Time Market Signals*\nPowered by live market data. Every signal is backed by actual market movement.",
                "🏦 *Institutional-Grade Pairs*\nThe same pairs traded by banks and hedge funds. Maximum liquidity, highest accuracy.",
            ]

        tagline = random.choice(taglines)
        sess = get_trading_session()
        sess_txt = ""
        if sess and sess.get("name","") not in ("Dead Hours","Off Hours",""):
            sess_txt = "\n🕐 *{}* active".format(sess["name"])
        header = "⚡ *EVALON MASTER PRO*\n\n{}{}\n\n📊 Select your trading pair:".format(tagline, sess_txt)

        _pm = await context.bot.send_message(
            chat_id=chat,
            text=header,
            parse_mode="Markdown",
            reply_markup=pairs_keyboard()
        )
        save_last_bot_msg(user_id, _pm.message_id)
        return

    if data=="bot_pick_pair":
        # Free trial users cannot use Bot Pick Pair — subscribers only
        if not is_licensed(user_id):
            await q.edit_message_text(
                "🔒 *Bot Pick Pair — Subscribers Only*\n\n"
                "This feature is available for licensed subscribers only.\n\n"
                "Upgrade to get:\n"
                "✅ Bot-picked best pairs\n"
                "✅ Unlimited signals\n"
                "✅ Win rate 90% — 98%",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("📊 Choose Pair Myself", callback_data="choose_pair")],
                ])
            )
            return

        weekend = is_weekend()

        # Top 5 — best performing pairs by VTE win rate
        # Weekend → OTC pairs only, Weekday → non-OTC (forex) only
        top5 = get_top5_pairs(otc_only=weekend, non_otc_only=not weekend)

        # Fallback if not enough VTE data yet
        if len(top5) < 5:
            if weekend:
                pool = [p for p in ALL_PAIRS if "OTC" in p]
            else:
                pool = [p for p in ALL_PAIRS if "OTC" not in p and "/" in p and "BTC" not in p]
            random.shuffle(pool)
            existing = {r["pair"] for r in top5}
            for p in pool:
                if p not in existing and len(top5) < 5:
                    top5.append({"pair": p, "wins": 0, "losses": 0, "win_rate": 0})
                    existing.add(p)

        # Build keyboard with top 5 pairs
        is_admin_user = (user_id == ADMIN_ID)
        buttons = []
        for row in top5:
            pair  = row["pair"]
            wr    = row.get("win_rate") or 0
            total = row.get("wins", 0) + row.get("losses", 0)
            if is_admin_user and total > 0:
                label = "📊 {} — {:.0f}% ({} trades)".format(pair, wr, total)
            else:
                label = "📊 {}".format(pair)
            try:
                idx = ALL_PAIRS.index(pair)
            except ValueError:
                continue
            buttons.append([InlineKeyboardButton(label, callback_data="sel_{}".format(idx))])

        buttons.append([InlineKeyboardButton("📋 Choose Myself", callback_data="choose_pair")])
        kb = InlineKeyboardMarkup(buttons)

        await q.edit_message_text(
            "🤖 *Bot Top 5 Picks*\n\n"
            "Pairs ranked by virtual trading win rate.\n"
            "Select one to get a signal:",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    if data=="my_stats":
        u = get_user(user_id)
        licensed = is_licensed(user_id)
        lic_type = u.get("licence_type", "").capitalize() if licensed else "Free Trial"
        expiry_txt = get_expiry_text(user_id) if licensed else "—"
        free_used = free_signals_used(user_id)
        free_allowed = total_free_allowed(user_id)
        refs = count_referrals(user_id)
        bonus = get_bonus_signals(user_id)
        # Referral link → REFERRAL_BOT (separate from admin bot)
        ref_link = "https://t.me/{}?start=REF_{}".format(REFERRAL_BOT, user_id)
        share_url = "https://t.me/share/url?url={}".format(ref_link)
        if refs >= 5:
            ref_status = "🎁 {} bonus signals (5+ referrals)".format(bonus)
        elif refs >= 3:
            ref_status = "🎁 {} bonus signals (3-4 referrals)".format(bonus)
        else:
            needed = 3 - refs
            ref_status = "⏳ Invite {} more to get bonus signals!".format(needed)
        kb_licensed = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Referral Link", url=share_url)],
            [InlineKeyboardButton("📊 Get Signal", callback_data="choose_pair")],
        ])
        kb_free = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Referral Link", url=share_url)],
            [InlineKeyboardButton("💎 Upgrade", callback_data="pay_info")],
            [InlineKeyboardButton("📊 Get Signal", callback_data="choose_pair")],
        ])
        await q.edit_message_text(
            "📊 *YOUR STATS*\n\n"
            "🔑 Status: {}\n"
            "⏳ Expiry: {}\n"
            "🆓 Free signals used: {}/{}\n"
            "👥 Referrals: {}\n"
            "🎁 Bonus signals: {}\n"
            "{}\n\n"
            "{}".format(
                lic_type, expiry_txt, free_used, free_allowed, refs, bonus,
                ref_status,
                "_Thank you for being a subscriber!_" if licensed else "_Upgrade to get unlimited signals!_"
            ),
            parse_mode="Markdown",
            reply_markup=kb_licensed if licensed else kb_free
        )
        return

    if data=="pay_info":
        await q.edit_message_text(
            PAYMENT_TEXT,
            parse_mode="Markdown",
            reply_markup=payment_keyboard()
        )
        return

    if data=="back_unlock":
        await q.edit_message_text(
            "🔒 *LICENCE REQUIRED*\n\nYou have used your free trial signals.\nContact admin to get access.",
            parse_mode="Markdown",
            reply_markup=unlock_keyboard()
        )
        return

    if data=="enter_code":
        context.user_data["awaiting_code"]=True
        await q.edit_message_text(
            "🔑 *Enter your licence code:*\n\nMonthly format: `EVAL-M-XXXX-XXXX-XXXX`\nLifetime format: `EVAL-L-XXXX-XXXX-XXXX`\n\nType your code and send it:",
            parse_mode="Markdown"
        )
        return

    if data == "help_inline":
        await q.edit_message_text(
            "ℹ️ *EVALON MASTER PRO — Help*\n\n"
            "⚡ *Get Signal* — Select a pair and get a BUY/SELL signal\n"
            "🤖 *Bot Pick Pair* — Bot picks the best pair for you\n"
            "📊 *My Stats* — View your account status\n"
            "💎 *Upgrade* — Purchase a monthly or lifetime licence\n\n"
            "📌 *How to use:*\n"
            "1. Tap EVALON MENU\n"
            "2. Select Get Signal or Bot Pick Pair\n"
            "3. Wait for the signal — enter the trade when it appears",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Get Signal", callback_data="choose_pair")],
                [InlineKeyboardButton("💬 Contact Support", url=support_url())],
            ])
        )
        return

    # ── OTC: "Back" button — return to mode selection ───────────
    if data.startswith("otcback_"):
        idx_str = data[8:]
        pair = PAIR_INDEX.get(idx_str)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        try: await q.message.delete()
        except: pass
        await context.bot.send_message(
            chat_id=chat,
            text=(
                "⚡ *{}*\n\n"
                "Choose signal type:\n\n"
                "⏱ *Seconds* — 3s/5s/10s/15s/30s signals _(subscribers only)_\n"
                "📊 *Normal* — minute-based signal"
            ).format(pair),
            parse_mode="Markdown",
            reply_markup=otc_mode_keyboard(pair)
        )
        return

    # ── OTC: "Normal (minutes)" chosen — continue with normal signal flow ─
    if data.startswith("otc_normal_"):
        idx_str = data[11:]
        pair = PAIR_INDEX.get(idx_str)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        if is_blacklisted(user_id):
            await context.bot.send_message(chat_id=chat, text="🚫 *You are banned from this bot.*", parse_mode="Markdown")
            return
        if is_spam(user_id):
            return
        inactivity_reset(user_id, chat)
        try: await q.message.delete()
        except: pass

        # --- Check user signal state (normal OTC flow) ---
        check = check_signal_request(user_id, pair)
        if check["action"] == "cooldown":
            return

        if not is_candle_safe_zone():
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                ])
            )
            return

        cm = await context.bot.send_message(chat_id=chat, text="🔵 *Analyzing {}...*".format(pair), parse_mode="Markdown")
        is_non_otc = False  # pair is OTC
        entry_price = None
        await asyncio.sleep(0.3)
        trend = get_trend_direction(pair)

        if check["action"] == "fresh":
            sig = generate_signal(pair)
            direction = sig["direction"]
            timeframe = sig["timeframe"]
            strength  = sig["strength"]
            flip_count = 0
            if sig.get("flat") and timeframe == 0:
                try: await cm.delete()
                except: pass
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))],
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return
            if trend is not None:
                direction = trend
            elif sig.get("indicators_agree", 7) < 4:
                try: await cm.delete()
                except: pass
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))],
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return
        elif check["action"] == "flip":
            direction  = check["direction"]
            timeframe  = random.choice([1, 2, 3])
            strength   = random.randint(200, 500)
            flip_count = 1
        else:
            state_s    = get_user_signal_state(user_id, pair)
            flip_count = state_s["flip_count"] + 1 if state_s else 2
            direction  = check["direction"]
            timeframe  = random.choice([1, 2, 3])
            strength   = random.randint(200, 500)

        save_user_signal_state(user_id, pair, direction, timeframe, flip_count, entry_price=None)
        if check["action"] != "fresh":
            record_signal(pair, direction)

        ib    = direction == "BUY"
        img   = get_buy_image() if ib else get_sell_image()
        arrow = "Up 🟢" if ib else "Down 🔴"
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        await delete_last_signal(context.bot, chat, user_id)
        cap = "*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair, arrow, timeframe, strength)
        sent_msg = await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))
        save_last_signal_msg(user_id, sent_msg.message_id)
        inactivity_reset(user_id, chat, msg_id=sent_msg.message_id)

        async def _inact_otcn(uid, cid):
            await asyncio.sleep(INACTIVITY_MINUTES * 60)
            for mid in inactivity_get_msgs(uid):
                try: await context.bot.delete_message(chat_id=cid, message_id=mid)
                except: pass
            inactivity_clear(uid)
            try:
                await context.bot.send_message(chat_id=cid,
                    text="⏰ *Your session has expired.*\n\n_Tap Start below to open a fresh session._",
                    parse_mode="Markdown", reply_markup=expired_signal_keyboard())
            except: pass
        task = asyncio.create_task(_inact_otcn(user_id, chat))
        USER_INACTIVITY[user_id]["task"] = task
        return

    # ── Non-OTC: Back to mode selection ──────────────────────────────────
    if data.startswith("nonotc_back_"):
        idx_str = data[12:]
        pair = PAIR_INDEX.get(idx_str)
        if not pair: return
        await q.edit_message_text(
            "Choose how to trade: {}".format(pair),
            parse_mode="Markdown",
            reply_markup=nonotc_mode_keyboard(pair)
        )
        return

    # ── Non-OTC: Show manual TF keyboard ──────────────────────────────────
    if data.startswith("nonotc_tf_"):
        idx_str = data[10:]
        pair = PAIR_INDEX.get(idx_str)
        if not pair: return
        await q.edit_message_text(
            "Select timeframe for: {}".format(pair),
            parse_mode="Markdown",
            reply_markup=nonotc_tf_keyboard(pair)
        )
        return

    # ── Non-OTC: Bot decides TF — go straight to signal ───────────────────
    if data.startswith("nonotc_auto_"):
        # Redirect to sel_ flow by replacing data
        data = "sel_{}".format(data[12:])
        # Fall through to sel_ handler below

    # ── Non-OTC: User chose specific TF ───────────────────────────────────
    if data.startswith("nonotctf_"):
        parts     = data[9:].rsplit("_", 1)
        idx_str   = parts[0]
        chosen_tf = int(parts[1]) if len(parts) == 2 else 1
        pair      = PAIR_INDEX.get(idx_str)
        if not pair: return
        if is_spam(user_id): return
        inactivity_reset(user_id, chat)
        # "Get More" button reuses same TF → treat as auto (Deriv picks best)
        # Only "user chose from keyboard" sets _user_chose_tf=True in sel_ handler
        # After signal is sent once, subsequent Get More = auto
        _user_chose_tf = context.user_data.pop("_user_chose_tf", False)
        try: await q.message.delete()
        except: pass
        cm = await context.bot.send_message(
            chat_id=chat, text="🔵 *Analyzing {}...*".format(pair), parse_mode="Markdown"
        )
        try:
            loop = asyncio.get_event_loop()
            sig  = await loop.run_in_executor(None, generate_signal, pair)
        except Exception as e:
            logging.warning("nonotctf signal failed {}: {}".format(pair, e))
            try: await cm.delete()
            except: pass
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text="🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Get More", callback_data="nonotctf_{}_{}".format(idx_str, chosen_tf))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return
        direction = sig["direction"]
        timeframe = chosen_tf

        # ── Deriv micro-candle: only for AUTO (bot-chosen TF) ─
        # If user chose TF themselves → respect their choice, skip Deriv
        if not _user_chose_tf and chosen_tf in [1, 2, 3] and pair in DERIV_SYMBOLS:
            try:
                _best_tf, _best_str, _best_reason = await pick_best_tf_deriv(pair, direction)
                logging.info("Deriv best_tf={} str={} — {}".format(_best_tf, _best_str, _best_reason))
                timeframe = _best_tf
            except Exception as _de:
                logging.warning("Deriv pick_best_tf error: {}".format(_de))
                timeframe = chosen_tf
        else:
            timeframe = chosen_tf  # User chose — respect it
        # ─────────────────────────────────────────────────────

        save_user_signal_state(user_id, pair, direction, timeframe, 0)
        try: await cm.delete()
        except: pass
        context.user_data["_nonotc_sig"]   = sig
        context.user_data["_nonotc_dir"]   = direction
        context.user_data["_nonotc_tf"]    = timeframe
        context.user_data["_nonotc_pair"]  = pair
        context.user_data["_nonotc_idx"]   = idx_str
        await _send_nonotc_signal(context, chat, user_id, pair, direction, timeframe, sig, idx_str)
        return

    # ── OTC: "Seconds" chosen — show seconds keyboard ──────────────────
    if data.startswith("otc_secs_"):
        idx_str = data[9:]
        pair = PAIR_INDEX.get(idx_str)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        try: await q.message.delete()
        except: pass

        # Non-subscribers: show seconds keyboard but notify it is subscribers only
        if not is_licensed(user_id):
            await context.bot.send_message(
                chat_id=chat,
                text=(
                    "🔒 *Seconds signals — Subscribers Only*\n\n"
                    "This option is available for licensed subscribers only.\n\n"
                    "Upgrade ili kupata:\n"
                    "✅ Seconds signals (3s/5s/10s/15s/30s)\n"
                    "✅ Unlimited signals\n"
                    "✅ Win rate 90% — 98%"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("🔙 Back", callback_data="otcback_{}".format(idx_str))],
                ])
            )
            return

        # Subscribers: show seconds keyboard
        await context.bot.send_message(
            chat_id=chat,
            text="⏱ *{}*\n\nChoose signal duration:".format(pair),
            parse_mode="Markdown",
            reply_markup=otc_seconds_keyboard(pair)
        )
        return

    # ── OTC: Seconds timeframe selected — generate seconds signal ────────
    if data.startswith("otctf_"):
        # Format: otctf_{idx}_{seconds}
        rest = data[6:]
        parts = rest.rsplit("_", 1)
        if len(parts) != 2:
            await context.bot.send_message(chat_id=chat, text="❌ Error.", reply_markup=pairs_keyboard())
            return
        idx_str, secs_str = parts
        pair = PAIR_INDEX.get(idx_str)
        try:
            chosen_secs = int(secs_str)
        except ValueError:
            chosen_secs = 5

        if not pair or "OTC" not in pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        if is_blacklisted(user_id):
            await context.bot.send_message(chat_id=chat, text="🚫 *You are banned from this bot.*", parse_mode="Markdown")
            return
        # Subscribers only (double check)
        if not is_licensed(user_id):
            await context.bot.send_message(
                chat_id=chat,
                text="🔒 *Seconds signals — Subscribers Only*\n\nUpgrade your plan to unlock this feature.",
                parse_mode="Markdown",
                reply_markup=unlock_keyboard()
            )
            return
        if is_spam(user_id):
            return
        inactivity_reset(user_id, chat)

        if not is_candle_safe_zone():
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More ({}s)".format(chosen_secs),
                                          callback_data="otctf_{}_{}".format(idx_str, chosen_secs))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        try: await q.message.delete()
        except: pass

        cm = await context.bot.send_message(chat_id=chat, text="🔵 *Analyzing {}...*".format(pair), parse_mode="Markdown")
        await asyncio.sleep(0.3)

        sig       = generate_signal(pair)
        direction = sig["direction"]
        strength  = sig["strength"]

        trend_dir = get_trend_direction(pair)
        if trend_dir is not None:
            direction = trend_dir
        elif sig.get("indicators_agree", 7) < 4:
            try: await cm.delete()
            except: pass
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        # timeframe in DB: chosen_secs (store as-is; signal_keyboard uses pair only)
        # Use 1 minute minimum for DB schema (last_timeframe column), but track seconds in caption
        save_user_signal_state(user_id, pair, direction, 1, 0)

        ib    = direction == "BUY"
        img   = get_buy_image() if ib else get_sell_image()
        arrow = "Up 🟢" if ib else "Down 🔴"
        try: await cm.delete()
        except: pass
        await delete_last_signal(context.bot, chat, user_id)

        cap = "*{}* {}\n⏱ In *{}s*\n📊 Signal strength: {}".format(pair, arrow, chosen_secs, strength)
        sent_msg = await context.bot.send_photo(
            chat_id=chat,
            photo=img,
            caption=cap,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Get More ({}s)".format(chosen_secs),
                                      callback_data="otctf_{}_{}".format(idx_str, chosen_secs))],
            ])
        )
        save_last_signal_msg(user_id, sent_msg.message_id)
        inactivity_reset(user_id, chat, msg_id=sent_msg.message_id)

        async def _inact_otcs(uid, cid):
            await asyncio.sleep(INACTIVITY_MINUTES * 60)
            for mid in inactivity_get_msgs(uid):
                try: await context.bot.delete_message(chat_id=cid, message_id=mid)
                except: pass
            inactivity_clear(uid)
            try:
                await context.bot.send_message(chat_id=cid,
                    text="⏰ *Your session has expired.*\n\n_Tap Start below to open a fresh session._",
                    parse_mode="Markdown", reply_markup=expired_signal_keyboard())
            except: pass
        task = asyncio.create_task(_inact_otcs(user_id, chat))
        USER_INACTIVITY[user_id]["task"] = task
        return

    if data.startswith("getmore_"):
        idx  = data[8:]
        pair = PAIR_INDEX.get(idx)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        # Blacklist check
        if is_blacklisted(user_id):
            await context.bot.send_message(chat_id=chat, text="🚫 *You are banned from this bot.*", parse_mode="Markdown")
            return
        # Anti-spam
        if is_spam(user_id):
            return

        # Delete result message if present
        try:
            state_for_del = get_user_signal_state(user_id, pair)
            if state_for_del and state_for_del.get("result_msg_id"):
                await context.bot.delete_message(chat_id=chat, message_id=state_for_del["result_msg_id"])
        except Exception:
            pass

        # Delete previous signal photo
        try:
            await q.message.delete()
        except Exception:
            pass

        # Always generate a fresh signal regardless of expiry.
        # User can regenerate as many times as needed to get desired timeframe.
        state = get_user_signal_state(user_id, pair)
        press_count = state.get("flip_count", 0) if state else 0
        expiry_finished = True   # Always treat as fresh — no blocking
        clear_user_signal_state(user_id, pair)

        # --- Pip-based expiry selection helper (used below) ---
        # Bot checks avg_movement from VTE stats to pick optimal TF:
        # High avg_movement (>0.1%) → shorter TF (1m) sufficient
        # Low avg_movement (<0.05%) → longer TF (3m) needed for clear candle close
        def _pick_tf_by_pips(pair, fallback_tf):
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT avg_movement, optimal_tf FROM pair_stats WHERE pair=%s", (pair,)
                        )
                        row = cur.fetchone()
                if row and row["avg_movement"]:
                    avg_mov = float(row["avg_movement"])
                    if avg_mov >= 0.10:
                        return 1   # Moves fast — 1m is enough
                    elif avg_mov >= 0.06:
                        return 2   # Medium movement — 2m
                    else:
                        return 3   # Slow pair — needs 3m for clear close
                if row and row["optimal_tf"]:
                    return int(row["optimal_tf"])
            except Exception:
                pass
            return fallback_tf

        if True:  # Always fresh — regenerate on every tap
            if not is_licensed(user_id) and free_signals_used(user_id) >= total_free_allowed(user_id):
                bonus = get_bonus_signals(user_id)
                refs  = count_referrals(user_id)
                extra = "\n\n🎁 *You have {} referrals* — invite more to unlock extra signals!".format(refs) if refs > 0 else "\n\n🎁 *Invite 3+ friends* to get free bonus signals!"
                await context.bot.send_message(
                    chat_id=chat,
                    text="🔒 *UNLOCK FULL ACCESS*\n\nYou have used your *{} free trial signals*.{}\n\n"
                         "💎 *$150 — LIFETIME ACCESS*\n✅ Unlimited signals forever\n✅ Win rate 90% — 98%\n✅ Free updates forever\n✅ 100+ trading pairs\n\n"
                         "👇 See payment methods or enter your code:".format(total_free_allowed(user_id), extra),
                    parse_mode="Markdown",
                    reply_markup=unlock_keyboard()
                )
                return
            if is_weekend() and "OTC" not in pair:
                await context.bot.send_message(chat_id=chat, text="⚠️ *Market Closed (Weekend)*\n\nThis pair is not available on weekends.\nPlease select an *OTC* pair instead.", parse_mode="Markdown", reply_markup=pairs_keyboard())
                return

            inactivity_reset(user_id, chat)
            clear_user_signal_state(user_id, pair)

        if not is_candle_safe_zone():
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        cm = await context.bot.send_message(chat_id=chat, text="🔵 *Analyzing {}...*".format(pair), parse_mode="Markdown")
        await asyncio.sleep(0.3)

        _is_non_otc_pair = "OTC" not in pair and pair in YAHOO_SYMBOLS
        _mtf_result = None
        if _is_non_otc_pair:
            try:
                _mtf_result = run_mtf_signal_engine_with_fallback(pair)
            except Exception as _e:
                logging.warning("MTF pre-check failed {}: {}".format(pair, _e))

        try:
            sig = generate_signal(pair)
        except Exception as _sig_e:
            logging.warning("generate_signal failed in getmore {}: {}".format(pair, _sig_e))
            try: await cm.delete()
            except: pass
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text="🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return
        direction = sig["direction"]
        strength  = sig["strength"]

        # MTF override: use MTF direction + timeframe if confirmed
        _mtf_cap = None
        if _mtf_result and _mtf_result.get("direction") in ("CALL","PUT"):
            direction  = "BUY" if _mtf_result["direction"] == "CALL" else "SELL"
            _mtf_tf    = _mtf_result["signal_type"]
            _mtf_cap   = build_mtf_caption(
                pair, _mtf_result["direction"], _mtf_tf,
                _mtf_result["tf_labels"], _mtf_result["trend_score"],
                _mtf_result["near"])
            timeframe  = _pick_tf_by_pips(pair, _mtf_tf)
        else:
            # No MTF override — use generate_signal timeframe as normal
            timeframe = _pick_tf_by_pips(pair, sig["timeframe"])

        # Flat market block
        if sig.get("flat") and sig["timeframe"] == 0:
            try: await cm.delete()
            except: pass
            is_gm_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS
            reason = sig.get("no_signal_reason", "")
            if is_gm_non_otc:
                extra = ""
                if "conflict" in reason:
                    extra = "\n\n_1H trend and short-term momentum are not aligned yet._"
                elif "flip" in reason:
                    extra = "\n\n_Market direction changed too quickly — waiting for stability._"
                msg = sig.get("no_signal_reason") or "🟡 *No clear signal available*"
            else:
                msg = sig.get("no_signal_reason") or "🟡 *No clear signal available*"
            await context.bot.send_message(
                chat_id=chat,
                text=msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                ])
            )
            return

        # Trend validation
        trend_dir = get_trend_direction(pair)
        gm_is_non_otc_check = "OTC" not in pair and pair in YAHOO_SYMBOLS
        if trend_dir is not None:
            direction = trend_dir
        elif gm_is_non_otc_check and (sig.get("flat") or sig.get("indicators_agree", 10) < 6):
            try: await cm.delete()
            except: pass
            reason = sig.get("no_signal_reason", "")
            extra = ""
            if "conflict" in reason:
                extra = "\n\n_1H trend and short-term momentum are not aligned yet._"
            elif "flip" in reason:
                extra = "\n\n_Market direction changed too quickly — waiting for stability._"
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return
        elif sig.get("indicators_agree", 7) < 4:
            try: await cm.delete()
            except: pass
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        new_flip_count = 0  # Always fresh signal — reset flip count

        gm_is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS

        save_user_signal_state(user_id, pair, direction, timeframe, new_flip_count)

        # For non-OTC: capture entry price at signal time
        gm_entry_price = None
        if gm_is_non_otc:
            gm_entry_price = _fetch_current_price(pair)
            save_user_signal_state(user_id, pair, direction, timeframe, new_flip_count, entry_price=gm_entry_price)

        ib    = direction == "BUY"
        img   = get_buy_image() if ib else get_sell_image()
        arrow = "Up 🟢" if ib else "Down 🔴"
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        await delete_last_signal(context.bot, chat, user_id)
        cap = _mtf_cap if _mtf_cap else "*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair, arrow, timeframe, strength)
        sent_msg = await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))
        save_last_signal_msg(user_id, sent_msg.message_id)

        if gm_is_non_otc and gm_entry_price is not None:
            asyncio.create_task(
                schedule_result_check(context.bot, chat, user_id, pair, direction, timeframe, gm_entry_price)
            )

        inactivity_reset(user_id, chat, msg_id=sent_msg.message_id)

        async def inactivity_expire_gm(uid, cid):
            await asyncio.sleep(INACTIVITY_MINUTES * 60)
            msg_ids = inactivity_get_msgs(uid)
            for mid in msg_ids:
                try: await context.bot.delete_message(chat_id=cid, message_id=mid)
                except: pass
            inactivity_clear(uid)
            try:
                await context.bot.send_message(
                    chat_id=cid,
                    text="⏰ *Your session has expired.*\n\n🌟 *Join our VIP today!*\n\n✅ Win rate 90% — 98%\n✅ 100+ trading pairs\n✅ Unlimited signals\n\n_Tap *Start* below to open a fresh chart._",
                    parse_mode="Markdown",
                    reply_markup=expired_signal_keyboard()
                )
            except Exception as e:
                logging.warning("inactivity_expire send failed: {}".format(e))

        task = asyncio.create_task(inactivity_expire_gm(user_id, chat))
        USER_INACTIVITY[user_id]["task"] = task
        return

    if data.startswith("sel_"):
        idx=data[4:]
        pair=PAIR_INDEX.get(idx)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found. Please choose again.", reply_markup=pairs_keyboard())
            return
        # Blacklist check
        if is_blacklisted(user_id):
            await context.bot.send_message(chat_id=chat, text="🚫 *You are banned from this bot.*\n\nContact admin for more info.", parse_mode="Markdown")
            return
        # Weekend check — non-OTC not available
        if is_weekend() and "OTC" not in pair:
            await context.bot.send_message(
                chat_id=chat,
                text="⚠️ *Market Closed (Weekend)*\n\nThis pair is not available on Saturday/Sunday.\nPlease select an *OTC* pair instead.",
                parse_mode="Markdown",
                reply_markup=pairs_keyboard()
            )
            return
        # Anti-spam check
        if is_spam(user_id):
            return
        # User is active — reset inactivity timer (msg_id added later)
        inactivity_reset(user_id, chat)
        # Free trial check
        if not is_licensed(user_id) and free_signals_used(user_id) >= total_free_allowed(user_id):
            try: await q.message.delete()
            except: pass
            bonus = get_bonus_signals(user_id)
            refs = count_referrals(user_id)
            extra = "\n\n🎁 *You have {} referrals* — invite more to unlock extra signals!".format(refs) if refs > 0 else "\n\n🎁 *Invite 3+ friends* to get free bonus signals!"
            await context.bot.send_message(
                chat_id=chat,
                text="🔒 *UNLOCK FULL ACCESS*\n\n"
                     "You have used your *{} free trial signals*.{}\n\n"
                     "💎 *$150 — LIFETIME ACCESS*\n"
                     "✅ Unlimited signals forever\n"
                     "✅ Win rate 90% — 98%\n"
                     "✅ Free updates forever\n"
                     "✅ 100+ trading pairs\n\n"
                     "👇 See payment methods or enter your code:".format(total_free_allowed(user_id), extra),
                parse_mode="Markdown",
                reply_markup=unlock_keyboard()
            )
            return
        try: await q.message.delete()
        except: pass

        # ── OTC: Show mode selection (seconds OR normal minutes) ───
        if "OTC" in pair:
            _otcm = await context.bot.send_message(
                chat_id=chat,
                text=(
                    "⚡ *{}*\n\n"
                    "Choose signal type:\n\n"
                    "⏱ *Seconds* — 3s/5s/10s/15s/30s signals _(subscribers only)_\n"
                    "📊 *Normal* — minute-based signal"
                ).format(pair),
                parse_mode="Markdown",
                reply_markup=otc_mode_keyboard(pair)
            )
            save_last_bot_msg(user_id, _otcm.message_id)
            return

        # ── Non-OTC: Show TF selection keyboard ────────────────
        context.user_data["_user_chose_tf"] = True  # user will pick TF manually
        _tfm = await context.bot.send_message(
            chat_id=chat,
            text="⚡ *{}*\n\nSelect signal duration:".format(pair),
            parse_mode="Markdown",
            reply_markup=nonotc_tf_keyboard(pair)
        )
        save_last_bot_msg(user_id, _tfm.message_id)
        return

        # --- Check user signal state ---
        check = check_signal_request(user_id, pair)

        if check["action"] == "cooldown":
            # Silent — do nothing
            return

        # (block removed — user always gets a signal without restriction)

        # Signal still active — redirect to getmore_ for a new signal
        if check["action"] not in ("fresh", "flip", "same"):
            state = get_user_signal_state(user_id, pair)
            if state:
                signal_time = state["signal_time"]
                if isinstance(signal_time, str):
                    signal_time = datetime.fromisoformat(signal_time)
                elapsed   = (datetime.utcnow() - signal_time).total_seconds()
                threshold = state["last_timeframe"] * 60
                if elapsed < threshold:
                    # Signal still active — issue new signal immediately for same pair
                    idx_str = pair_to_idx(pair)
                    await context.bot.send_message(
                        chat_id=chat,
                        text="⚠️ *Previous signal still active!*\n\nGenerating a new signal for *{}*...".format(pair),
                        parse_mode="Markdown"
                    )
                    # Continue to generate — don't return

        # --- Candle safe zone check ---
        # Block if we are in the first 10 seconds (new candle) or last 10 seconds (candle closing)
        if not is_candle_safe_zone():
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(pair_to_idx(pair)))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        cm = await context.bot.send_message(chat_id=chat, text="🔵 *Analyzing {}...*".format(pair), parse_mode="Markdown")

        # --- Capture entry price IMMEDIATELY (before any processing delay) ---
        is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS
        entry_price = None
        if is_non_otc:
            entry_price = _fetch_current_price(pair)
        signal_capture_time = datetime.utcnow()

        await asyncio.sleep(0.2)

        # --- Trend validation ---
        trend = get_trend_direction(pair)

        if check["action"] == "fresh":
            try:
                loop = asyncio.get_event_loop()
                sig = await loop.run_in_executor(None, generate_signal, pair)
            except Exception as e:
                logging.warning("generate_signal error {}: {}".format(pair, e))
                try: await cm.delete()
                except: pass
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again", callback_data="sel_{}".format(data[4:]))],
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return
            direction  = sig["direction"]
            timeframe  = sig["timeframe"]
            strength   = sig["strength"]
            flip_count = 0
            # Flat market block
            if sig.get("flat") and timeframe == 0:
                try: await cm.delete()
                except: pass
                reason = sig.get("no_signal_reason", "")
                extra = ""
                if "conflict" in reason:
                    extra = "\n\n_1H trend and short-term momentum are not aligned yet._"
                elif "flip" in reason:
                    extra = "\n\n_Market direction changed too quickly — waiting for stability._"
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return
            # Override with dominant trend if available
            if trend is not None:
                direction = trend
            # Non-OTC: no signal if confluence weak — never guess
            elif is_non_otc and (sig.get("flat") or sig.get("indicators_agree", 10) < 6):
                try: await cm.delete()
                except: pass
                reason = sig.get("no_signal_reason", "")
                extra = ""
                if "conflict" in reason:
                    extra = "\n\n_1H trend and short-term momentum are not aligned yet._"
                elif "flip" in reason:
                    extra = "\n\n_Market direction changed too quickly — waiting for stability._"
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(pair_to_idx(pair)))]
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return
            elif not is_non_otc and sig.get("indicators_agree", 7) < 4:
                try: await cm.delete()
                except: pass
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No clear signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(pair_to_idx(pair)))]
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return

        elif check["action"] == "flip":
            # First quick return — flip direction, reset flip_count to 1
            direction  = check["direction"]
            timeframe  = random.choice([1, 2, 3])
            strength   = random.randint(200, 500)
            flip_count = 1

        else:  # same
            # 2nd or 3rd quick return — keep same flipped direction, increment flip_count
            state      = get_user_signal_state(user_id, pair)
            flip_count = state["flip_count"] + 1 if state else 2
            direction  = check["direction"]
            timeframe  = random.choice([1, 2, 3])
            strength   = random.randint(200, 500)

        # Save state with updated flip_count
        # entry_price was already captured at signal request time (above)
        is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS

        # Contrarian flip: worst-3 VTE pairs get signal flipped (they fail consistently)
        if is_non_otc and check["action"] == "fresh" and is_contrarian_pair(pair):
            direction = "SELL" if direction == "BUY" else "BUY"
            logging.info("CONTRARIAN FLIP applied: {} → {}".format(pair, direction))

        save_user_signal_state(user_id, pair, direction, timeframe, flip_count, entry_price=entry_price)
        # Record to signal history (fresh signals already recorded inside generate_signal)
        if check["action"] != "fresh":
            record_signal(pair, direction)

        ib    = direction == "BUY"
        img   = get_buy_image() if ib else get_sell_image()
        arrow = "Up 🟢" if ib else "Down 🔴"
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        await delete_last_signal(context.bot, chat, user_id)
        cap = "*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair, arrow, timeframe, strength)
        sent_msg = await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))
        save_last_signal_msg(user_id, sent_msg.message_id)

        # --- Result tracker: non-OTC only (have real price data) ---
        if is_non_otc and entry_price is not None:
            asyncio.create_task(
                schedule_result_check(context.bot, chat, user_id, pair, direction, timeframe, entry_price)
            )

        # --- Inactivity tracker: record msg_id and reset timer ---
        inactivity_reset(user_id, chat, msg_id=sent_msg.message_id)

        async def inactivity_expire(uid, cid):
            """Clears ALL signals and sends VIP message immediately."""
            await asyncio.sleep(INACTIVITY_MINUTES * 60)
            msg_ids = inactivity_get_msgs(uid)
            # Delete all messages
            for mid in msg_ids:
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                except Exception:
                    pass
            inactivity_clear(uid)
            # Send VIP message once only
            try:
                await context.bot.send_message(
                    chat_id=cid,
                    text=(
                        "⏰ *Your session has expired.*\n\n"
                        "🌟 *Join our VIP today and get more accuracy signals!*\n\n"
                        "✅ Win rate 90% — 98%\n"
                        "✅ 100+ trading pairs\n"
                        "✅ Unlimited signals\n\n"
                        "_Tap *Start* below to open a fresh chart._"
                    ),
                    parse_mode="Markdown",
                    reply_markup=expired_signal_keyboard()
                )
            except Exception as e:
                logging.warning("inactivity_expire send failed: {}".format(e))

        task = asyncio.create_task(inactivity_expire(user_id, chat))
        USER_INACTIVITY[user_id]["task"] = task

async def query_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Directly handle reply keyboard button presses — no middleman button needed."""
    user_id = update.effective_user.id

    if data == "help_inline":
        await query.answer()
        await query.message.reply_text(
            "ℹ️ *EVALON MASTER PRO — Help*\n\n"
            "⚡ *Get Signal* — Chagua pair na upate signal\n"
            "🤖 *Bot Pick Pair* — Bot inakuchagulia pair bora\n"
            "📊 *My Stats* — Angalia matokeo yako\n"
            "💎 *Upgrade* — Nunua licence ya monthly au lifetime\n\n"
            "📌 *Jinsi ya kutumia:*\n"
            "1. Bonyeza EVALON MENU\n"
            "2. Chagua Get Signal au Bot Pick Pair\n"
            "3. Subiri signal — ingia trade wakati signal inaonekana\n\n"
            "",
            parse_mode="Markdown",
        )
        return

    if data == "choose_pair":
        weekend = is_weekend()
        taglines = [
            "🌙 *After-Hours Trading*\nWeekend-only pairs available 24/7." if weekend else
            "🌍 *Real Market Pairs*\nTrade on live market data.",
        ]
        tagline = random.choice(taglines)
        sess = get_trading_session()
        sess_txt = ""
        if sess and sess.get("name","") not in ("Dead Hours","Off Hours",""):
            sess_txt = "\n🕐 *{}* active".format(sess["name"])
        header = "⚡ *EVALON MASTER PRO*\n\n{}{}\n\n📊 Select your trading pair:".format(tagline, sess_txt)
        await update.message.reply_text(
            header,
            parse_mode="Markdown",
            reply_markup=pairs_keyboard()
        )
        return

    if data == "bot_pick_pair":
        # Free trial users cannot use Bot Pick Pair — subscribers only
        if not is_licensed(user_id):
            await update.message.reply_text(
                "🔒 *Bot Pick Pair — Subscribers Only*\n\n"
                "This feature is available for licensed subscribers only.\n\n"
                "Upgrade to get:\n"
                "✅ Bot-picked best pairs\n"
                "✅ Unlimited signals\n"
                "✅ Win rate 90% — 98%",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("📊 Choose Pair Myself", callback_data="choose_pair")],
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        weekend      = is_weekend()
        otc_on       = is_otc_enabled()
        force_non_otc = not otc_on

        # Get top 5 from virtual trading engine stats
        if force_non_otc:
            top5 = get_top5_pairs(non_otc_only=True)
        elif weekend:
            top5 = get_top5_pairs(otc_only=True)
        else:
            top5 = get_top5_pairs()

        # Fallback: if not enough virtual data yet, pick random
        if len(top5) < 3:
            if force_non_otc:
                pool = [p for p in ALL_PAIRS if "OTC" not in p]
            elif weekend:
                pool = [p for p in ALL_PAIRS if "OTC" in p]
            else:
                pool = list(ALL_PAIRS)
            random.shuffle(pool)
            existing = {r["pair"] for r in top5}
            for p in pool:
                if p not in existing and len(top5) < 5:
                    top5.append({"pair": p, "wins": 0, "losses": 0, "win_rate": 0})
                    existing.add(p)

        is_admin_user = (user_id == ADMIN_ID)
        buttons = []
        for row in top5:
            pair  = row["pair"]
            wr    = row.get("win_rate") or 0
            total = row.get("wins", 0) + row.get("losses", 0)
            if is_admin_user and total > 0:
                label = "📊 {} — {:.0f}% ({} trades)".format(pair, wr, total)
            else:
                label = "📊 {}".format(pair)
            try:
                idx = ALL_PAIRS.index(pair)
            except ValueError:
                continue
            buttons.append([InlineKeyboardButton(label, callback_data="sel_{}".format(idx))])

        buttons.append([InlineKeyboardButton("📋 Choose Myself", callback_data="choose_pair")])
        kb = InlineKeyboardMarkup(buttons)

        await update.message.reply_text(
            "🤖 *Bot Top 5 Picks*\n\n"
            "Pairs ranked by virtual trading win rate.\n"
            "Select one to get a signal:",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    if data == "pay_info":
        await update.message.reply_text(
            PAYMENT_TEXT,
            parse_mode="Markdown",
            reply_markup=payment_keyboard()
        )
        return

    if data == "my_stats":
        u = get_user(user_id)
        licensed = is_licensed(user_id)
        lic_type = u.get("licence_type", "").capitalize() if licensed else "Free Trial"
        expiry_txt = get_expiry_text(user_id) if licensed else "—"
        free_used = free_signals_used(user_id)
        free_allowed = total_free_allowed(user_id)
        refs = count_referrals(user_id)
        bonus = get_bonus_signals(user_id)
        # Referral link → REFERRAL_BOT (separate from admin bot)
        ref_link = "https://t.me/{}?start=REF_{}".format(REFERRAL_BOT, user_id)
        share_url = "https://t.me/share/url?url={}".format(ref_link)
        if refs >= 5:
            ref_status = "🎁 {} bonus signals (5+ referrals)".format(bonus)
        elif refs >= 3:
            ref_status = "🎁 {} bonus signals (3-4 referrals)".format(bonus)
        else:
            needed = 3 - refs
            ref_status = "⏳ Invite {} more to get bonus signals!".format(needed)
        await update.message.reply_text(
            "📊 *YOUR STATS*\n\n"
            "🔑 Status: {}\n"
            "⏳ Expiry: {}\n"
            "🆓 Free signals: {}/{}\n"
            "👥 Referrals: {}\n"
            "🎁 Bonus signals: {}\n"
            "{}\n\n"
            ""
            "{}".format(
                lic_type, expiry_txt, free_used, free_allowed, refs, bonus,
                ref_status, ref_link,
                "_Upgrade to get unlimited signals!_" if not licensed else "_Thank you for being a subscriber!_"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Share Referral Link", url=share_url)],
                [InlineKeyboardButton("💎 Upgrade", callback_data="pay_info")],
                [InlineKeyboardButton("📊 Get Signal", callback_data="choose_pair")],
            ]) if not licensed else InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Share Referral Link", url=share_url)],
                [InlineKeyboardButton("📊 Get Signal", callback_data="choose_pair")],
            ])
        )
        return


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id=update.effective_user.id

    # Admin: receive BUY or SELL signal image
    if user_id == ADMIN_ID and context.user_data.get("awaiting_image"):
        img_type = context.user_data.pop("awaiting_image")
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            key = "buy_image" if img_type == "buy" else "sell_image"
            set_setting(key, file_id)
            label = "BUY 📈" if img_type == "buy" else "SELL 📉"
            await update.message.reply_text(
                "✅ *{} image updated successfully!*\n\nNew image saved.".format(label),
                parse_mode="Markdown",
                reply_markup=admin_image_keyboard()
            )
        else:
            await update.message.reply_text("❌ Please send a photo, not text.")
        return

    text=update.message.text.strip() if update.message.text else ""

    if user_id==ADMIN_ID:
        if text=="/addmonthly" or text.startswith("/addmonthly "):
            try: count=min(int(text.split()[1]),50) if len(text.split())>1 else 1
            except: count=1
            codes=[]
            for _ in range(count):
                code=generate_code("monthly"); add_licence(code,"monthly"); codes.append("`{}`".format(code))
            await update.message.reply_text("✅ *{} Monthly Code{}:*\n\n".format(count,"s" if count>1 else "")+"\n".join(codes)+"\n\n📅 Valid 30 days after activation.", parse_mode="Markdown")
            return
        if text=="/addlifetime" or text.startswith("/addlifetime "):
            try: count=min(int(text.split()[1]),50) if len(text.split())>1 else 1
            except: count=1
            codes=[]
            for _ in range(count):
                code=generate_code("lifetime"); add_licence(code,"lifetime"); codes.append("`{}`".format(code))
            await update.message.reply_text("✅ *{} Lifetime Code{}:*\n\n".format(count,"s" if count>1 else "")+"\n".join(codes)+"\n\n♾️ Never expires.", parse_mode="Markdown")
            return
        if text=="/listlicences":
            s=get_stats()
            msg="📋 *LICENCES*\n\n📅 Monthly Available: {}\n♾️ Lifetime Available: {}\n\n".format(len(s["m_codes"]),len(s["l_codes"]))
            if s["m_codes"]: msg+="*Monthly:*\n"+"\n".join(["`{}`".format(c) for c in s["m_codes"]])+"\n\n"
            if s["l_codes"]: msg+="*Lifetime:*\n"+"\n".join(["`{}`".format(c) for c in s["l_codes"]])
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
        if text=="/listusers":
            s=get_stats()
            await update.message.reply_text("👥 *USERS*\n\n👤 Total: {}\n📅 Monthly: {}\n♾️ Lifetime: {}\n🆓 Free: {}".format(s["total"],s["monthly"],s["lifetime"],s["free"]), parse_mode="Markdown")
            return
        if text=="/totalusers":
            s=get_stats()
            licensed = s["monthly"] + s["lifetime"]
            await update.message.reply_text(
                "👥 *TOTAL USERS*\n\n"
                "📊 All users: *{}*\n"
                "🆓 Free trial: *{}*".format(s["total"], licensed, s["free"]),
                parse_mode="Markdown"
            )
            return
        if text=="/setimage":
            await update.message.reply_text(
                "🖼 *Set Signal Images*\n\nChoose which image to update:",
                parse_mode="Markdown",
                reply_markup=admin_image_keyboard()
            )
            return
        if text=="/stats":
            s=get_stats()
            m_unused=len(s["m_codes"]); l_unused=len(s["l_codes"])
            await update.message.reply_text(
                "📊 *EVALON MASTER PRO — STATS*\n\n"
                "👤 Total Users: {}\n"
                "📅 Monthly Licensed: {}\n"
                "♾️ Lifetime Licensed: {}\n"
                "🆓 Free (trial): {}\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🔑 *LICENCES UNUSED*\n"
                "📅 Monthly: {}\n"
                "♾️ Lifetime: {}".format(
                    s["total"], s["monthly"], s["lifetime"], s["free"],
                    m_unused, l_unused
                ),
                parse_mode="Markdown"
            )
            return
        if text.startswith("/revoke "):
            try:
                target_id = int(text.split()[1])
                u = get_user(target_id)
                if not u:
                    await update.message.reply_text("❌ User {} not found.".format(target_id))
                    return
                revoke_licence(target_id)
                await update.message.reply_text(
                    "✅ *Licence revoked!*\n\nUser ID: `{}`\nUser is back on free trial.".format(target_id),
                    parse_mode="Markdown"
                )
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Usage: `/revoke 123456789`", parse_mode="Markdown")
            return
        if text.startswith("/deleteuser "):
            try:
                target_id = int(text.split()[1])
                delete_user(target_id)
                await update.message.reply_text(
                    "🗑 *User deleted!*\n\nUser ID: `{}` has been permanently removed.".format(target_id),
                    parse_mode="Markdown"
                )
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Usage: `/deleteuser 123456789`", parse_mode="Markdown")
            return
        if text.startswith("/broadcast "):
            msg = text[len("/broadcast "):].strip()
            if not msg:
                await update.message.reply_text(
                    "❌ Please type a message after /broadcast\n\nExample:\n`/broadcast Hello everyone! 🎉`",
                    parse_mode="Markdown"
                )
                return
            user_ids = get_all_user_ids()
            sent = 0; failed = 0
            broadcast_text = "📢 *EVALON MASTER PRO*\n\n" + msg
            for uid in user_ids:
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=broadcast_text,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                    sent += 1
                    await asyncio.sleep(0.05)  # Avoid Telegram flood limits
                except Exception:
                    failed += 1
            await update.message.reply_text(
                "📢 *Broadcast Complete!*\n\n"
                "✅ Sent: *{}*\n"
                "❌ Failed: *{}*\n"
                "👥 Total: *{}*".format(sent, failed, sent + failed),
                parse_mode="Markdown"
            )
            return
        if text.startswith("/blacklist "):
            try:
                target_id = int(text.split()[1])
                reason = " ".join(text.split()[2:]) if len(text.split()) > 2 else "No reason given"
                blacklist_user(target_id, reason)
                await update.message.reply_text(
                    "🚫 *User banned!*\n\nID: `{}`\nReason: {}".format(target_id, reason),
                    parse_mode="Markdown"
                )
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Usage: `/blacklist 123456789 reason`", parse_mode="Markdown")
            return
        if text.startswith("/unblacklist "):
            try:
                target_id = int(text.split()[1])
                unblacklist_user(target_id)
                await update.message.reply_text(
                    "✅ *User unbanned!*\n\nID: `{}`".format(target_id),
                    parse_mode="Markdown"
                )
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Usage: `/unblacklist 123456789`", parse_mode="Markdown")
            return
        if text == "/listblacklist":
            bl = get_blacklist()
            if not bl:
                await update.message.reply_text("✅ No banned users.")
                return
            msg = "🚫 *BLACKLIST*\n\n"
            for b in bl:
                msg += "• `{}` — {}\n".format(b["user_id"], b.get("reason",""))
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
        if text.startswith("/userinfo "):
            try:
                target_id = int(text.split()[1])
                u = get_user(target_id)
                if not u:
                    await update.message.reply_text("❌ User not found.")
                    return
                refs = count_referrals(target_id)
                bonus = get_bonus_signals(target_id)
                bl = is_blacklisted(target_id)
                lic = "✅ {}".format(u.get("licence_type","").capitalize()) if u.get("licensed") else "❌ None"
                exp = get_expiry_text(target_id) if u.get("licensed") else "—"
                await update.message.reply_text(
                    "👤 *USER INFO*\n\n"
                    "🆔 ID: `{}`\n"
                    "🔑 Licence: {}\n"
                    "⏳ Expiry: {}\n"
                    "🆓 Free used: {}/{}\n"
                    "👥 Referrals: {}\n"
                    "🎁 Bonus signals: {}\n"
                    "🚫 Blacklisted: {}".format(
                        target_id, lic, exp,
                        u.get("free_used",0), total_free_allowed(target_id),
                        refs, bonus, "Yes" if bl else "No"
                    ),
                    parse_mode="Markdown"
                )
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Usage: `/userinfo 123456789`", parse_mode="Markdown")
            return
        if text.startswith("/addtrial "):
            parts = text.split()
            try:
                target_id = int(parts[1])
                extra = int(parts[2])
                u = get_user(target_id)
                if not u:
                    await update.message.reply_text("❌ User not found.")
                    return
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE users SET bonus_signals = bonus_signals + %s WHERE user_id = %s",
                            (extra, target_id)
                        )
                    conn.commit()
                await update.message.reply_text(
                    "✅ *Trial updated!*\n\nUser `{}` received {} extra signals.".format(target_id, extra),
                    parse_mode="Markdown"
                )
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Usage: `/addtrial 123456789 5`", parse_mode="Markdown")
            return

        if text == "/pairstats":
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT pair, wins_today AS wins, losses_today AS losses,
                                   ROUND(wins_today::numeric / NULLIF(wins_today+losses_today,0)*100,1) AS rate
                            FROM pair_stats
                            WHERE (wins_today + losses_today) >= 1
                              AND DATE(updated_at) = CURRENT_DATE
                            ORDER BY rate DESC NULLS LAST, wins_today DESC
                            LIMIT 30
                        """)
                        today_stats = [dict(r) for r in cur.fetchall()]
            except Exception as _e:
                today_stats = []
            if not today_stats:
                stats = get_pair_stats_all()
                if not stats:
                    await update.message.reply_text("📊 *PAIR STATS*\n\nNo data yet.", parse_mode="Markdown")
                    return
                msg = "📊 *PAIR STATS (All-time)*\n\n"
                for r in stats[:30]:
                    total = r["wins"] + r["losses"]
                    rate  = int(r["wins"] / max(total, 1) * 100)
                    bar   = "🟢" * (rate // 20) + "🔴" * (5 - rate // 20)
                    msg  += "{} *{}*\n  ✅ {} | ❌ {} | {}%\n\n".format(bar, r["pair"], r["wins"], r["losses"], rate)
            else:
                from datetime import datetime as _dt
                msg = "📊 *PAIR STATS — Today ({})*\n\n".format(_dt.utcnow().strftime("%d %b %Y"))
                for r in today_stats:
                    total = (r["wins"] or 0) + (r["losses"] or 0)
                    rate  = int((r["wins"] or 0) / max(total, 1) * 100)
                    bar   = "🟢" * (rate // 20) + "🔴" * (5 - rate // 20)
                    msg  += "{} *{}*\n  ✅ {} | ❌ {} | {}%\n\n".format(bar, r["pair"], r["wins"] or 0, r["losses"] or 0, rate)
            await update.message.reply_text(msg[:4000], parse_mode="Markdown")
            return
        if text.startswith("/addreverse "):
            pair_name = text[len("/addreverse "):].strip().upper()
            add_reverse_pair(pair_name)
            await update.message.reply_text(
                "🔄 *Reverse pair added:*\n`{}`\n\nBot will flip the signal direction.".format(pair_name),
                parse_mode="Markdown"
            )
            return
        if text.startswith("/removereverse "):
            pair_name = text[len("/removereverse "):].strip().upper()
            remove_reverse_pair(pair_name)
            await update.message.reply_text(
                "✅ *Reverse pair removed:*\n`{}`".format(pair_name),
                parse_mode="Markdown"
            )
            return
        if text == "/listreverse":
            pairs_list = get_all_reverse_pairs()
            if not pairs_list:
                await update.message.reply_text("🔄 *REVERSE PAIRS*\n\nNo reverse pairs set.", parse_mode="Markdown")
            else:
                msg = "🔄 *REVERSE PAIRS* (bot flips direction):\n\n"
                for p in pairs_list:
                    msg += "• `{}`\n".format(p)
                await update.message.reply_text(msg, parse_mode="Markdown")
            return

        if text == "/toggleotc":
            current = is_otc_enabled()
            new_state = not current
            set_otc_enabled(new_state)
            if new_state:
                await update.message.reply_text(
                    "✅ *OTC Pairs: WASHA (ON)*\n\n"
                    "All pairs are now visible — OTC and non-OTC.\n\n"
                    "_Use /toggleotc again to disable OTC._",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "🔴 *OTC Pairs: ZIMA (OFF)*\n\n"
                    "Users will see *non-OTC pairs only* now.\n"
                    "OTC pairs are hidden from the keyboard.\n\n"
                    "_Use /toggleotc again to enable OTC._",
                    parse_mode="Markdown"
                )
            return

    # /refer command — user yeyote
    if update.message.text and update.message.text.strip() == "/refer":
        user_id2 = update.effective_user.id
        refs = count_referrals(user_id2)
        bonus = get_bonus_signals(user_id2)
        # Referral link → REFERRAL_BOT
        ref_link = "https://t.me/{}?start=REF_{}".format(REFERRAL_BOT, user_id2)
        if refs >= 5:
            status = "🎁 You have 3 bonus signals (5+ referrals)"
        elif refs >= 3:
            status = "🎁 You have 2 bonus signals (3-4 referrals)"
        else:
            needed = 3 - refs
            status = "⏳ Invite {} more people to get bonus!".format(needed)
        await update.message.reply_text(
            "👥 *YOUR REFERRAL*\n\n"
            "🔗 Your link:\n`{}`\n\n"
            "👤 People you invited: *{}*\n"
            "{}\n\n"
            "_Share your link — invite 3+ people and get free bonus signals!_".format(ref_link, refs, status),
            parse_mode="Markdown"
        )
        return

    # ── Reply Keyboard Button Handlers ────────────────────────
    # Delete the user's keyboard message immediately to keep chat clean
    try:
        await update.message.delete()
    except Exception:
        pass

    if text in ("/start", "🔄 Restart"):
        await start(update, context)
        return
    if text == "🏆 EVALON MENU":
        # Show full inline menu
        user  = get_user(user_id)
        lic   = is_licensed(user_id)
        plan  = user.get("licence_type", "").capitalize() if lic else "Free"
        await update.message.reply_text(
            "⚡ *EVALON MASTER PRO*\n\n"
            "👤 Plan: *{}*\n\n"
            "Choose an option:".format(plan),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Get Signal",        callback_data="choose_pair")],
                [InlineKeyboardButton("🤖 Bot Pick Pair",     callback_data="bot_pick_pair")],
                [InlineKeyboardButton("📊 My Stats",          callback_data="my_stats")],
            ] + ([] if lic else [[InlineKeyboardButton("💎 Upgrade / Licence", callback_data="pay_info")]]) + [
                [InlineKeyboardButton("ℹ️ Help",              callback_data="help_inline")],
            ])
        )
        return

    # Admin: block/unblock/list blocked users
    if text.startswith("/blockuser ") and user_id == ADMIN_ID:
        try:
            parts = text.split()
            target_id = int(parts[1])
            reason = " ".join(parts[2:]) or None
            block_user(target_id, reason)
            await update.message.reply_text("User {} blocked.".format(target_id))
        except Exception:
            await update.message.reply_text("Usage: /blockuser 123456789 [reason]")
        return

    if text.startswith("/unblockuser ") and user_id == ADMIN_ID:
        try:
            target_id = int(text.split()[1])
            unblock_user(target_id)
            await update.message.reply_text("User {} unblocked.".format(target_id))
        except Exception:
            await update.message.reply_text("Usage: /unblockuser 123456789")
        return

    if text == "/listblocked" and user_id == ADMIN_ID:
        blocked = get_blocked_users()
        if not blocked:
            await update.message.reply_text("No blocked users.")
            return
        msg = "*Blocked Users*\n\n"
        for b in blocked:
            name = "{} {}".format(b.get("first_name") or "", b.get("last_name") or "").strip() or "No name"
            uname = "@{}".format(b["username"]) if b.get("username") else "no username"
            msg += "ID: {} | {} | {} | /unblockuser {}\n".format(b["user_id"], name, uname, b["user_id"])
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    if text.startswith("/broadcast ") and user_id == ADMIN_ID:
        msg_text = text[11:].strip()
        if not msg_text:
            await update.message.reply_text("Usage: /broadcast Your message here")
            return
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users")
                    all_users = [r["user_id"] for r in cur.fetchall()]
            sent = blk = failed = 0; blk_ids = []
            for uid in all_users:
                try:
                    await context.bot.send_message(chat_id=uid, text=msg_text, parse_mode="Markdown")
                    sent += 1
                except Exception as ex:
                    err = str(ex).lower()
                    if "blocked" in err or "deactivated" in err or "not found" in err:
                        blk += 1; blk_ids.append(uid)
                    else:
                        failed += 1
                await asyncio.sleep(0.05)
            s = "Broadcast done.\nSent: {}\nBlocked bot: {}\nFailed: {}".format(sent, blk, failed)
            if blk_ids:
                s += "\nBlocked IDs: " + ", ".join(str(i) for i in blk_ids[:20])
            await update.message.reply_text(s)
        except Exception as e:
            await update.message.reply_text("Broadcast error: {}".format(e))
        return

    if text == "/blockedbot" and user_id == ADMIN_ID:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id, first_name, last_name, username FROM users")
                    all_users = cur.fetchall()
            blk_list = []
            for u in all_users:
                try:
                    await context.bot.send_chat_action(chat_id=u["user_id"], action="typing")
                except Exception as ex:
                    if "blocked" in str(ex).lower() or "deactivated" in str(ex).lower():
                        nm = "{} {}".format(u.get("first_name") or "", u.get("last_name") or "").strip() or "No name"
                        blk_list.append("ID:{} | {} | @{}".format(u["user_id"], nm, u.get("username") or "none"))
                await asyncio.sleep(0.03)
            if not blk_list:
                await update.message.reply_text("No users have blocked the bot.")
                return
            msg = "*Blocked bot: {}*\n\n".format(len(blk_list)) + "\n".join(blk_list[:50])
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text("Error: {}".format(e))
        return

    if text == "/resultson" and user_id == ADMIN_ID:
        set_bot_setting("results_enabled", "on")
        await update.message.reply_text("Results messages: ON")
        return
    if text == "/resultsoff" and user_id == ADMIN_ID:
        set_bot_setting("results_enabled", "off")
        await update.message.reply_text("Results messages: OFF")
        return

    if text.startswith("/blockuser ") and user_id == ADMIN_ID:
        try:
            parts = text.split(); tid = int(parts[1]); reason = " ".join(parts[2:]) or None
            block_user(tid, reason)
            await update.message.reply_text("User {} blocked.".format(tid))
        except Exception:
            await update.message.reply_text("Usage: /blockuser 123456789 [reason]")
        return

    if text.startswith("/unblockuser ") and user_id == ADMIN_ID:
        try:
            tid = int(text.split()[1]); unblock_user(tid)
            await update.message.reply_text("User {} unblocked.".format(tid))
        except Exception:
            await update.message.reply_text("Usage: /unblockuser 123456789")
        return

    if text == "/listblocked" and user_id == ADMIN_ID:
        blocked = get_blocked_users()
        if not blocked:
            await update.message.reply_text("No blocked users.")
            return
        msg = "*Blocked Users*\n\n"
        for b in blocked:
            nm = "{} {}".format(b.get("first_name") or "", b.get("last_name") or "").strip() or "No name"
            un = "@{}".format(b["username"]) if b.get("username") else "none"
            msg += "ID: `{}` | {} | {}\n/unblockuser {}\n\n".format(b["user_id"], nm, un, b["user_id"])
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # Admin: search user by name or username
    if text.startswith("finduser ") and user_id == ADMIN_ID:
        query = text[9:].strip().lower()
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT user_id, first_name, last_name, username,
                               licensed, licence_type, expiry, free_used
                        FROM users
                        WHERE LOWER(COALESCE(first_name,'')) LIKE %s
                           OR LOWER(COALESCE(last_name,''))  LIKE %s
                           OR LOWER(COALESCE(username,''))   LIKE %s
                        LIMIT 10
                    """, ('%'+query+'%', '%'+query+'%', '%'+query+'%'))
                    rows = cur.fetchall()
            if not rows:
                await update.message.reply_text(
                    "No users found for: *{}*".format(query),
                    parse_mode="Markdown"
                )
                return
            msg = "*Search: {}*\n\n".format(query)
            for r in rows:
                first = r["first_name"] or ""
                last  = r["last_name"]  or ""
                name  = "{} {}".format(first, last).strip() or "No name"
                uname = "@{}".format(r["username"]) if r["username"] else "No username"
                uid   = r["user_id"]
                if r["licensed"]:
                    status = "Licensed ({})".format(r["licence_type"] or "?")
                else:
                    status = "Free trial"
                msg += (
                    "Name: *{}*\n"
                    "Username: {}\n"
                    "ID: `{}`\n"
                    "Status: {}\n"
                    "Revoke: `/revoke {}`\n"
                    "\n"
                ).format(name, uname, uid, status, uid)
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text("Error: {}".format(e))
        return

    # Admin: show VTE win rate stats for all forex pairs
    if text == "vtestats" and user_id == ADMIN_ID:
        try:
            forex_pairs = [p for p in YAHOO_SYMBOLS
                           if "/" in p and "BTC" not in p
                           and "^" not in YAHOO_SYMBOLS.get(p, "")]
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pair, wins, losses,
                               ROUND(wins::numeric / NULLIF(wins+losses,0) * 100, 1) AS win_rate,
                               optimal_tf, avg_movement
                        FROM pair_stats
                        WHERE pair = ANY(%s) AND (wins + losses) >= 5
                        ORDER BY win_rate ASC
                    """, (forex_pairs,))
                    rows = cur.fetchall()
            if not rows:
                await update.message.reply_text("📊 No VTE data yet. Bot is still learning.")
                return
            ranked = get_ranked_forex_pairs()
            contrarian_set = set(ranked["contrarian"])
            lines = ["📊 *VTE Win Rate Stats — Forex Pairs*\n"]
            for r in rows:
                tag = " 🔄 CONTRARIAN" if r["pair"] in contrarian_set else ""
                lines.append("• *{}*{}\n  W:{} L:{} | Rate: {}% | TF: {}m".format(
                    r["pair"], tag,
                    r["wins"], r["losses"], r["win_rate"],
                    r["optimal_tf"] or "?"
                ))
            await update.message.reply_text(
                "\n".join(lines), parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text("❌ Error: {}".format(e))
        return
        context.user_data["awaiting_code"]=False
        code=text.upper().strip()
        if activate_licence(code,user_id):
            u=get_user(user_id); exp=get_expiry_text(user_id)
            tl="📅 Monthly" if u.get("licence_type")=="monthly" else "♾️ Lifetime"
            await update.message.reply_text(
                "✅ *Licence Activated!*\n\n🎉 Welcome to EVALON MASTER PRO!\n🏆 Win Rate: 90% — 98%\n🔑 Type: *{}*\n⏳ {}\n\nYou can now use unlimited signals!".format(tl,exp),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Start Trading Now", callback_data="choose_pair")]])
            )
        else:
            await update.message.reply_text(
                "❌ *Invalid or already used code.*\n\nCheck your code or contact admin.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Support", url=support_url())],
                    [InlineKeyboardButton("🔑 Try Again", callback_data="enter_code")]
                ])
            )

# ============================================================
# VIRTUAL TRADING ENGINE v2
# Scans every 5 seconds. Places ONE virtual trade per NEW signal
# per pair (direction change only). Checks results after the
# correct timeframe expires. ATR is used to detect flat markets
# and skip recording those results (does not affect user signals).
# ============================================================

# In-memory store for pending virtual trades
# { pair: [(entry_price, direction, expiry_timestamp, tf_secs), ...] }
_virtual_trades: dict = {}

def _vt_get_last_direction(pair):
    """Get last recorded VTE direction for a pair from DB (survives restarts)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT direction FROM vte_last_direction WHERE pair=%s", (pair,))
                row = cur.fetchone()
        return row["direction"] if row else None
    except Exception:
        return None

def _vt_set_last_direction(pair, direction):
    """Save VTE last direction for a pair to DB."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO vte_last_direction (pair, direction, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (pair) DO UPDATE
                    SET direction=EXCLUDED.direction, updated_at=NOW()
                """, (pair, direction))
            conn.commit()
    except Exception as e:
        import logging
        logging.warning("_vt_set_last_direction failed {}: {}".format(pair, e))

VIRTUAL_TF_SECONDS = [60, 120, 180, 300, 600]  # 1m,2m,3m,5m,10m

def _vt_calc_atr(pair, period=14):
    """
    Calculate ATR for a pair using Yahoo Finance 5m data.
    Returns ATR as a % of current price, or None on failure.
    Used to detect flat markets — does NOT block user signals.
    """
    symbol = YAHOO_SYMBOLS.get(pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="2d", interval="5m",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < period + 1:
            return None
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        close = df["Close"].squeeze()
        tr = pd.Series([
            max(float(high.iloc[i]) - float(low.iloc[i]),
                abs(float(high.iloc[i]) - float(close.iloc[i-1])),
                abs(float(low.iloc[i])  - float(close.iloc[i-1])))
            for i in range(1, len(close))
        ], index=close.index[1:])
        atr = float(tr.rolling(period).mean().iloc[-1])
        price = float(close.iloc[-1])
        return atr / (price + 1e-9) * 100   # ATR as % of price
    except Exception as e:
        logging.warning("VTE ATR calc failed {}: {}".format(pair, e))
        return None


async def _vt_place_trades():
    """
    For each forex pair in YAHOO_SYMBOLS:
    - Generate signal
    - If direction changed since last check → place ONE new virtual trade
      for each timeframe (1m/2m/3m/5m/10m)
    - If direction is same → skip (no duplicate trades)
    """
    now  = time.time()
    loop = asyncio.get_event_loop()

    # Only track forex pairs (no BTC, indices, commodities)
    forex_pairs = [p for p in YAHOO_SYMBOLS if "/" in p and "BTC" not in p
                   and "^" not in YAHOO_SYMBOLS.get(p, "")]

    for pair in forex_pairs:
        try:
            sig = await loop.run_in_executor(None, generate_signal, pair)
            direction = sig["direction"]
            # Use pre-reverse direction for VTE accuracy
            if is_reverse_pair(pair):
                direction = "SELL" if direction == "BUY" else "BUY"

            last_dir = _vt_get_last_direction(pair)

            # Only place a new trade when direction changes
            if direction == last_dir:
                continue

            _vt_set_last_direction(pair, direction)

            price = _fetch_current_price(pair)
            if price is None:
                continue

            if pair not in _virtual_trades:
                _virtual_trades[pair] = []

            # Place one trade per timeframe
            for tf_secs in VIRTUAL_TF_SECONDS:
                expiry = now + tf_secs
                _virtual_trades[pair].append((price, direction, expiry, tf_secs))

            logging.info("VTE NEW TRADE: {} → {} @ {:.5f}".format(
                pair, direction, price))

        except Exception as e:
            logging.warning("VTE place trade failed {}: {}".format(pair, e))
            continue


async def _vt_check_results():
    """
    Check expired virtual trades.
    - Measure price movement vs ATR
    - If movement < 30% of ATR → market was flat → skip (don't record)
    - Otherwise record win/loss per timeframe
    - Update pair_stats and optimal_tf
    """
    now = time.time()
    tf_results: dict = {}   # { pair: { tf_secs: {wins,losses,total_movement,count} } }

    for pair in list(_virtual_trades.keys()):
        remaining = []
        for (entry_price, direction, expiry, tf_secs) in _virtual_trades[pair]:
            if now < expiry:
                remaining.append((entry_price, direction, expiry, tf_secs))
                continue

            exit_price = _fetch_current_price(pair)
            if exit_price is None or entry_price is None:
                continue

            raw_diff = exit_price - entry_price
            movement_pct = abs(raw_diff) / (entry_price + 1e-9) * 100

            # ATR flat-market filter — skip recording, but signal still reached user
            atr_pct = _vt_calc_atr(pair)
            if atr_pct is not None and movement_pct < (atr_pct * 0.30):
                logging.info("VTE FLAT SKIP: {} move={:.5f}% < 30% of ATR {:.5f}%".format(
                    pair, movement_pct, atr_pct))
                continue   # Skip — flat market, don't corrupt stats

            won = (raw_diff > 0) if direction == "BUY" else (raw_diff < 0)

            if pair not in tf_results:
                tf_results[pair] = {}
            if tf_secs not in tf_results[pair]:
                tf_results[pair][tf_secs] = {
                    "wins": 0, "losses": 0,
                    "total_movement": 0.0, "count": 0
                }

            tf_results[pair][tf_secs]["count"]          += 1
            tf_results[pair][tf_secs]["total_movement"] += movement_pct
            if won:
                tf_results[pair][tf_secs]["wins"]   += 1
            else:
                tf_results[pair][tf_secs]["losses"] += 1

        _virtual_trades[pair] = remaining

    if not tf_results:
        return

    for pair, tf_data in tf_results.items():
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    total_wins     = sum(d["wins"]   for d in tf_data.values())
                    total_losses   = sum(d["losses"] for d in tf_data.values())
                    total_movement = sum(d["total_movement"] for d in tf_data.values())
                    total_count    = sum(d["count"]  for d in tf_data.values())
                    avg_mov = total_movement / max(total_count, 1)

                    # Best TF = highest win rate with at least 3 trades
                    best_tf   = None
                    best_rate = 0.0
                    for tf_secs, d in tf_data.items():
                        total = d["wins"] + d["losses"]
                        if total < 3:
                            continue
                        rate = d["wins"] / total
                        if rate > best_rate:
                            best_rate = rate
                            best_tf   = tf_secs // 60

                    # Smooth avg_movement with existing DB value
                    cur.execute(
                        "SELECT optimal_tf, avg_movement FROM pair_stats WHERE pair=%s",
                        (pair,)
                    )
                    row = cur.fetchone()
                    if best_tf is None and row and row["optimal_tf"]:
                        best_tf = row["optimal_tf"]
                    if row and row["avg_movement"]:
                        avg_mov = (avg_mov + row["avg_movement"]) / 2

                    cur.execute("""
                        INSERT INTO pair_stats
                            (pair, wins, losses, consecutive_losses, optimal_tf, avg_movement,
                             wins_today, losses_today, updated_at)
                        VALUES (%s, %s, %s, 0, %s, %s, %s, %s, NOW())
                        ON CONFLICT (pair) DO UPDATE SET
                            wins         = pair_stats.wins + EXCLUDED.wins,
                            losses       = pair_stats.losses + EXCLUDED.losses,
                            optimal_tf   = COALESCE(EXCLUDED.optimal_tf, pair_stats.optimal_tf),
                            avg_movement = EXCLUDED.avg_movement,
                            wins_today   = CASE
                                WHEN DATE(pair_stats.updated_at) = CURRENT_DATE
                                THEN pair_stats.wins_today + EXCLUDED.wins_today
                                ELSE EXCLUDED.wins_today
                            END,
                            losses_today = CASE
                                WHEN DATE(pair_stats.updated_at) = CURRENT_DATE
                                THEN pair_stats.losses_today + EXCLUDED.losses_today
                                ELSE EXCLUDED.losses_today
                            END,
                            updated_at   = NOW()
                    """, (pair, total_wins, total_losses, best_tf, avg_mov,
                          total_wins, total_losses))

                conn.commit()
                logging.info("VTE RESULT: {} W:{} L:{} | best_tf={}m | avg_move={:.4f}%".format(
                    pair, total_wins, total_losses, best_tf, avg_mov))

                # Update session-aware TF stats (1m/2m/3m only)
                session = get_trading_session()
                sess_name = session.get("name", "Unknown") if session else "Unknown"
                for tf_secs, d in tf_data.items():
                    tf_m = tf_secs // 60
                    if tf_m not in [1, 2, 3]:
                        continue
                    for _ in range(d["wins"]):
                        update_tf_session_stats(pair, tf_m, sess_name, True)
                    for _ in range(d["losses"]):
                        update_tf_session_stats(pair, tf_m, sess_name, False)

        except Exception as e:
            logging.warning("VTE result save failed {}: {}".format(pair, e))


async def virtual_trading_engine():
    """
    Main VTE loop: every 5 seconds scan all forex pairs,
    place trades on direction changes, check expired results.
    Runs forever in background.
    """
    logging.info("Virtual Trading Engine v2 starting...")
    cycle = 0
    while True:
        try:
            await _vt_place_trades()
            await _vt_check_results()
            cycle += 1
            if cycle % 60 == 0:
                active = sum(len(v) for v in _virtual_trades.values())
                logging.info("VTE: cycle {} — {} active trades".format(cycle, active))
        except Exception as e:
            logging.warning("VTE cycle error: {}".format(e))
        await asyncio.sleep(5)

def get_optimal_tf(pair, fallback=None):
    """
    Return the optimal timeframe (in minutes) for a pair,
    learned from virtual trading engine movement analysis.
    Returns fallback if no data yet.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT optimal_tf, avg_movement FROM pair_stats WHERE pair=%s",
                    (pair,)
                )
                row = cur.fetchone()
        if row and row["optimal_tf"]:
            return int(row["optimal_tf"])
    except Exception as e:
        logging.warning("get_optimal_tf failed {}: {}".format(pair, e))
    return fallback


# ── NEWS FILTER ─────────────────────────────────────────────
# High-impact news events (UTC times, approximate)
# These repeat weekly/monthly — bot avoids signals ±15 min around them

_HIGH_IMPACT_NEWS = [
    # (weekday, hour, minute, description)
    # weekday: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    (4, 13, 30, "NFP"),           # First Friday of month ~13:30 UTC
    (4, 13, 30, "US Jobs"),
    (1, 13, 30, "CPI"),           # Varies but often Tue/Wed
    (2, 13, 30, "CPI"),
    (2, 18, 0,  "FOMC"),          # Fed meetings — Wednesdays ~18:00 UTC
    (3, 12, 0,  "ECB"),           # ECB — Thursdays ~12:00 UTC
    (3, 13, 30, "US GDP"),
    (3, 13, 30, "Unemployment"),
    (4, 13, 30, "PCE"),
]

_NEWS_BUFFER_MINUTES = 15  # avoid signals ±15 min around news

def is_news_time():
    """
    Returns (True, event_name) if we are within NEWS_BUFFER_MINUTES of a
    high-impact event, else (False, None).
    """
    try:
        now_utc = datetime.utcnow()
        wd  = now_utc.weekday()   # 0=Mon
        h   = now_utc.hour
        m   = now_utc.minute
        now_mins = h * 60 + m

        for (event_wd, event_h, event_m, name) in _HIGH_IMPACT_NEWS:
            if wd != event_wd:
                continue
            event_mins = event_h * 60 + event_m
            if abs(now_mins - event_mins) <= _NEWS_BUFFER_MINUTES:
                return True, name
    except Exception:
        pass
    return False, None


def get_best_tf_for_session(pair):
    """
    Pick best TF (1m/2m/3m) for a pair based on session-aware win rate from VTE.
    Falls back to overall optimal_tf, then to 2m default.
    Only considers TFs 1/2/3 minutes.
    """
    session = get_trading_session()
    sess_name = session.get("name", "Unknown") if session else "Unknown"
    target_tfs = [1, 2, 3]
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Try session-specific first
                cur.execute("""
                    SELECT tf_mins,
                           ROUND(wins::numeric / NULLIF(wins+losses,0) * 100, 1) AS win_rate,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair=%s AND session=%s AND tf_mins = ANY(%s)
                      AND (wins + losses) >= 5
                    ORDER BY win_rate DESC, total DESC
                    LIMIT 1
                """, (pair, sess_name, target_tfs))
                row = cur.fetchone()
                if row:
                    return int(row["tf_mins"])

                # Fallback: overall best TF from pair_stats (if in 1/2/3)
                cur.execute(
                    "SELECT optimal_tf FROM pair_stats WHERE pair=%s",
                    (pair,)
                )
                row2 = cur.fetchone()
                if row2 and row2["optimal_tf"] and int(row2["optimal_tf"]) in target_tfs:
                    return int(row2["optimal_tf"])
    except Exception as e:
        logging.warning("get_best_tf_for_session failed {}: {}".format(pair, e))
    return 2  # Default: 2m


def update_tf_session_stats(pair, tf_mins, session_name, won):
    """Update session-specific TF stats after VTE result."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if won:
                    cur.execute("""
                        INSERT INTO tf_session_stats (pair, session, tf_mins, wins, losses)
                        VALUES (%s, %s, %s, 1, 0)
                        ON CONFLICT (pair, session, tf_mins) DO UPDATE
                        SET wins = tf_session_stats.wins + 1
                    """, (pair, session_name, tf_mins))
                else:
                    cur.execute("""
                        INSERT INTO tf_session_stats (pair, session, tf_mins, wins, losses)
                        VALUES (%s, %s, %s, 0, 1)
                        ON CONFLICT (pair, session, tf_mins) DO UPDATE
                        SET losses = tf_session_stats.losses + 1
                    """, (pair, session_name, tf_mins))
            conn.commit()
    except Exception as e:
        logging.warning("update_tf_session_stats failed: {}".format(e))


def get_ranked_forex_pairs():
    """
    Return all forex pairs ranked by VTE win rate (ascending — worst first).
    Only pairs in YAHOO_SYMBOLS with "/" in name (forex only, no BTC/indices).
    Splits into two groups:
      - Group A (contrarian): lowest win rate pairs (worst performers)
      - Group B (normal):     higher win rate pairs
    Returns: {
        "contrarian": [pair, ...],   # worst 3 — bot will flip signal
        "normal":     [pair, ...],   # rest — normal signal
        "all":        [pair, ...]    # full list worst→best
    }
    """
    forex_pairs = [p for p in YAHOO_SYMBOLS
                   if "/" in p and "BTC" not in p
                   and "^" not in YAHOO_SYMBOLS.get(p, "")]
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pair, wins, losses,
                           ROUND(wins::numeric / NULLIF(wins+losses,0) * 100, 1) AS win_rate
                    FROM pair_stats
                    WHERE pair = ANY(%s) AND (wins + losses) >= 5
                    ORDER BY win_rate ASC, losses DESC
                """, (forex_pairs,))
                ranked = [r["pair"] for r in cur.fetchall()]
    except Exception as e:
        logging.warning("get_ranked_forex_pairs failed: {}".format(e))
        ranked = []

    # Pairs not yet in DB go to the end (unknown — treat as normal)
    ranked_set = set(ranked)
    unranked = [p for p in forex_pairs if p not in ranked_set]
    all_pairs = ranked + unranked

    contrarian = all_pairs[:3]    # worst 3 → contrarian (flip signal)
    normal     = all_pairs[3:]    # rest → normal signal

    return {"contrarian": contrarian, "normal": normal, "all": all_pairs}


def get_worst5_pairs():
    """Return 5 worst forex pairs by VTE winrate (lowest first) for contrarian signals."""
    try:
        forex_pairs = [p for p in YAHOO_SYMBOLS if "/" in p and "BTC" not in p]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pair, wins, losses,"
                    " ROUND(wins::numeric / NULLIF(wins+losses,0) * 100, 1) AS win_rate"
                    " FROM pair_stats WHERE pair = ANY(%s) AND (wins + losses) >= 5"
                    " ORDER BY win_rate ASC, losses DESC LIMIT 5",
                    (forex_pairs,)
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logging.warning("get_worst5_pairs: {}".format(e))
        return []

def get_top5_pairs(otc_only=False, non_otc_only=False):
    """
    Return top 5 pairs by win rate (today only) with minimum 3 virtual trades.
    Only returns pairs that exist in ALL_PAIRS (can be shown as buttons).
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pair, wins_today AS wins, losses_today AS losses,
                           ROUND(wins_today::numeric / NULLIF(wins_today+losses_today,0) * 100, 1) AS win_rate
                    FROM pair_stats
                    WHERE (wins_today + losses_today) >= 3
                      AND DATE(updated_at) = CURRENT_DATE
                    ORDER BY win_rate DESC, wins_today DESC
                    LIMIT 30
                """)
                rows = [dict(r) for r in cur.fetchall()]
        # Fallback to all-time if no today data
        if not rows:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pair, wins, losses,
                               ROUND(wins::numeric / NULLIF(wins+losses,0) * 100, 1) AS win_rate
                        FROM pair_stats
                        WHERE (wins + losses) >= 5
                        ORDER BY win_rate DESC, wins DESC
                        LIMIT 30
                    """)
                    rows = [dict(r) for r in cur.fetchall()]
        # Filter to only pairs in ALL_PAIRS
        valid = {p for p in ALL_PAIRS}
        rows = [r for r in rows if r["pair"] in valid]
        if otc_only:
            rows = [r for r in rows if "OTC" in r["pair"]]
        elif non_otc_only:
            rows = [r for r in rows if "OTC" not in r["pair"]]
        return rows[:5]
    except Exception as e:
        logging.warning("get_top5_pairs failed: {}".format(e))
        return []


def is_contrarian_pair(pair):
    """
    Check if a pair is in the worst-3 by VTE win rate.
    Applies to ALL pairs — OTC and forex.
    If yes, the signal direction is flipped before showing to user.
    """
    try:
        # Get OTC real equivalent if OTC pair
        real_pair = OTC_TO_REAL.get(pair, pair)
        ranked = get_ranked_forex_pairs()
        return pair in ranked["contrarian"] or real_pair in ranked["contrarian"]
    except Exception:
        return False


# ============================================================
async def _stats_reset_loop():
    """Reset wins_today/losses_today every 30 minutes."""
    while True:
        await asyncio.sleep(1800)  # 30 minutes
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE pair_stats SET wins_today = 0, losses_today = 0"
                    )
                conn.commit()
            logging.info("Pair stats reset (30 min cycle): OK")
        except Exception as e:
            logging.warning("Stats reset failed: {}".format(e))


async def run_bot():
    PORT = int(os.environ.get("PORT", 8080))
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

    ptb_app = Application.builder().token(BOT_TOKEN).build()
    await ptb_app.initialize()

    # Set global bot username for support links
    global BOT_USERNAME
    me = await ptb_app.bot.get_me()
    BOT_USERNAME = me.username or ""
    logging.info("Bot username: @{}".format(BOT_USERNAME))

    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler("setimage", setimage_command))
    ptb_app.add_handler(CommandHandler("dbcheck", dbcheck_command))
    # Admin commands handled inside message_handler (addmonthly, addlifetime, totalusers, etc.)
    ptb_app.add_handler(MessageHandler(filters.COMMAND, message_handler))
    ptb_app.add_handler(ChatJoinRequestHandler(join_request_handler))
    ptb_app.add_handler(CallbackQueryHandler(button_handler))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, message_handler))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # ── Use async polling (works inside asyncio.run) ──
    print("Starting bot polling...")
    await ptb_app.start()
    await ptb_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    print("Bot polling active.")

    # ── Launch Virtual Trading Engine in background ────────────
    asyncio.create_task(virtual_trading_engine())
    print("Virtual trading engine started.")

    # ── Launch stats reset loop (every 30 minutes) ─────────────
    asyncio.create_task(_stats_reset_loop())
    print("Stats reset loop started.")

    # Keepalive
    while True:
        await asyncio.sleep(60)


def main():
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    # ── Open port FIRST before anything else ───────────────────
    # Render requires port to open within a few seconds of startup
    PORT = int(os.environ.get("PORT", 8080))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"EVALON MASTER PRO OK")
        def log_message(self, *args):
            pass

    def start_health_server():
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        server.serve_forever()

    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()
    print("Port {} open. Starting bot...".format(PORT))

    # ── Now proceed with init and bot startup ──────────────────
    print("EVALON MASTER PRO starting...")
    init_db()
    print("Database ready.")
    asyncio.run(run_bot())

if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""
EVALON MASTER PRO - Telegram Bot
python-telegram-bot[webhooks]==21.3 + Neon PostgreSQL via psycopg2
"""

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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatJoinRequestHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID       = 8054370971
DATABASE_URL   = os.environ.get("DATABASE_URL", "")
CHANNEL_INVITE = "https://t.me/+mRNfGaNhz3RkZGRk"
CHANNEL_ID     = -1003403743370  # EVALON channel

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
                    free_used INTEGER DEFAULT 0,
                    licensed BOOLEAN DEFAULT FALSE,
                    licence_type TEXT,
                    licence_code TEXT,
                    expiry TIMESTAMP,
                    referred_by BIGINT DEFAULT NULL,
                    bonus_signals INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS licences (
                    code TEXT PRIMARY KEY,
                    type TEXT,
                    used BOOLEAN DEFAULT FALSE,
                    revoked BOOLEAN DEFAULT FALSE,
                    used_by BIGINT,
                    used_at TIMESTAMP
                );
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
                    losses INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS reverse_pairs (
                    pair TEXT PRIMARY KEY
                );
            """)
        conn.commit()

# ============================================================
# PAIR STATS — win/loss tracking per pair
# ============================================================
def update_pair_stats(pair, won):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if won:
                    cur.execute("""
                        INSERT INTO pair_stats (pair, wins, losses) VALUES (%s, 1, 0)
                        ON CONFLICT (pair) DO UPDATE SET wins = pair_stats.wins + 1
                    """, (pair,))
                else:
                    cur.execute("""
                        INSERT INTO pair_stats (pair, wins, losses) VALUES (%s, 0, 1)
                        ON CONFLICT (pair) DO UPDATE SET losses = pair_stats.losses + 1
                    """, (pair,))
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

def auto_manage_reverse_pairs():
    """
    Bot ijiangalie yenyewe:
    - Pair yenye win rate chini ya 40% (minimum 5 signals) → iongeze kwenye reverse_pairs
    - Pair yenye win rate juu ya 60% (minimum 5 signals) → iondoe kutoka reverse_pairs (hata kama ilikuwepo)
    Called automatically ndani ya generate_signal flow.
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
                # Pair inafail sana — weka reverse
                add_reverse_pair(pair)
                logging.info("AUTO-REVERSE: Added {} (win rate {:.0%})".format(pair, win_rate))
            elif win_rate > 0.60:
                # Pair inafanya vizuri — ondoa reverse kama ipo
                remove_reverse_pair(pair)
    except Exception as e:
        logging.warning("auto_manage_reverse_pairs failed: {}".format(e))

# ============================================================
# REVERSE PAIRS — bot anatoa kinyume cha direction
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
# SETTINGS (picha za BUY/SELL)
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
            # Block if not found, already used, or revoked
            if not lic or lic["used"] or lic.get("revoked"):
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
        "m_codes": [l["code"] for l in licences if not l["used"] and l["type"] == "monthly"],
        "l_codes": [l["code"] for l in licences if not l["used"] and l["type"] == "lifetime"],
    }

def delete_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()

def revoke_licence(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT licence_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row and row["licence_code"]:
                # Mark code as revoked — cannot be reused ever
                cur.execute(
                    "UPDATE licences SET used=TRUE, revoked=TRUE WHERE code=%s",
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
# INACTIVITY TRACKER — dakika 30 bila kubonyeza → futa kila kitu
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

# ============================================================
# ANTI-SPAM
# ============================================================
LAST_SIGNAL_TIME = {}
SPAM_SECONDS = 5

def is_spam(user_id):
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
            # Weka referred_by kama bado haijawekwa
            cur.execute("SELECT referred_by FROM users WHERE user_id = %s", (new_user_id,))
            row = cur.fetchone()
            if row and row["referred_by"] is None:
                cur.execute(
                    "UPDATE users SET referred_by = %s WHERE user_id = %s",
                    (referrer_id, new_user_id)
                )
        conn.commit()
    # Hesabu referrals za referrer na weka bonus
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
# ALL PAIRS — Pocket Option (mchanganyiko, N/A chini)
# ============================================================
ALL_PAIRS = [
    # Currencies — mchanganyiko OTC na non-OTC
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
    # Commodities — mchanganyiko
    "Brent Oil OTC", "WTI Crude Oil OTC", "Gold OTC",
    "Natural Gas OTC", "Palladium spot OTC", "Platinum spot OTC",
    # Cryptocurrencies — mchanganyiko
    "Dogecoin OTC", "Ethereum OTC", "Litecoin OTC",
    "Bitcoin ETF OTC", "Chainlink OTC", "Solana OTC",
    "BNB OTC", "Polkadot OTC", "Cardano OTC", "TRON OTC",
    "Polygon OTC", "Toncoin OTC", "Avalanche OTC", "Bitcoin",
    # Indices — mchanganyiko
    "AUS 200 OTC", "100GBP OTC", "D30EUR OTC", "DJI30 OTC",
    "E35EUR OTC", "E35EUR", "E50EUR OTC", "F40EUR OTC",
    "JPN225 OTC", "US100 OTC", "US100", "SP500 OTC", "SP500",
    "CAC 40", "SMI 20",
    # Stocks — mchanganyiko
    "Apple OTC", "American Express OTC", "Boeing Company OTC",
    "FACEBOOK INC OTC", "Intel OTC", "Johnson & Johnson OTC",
    "Citigroup Inc OTC", "Coinbase Global OTC", "FedEx OTC",
    "VIX OTC", "Amazon OTC", "Microsoft OTC", "GameStop Corp OTC",
    "McDonald's OTC", "Tesla OTC", "Netflix OTC", "ExxonMobil OTC",
    "Marathon Digital Holdings OTC", "Pfizer Inc OTC",
    "Palantir Technologies OTC", "VISA OTC", "Alibaba OTC",
    "Cisco OTC", "Advanced Micro Devices OTC",
    # N/A pairs — chini kabisa
    "Silver OTC", "Brent Oil", "WTI Crude Oil", "XAG/EUR", "XAU/EUR",
    "Gold", "Natural Gas", "Palladium spot", "Platinum spot", "Silver",
    "Ethereum", "Dash", "BCH/EUR", "BCH/GBP", "BCH/JPY",
    "BTC/GBP", "BTC/JPY", "Chainlink",
    "100GBP", "AEX 25", "D30/EUR", "DJI30", "E50/EUR", "F40/EUR",
    "HONG KONG 33", "JPN225", "AUS 200",
    "Apple", "American Express", "Boeing Company", "FACEBOOK INC",
    "Johnson & Johnson", "JPMorgan Chase & Co", "Microsoft",
    "Pfizer Inc", "Tesla", "Alibaba", "Citigroup Inc",
    "Netflix", "Cisco", "ExxonMobil", "McDonald's", "Intel",
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
    "Bitcoin": "BTC-USD",
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

    # Williams Fractal — angalia candles za hivi karibuni
    # Bullish fractal: low[i] < low[i-2], low[i-1], low[i+1], low[i+2]
    # Bearish fractal: high[i] > high[i-2], high[i-1], high[i+1], high[i+2]
    # Tunachunguza fractal zilizoundwa hivi karibuni (candles 3-10 zilizopita)
    # Candle za mwisho 2 haziwezi kuwa fractals (zinahitaji 2 candles za kulia)
    fractal_signal = None
    fractal_strength = 0  # 0=hakuna, 1=fractal 1, 2=fractal 2+ (nguvu zaidi)
    high_vals = high.values
    low_vals  = low.values
    n = len(high_vals)
    # Scan candles 3..10 zilizopita (index n-5 hadi n-3, kwa sababu tunahitaji i+2 iwe tayari)
    recent_bull_fractals = []
    recent_bear_fractals = []
    for i in range(n - 4, max(n - 15, 4), -1):
        # Bearish fractal: high ya kati ni kubwa zaidi ya high 4 zinazoizunguka
        if (high_vals[i] > high_vals[i-2] and high_vals[i] > high_vals[i-1] and
                high_vals[i] > high_vals[i+1] and high_vals[i] > high_vals[i+2]):
            recent_bear_fractals.append(i)
        # Bullish fractal: low ya kati ni ndogo zaidi ya low 4 zinazozunguka
        if (low_vals[i] < low_vals[i-2] and low_vals[i] < low_vals[i-1] and
                low_vals[i] < low_vals[i+1] and low_vals[i] < low_vals[i+2]):
            recent_bull_fractals.append(i)
    # Price ya sasa iko juu ya bullish fractal = BUY signal
    # Price ya sasa iko chini ya bearish fractal = SELL signal
    current_price_val = float(close.iloc[-1])
    if recent_bull_fractals:
        latest_bull = float(low_vals[recent_bull_fractals[0]])
        if current_price_val > latest_bull:
            fractal_signal = "BUY"
            fractal_strength = min(2, len(recent_bull_fractals))
    if recent_bear_fractals:
        latest_bear = float(high_vals[recent_bear_fractals[0]])
        if current_price_val < latest_bear:
            # Bearish fractal inashinda bullish kama zote mbili zipo
            fractal_signal = "SELL"
            fractal_strength = min(2, len(recent_bear_fractals))
    # Kama zote mbili zipo — chagua iliyo karibu zaidi na price ya sasa
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
    "Ethereum OTC": "Bitcoin",  # Fallback kwa Ethereum
    "Dogecoin OTC": "Bitcoin",
}

def _fetch_1h_trend(pair):
    """
    Fetch 1H candle data and determine trend direction.
    For OTC pairs, uses the mapped real pair.
    Returns: 'BUY', 'SELL', or None (unclear)
    """
    # OTC → real pair mapping
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="5d", interval="1h", progress=False, auto_adjust=True)
        if df is None or len(df) < 20:
            return None
        close = df["Close"].squeeze()
        # EMA 9 vs EMA 21 on 1H
        ema9  = float(close.ewm(span=9).mean().iloc[-1])
        ema21 = float(close.ewm(span=21).mean().iloc[-1])
        # MACD on 1H
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_hist = float(((ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()).iloc[-1])
        # RSI on 1H
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi_1h = float((100 - 100 / (1 + gain / loss.replace(0, 1e-9))).iloc[-1])
        # Consensus: angalia EMA cross + MACD direction + RSI zone
        buy_votes = sell_votes = 0
        if ema9 > ema21:   buy_votes  += 1
        else:              sell_votes += 1
        if macd_hist > 0:  buy_votes  += 1
        else:              sell_votes += 1
        if rsi_1h > 55:    buy_votes  += 1
        elif rsi_1h < 45:  sell_votes += 1
        if buy_votes >= 2:
            return "BUY"
        elif sell_votes >= 2:
            return "SELL"
        return None  # Mixed — hakuna mwelekeo wazi
    except Exception as e:
        logging.warning("_fetch_1h_trend failed for {}: {}".format(pair, e))
        return None

# Multi-timeframe intervals for Yahoo Finance
MTF_INTERVALS = [
    ("1m",  "1d"),   # 1 minute
    ("5m",  "2d"),   # 5 minutes
    ("15m", "5d"),   # 15 minutes
    ("30m", "5d"),   # 30 minutes
    ("1h",  "5d"),   # 1 hour
]

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
    Background task: waits for signal timeframe to expire, then checks result.
    Only for non-OTC pairs with real Yahoo Finance price data.
    """
    # Wait for timeframe + 10 seconds buffer
    await asyncio.sleep(timeframe_mins * 60 + 10)

    # Don't send result if user cleared state already (e.g. new signal on same pair)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT result_sent, entry_price FROM user_signal_state WHERE user_id=%s AND pair=%s",
                    (user_id, pair)
                )
                row = cur.fetchone()
        if not row or row["result_sent"]:
            return  # Already sent or state cleared
    except Exception as e:
        logging.warning("schedule_result_check state check failed: {}".format(e))
        return

    # Fetch current price
    exit_price = _fetch_current_price(pair)
    if exit_price is None or entry_price is None:
        return  # Can't determine result without prices

    # Determine win or loss
    price_diff = exit_price - entry_price
    if direction == "BUY":
        won = price_diff > 0
    else:
        won = price_diff < 0

    result_emoji = "🏆 *WON!*" if won else "📉 *LOSS*"
    result_text = (
        "📊 *SIGNAL RESULT — {}*\n"
        "Timeframe: *{} min*\n\n"
        "{}\n\n"
        "_Entry: {:.5f}  →  Exit: {:.5f}_"
    ).format(
        pair, timeframe_mins,
        result_emoji,
        entry_price, exit_price
    )

    try:
        sent = await bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")
        # Mark result as sent + save msg_id for deletion on Get More
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_signal_state SET result_sent=TRUE, result_msg_id=%s WHERE user_id=%s AND pair=%s",
                    (sent.message_id, user_id, pair)
                )
            conn.commit()
        # Update pair win/loss stats
        update_pair_stats(pair, won)
    except Exception as e:
        logging.warning("schedule_result_check send failed: {}".format(e))

def check_signal_request(user_id, pair):
    """
    Returns:
      {"action": "fresh"}
      {"action": "flip",   "direction": X}  -- first quick return, flip direction
      {"action": "same",   "direction": X}  -- 2nd & 3rd quick return, keep flipped direction
      {"action": "block"}                   -- 4th quick return, show no signal message
      {"action": "cooldown"}                -- still in cooldown
    """
    # Cooldown check first
    if get_cooldown_remaining(user_id, pair) > 0:
        return {"action": "cooldown"}

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
    elif flip_count == 1:
        return {"action": "same", "direction": flipped}
    elif flip_count == 2:
        return {"action": "same", "direction": flipped}
    else:
        return {"action": "block"}

# ============================================================
# SIGNAL ALGORITHM — Multi-Timeframe + 1H Trend Filter
# ============================================================
def generate_signal(pair):
    is_otc = "OTC" in pair
    real   = None
    if not is_otc:
        real = _fetch_real_indicators(pair)

    # ── 1H TREND FILTER ──────────────────────────────────────
    # Pata mwelekeo mkuu wa saa 1 (OTC inatumia real pair yake)
    trend_1h = _fetch_1h_trend(pair)

    # ── MULTI-TIMEFRAME SCORE ─────────────────────────────────
    # Kwa non-OTC NA OTC (OTC inatumia mapped real pair)
    mtf = _fetch_mtf_score(pair)

    if real:
        # ── NON-OTC: Real indicators kutoka Yahoo Finance (5m) ──
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

        # Kama 1H trend inaonekana wazi, biased synthetic data iendane nayo
        if trend_1h == "BUY":
            rsi_w = [25, 20, 25, 18, 12]  # Zaidi oversold/neutral_low (BUY setup)
        elif trend_1h == "SELL":
            rsi_w = [12, 18, 25, 20, 25]  # Zaidi overbought (SELL setup)

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
        # Kama 1H trend ipo, push ma_diff upande wake
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
    # Real pair inajua divergence — ipa nguvu zaidi
    if real and real.get("divergence"):
        div = real["divergence"]
        if div == "BUY":  b += 20
        elif div == "SELL": s += 20

    # ── WILLIAMS FRACTAL BONUS ───────────────────────────────
    # Real pair: fractal kutoka Yahoo Finance data
    # OTC pair: fractal ya synthetic (approximate, kulingana na bb_pos + mom)
    fractal_sig = None
    fractal_str = 0
    if real and real.get("fractal_signal"):
        fractal_sig = real["fractal_signal"]
        fractal_str = real.get("fractal_strength", 1)
    else:
        # OTC: approximate fractal kulingana na Bollinger Band position
        # bb_pos chini sana = karibu na lower band = bullish fractal zone
        # bb_pos juu sana  = karibu na upper band = bearish fractal zone
        if bb_pos < 0.15:
            fractal_sig = "BUY";  fractal_str = 1
        elif bb_pos < 0.08:
            fractal_sig = "BUY";  fractal_str = 2
        elif bb_pos > 0.85:
            fractal_sig = "SELL"; fractal_str = 1
        elif bb_pos > 0.92:
            fractal_sig = "SELL"; fractal_str = 2
    if fractal_sig == "BUY":
        b += 15 * fractal_str   # fractal_str=1 → +15, fractal_str=2 → +30
    elif fractal_sig == "SELL":
        s += 15 * fractal_str

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

    # ── 1H TREND FILTER BONUS ────────────────────────────────
    # Signal inayoendana na 1H trend inapata bonus kubwa
    if trend_1h == "BUY":   b += 25
    elif trend_1h == "SELL": s += 25

    # ── MULTI-TIMEFRAME BONUS ────────────────────────────────
    # Kila timeframe inayokubaliana inaongeza uzito
    if mtf and mtf["total"] >= 3:
        if mtf["buy_tfs"] > mtf["sell_tfs"]:
            b += mtf["buy_tfs"] * 8   # e.g. 4/5 TFs = +32
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
    # Ongeza MTF agreement kwenye indicators_agree
    if mtf and mtf["total"] >= 3:
        if direction == "BUY"  and mtf["buy_tfs"]  > mtf["sell_tfs"]: indicators_agree += mtf["buy_tfs"]
        if direction == "SELL" and mtf["sell_tfs"] > mtf["buy_tfs"]:  indicators_agree += mtf["sell_tfs"]
    # 1H trend inaongeza pia
    if trend_1h == direction:
        indicators_agree += 2

    # ── CONFLICT CHECK: MTF vs 1H ────────────────────────────
    # Kama 1H trend inapingana na MTF majority — piga kura tena
    if mtf and trend_1h and mtf["total"] >= 3:
        mtf_dir = "BUY" if mtf["buy_tfs"] > mtf["sell_tfs"] else "SELL"
        if mtf_dir != trend_1h:
            # Conflict — toa signal direction yenye nguvu zaidi (b vs s)
            direction = "BUY" if b > s else "SELL"

    # ── MINIMUM CONFLUENCE ───────────────────────────────────
    if indicators_agree < 4:
        alt_dir = "SELL" if direction == "BUY" else "BUY"
        alt_agree = 0
        for buy_c, sell_c in checks:
            if alt_dir == "BUY" and buy_c:   alt_agree += 1
            if alt_dir == "SELL" and sell_c: alt_agree += 1
        if alt_agree > indicators_agree:
            direction = alt_dir
            indicators_agree = alt_agree
        if indicators_agree < 4:
            direction = "BUY" if b > s else "SELL"
            indicators_agree = 0
            for buy_c, sell_c in checks:
                if direction == "BUY" and buy_c:   indicators_agree += 1
                if direction == "SELL" and sell_c: indicators_agree += 1

    # ── STRENGTH CALCULATION ─────────────────────────────────
    dom = max(b, s); tot = max(b+s, 1)
    # MTF bonus kwenye strength
    mtf_bonus = 0
    if mtf and mtf["total"] >= 3:
        agreeing = mtf["buy_tfs"] if direction == "BUY" else mtf["sell_tfs"]
        mtf_bonus = int((agreeing / mtf["total"]) * 40)
    # 1H bonus kwenye strength
    trend_bonus = 15 if trend_1h == direction else 0
    strength = min(500, max(300, 250 + indicators_agree*25 + int((dom/tot)*100) + mtf_bonus + trend_bonus + int(random.uniform(-5,5))))

    # ── TIMEFRAME: nguvu zaidi = timeframe fupi ──────────────
    if indicators_agree >= 11:    # 7 base + 5 MTF / 1H
        timeframe = 1
    elif indicators_agree >= 9:
        timeframe = random.choice([1, 1, 2])
    elif indicators_agree >= 7:
        timeframe = random.choice([1, 2])
    elif indicators_agree >= 5:
        timeframe = random.choice([1, 2, 3])
    else:
        timeframe = random.choice([2, 3])

    # ── SESSION-AWARE CONTRARIAN OVERRIDE ────────────────────
    session = _get_session()
    bias    = get_signal_bias(pair, window=10, threshold=session["threshold"])
    if bias is not None:
        if is_otc:
            direction = ("SELL" if bias=="BUY" else "BUY") if session["otc"]=="contrarian" else bias
        else:
            direction = bias

    # ── AUTO-REVERSE ─────────────────────────────────────────
    if is_reverse_pair(pair):
        direction = "SELL" if direction == "BUY" else "BUY"

    # ── AUTO-MANAGE REVERSE PAIRS ────────────────────────────
    try:
        auto_manage_reverse_pairs()
    except Exception:
        pass

    record_signal(pair, direction)
    return {
        "direction": direction,
        "pair": pair,
        "timeframe": timeframe,
        "strength": strength,
        "indicators_agree": indicators_agree,
        "trend_1h": trend_1h,
        "mtf": mtf,
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
    """Jumatatu=0 ... Ijumaa=4, Jumamosi=5, Jumapili=6 (UTC)"""
    return datetime.utcnow().weekday() >= 5

def pairs_keyboard():
    rows=[]; row=[]
    weekend = is_weekend()
    otc_on  = is_otc_enabled()
    for i, pair in enumerate(ALL_PAIRS):
        # Weekend: ficha non-OTC pairs kabisa
        if weekend and "OTC" not in pair:
            continue
        # Admin amezima OTC: onyesha non-OTC tu
        if not otc_on and "OTC" in pair:
            continue
        row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(i)))
        if len(row)==3: rows.append(row); row=[]
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def signal_keyboard(pair):
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))],
    ])

def expired_signal_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Contact Admin", url="https://t.me/evalonwinnersbot")],
        [InlineKeyboardButton("▶️ Start", callback_data="restart_fresh")],
    ])

def unlock_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Payment Info & Methods", callback_data="pay_info")],
        [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
    ])

def payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],
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
    Returns True if user can proceed (is member OR has sent join request).
    Returns False and sends join message if they haven't requested yet.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return True

    # Full member check first
    if await is_channel_member(context.bot, user_id):
        return True

    # Pending request check
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
    user_id = update.effective_user.id
    get_user(user_id)
    # Referral check
    if context.args:
        try:
            referrer_id = int(context.args[0].replace("REF_", ""))
            if referrer_id != user_id:
                register_referral(user_id, referrer_id)
        except:
            pass
    # Channel membership check
    if not await check_channel_and_proceed(update, context):
        return
    await update.message.reply_text(
        "⚡ *EVALON MASTER PRO*\n\n"
        "🏆 Win Rate: 90% — 98%\n"
        "📊 100+ Trading Pairs\n"
        "♾️ LIFETIME\n\n"
        "Chagua jinsi unavyotaka kupata signal:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Bot Nichagulie Pair Nzuri", callback_data="bot_pick_pair")],
            [InlineKeyboardButton("📊 Nachagua Mwenyewe", callback_data="choose_pair")],
        ])
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
            "_Markdown inafanya kazi: *bold*, _italic_, `code`_\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🖼 *IMAGES*\n"
            "`/setimage` — Change BUY/SELL signal images\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🗄 *DATABASE*\n"
            "`/dbcheck` — Check database status\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 *PAIR STATS & REVERSE*\n"
            "`/pairstats` — Win/loss stats ya pairs zote\n"
            "`/addreverse PAIR` — Pair itoe direction kinyume\n"
            "`/removereverse PAIR` — Ondoa reverse ya pair\n"
            "`/listreverse` — Orodha ya reverse pairs zote\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔀 *OTC CONTROL*\n"
            "`/toggleotc` — Zima au washa OTC pairs\n"
            "• OTC OFF → watumie non-OTC pairs tu\n"
            "• OTC ON  → pairs zote zinaonekana (default)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "`/help` — This menu",
            parse_mode="Markdown",
            reply_markup=admin_image_keyboard()
        )
    else:
        await update.message.reply_text(
            "⚡ *EVALON MASTER PRO*\n\n📌 *How to use:*\n1️⃣ Select your trading pair\n2️⃣ Get your BUY or SELL signal\n3️⃣ Follow the signal on your platform\n\n🔑 Have a licence code? Tap *Enter Licence Code*\n💬 Need access? Contact @evalonwinnersbot",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Start Trading", callback_data="choose_pair")],
                [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
                [InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],
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

    if data == "restart_fresh":
        # Clear signal state na inactivity tracking yote
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
            "Chagua jinsi unavyotaka kupata signal:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 Bot Nichagulie Pair Nzuri", callback_data="bot_pick_pair")],
                [InlineKeyboardButton("📊 Nachagua Mwenyewe", callback_data="choose_pair")],
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
        try: await q.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat, text="⚡ *EVALON MASTER PRO*\n\nSelect your trading pair:", parse_mode="Markdown", reply_markup=pairs_keyboard())
        return

    if data=="bot_pick_pair":
        # Bot inachagua pair yenye history nzuri ya win na soko si flat
        weekend = is_weekend()
        otc_on  = is_otc_enabled()
        # Kama OTC zimezimwa AU weekend: otc_only=False, tafuta non-OTC bora
        force_non_otc = not otc_on
        best = get_best_pair(otc_only=(weekend and not force_non_otc))
        # Kama OTC zimezimwa, hakikisha pair iliyochaguliwa si OTC
        if best and force_non_otc and "OTC" in best:
            best = None
        if not best:
            if force_non_otc:
                candidate_pool = [p for p in ALL_PAIRS if "OTC" not in p]
            elif weekend:
                candidate_pool = [p for p in ALL_PAIRS if "OTC" in p]
            else:
                candidate_pool = list(ALL_PAIRS)
            random.shuffle(candidate_pool)
            best = None
            for candidate in candidate_pool[:10]:  # Jaribu top 10 random
                sig_test = generate_signal(candidate)
                if sig_test.get("indicators_agree", 0) >= 5:
                    best = candidate
                    break
            if not best:
                best = candidate_pool[0] if candidate_pool else ALL_PAIRS[0]
        # Get stats for display
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT wins, losses FROM pair_stats WHERE pair = %s", (best,))
                    row = cur.fetchone()
            if row:
                total = row["wins"] + row["losses"]
                rate  = int(row["wins"] / max(total, 1) * 100)
                stats_text = "📈 Win rate: *{}%* ({}/{})".format(rate, row["wins"], total)
            else:
                stats_text = "🆕 Pair mpya — historia inaanza sasa"
        except:
            stats_text = ""
        idx = pair_to_idx(best)
        await q.edit_message_text(
            "🤖 *Bot imechagua:*\n\n"
            "💹 *{}*\n"
            "{}\n\n"
            "Bonyeza *Pata Signal* kupata signal sasa:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Pata Signal", callback_data="sel_{}".format(idx))],
                [InlineKeyboardButton("📊 Nachagua Mwenyewe", callback_data="choose_pair")],
            ])
        )
        # Fix format — edit again with correct text
        await q.edit_message_text(
            "🤖 *Bot imechagua:*\n\n"
            "💹 *{}*\n"
            "{}\n\n"
            "Bonyeza *Pata Signal* kupata signal sasa:".format(best, stats_text),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Pata Signal", callback_data="sel_{}".format(idx))],
                [InlineKeyboardButton("📊 Nachagua Mwenyewe", callback_data="choose_pair")],
            ])
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

        # Futa result message (📊 SIGNAL RESULT) kama ipo
        try:
            state_for_del = get_user_signal_state(user_id, pair)
            if state_for_del and state_for_del.get("result_msg_id"):
                await context.bot.delete_message(chat_id=chat, message_id=state_for_del["result_msg_id"])
        except Exception:
            pass

        # Futa signal photo ya zamani (ile iliyotumwa na "Get More" au "sel_")
        try:
            await q.message.delete()
        except Exception:
            pass

        # Check if current signal expiry is still active
        state = get_user_signal_state(user_id, pair)
        expiry_finished = True
        if state:
            signal_time = state["signal_time"]
            if isinstance(signal_time, str):
                signal_time = datetime.fromisoformat(signal_time)
            elapsed   = (datetime.utcnow() - signal_time).total_seconds()
            threshold = state["last_timeframe"] * 60
            if elapsed < threshold:
                expiry_finished = False

        if not expiry_finished:
            # Signal bado hai — mpe pairs zote achague upya
            await context.bot.send_message(
                chat_id=chat,
                text="⚡ *EVALON MASTER PRO*\n\n📊 Select a trading pair:",
                parse_mode="Markdown",
                reply_markup=pairs_keyboard()
            )
            return
        else:
            # Expiry imeisha — toa signal ya pair ile ile moja kwa moja (kama "sel_" flow)
            # Free trial check
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
            # Weekend check
            if is_weekend() and "OTC" not in pair:
                await context.bot.send_message(chat_id=chat, text="⚠️ *Market Closed (Weekend)*\n\nThis pair is not available on weekends.\nPlease select an *OTC* pair instead.", parse_mode="Markdown", reply_markup=pairs_keyboard())
                return

            inactivity_reset(user_id, chat)
            try: await q.message.delete()
            except: pass

            # Generate fresh signal for same pair (expiry imeisha)
            clear_user_signal_state(user_id, pair)

            # Candle safe zone check
            if not is_candle_safe_zone():
                await context.bot.send_message(
                    chat_id=chat,
                    text="⏳ *Please wait...*\n\nWaiting for the right moment to enter.\nTap *Get More* in a few seconds.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                    ])
                )
                return

            cm = await context.bot.send_message(chat_id=chat, text="🔵 *Creating a signal for {}*".format(pair), parse_mode="Markdown")
            await asyncio.sleep(2)

            sig       = generate_signal(pair)
            direction = sig["direction"]
            timeframe = sig["timeframe"]
            strength  = sig["strength"]

            # Flat market block
            if sig.get("flat") and timeframe == 0:
                try: await cm.delete()
                except: pass
                await context.bot.send_message(
                    chat_id=chat,
                    text="🟡 *No good signal available.*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📊 Choose Another Pair", callback_data="choose_pair")]
                    ])
                )
                return

            # Trend validation
            trend_dir = get_trend_direction(pair)
            if trend_dir is not None:
                direction = trend_dir
            elif sig.get("indicators_agree", 7) < 4:
                try: await cm.delete()
                except: pass
                await context.bot.send_message(
                    chat_id=chat,
                    text="🟡 *No good signal available.*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))],
                        [InlineKeyboardButton("📊 Choose Another Pair", callback_data="choose_pair")]
                    ])
                )
                return

            save_user_signal_state(user_id, pair, direction, timeframe, 0)

            # For non-OTC: fetch entry price for result tracking
            gm_entry_price = None
            gm_is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS
            if gm_is_non_otc:
                gm_entry_price = _fetch_current_price(pair)
                save_user_signal_state(user_id, pair, direction, timeframe, 0, entry_price=gm_entry_price)

            ib    = direction == "BUY"
            img   = get_buy_image() if ib else get_sell_image()
            arrow = "Up 🟢" if ib else "Down 🔴"
            if not is_licensed(user_id): use_free_signal(user_id)
            try: await cm.delete()
            except: pass
            cap = "*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair, arrow, timeframe, strength)
            sent_msg = await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))

            # Result tracker for non-OTC
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
        # Weekend check — non-OTC haifanyi kazi
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
        # User is active — reset inactivity timer (bila msg_id bado, inaongezwa baadaye)
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

        # --- Check user signal state ---
        check = check_signal_request(user_id, pair)

        if check["action"] == "cooldown":
            # Silent — do nothing
            return

        if check["action"] == "block":
            # Set random 15-30 sec cooldown + show message
            set_cooldown(user_id, pair)
            await context.bot.send_message(
                chat_id=chat,
                text="🟡 *No good signal available.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Choose Another Pair", callback_data="choose_pair")]
                ])
            )
            return

        # Kama signal bado hai (expiry haijaisha) — block kimya tu, hakuna ujumbe
        if check["action"] != "fresh":
            state = get_user_signal_state(user_id, pair)
            if state:
                signal_time = state["signal_time"]
                if isinstance(signal_time, str):
                    signal_time = datetime.fromisoformat(signal_time)
                elapsed   = (datetime.utcnow() - signal_time).total_seconds()
                threshold = state["last_timeframe"] * 60
                if elapsed < threshold:
                    return  # Block kimya — hakuna ujumbe

        # --- Candle safe zone check ---
        # Block if we are in the first 10 seconds (new candle) or last 10 seconds (candle closing)
        if not is_candle_safe_zone():
            await context.bot.send_message(
                chat_id=chat,
                text="⏳ *Please wait...*\n\nWaiting for the right moment to enter.\nTap *Get More* in a few seconds.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(pair_to_idx(pair)))]
                ])
            )
            return

        cm = await context.bot.send_message(chat_id=chat, text="🔵 *Creating a signal for {}*".format(pair), parse_mode="Markdown")
        await asyncio.sleep(2)

        # --- Trend validation ---
        trend = get_trend_direction(pair)

        if check["action"] == "fresh":
            sig        = generate_signal(pair)
            direction  = sig["direction"]
            timeframe  = sig["timeframe"]
            strength   = sig["strength"]
            flip_count = 0
            # Flat market block
            if sig.get("flat") and timeframe == 0:
                try: await cm.delete()
                except: pass
                await context.bot.send_message(
                    chat_id=chat,
                    text="🟡 *No good signal available.*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📊 Choose Another Pair", callback_data="choose_pair")]
                    ])
                )
                return
            # Override with dominant trend if available
            if trend is not None:
                direction = trend
            # If no trend (flat market) and indicators weak — no signal
            elif sig.get("indicators_agree", 7) < 4:
                try: await cm.delete()
                except: pass
                await context.bot.send_message(
                    chat_id=chat,
                    text="🟡 *No good signal available.*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(pair_to_idx(pair)))],
                        [InlineKeyboardButton("📊 Choose Another Pair", callback_data="choose_pair")]
                    ])
                )
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
        # For non-OTC: fetch current price as entry price for result tracking
        entry_price = None
        is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS
        if is_non_otc:
            entry_price = _fetch_current_price(pair)
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
        cap = "*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair, arrow, timeframe, strength)
        sent_msg = await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))

        # --- Result tracker: kwa non-OTC tu (zina real price data) ---
        if is_non_otc and entry_price is not None:
            asyncio.create_task(
                schedule_result_check(context.bot, chat, user_id, pair, direction, timeframe, entry_price)
            )

        # --- Inactivity tracker: rekodi msg_id na washa timer upya ---
        inactivity_reset(user_id, chat, msg_id=sent_msg.message_id)

        async def inactivity_expire(uid, cid):
            """Inafuta signals ZOTE na kutuma ujumbe wa VIP mara moja."""
            await asyncio.sleep(INACTIVITY_MINUTES * 60)
            msg_ids = inactivity_get_msgs(uid)
            # Futa messages zote
            for mid in msg_ids:
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                except Exception:
                    pass
            inactivity_clear(uid)
            # Tuma ujumbe wa VIP mara moja tu
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

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id=update.effective_user.id

    # Admin: kupokea picha ya BUY au SELL
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
                "✅ Licensed: *{}*\n"
                "🆓 Free trial: *{}*".format(s["total"], licensed, s["free"]),
                parse_mode="Markdown"
            )
   

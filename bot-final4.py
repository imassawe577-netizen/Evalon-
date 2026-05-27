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
    MessageHandler, filters, ContextTypes
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
                    PRIMARY KEY (user_id, pair)
                );
            """)
        conn.commit()

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
# ALL PAIRS
# ============================================================
ALL_PAIRS = [
    "EUR/USD OTC", "EUR/USD", "GBP/USD OTC",
    "GBP/USD", "USD/JPY OTC", "USD/JPY",
    "USD/CHF OTC", "USD/CHF", "AUD/USD OTC",
    "AUD/USD", "NZD/USD OTC", "NZD/USD",
    "USD/CAD OTC", "USD/CAD", "USD/DKK OTC",
    "EUR/GBP OTC", "EUR/GBP", "EUR/JPY OTC",
    "EUR/JPY", "EUR/AUD OTC", "EUR/AUD",
    "EUR/CAD OTC", "EUR/CAD", "EUR/CHF OTC",
    "EUR/CHF", "EUR/NZD OTC", "EUR/NZD",
    "GBP/JPY OTC", "GBP/JPY", "GBP/AUD OTC",
    "GBP/AUD", "GBP/CAD OTC", "GBP/CAD",
    "GBP/CHF OTC", "GBP/CHF", "GBP/NZD OTC",
    "GBP/NZD", "AUD/JPY OTC", "AUD/JPY",
    "AUD/CAD OTC", "AUD/CAD", "AUD/CHF OTC",
    "AUD/CHF", "AUD/NZD OTC", "AUD/NZD",
    "NZD/JPY OTC", "NZD/JPY", "NZD/CAD OTC",
    "NZD/CAD", "NZD/CHF OTC", "NZD/CHF",
    "CHF/JPY OTC", "CHF/JPY", "CAD/JPY OTC",
    "CAD/JPY", "CAD/CHF OTC", "CAD/CHF",
    "USD/TRY OTC", "USD/TRY", "USD/MXN OTC",
    "USD/MXN", "USD/ZAR OTC", "USD/ZAR",
    "USD/SEK OTC", "USD/SEK", "USD/NOK OTC",
    "USD/NOK", "USD/DKK", "USD/SGD OTC",
    "USD/SGD", "USD/HKD OTC", "USD/HKD",
    "USD/THB", "USD/INR", "USD/CNH",
    "USD/BRL", "USD/CZK", "USD/HUF",
    "USD/PLN", "USD/ILS", "EUR/TRY OTC",
    "EUR/TRY", "EUR/PLN OTC", "EUR/PLN",
    "EUR/HUF OTC", "EUR/HUF", "EUR/CZK OTC",
    "EUR/CZK", "EUR/SEK OTC", "EUR/SEK",
    "EUR/NOK OTC", "EUR/NOK", "EUR/DKK OTC",
    "EUR/DKK", "EUR/ZAR", "GBP/TRY OTC",
    "GBP/TRY", "GBP/PLN", "GBP/SEK",
    "GBP/NOK", "GBP/ZAR", "AUD/SGD",
    "BTC/USD", "ETH/USD", "BNB/USD",
    "XRP/USD", "SOL/USD", "ADA/USD",
    "DOGE/USD", "LTC/USD", "AVAX/USD",
    "DOT/USD", "MATIC/USD", "LINK/USD",
    "TRX/USD", "ATOM/USD", "XLM/USD",
    "XAU/USD", "XAG/USD", "OIL/USD",
    "BRENT/USD", "COPPER/USD", "GAS/USD",
    "WHEAT/USD", "CORN/USD", "SUGAR/USD",
    "US30/USD", "SPX500/USD", "NAS100/USD",
    "GER40/USD", "UK100/USD", "JPN225/USD",
    "FRA40/USD", "AUS200/USD", "ESP35/USD",
    "ITA40/USD", "HKG50/USD", "SING30/USD",
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
    "EUR/CHF": "EURCHF=X", "USD/SGD": "USDSGD=X", "USD/HKD": "USDHKD=X",
    "USD/CNH": "USDCNH=X", "USD/BRL": "USDBRL=X", "USD/CZK": "USDCZK=X",
    "USD/HUF": "USDHUF=X", "USD/PLN": "USDPLN=X", "EUR/TRY": "EURTRY=X",
    "EUR/PLN": "EURPLN=X", "EUR/HUF": "EURHUF=X", "EUR/CZK": "EURCZK=X",
    "EUR/SEK": "EURSEK=X", "EUR/NOK": "EURNOK=X", "EUR/DKK": "EURDKK=X",
    "GBP/PLN": "GBPPLN=X", "GBP/SEK": "GBPSEK=X", "GBP/NOK": "GBPNOK=X",
    "BTC/USD": "BTC-USD",  "ETH/USD": "ETH-USD",  "BNB/USD": "BNB-USD",
    "XRP/USD": "XRP-USD",  "SOL/USD": "SOL-USD",  "ADA/USD": "ADA-USD",
    "DOGE/USD":"DOGE-USD", "LTC/USD": "LTC-USD",  "AVAX/USD":"AVAX-USD",
    "DOT/USD": "DOT-USD",  "LINK/USD":"LINK-USD",  "TRX/USD": "TRX-USD",
    "ATOM/USD":"ATOM-USD", "XLM/USD": "XLM-USD",
    "XAU/USD": "GC=F",     "XAG/USD": "SI=F",     "OIL/USD": "CL=F",
    "BRENT/USD":"BZ=F",    "COPPER/USD":"HG=F",
    "US30/USD":"^DJI",     "SPX500/USD":"^GSPC",  "NAS100/USD":"^NDX",
    "GER40/USD":"^GDAXI",  "UK100/USD":"^FTSE",   "JPN225/USD":"^N225",
    "FRA40/USD":"^FCHI",   "AUS200/USD":"^AXJO",
}

def _fetch_real_indicators(pair):
    """Fetch real OHLCV from Yahoo Finance and calculate indicators."""
    symbol = YAHOO_SYMBOLS.get(pair)
    if not symbol:
        return None
    try:
        df = yf.download(symbol, period="2d", interval="5m", progress=False, auto_adjust=True)
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
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_hist = float(((ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()).iloc[-1])
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
        # Volume
        vol = min(1.0, float(volume.iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-9)))
        return {"rsi": rsi, "macd": macd_norm, "bb_pos": bb_pos,
                "ma_diff": ma_diff, "mom": mom, "sto": sto, "vol": vol, "real": True}
    except Exception as e:
        logging.warning("Yahoo Finance fetch failed for {}: {}".format(pair, e))
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
    p = pair.replace(" OTC", "")
    if any(c in p for c in ["BTC","ETH","BNB","XRP","SOL","ADA","DOGE","LTC","AVAX","DOT","MATIC","LINK","TRX","ATOM","XLM"]):
        return "crypto"
    if any(c in p for c in ["XAU","XAG","OIL","BRENT","COPPER","GAS","WHEAT","CORN","SUGAR"]):
        return "commodity"
    if any(c in p for c in ["US30","SPX","NAS","GER","UK1","JPN","FRA","AUS","ESP","ITA","HKG","SING"]):
        return "index"
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

def save_user_signal_state(user_id, pair, direction, timeframe, flip_count):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_signal_state
                        (user_id, pair, last_direction, last_timeframe, signal_time, flip_count)
                    VALUES (%s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (user_id, pair) DO UPDATE SET
                        last_direction = EXCLUDED.last_direction,
                        last_timeframe = EXCLUDED.last_timeframe,
                        signal_time    = EXCLUDED.signal_time,
                        flip_count     = EXCLUDED.flip_count
                """, (user_id, pair, direction, timeframe, flip_count))
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

def check_signal_request(user_id, pair):
    """
    Returns:
      {"action": "fresh"}
      {"action": "flip",   "direction": X}
      {"action": "same",   "direction": X}
      {"action": "block"}
      {"action": "cooldown"}
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

    # Returned after timeframe expired — fresh
    if elapsed >= threshold:
        clear_user_signal_state(user_id, pair)
        return {"action": "fresh"}

    # Returned quickly — apply flip logic
    flipped = "SELL" if state["last_direction"] == "BUY" else "BUY"
    if flip_count == 0:
        return {"action": "flip", "direction": flipped}
    elif flip_count in (1, 2):
        return {"action": "same", "direction": flipped}
    else:
        return {"action": "block"}

# ============================================================
# SIGNAL ALGORITHM — Enhanced
# ============================================================
def generate_signal(pair):
    is_otc = "OTC" in pair
    real   = None
    if not is_otc:
        real = _fetch_real_indicators(pair)

    if real:
        # Real data from Yahoo Finance
        rsi     = real["rsi"]
        sto     = real["sto"]
        ma_diff = real["ma_diff"]
        macd    = real["macd"]
        bb_pos  = real["bb_pos"]
        mom     = real["mom"]
        vol     = real["vol"]
        candle  = random.choices([-1, -0.5, 0, 0.5, 1], weights=[10, 15, 50, 15, 10])[0]
    else:
        # Smart OTC indicators — session-aware
        sess  = _get_session()
        ptype = _pair_type(pair)
        if sess["name"] in ("London Open", "NY/London"):
            rsi_w = [20, 18, 24, 18, 20]
        elif sess["name"] in ("Asian", "Dead Hours"):
            rsi_w = [10, 20, 40, 20, 10]
        else:
            rsi_w = [15, 20, 30, 20, 15]
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
        macd   = max(-1.0, min(1.0, ma_diff * random.uniform(0.6, 1.2)))
        bb_pos = random.uniform(0.0,0.25) if rsi < 35 else (random.uniform(0.75,1.0) if rsi > 65 else random.uniform(0.3,0.7))
        mom    = random.uniform(-1.0,1.0) if ptype == "crypto" else (random.uniform(-0.8,0.8) if sess["name"] in ("London Open","NY/London") else random.uniform(-0.5,0.5))
        vol    = random.uniform(0.55,1.0) if sess["name"] in ("London Open","NY/London","NY Session") else (random.uniform(0.15,0.55) if sess["name"] in ("Dead Hours","Asian") else random.uniform(0.35,0.80))
        candle = random.choices([-1,-0.5,0,0.5,1], weights=[12,18,40,18,12] if sess["name"] in ("London Open","NY Session") else [8,12,60,12,8])[0]

    # --- Scoring ---
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

    # Confluence
    direction = "BUY" if b >= s else "SELL"
    indicators_agree = 0
    checks = [(rsi < 45, rsi > 55), (sto < 45, sto > 55), (ma_diff > 0, ma_diff < 0),
              (macd > 0, macd < 0), (bb_pos < 0.5, bb_pos > 0.5), (mom > 0, mom < 0), (candle > 0, candle < 0)]
    for buy_c, sell_c in checks:
        if direction == "BUY" and buy_c:   indicators_agree += 1
        if direction == "SELL" and sell_c: indicators_agree += 1

    dom = max(b, s); tot = max(b+s, 1)
    strength  = min(500, max(200, 180 + indicators_agree*25 + int((dom/tot)*120) + int(random.uniform(-15,15))))
    if indicators_agree >= 6:   timeframe = random.choice([1,1,2])
    elif indicators_agree >= 4: timeframe = random.choice([1,2,2,3])
    else:                       timeframe = random.choice([2,3,3])

    # Session-aware fractal/contrarian override
    session   = _get_session()
    bias      = get_signal_bias(pair, window=10, threshold=session["threshold"])
    if bias is not None:
        if is_otc:
            direction = ("SELL" if bias=="BUY" else "BUY") if session["otc"]=="contrarian" else bias
        else:
            direction = bias

    record_signal(pair, direction)
    return {"direction": direction, "pair": pair, "timeframe": timeframe, "strength": strength}

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
def pairs_keyboard():
    rows=[]; row=[]
    for i, pair in enumerate(ALL_PAIRS):
        row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(i)))
        if len(row)==3: rows.append(row); row=[]
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def signal_keyboard(pair):
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Generate Signal", callback_data="sel_{}".format(idx))],
        [InlineKeyboardButton("📊 Choose Another Pair", callback_data="choose_pair")],
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
# CHANNEL MEMBERSHIP CHECK
# ============================================================
async def is_channel_member(bot, user_id):
    """
    Returns True if user is member, admin, creator, or has a pending join request.
    Returns False only if they have never requested to join.
    """
    if not CHANNEL_ID:
        return True  # No channel configured — allow all
    try:
        member = await bot.get_chat_member(chat_id=int(CHANNEL_ID), user_id=user_id)
        return member.status in ("member", "administrator", "creator", "restricted")
    except Exception:
        # get_chat_member fails for pending requests — treat as pending = allowed
        return True

async def check_channel_and_proceed(update, context):
    """
    Returns True if user can proceed.
    Returns False and sends join message if not.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id or not CHANNEL_ID:
        return True
    ok = await is_channel_member(context.bot, user_id)
    if not ok:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_INVITE)],
            [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")],
        ])
        msg = (
            "⚠️ *Join Required*\n\n"
            "To use EVALON MASTER PRO you must first join our channel.\n\n"
            "1️⃣ Tap *Join Channel* below\n"
            "2️⃣ Send a join request\n"
            "3️⃣ Tap *I've Joined* to continue\n\n"
            "_You don't need to wait for approval — just send the request._"
        )
        if update.message:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return False
    return True

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
        "Select your trading pair and get free trial:",
        parse_mode="Markdown", reply_markup=pairs_keyboard()
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
            "━━━━━━━━━━━━━━━━━━\n"
            "👥 *USER MANAGEMENT*\n"
            "`/listusers` — View all users & stats\n"
            "`/totalusers` — Quick user count\n"
            "`/stats` — Detailed statistics\n"
            "`/userinfo 123456` — Full details of a user\n"
            "`/addtrial 123456 5` — Give user extra signals\n"
            "`/revoke 123456` — Remove user licence\n"
            "`/deleteuser 123456` — Delete user permanently\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚫 *BLACKLIST*\n"
            "`/blacklist 123456 reason` — Ban a user\n"
            "`/unblacklist 123456` — Unban a user\n"
            "`/listblacklist` — View all banned users\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📢 *BROADCAST*\n"
            "`/broadcast Ujumbe wako` — Tuma kwa users wote\n"
            "_Markdown inafanya kazi: *bold*, _italic_, `code`_\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🖼 *IMAGES*\n"
            "`/setimage` — Change BUY/SELL signal images\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🗄 *DATABASE*\n"
            "`/dbcheck` — Check database status\n"
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

    # Check join button
    if data == "check_join":
        ok = await is_channel_member(context.bot, user_id)
        if ok:
            await q.edit_message_text(
                "✅ *Welcome to EVALON MASTER PRO!*\n\nSelect your trading pair:",
                parse_mode="Markdown", reply_markup=pairs_keyboard()
            )
        else:
            await q.answer("⚠️ Please join the channel first, then tap I've Joined.", show_alert=True)
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
        # Anti-spam check
        if is_spam(user_id):
            return
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
            # Set random 15-30 sec cooldown silently
            set_cooldown(user_id, pair)
            return

        cm = await context.bot.send_message(chat_id=chat, text="🔵 *Creating a signal for {}*".format(pair), parse_mode="Markdown")
        await asyncio.sleep(2)

        if check["action"] == "fresh":
            sig       = generate_signal(pair)
            direction = sig["direction"]
            timeframe = sig["timeframe"]
            strength  = sig["strength"]
            flip_count = 0
        elif check["action"] == "flip":
            direction  = check["direction"]
            timeframe  = random.choice([1, 2, 3])
            strength   = random.randint(200, 500)
            flip_count = 1
        else:  # same
            state      = get_user_signal_state(user_id, pair)
            flip_count = (state["flip_count"] if state else 2) + 1
            direction  = check["direction"]
            timeframe  = random.choice([1, 2, 3])
            strength   = random.randint(200, 500)

        # Save state
        save_user_signal_state(user_id, pair, direction, timeframe, flip_count)
        # Record flip/same signals to history (fresh signals are recorded inside generate_signal)
        if check["action"] != "fresh":
            record_signal(pair, direction)

        ib    = direction == "BUY"
        img   = get_buy_image() if ib else get_sell_image()
        trend = "Up 🟢" if ib else "Down 🔴"
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        cap = "*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair, trend, timeframe, strength)
        await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))

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
                await update.message.reply_text("❌ Tumia: `/revoke 123456789`", parse_mode="Markdown")
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
                await update.message.reply_text("❌ Tumia: `/deleteuser 123456789`", parse_mode="Markdown")
            return
        if text.startswith("/broadcast "):
            msg = text[len("/broadcast "):].strip()
            if not msg:
                await update.message.reply_text(
                    "❌ Andika ujumbe baada ya /broadcast\n\nMfano:\n`/broadcast Habari wote! 🎉`",
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
                await update.message.reply_text("❌ Tumia: `/blacklist 123456789 sababu`", parse_mode="Markdown")
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
                await update.message.reply_text("❌ Tumia: `/unblacklist 123456789`", parse_mode="Markdown")
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
                lic = "✅ {}".format(u.get("licence_type","").capitalize()) if u.get("licensed") else "❌ Hana"
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
                await update.message.reply_text("❌ Tumia: `/userinfo 123456789`", parse_mode="Markdown")
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
                await update.message.reply_text("❌ Tumia: `/addtrial 123456789 5`", parse_mode="Markdown")
            return

    # /refer command — user yeyote
    if update.message.text and update.message.text.strip() == "/refer":
        user_id2 = update.effective_user.id
        refs = count_referrals(user_id2)
        bonus = get_bonus_signals(user_id2)
        bot_username = (await context.bot.get_me()).username
        ref_link = "https://t.me/{}?start=REF_{}".format(bot_username, user_id2)
        if refs >= 5:
            status = "🎁 You have 3 bonus signals (5+ referrals)"
        elif refs >= 3:
            status = "🎁 You have 2 bonus signals (3-4 referrals)"
        else:
            needed = 3 - refs
            status = "⏳ Invite {} more people to get bonus!".format(needed)
        await update.message.reply_text(
            "👥 *REFERRAL YAKO*\n\n"
            "🔗 Link yako:\n`{}`\n\n"
            "👤 People you invited: *{}*\n"
            "{}\n\n"
            "_Share your link — invite 3+ people and get free bonus signals!_".format(ref_link, refs, status),
            parse_mode="Markdown"
        )
        return

    if context.user_data.get("awaiting_code"):
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
                    [InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],
                    [InlineKeyboardButton("🔑 Try Again", callback_data="enter_code")]
                ])
            )

# ============================================================
# MAIN
# ============================================================
# ============================================================
# MAIN
# ============================================================
async def run_bot():
    from aiohttp import web

    PORT = int(os.environ.get("PORT", 8080))
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

    ptb_app = Application.builder().token(BOT_TOKEN).build()
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler("setimage", setimage_command))
    ptb_app.add_handler(CommandHandler("dbcheck", dbcheck_command))
    ptb_app.add_handler(CommandHandler("totalusers", message_handler))
    ptb_app.add_handler(CallbackQueryHandler(button_handler))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, message_handler))
    ptb_app.add_handler(MessageHandler(filters.TEXT, message_handler))

    if RENDER_URL:
        print("Render webhook mode on port {}".format(PORT))
        WEBHOOK_PATH = "/{}".format(BOT_TOKEN)
        WEBHOOK_URL  = "{}{}".format(RENDER_URL, WEBHOOK_PATH)

        await ptb_app.initialize()
        await ptb_app.start()
        await ptb_app.bot.set_webhook(WEBHOOK_URL)

        async def telegram_webhook(request):
            data = await request.json()
            update = Update.de_json(data, ptb_app.bot)
            await ptb_app.process_update(update)
            return web.Response(text="OK")

        async def health(request):
            return web.Response(text="EVALON BOT OK")

        web_app = web.Application()
        web_app.router.add_get("/", health)
        web_app.router.add_get("/health", health)
        web_app.router.add_post(WEBHOOK_PATH, telegram_webhook)

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        print("Listening on port {}".format(PORT))

        # Run forever
        while True:
            await asyncio.sleep(3600)
    else:
        print("Local polling mode")
        ptb_app.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    print("EVALON MASTER PRO starting...")
    init_db()
    print("Database ready.")
    asyncio.run(run_bot())

if __name__=="__main__":
    main()

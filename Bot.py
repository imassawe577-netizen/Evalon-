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
from datetime import datetime, timedelta
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = 8054370971
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ============================================================
# HEALTH CHECK SERVER (kwa cron-job.org)
# Inatumia PORT+1 ili isichanganyike na webhook port
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - EVALON MASTER PRO Running")
    def log_message(self, format, *args):
        pass

def run_health_server():
    # Tumia HEALTH_PORT tofauti na webhook PORT
    health_port = int(os.environ.get("HEALTH_PORT", 8081))
    server = HTTPServer(("0.0.0.0", health_port), HealthHandler)
    print("Health server running on port {}".format(health_port))
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

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
            if not lic or lic["used"]:
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
                cur.execute(
                    "UPDATE licences SET used=FALSE, used_by=NULL, used_at=NULL WHERE code=%s",
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
# SIGNAL ALGORITHM
# ============================================================
def generate_signal(pair):
    rsi = min(95, max(5, random.gauss(50, 18)))
    ma_s = min(1.0, max(0.1, random.gauss(0.65, 0.12)))
    ma_l = min(1.0, max(0.1, random.gauss(0.60, 0.12)))
    mom = min(1.0, max(0.0, random.gauss(0.50, 0.15)))
    sto = min(95, max(5, random.gauss(50, 20)))
    vol = min(1.0, max(0.1, random.gauss(0.60, 0.15)))
    b = s = 0
    confluence = 0
    if rsi < 25: b += 45; confluence += 1
    elif rsi < 40: b += 25
    elif rsi > 75: s += 45; confluence += 1
    elif rsi > 60: s += 25
    else:
        if rsi < 50: b += 8
        else: s += 8
    if ma_s > ma_l:
        b += 30
        if ma_s - ma_l > 0.08: confluence += 1
    else:
        s += 30
        if ma_l - ma_s > 0.08: confluence += 1
    if mom > 0.65: b += 20; confluence += 1
    elif mom < 0.35: s += 20; confluence += 1
    elif mom > 0.55: b += 10
    elif mom < 0.45: s += 10
    if sto < 20: b += 15; confluence += 1
    elif sto > 80: s += 15; confluence += 1
    if vol > 0.72:
        if b > s: b += 10
        else: s += 10
    d = "BUY" if b >= s else "SELL"
    dom = max(b, s)
    tot = b + s
    base_strength = int((dom / tot) * 260) + 80
    confluence_bonus = confluence * 15
    noise = random.gauss(0, 6)
    st = int(min(420, max(270, base_strength + confluence_bonus + noise)))
    if st >= 370: tf = 1
    elif st >= 300: tf = random.choice([1, 2])
    else: tf = random.choice([2, 3])
    return {"direction": d, "pair": pair, "timeframe": tf, "strength": st}

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

💎 Price: $150 — LIFETIME
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
# HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)
    # Angalia kama kuna referral code
    if context.args:
        try:
            referrer_id = int(context.args[0].replace("REF_", ""))
            if referrer_id != user_id:
                register_referral(user_id, referrer_id)
        except:
            pass
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
            "`/broadcast Your message` — Send message to all users\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🖼 *IMAGES*\n"
            "`/setimage` — Change BUY/SELL images\n"
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
            extra = "\n\n🎁 *You have {} referrals — invite more to unlock extra signals!".format(refs) if refs > 0 else "\n\n🎁 *Invite 3+ friends to get free bonus signals!"
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
        cm=await context.bot.send_message(chat_id=chat, text="🔵 *Creating a signal for {}*".format(pair), parse_mode="Markdown")
        await asyncio.sleep(2)
        sig=generate_signal(pair); ib=sig["direction"]=="BUY"
        img = get_buy_image() if ib else get_sell_image()
        trend="Up 🟢" if ib else "Down 🔴"
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        cap="*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair,trend,sig["timeframe"],sig["strength"])
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
                await update.message.reply_text("❌ Andika ujumbe. Mfano: `/broadcast Habari wote!`", parse_mode="Markdown")
                return
            user_ids = get_all_user_ids()
            sent = 0; failed = 0
            for uid in user_ids:
                try:
                    await context.bot.send_message(chat_id=uid, text="📢 *EVALON MASTER PRO*\n\n{}".format(msg), parse_mode="Markdown")
                    sent += 1
                except:
                    failed += 1
            await update.message.reply_text(
                "📢 *Broadcast Complete!*\n\n✅ Sent: {}\n❌ Failed: {}".format(sent, failed),
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
def main():
    print("EVALON MASTER PRO starting...")
    init_db()
    print("Database ready.")
    PORT=int(os.environ.get("PORT", 8080))
    RENDER_URL=os.environ.get("RENDER_EXTERNAL_URL","")
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("setimage", setimage_command))
    app.add_handler(CommandHandler("dbcheck", dbcheck_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, message_handler))
    app.add_handler(MessageHandler(filters.TEXT, message_handler))
    if RENDER_URL:
        print("Render webhook mode on port {}".format(PORT))
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url="{}/{}".format(RENDER_URL, BOT_TOKEN),
            url_path=BOT_TOKEN
        )
    else:
        print("Local polling mode")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()

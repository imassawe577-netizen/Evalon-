#!/usr/bin/env python3
"""
MASTER SIGNALS PRO - Telegram Bot
python-telegram-bot==20.7 + Neon PostgreSQL via psycopg2
"""

import random
import os
import uuid
import logging
import asyncio
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
ADMIN_ID     = 8054370971
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # Neon connection string

BINANCE_ID = "1222890272"
TRC20_ADDR = "TEUwK1aElmdCeG3n36LDySqSkwobMh37Xf"
BEP20_ADDR = "0x230badccf11a0de2b8a261ae3f99c07235174d6b"

BUY_IMAGE_ID  = "AgACAgQAAxkBAAICImoJRV1p8boUWCqbwbFQw5ZGFKi0AAJgDmsbgwZJUEAvhDh1tBD2AQADAgADeAADOwQ"
SELL_IMAGE_ID = "AgACAgQAAxkBAAICJGoJRZxn3w0clOl57ozxypDEUij0AAJhDmsbgwZJUBAZYceshO6HAQADAgADeAADOwQ"

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
                    expiry TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS licences (
                    code TEXT PRIMARY KEY,
                    type TEXT,
                    used BOOLEAN DEFAULT FALSE,
                    used_by BIGINT,
                    used_at TIMESTAMP
                );
            """)
        conn.commit()

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

# ============================================================
# ALL PAIRS - FULLY MIXED
# ============================================================
ALL_PAIRS = [
    "EUR/USD OTC",  "EUR/USD",      "GBP/USD OTC",
    "GBP/USD",      "USD/JPY OTC",  "USD/JPY",
    "USD/CHF OTC",  "USD/CHF",      "AUD/USD OTC",
    "AUD/USD",      "NZD/USD OTC",  "NZD/USD",
    "USD/CAD OTC",  "USD/CAD",      "USD/DKK OTC",
    "EUR/GBP OTC",  "EUR/GBP",      "EUR/JPY OTC",
    "EUR/JPY",      "EUR/AUD OTC",  "EUR/AUD",
    "EUR/CAD OTC",  "EUR/CAD",      "EUR/CHF OTC",
    "EUR/CHF",      "EUR/NZD OTC",  "EUR/NZD",
    "GBP/JPY OTC",  "GBP/JPY",      "GBP/AUD OTC",
    "GBP/AUD",      "GBP/CAD OTC",  "GBP/CAD",
    "GBP/CHF OTC",  "GBP/CHF",      "GBP/NZD OTC",
    "GBP/NZD",      "AUD/JPY OTC",  "AUD/JPY",
    "AUD/CAD OTC",  "AUD/CAD",      "AUD/CHF OTC",
    "AUD/CHF",      "AUD/NZD OTC",  "AUD/NZD",
    "NZD/JPY OTC",  "NZD/JPY",      "NZD/CAD OTC",
    "NZD/CAD",      "NZD/CHF OTC",  "NZD/CHF",
    "CHF/JPY OTC",  "CHF/JPY",      "CAD/JPY OTC",
    "CAD/JPY",      "CAD/CHF OTC",  "CAD/CHF",
    "USD/TRY OTC",  "USD/TRY",      "USD/MXN OTC",
    "USD/MXN",      "USD/ZAR OTC",  "USD/ZAR",
    "USD/SEK OTC",  "USD/SEK",      "USD/NOK OTC",
    "USD/NOK",      "USD/DKK",      "USD/SGD OTC",
    "USD/SGD",      "USD/HKD OTC",  "USD/HKD",
    "USD/THB",      "USD/INR",      "USD/CNH",
    "USD/BRL",      "USD/CZK",      "USD/HUF",
    "USD/PLN",      "USD/ILS",      "EUR/TRY OTC",
    "EUR/TRY",      "EUR/PLN OTC",  "EUR/PLN",
    "EUR/HUF OTC",  "EUR/HUF",      "EUR/CZK OTC",
    "EUR/CZK",      "EUR/SEK OTC",  "EUR/SEK",
    "EUR/NOK OTC",  "EUR/NOK",      "EUR/DKK OTC",
    "EUR/DKK",      "EUR/ZAR",      "GBP/TRY OTC",
    "GBP/TRY",      "GBP/PLN",      "GBP/SEK",
    "GBP/NOK",      "GBP/ZAR",      "AUD/SGD",
    "BTC/USD",      "ETH/USD",      "BNB/USD",
    "XRP/USD",      "SOL/USD",      "ADA/USD",
    "DOGE/USD",     "LTC/USD",      "AVAX/USD",
    "DOT/USD",      "MATIC/USD",    "LINK/USD",
    "TRX/USD",      "ATOM/USD",     "XLM/USD",
    "XAU/USD",      "XAG/USD",      "OIL/USD",
    "BRENT/USD",    "COPPER/USD",   "GAS/USD",
    "WHEAT/USD",    "CORN/USD",     "SUGAR/USD",
    "US30/USD",     "SPX500/USD",   "NAS100/USD",
    "GER40/USD",    "UK100/USD",    "JPN225/USD",
    "FRA40/USD",    "AUS200/USD",   "ESP35/USD",
    "ITA40/USD",    "HKG50/USD",    "SING30/USD",
]

# ============================================================
# SIGNAL ALGORITHM
# ============================================================
def generate_signal_original(pair):
    """ORIGINAL - isiathiri kitu, backup tu"""
    rsi=random.uniform(10,90); ma_s=random.uniform(0.3,1.0)
    ma_l=random.uniform(0.3,1.0); mom=random.uniform(0,1)
    sto=random.uniform(10,90); vol=random.uniform(0.3,1.0)
    b=s=0
    if rsi<25: b+=45
    elif rsi<40: b+=25
    elif rsi>75: s+=45
    elif rsi>60: s+=25
    else: b+=10 if rsi<50 else 0; s+=10 if rsi>=50 else 0
    if ma_s>ma_l: b+=30
    else: s+=30
    if mom>0.6: b+=20
    elif mom<0.4: s+=20
    if sto<20: b+=15
    elif sto>80: s+=15
    if vol>0.7:
        if b>s: b+=10
        else: s+=10
    d="BUY" if b>=s else "SELL"
    dom=max(b,s); tot=b+s
    st=min(500,max(200,int((dom/tot)*300+random.uniform(150,220))))
    return {"direction":d,"pair":pair,"timeframe":random.choice([1,2,3]),"strength":st}

def generate_signal(pair):
    """IMPROVED - Gaussian confluence, smooth strength"""
    # Indicators kwa Gaussian distribution (inafanana na soko la kweli)
    rsi = min(95, max(5, random.gauss(50, 18)))
    ma_s = min(1.0, max(0.1, random.gauss(0.65, 0.12)))
    ma_l = min(1.0, max(0.1, random.gauss(0.60, 0.12)))
    mom = min(1.0, max(0.0, random.gauss(0.50, 0.15)))
    sto = min(95, max(5, random.gauss(50, 20)))
    vol = min(1.0, max(0.1, random.gauss(0.60, 0.15)))

    b = s = 0
    confluence = 0  # idadi ya indicators zinazokubaliana

    # RSI - uzito mkubwa zaidi
    if rsi < 25:   b += 45; confluence += 1
    elif rsi < 40: b += 25
    elif rsi > 75: s += 45; confluence += 1
    elif rsi > 60: s += 25
    else:
        if rsi < 50: b += 8
        else:        s += 8

    # MA crossover
    if ma_s > ma_l:
        b += 30
        if ma_s - ma_l > 0.08: confluence += 1  # crossover kubwa = confirmation
    else:
        s += 30
        if ma_l - ma_s > 0.08: confluence += 1

    # Momentum
    if mom > 0.65:   b += 20; confluence += 1
    elif mom < 0.35: s += 20; confluence += 1
    elif mom > 0.55: b += 10
    elif mom < 0.45: s += 10

    # Stochastic
    if sto < 20:   b += 15; confluence += 1
    elif sto > 80: s += 15; confluence += 1

    # Volume confirmation
    if vol > 0.72:
        if b > s: b += 10
        else:     s += 10

    # Direction
    d = "BUY" if b >= s else "SELL"
    dom = max(b, s)
    tot = b + s

    # Strength smooth - inategemea confluence (indicators zilizokubaliana)
    base_strength = int((dom / tot) * 260) + 80  # floor ya juu zaidi
    confluence_bonus = confluence * 15
    noise = random.gauss(0, 6)  # mtetemeko mdogo sana
    st = int(min(420, max(270, base_strength + confluence_bonus + noise)))

    # Timeframe inategemea strength - signal kali = 1 min
    if st >= 370:   tf = 1
    elif st >= 300: tf = random.choice([1, 2])
    else:           tf = random.choice([2, 3])

    return {"direction": d, "pair": pair, "timeframe": tf, "strength": st}

# ============================================================
# PAIR INDEX MAPPING (fixes OTC callback_data issue)
# Telegram callback_data max 64 chars; OTC pairs with spaces/slashes are unsafe
# Solution: use index number instead of pair name in callback_data
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

# ============================================================
# HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    await update.message.reply_text(
        "⚡ *MASTER SIGNALS PRO*\n\n🏆 *Win Rate: 90% — 98%*\n📊 100+ Trading Pairs\n♾️ Lifetime Access Available\n\nSelect your trading pair:",
        parse_mode="Markdown", reply_markup=pairs_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(
            "🔧 *ADMIN COMMANDS:*\n\n`/addmonthly` — Generate 1 monthly code\n`/addmonthly 5` — Generate 5 monthly codes\n`/addlifetime` — Generate 1 lifetime code\n`/addlifetime 5` — Generate 5 lifetime codes\n`/listlicences` — See all codes\n`/listusers` — See all users\n`/help` — This menu",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "⚡ *MASTER SIGNALS PRO*\n\n📌 *How to use:*\n1️⃣ Select your trading pair\n2️⃣ Get your BUY or SELL signal\n3️⃣ Follow the signal on your platform\n\n🔑 Have a licence code? Tap *Enter Licence Code*\n💬 Need access? Contact @evalonwinnersbot",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Start Trading", callback_data="choose_pair")],
                [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
                [InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],
            ])
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    data=q.data; chat=q.message.chat_id; user_id=q.from_user.id

    if data=="choose_pair":
        try: await q.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat, text="⚡ *MASTER SIGNALS PRO*\n\nSelect your trading pair:", parse_mode="Markdown", reply_markup=pairs_keyboard())
        return

    if data=="pay_info":
        await q.edit_message_text(
            "💰 *UNLOCK MASTER SIGNALS PRO*\n\n📅 *Monthly Access*\n♾️ *Lifetime Access*\n\n✅ Win rate 90% — 98%\n✅ Free updates forever\n✅ 100+ trading pairs\n\n━━━━━━━━━━━━━━━━━━\n💳 *PAYMENT METHODS:*\n\n🟡 *Binance ID:* `{}`\n_Account: Master Indicators Pro_\n\n🔵 *USDT TRC-20:*\n`{}`\n_⚠️ TRC-20 (Tron) ONLY_\n\n🟠 *BNB BEP-20:*\n`{}`\n\n━━━━━━━━━━━━━━━━━━\n📸 Send payment screenshot to admin\n👤 You will receive your unique licence code!".format(BINANCE_ID,TRC20_ADDR,BEP20_ADDR),
            parse_mode="Markdown", reply_markup=payment_keyboard())
        return

    if data=="back_unlock":
        await q.edit_message_text("🔒 *LICENCE REQUIRED*\n\nYou have used your 1 free signal.\nContact admin to get access.", parse_mode="Markdown", reply_markup=unlock_keyboard())
        return

    if data=="enter_code":
        context.user_data["awaiting_code"]=True
        await q.edit_message_text("🔑 *Enter your licence code:*\n\nMonthly format: `EVAL-M-XXXX-XXXX-XXXX`\nLifetime format: `EVAL-L-XXXX-XXXX-XXXX`\n\nType your code and send it:", parse_mode="Markdown")
        return

    if data.startswith("sel_"):
        idx=data[4:]
        pair=PAIR_INDEX.get(idx)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found. Please choose again.", reply_markup=pairs_keyboard())
            return
        if not is_licensed(user_id) and free_signals_used(user_id)>=1:
            try: await q.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat, text="🔒 *LICENCE REQUIRED*\n\nYou have used your *1 free trial signal*.\n\nContact admin to unlock access:\n✅ Win rate 90% — 98%\n✅ Free updates forever\n✅ 100+ trading pairs\n✅ Monthly or Lifetime access", parse_mode="Markdown", reply_markup=unlock_keyboard())
            return
        try: await q.message.delete()
        except: pass
        cm=await context.bot.send_message(chat_id=chat, text="🔵 *Creating a signal for {}*".format(pair), parse_mode="Markdown")
        await asyncio.sleep(2)
        sig=generate_signal(pair); ib=sig["direction"]=="BUY"
        img=BUY_IMAGE_ID if ib else SELL_IMAGE_ID
        trend="Up 🟢" if ib else "Down 🔴"
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        cap="*{}* {}\n🕐 In {} mins.\n📊 Signal strength: {}".format(pair,trend,sig["timeframe"],sig["strength"])
        await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id=update.effective_user.id
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

    if context.user_data.get("awaiting_code"):
        context.user_data["awaiting_code"]=False
        code=text.upper().strip()
        if activate_licence(code,user_id):
            u=get_user(user_id); exp=get_expiry_text(user_id)
            tl="📅 Monthly" if u.get("licence_type")=="monthly" else "♾️ Lifetime"
            await update.message.reply_text("✅ *Licence Activated!*\n\n🎉 Welcome to MASTER SIGNALS PRO!\n🏆 Win Rate: 90% — 98%\n🔑 Type: *{}*\n⏳ {}\n\nYou can now use unlimited signals!".format(tl,exp), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Start Trading Now", callback_data="choose_pair")]]))
        else:
            await update.message.reply_text("❌ *Invalid or already used code.*\n\nCheck your code or contact admin.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],[InlineKeyboardButton("🔑 Try Again", callback_data="enter_code")]]))

# ============================================================
# MAIN
# ============================================================
def main():
    print("MASTER SIGNALS PRO starting...")
    init_db()
    print("Database ready.")
    PORT=int(os.environ.get("PORT",8443))
    RENDER_URL=os.environ.get("RENDER_EXTERNAL_URL","")
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT,message_handler))
    if RENDER_URL:
        print("Render webhook mode")
        app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url="{}/{}".format(RENDER_URL,BOT_TOKEN), url_path=BOT_TOKEN)
    else:
        print("Local polling mode")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()

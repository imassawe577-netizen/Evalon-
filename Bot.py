"""
╔══════════════════════════════════════════════════════╗
║         EVALON DERIV AUTO-TRADING BOT v2             ║
║         Single-file | All features rebuilt           ║
║         Admin: 8054370971                            ║
╚══════════════════════════════════════════════════════╝
ENV vars needed:
  BOT_TOKEN       = Telegram bot token
  DATABASE_URL    = Neon PostgreSQL connection string
  DERIV_APP_ID    = Deriv app id (default 1089)
"""

import asyncio
import json
import logging
import os
import random
import websockets
import pg8000.native
import urllib.parse as _urlparse
from aiohttp import web

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
BOT_TOKEN    = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089")
DERIV_WS_URL = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"
SUPPORT_URL  = "http://t.me/evalonwinnersbot"
ADMIN_ID     = 8054370971

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

GRANULARITY = {
    "1": 60, "2": 120, "3": 180, "5": 300,
    "10": 600, "15": 900, "30": 1800,
    "1m": 60, "2m": 120, "3m": 180, "5m": 300,
    "10m": 600, "15m": 900,
}

# ══════════════════════════════════════════════════════════════
# DATABASE — connection pool style via pg8000
# ══════════════════════════════════════════════════════════════
_db_params = None

def _get_conn_params():
    global _db_params
    if _db_params:
        return _db_params
    u = _urlparse.urlparse(DATABASE_URL)
    _db_params = {
        "host":        u.hostname,
        "port":        u.port or 5432,
        "database":    u.path.lstrip("/"),
        "user":        u.username,
        "password":    u.password,
        "ssl_context": True,
    }
    return _db_params

def _run(sql, params=(), fetch="none"):
    count   = sql.count("%s")
    new_sql = sql
    for i in range(count):
        new_sql = new_sql.replace("%s", f":p{i+1}", 1)
    con = pg8000.native.Connection(**_get_conn_params())
    try:
        result = con.run(new_sql, **{f"p{i+1}": v for i, v in enumerate(params)}) if params else con.run(new_sql)
        if fetch == "one":
            cols = [c["name"] for c in con.columns]
            return dict(zip(cols, result[0])) if result else None
        if fetch == "all":
            cols = [c["name"] for c in con.columns]
            return [dict(zip(cols, row)) for row in result]
    finally:
        con.close()

async def _db(sql, params=(), fetch="none"):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _run(sql, params, fetch))

# ══════════════════════════════════════════════════════════════
# INIT DB
# ══════════════════════════════════════════════════════════════
async def init_db():
    await _db("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        BIGINT PRIMARY KEY,
            username       TEXT,
            full_name      TEXT,
            license_status TEXT DEFAULT 'trial',
            trial_tokens   INTEGER DEFAULT 20,
            deriv_token    TEXT,
            created_at     TIMESTAMP DEFAULT NOW()
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id                  BIGINT PRIMARY KEY REFERENCES users(user_id),
            contract_type            TEXT DEFAULT 'rise_fall',
            pair                     TEXT DEFAULT '',
            timeframe                TEXT DEFAULT '1',
            stake                    NUMERIC DEFAULT 1.0,
            pair_mode                TEXT DEFAULT 'single',
            multi_pairs              TEXT DEFAULT '',
            auto_restart             BOOLEAN DEFAULT TRUE,
            martingale_enabled       BOOLEAN DEFAULT FALSE,
            martingale_multiplier    NUMERIC DEFAULT 2.0,
            martingale_max_steps     INTEGER DEFAULT 5,
            compound_enabled         BOOLEAN DEFAULT FALSE,
            tp_type                  TEXT DEFAULT 'percent',
            tp_value                 NUMERIC DEFAULT 110.0,
            sl_type                  TEXT DEFAULT 'percent',
            sl_value                 NUMERIC DEFAULT 100.0,
            multiplier_value         INTEGER DEFAULT 40,
            accumulator_growth       NUMERIC DEFAULT 0.03,
            digit_barrier            TEXT DEFAULT '5',
            digit_target             TEXT DEFAULT '5',
            turbo_duration           INTEGER DEFAULT 1,
            turbo_barrier_pct        NUMERIC DEFAULT 0.1,
            touch_duration           INTEGER DEFAULT 5,
            touch_barrier_pct        NUMERIC DEFAULT 0.2,
            vanilla_duration         INTEGER DEFAULT 5,
            vanilla_barrier_pct      NUMERIC DEFAULT 0.0,
            updated_at               TIMESTAMP DEFAULT NOW()
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS trade_sessions (
            id            SERIAL PRIMARY KEY,
            user_id       BIGINT REFERENCES users(user_id),
            contract_type TEXT,
            pair          TEXT,
            direction     TEXT,
            stake         NUMERIC,
            result        TEXT,
            profit        NUMERIC DEFAULT 0,
            step          INTEGER DEFAULT 1,
            cycle         INTEGER DEFAULT 1,
            created_at    TIMESTAMP DEFAULT NOW()
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            user_id       BIGINT PRIMARY KEY REFERENCES users(user_id),
            is_running    BOOLEAN DEFAULT FALSE,
            current_stake NUMERIC DEFAULT 0,
            current_step  INTEGER DEFAULT 1,
            current_cycle INTEGER DEFAULT 1,
            total_profit  NUMERIC DEFAULT 0,
            started_at    TIMESTAMP DEFAULT NOW()
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS user_states (
            user_id         BIGINT PRIMARY KEY REFERENCES users(user_id),
            state           TEXT DEFAULT '',
            last_message_id BIGINT DEFAULT NULL
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    logger.info("Database ready")

# ══════════════════════════════════════════════════════════════
# DB HELPERS
# ══════════════════════════════════════════════════════════════
async def get_config(key):
    row = await _db("SELECT value FROM bot_config WHERE key=%s", (key,), fetch="one")
    return row["value"] if row else None

async def set_config(key, value):
    await _db("""
        INSERT INTO bot_config (key,value) VALUES (%s,%s)
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
    """, (key, value))

async def get_user(uid):
    return await _db("SELECT * FROM users WHERE user_id=%s", (uid,), fetch="one")

async def create_user(uid, username, full_name):
    await _db("""
        INSERT INTO users (user_id,username,full_name)
        VALUES (%s,%s,%s) ON CONFLICT (user_id) DO NOTHING
    """, (uid, username, full_name))
    await _db("""
        INSERT INTO user_settings (user_id)
        VALUES (%s) ON CONFLICT (user_id) DO NOTHING
    """, (uid,))
    await _db("""
        INSERT INTO user_states (user_id, state)
        VALUES (%s,'') ON CONFLICT (user_id) DO NOTHING
    """, (uid,))

async def update_user(uid, **kw):
    sets = ", ".join(f"{k}=%s" for k in kw)
    vals = list(kw.values()) + [uid]
    await _db(f"UPDATE users SET {sets} WHERE user_id=%s", vals)

async def get_settings(uid):
    return await _db("SELECT * FROM user_settings WHERE user_id=%s", (uid,), fetch="one")

async def update_settings(uid, **kw):
    sets = ", ".join(f"{k}=%s" for k in kw)
    vals = list(kw.values()) + [uid]
    await _db(f"UPDATE user_settings SET {sets}, updated_at=NOW() WHERE user_id=%s", vals)

async def get_active_session(uid):
    return await _db("SELECT * FROM active_sessions WHERE user_id=%s", (uid,), fetch="one")

async def upsert_active_session(uid, **kw):
    row = await _db("SELECT user_id FROM active_sessions WHERE user_id=%s", (uid,), fetch="one")
    if row:
        sets = ", ".join(f"{k}=%s" for k in kw)
        vals = list(kw.values()) + [uid]
        await _db(f"UPDATE active_sessions SET {sets} WHERE user_id=%s", vals)
    else:
        kw["user_id"] = uid
        cols = ", ".join(kw.keys())
        phs  = ", ".join(["%s"] * len(kw))
        await _db(f"INSERT INTO active_sessions ({cols}) VALUES ({phs})", list(kw.values()))

async def save_trade(uid, contract_type, pair, direction, stake, result, profit, step, cycle):
    await _db("""
        INSERT INTO trade_sessions
          (user_id,contract_type,pair,direction,stake,result,profit,step,cycle)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (uid, contract_type, pair, direction, stake, result, profit, step, cycle))

async def get_trade_history(uid, limit=10):
    return await _db("""
        SELECT * FROM trade_sessions WHERE user_id=%s
        ORDER BY created_at DESC LIMIT %s
    """, (uid, limit), fetch="all")

async def deduct_trial_token(uid):
    await _db("""
        UPDATE users SET trial_tokens=trial_tokens-1
        WHERE user_id=%s AND trial_tokens>0
    """, (uid,))

async def get_all_users():
    return await _db("SELECT * FROM users ORDER BY created_at DESC", fetch="all")

async def get_user_state(uid):
    row = await _db("SELECT state FROM user_states WHERE user_id=%s", (uid,), fetch="one")
    return row["state"] if row else ""

async def set_user_state(uid, state):
    await _db("""
        INSERT INTO user_states (user_id,state) VALUES (%s,%s)
        ON CONFLICT (user_id) DO UPDATE SET state=EXCLUDED.state
    """, (uid, state))

async def get_last_msg_id(uid):
    row = await _db("SELECT last_message_id FROM user_states WHERE user_id=%s", (uid,), fetch="one")
    return row["last_message_id"] if row else None

async def set_last_msg_id(uid, msg_id):
    await _db("""
        INSERT INTO user_states (user_id, state, last_message_id) VALUES (%s, '', %s)
        ON CONFLICT (user_id) DO UPDATE SET last_message_id=EXCLUDED.last_message_id
    """, (uid, msg_id))

async def send_clean(context, uid, text, **kw):
    """Delete previous bot message, send new one, save its id."""
    old_id = await get_last_msg_id(uid)
    if old_id:
        try:
            await context.bot.delete_message(chat_id=uid, message_id=old_id)
        except Exception:
            pass
    msg = await context.bot.send_message(chat_id=uid, text=text, **kw)
    await set_last_msg_id(uid, msg.message_id)
    return msg

# ══════════════════════════════════════════════════════════════
# DERIV CLIENT
# ══════════════════════════════════════════════════════════════
class DerivClient:
    def __init__(self, token):
        self.token        = token
        self.ws           = None
        self.authorized   = False
        self.account_type = None

    async def connect(self):
        self.ws = await asyncio.wait_for(
            websockets.connect(DERIV_WS_URL), timeout=10
        )

    async def disconnect(self):
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

    async def _send(self, payload):
        await self.ws.send(json.dumps(payload))

    async def _recv(self):
        return json.loads(await asyncio.wait_for(self.ws.recv(), timeout=10))

    async def authorize(self):
        try:
            await asyncio.wait_for(self.connect(), timeout=10)
            await self._send({"authorize": self.token})
            resp = await asyncio.wait_for(self._recv(), timeout=10)
            if "error" in resp:
                await self.disconnect()
                return False, resp["error"]["message"]
            self.authorized   = True
            acc = resp.get("authorize", {})
            self.account_type = "demo" if acc.get("is_virtual") else "real"
            return True, acc
        except asyncio.TimeoutError:
            await self.disconnect()
            return False, "Connection timed out. Try again."
        except Exception as e:
            await self.disconnect()
            return False, f"Connection error: {str(e)}"

    async def validate_pair(self, pair):
        try:
            await self._send({"active_symbols": "brief", "product_type": "basic"})
            resp    = await self._recv()
            symbols = resp.get("active_symbols", [])
            query   = pair.upper().replace(" ", "")
            for s in symbols:
                disp = s.get("display_name", "").upper().replace(" ", "")
                sym  = s.get("symbol", "").upper()
                if query in disp or query == sym:
                    is_otc       = "otc" in s.get("symbol", "").lower()
                    market_label = "OTC" if is_otc else s.get("market", "")
                    return True, s["symbol"], s["display_name"], market_label
            return False, None, None, None
        except Exception as e:
            logger.error(f"validate_pair: {e}")
            return False, None, None, None

    async def get_candles(self, symbol, granularity, count=3):
        try:
            await self._send({
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "granularity": granularity,
                "style": "candles"
            })
            return (await self._recv()).get("candles", [])
        except Exception as e:
            logger.error(f"get_candles: {e}")
            return []

    async def get_last_tick(self, symbol):
        try:
            await self._send({"ticks": symbol, "subscribe": 0})
            return (await self._recv()).get("tick", {})
        except Exception as e:
            logger.error(f"get_last_tick: {e}")
            return {}

    async def get_balance(self):
        try:
            await self._send({"balance": 1})
            return (await self._recv()).get("balance", {})
        except Exception as e:
            logger.error(f"get_balance: {e}")
            return {}

    async def _buy(self, params, price):
        try:
            await self._send({"buy": 1, "price": price, "parameters": params})
            resp = await self._recv()
            if "error" in resp:
                return None, resp["error"]["message"]
            return resp.get("buy", {}).get("contract_id"), None
        except Exception as e:
            return None, str(e)

    async def buy_rise_fall(self, symbol, direction, stake, duration, unit):
        return await self._buy({
            "amount": stake, "basis": "stake",
            "contract_type": direction, "currency": "USD",
            "duration": duration, "duration_unit": unit, "symbol": symbol
        }, stake)

    async def buy_digit(self, symbol, dtype, stake, duration, barrier=None):
        params = {
            "amount": stake, "basis": "stake",
            "contract_type": dtype, "currency": "USD",
            "duration": duration, "duration_unit": "t", "symbol": symbol
        }
        if barrier is not None:
            params["barrier"] = str(barrier)
        return await self._buy(params, stake)

    async def buy_multiplier(self, symbol, direction, stake, multiplier, tp=None, sl=None):
        params = {
            "amount": stake, "basis": "stake",
            "contract_type": direction, "currency": "USD",
            "duration": 0, "duration_unit": "d",
            "symbol": symbol, "multiplier": multiplier, "cancellation": "0"
        }
        limit = {}
        if tp: limit["take_profit"] = tp
        if sl: limit["stop_loss"]   = sl
        if limit: params["limit_order"] = limit
        return await self._buy(params, stake)

    async def buy_accumulator(self, symbol, stake, growth_rate):
        return await self._buy({
            "amount": stake, "basis": "stake",
            "contract_type": "ACCU", "currency": "USD",
            "duration": 0, "duration_unit": "d",
            "symbol": symbol, "growth_rate": growth_rate
        }, stake)

    async def buy_turbo(self, symbol, direction, stake, duration, barrier):
        return await self._buy({
            "amount": stake, "basis": "stake",
            "contract_type": direction, "currency": "USD",
            "duration": duration, "duration_unit": "m",
            "symbol": symbol, "barrier": barrier
        }, stake)

    async def buy_touch(self, symbol, touch_type, stake, duration, barrier):
        return await self._buy({
            "amount": stake, "basis": "stake",
            "contract_type": touch_type, "currency": "USD",
            "duration": duration, "duration_unit": "m",
            "symbol": symbol, "barrier": barrier
        }, stake)

    async def buy_vanilla(self, symbol, direction, stake, duration, barrier):
        return await self._buy({
            "amount": stake, "basis": "stake",
            "contract_type": direction, "currency": "USD",
            "duration": duration, "duration_unit": "m",
            "symbol": symbol, "barrier": barrier
        }, stake)

    async def get_contract_status(self, contract_id):
        try:
            await self._send({"proposal_open_contract": 1, "contract_id": contract_id})
            return (await self._recv()).get("proposal_open_contract", {})
        except Exception as e:
            logger.error(f"get_contract_status: {e}")
            return {}

# ══════════════════════════════════════════════════════════════
# SIGNAL ENGINE
# ══════════════════════════════════════════════════════════════
async def get_signal(client, pair, contract_type, settings):
    """
    Returns direction string or None.
    For candle-based: reads last closed candle.
    close > open → BUY
    close < open → SELL
    close = open → None (doji, skip)
    """
    ct = contract_type

    if ct in ("rise_fall", "multiplier", "turbo", "touch", "vanilla"):
        tf   = str(settings["timeframe"])
        gran = GRANULARITY.get(tf, 60)
        candles = await client.get_candles(pair, gran, count=3)
        if not candles or len(candles) < 2:
            return None
        # Use second-to-last candle (fully closed)
        last = candles[-2]
        o = float(last.get("open", 0))
        c = float(last.get("close", 0))
        if c > o:
            return "BUY"
        if c < o:
            return "SELL"
        return None  # doji

    elif ct == "digit_over_under":
        tick  = await client.get_last_tick(pair)
        quote = str(tick.get("quote", "0"))
        digit = int(quote.replace(".", "")[-1])
        barrier = int(settings.get("digit_barrier", 5))
        return "OVER" if digit < barrier else "UNDER"

    elif ct == "digit_match_diff":
        tick  = await client.get_last_tick(pair)
        quote = str(tick.get("quote", "0"))
        digit = int(quote.replace(".", "")[-1])
        return str(digit)

    elif ct == "digit_even_odd":
        tick  = await client.get_last_tick(pair)
        quote = str(tick.get("quote", "0"))
        digit = int(quote.replace(".", "")[-1])
        return "EVEN" if digit % 2 == 0 else "ODD"

    elif ct == "accumulator":
        return "ACCU"

    return None

# ══════════════════════════════════════════════════════════════
# MULTI-PAIR TREND SELECTOR
# ══════════════════════════════════════════════════════════════
async def pick_best_pair(client, settings):
    """
    Multi-pair mode: check trend of each pair.
    Count consecutive candles same direction.
    Pick pair with longest streak.
    Tie? Pick first.
    """
    pairs_raw = settings.get("multi_pairs", "")
    pairs     = [p.strip() for p in pairs_raw.split(",") if p.strip()]
    if not pairs:
        return settings.get("pair", ""), "BUY"

    tf   = str(settings["timeframe"])
    gran = GRANULARITY.get(tf, 60)

    best_pair   = pairs[0]
    best_streak = 0
    best_dir    = "BUY"

    for p in pairs:
        try:
            candles = await client.get_candles(p, gran, count=6)
            if not candles or len(candles) < 2:
                continue
            # Count streak from most recent closed candle backwards
            streak    = 0
            direction = None
            for candle in reversed(candles[:-1]):  # skip last (may be forming)
                o = float(candle.get("open", 0))
                c = float(candle.get("close", 0))
                if c == o:
                    break
                d = "BUY" if c > o else "SELL"
                if direction is None:
                    direction = d
                if d == direction:
                    streak += 1
                else:
                    break
            if direction and streak > best_streak:
                best_streak = streak
                best_pair   = p
                best_dir    = direction
        except Exception as e:
            logger.warning(f"pick_best_pair {p}: {e}")
            continue

    return best_pair, best_dir

# ══════════════════════════════════════════════════════════════
# PLACE ORDER
# ══════════════════════════════════════════════════════════════
async def place_order(client, contract_type, pair, direction, stake, settings):
    ct  = contract_type
    tf  = str(settings["timeframe"])
    dur = int(tf.replace("m", "")) if tf.replace("m", "").isdigit() else 1

    if ct == "rise_fall":
        dc   = "CALL" if direction == "BUY" else "PUT"
        unit = "t" if dur <= 5 and "m" not in tf else "m"
        return await client.buy_rise_fall(pair, dc, stake, dur, unit)

    elif ct == "multiplier":
        dc  = "MULTUP" if direction == "BUY" else "MULTDOWN"
        mul = int(settings["multiplier_value"])
        tp_val = _calc_tp_sl(stake, settings, "tp")
        sl_val = _calc_tp_sl(stake, settings, "sl")
        return await client.buy_multiplier(pair, dc, stake, mul, tp_val, sl_val)

    elif ct == "digit_over_under":
        dt      = "DIGITOVER" if direction == "OVER" else "DIGITUNDER"
        barrier = settings.get("digit_barrier", "5")
        return await client.buy_digit(pair, dt, stake, dur, barrier)

    elif ct == "digit_match_diff":
        target = settings.get("digit_target", direction)
        return await client.buy_digit(pair, "DIGITMATCH", stake, dur, target)

    elif ct == "digit_even_odd":
        dt = "DIGITEVEN" if direction == "EVEN" else "DIGITODD"
        return await client.buy_digit(pair, dt, stake, dur)

    elif ct == "accumulator":
        growth = float(settings["accumulator_growth"])
        sl_val = _calc_tp_sl(stake, settings, "sl")
        return await client.buy_accumulator(pair, stake, growth)

    elif ct == "turbo":
        dc   = "TURBOSLONG" if direction == "BUY" else "TURBOSSHORT"
        tick = await client.get_last_tick(pair)
        p    = float(tick.get("quote", 0))
        pct  = float(settings.get("turbo_barrier_pct", 0.1)) / 100
        bar  = f"+{p * pct:.5f}" if direction == "BUY" else f"-{p * pct:.5f}"
        d    = int(settings.get("turbo_duration", 1))
        return await client.buy_turbo(pair, dc, stake, d, bar)

    elif ct == "touch":
        tick = await client.get_last_tick(pair)
        p    = float(tick.get("quote", 0))
        pct  = float(settings.get("touch_barrier_pct", 0.2)) / 100
        bar  = f"+{p * pct:.5f}"
        d    = int(settings.get("touch_duration", 5))
        return await client.buy_touch(pair, "ONETOUCH", stake, d, bar)

    elif ct == "vanilla":
        dc   = "VANILLALONGCALL" if direction == "BUY" else "VANILLALONGPUT"
        tick = await client.get_last_tick(pair)
        p    = float(tick.get("quote", 0))
        pct  = float(settings.get("vanilla_barrier_pct", 0.0)) / 100
        bar  = f"{p + p * pct:.5f}" if direction == "BUY" else f"{p - p * pct:.5f}"
        d    = int(settings.get("vanilla_duration", 5))
        return await client.buy_vanilla(pair, dc, stake, d, bar)

    return None, "Unknown contract type"

def _calc_tp_sl(stake, settings, which):
    """Calculate TP or SL value from settings (percent or fixed)."""
    s    = float(stake)
    t    = settings.get(f"{which}_type", "percent")
    v    = float(settings.get(f"{which}_value", 100.0))
    if t == "percent":
        return round(s * v / 100, 2)
    return round(v, 2)

# ══════════════════════════════════════════════════════════════
# WAIT FOR CONTRACT RESULT
# ══════════════════════════════════════════════════════════════
async def wait_for_result(client, contract_id, running_flag):
    """Poll every 2s until contract is sold/expired. Max 10 minutes."""
    for _ in range(300):
        await asyncio.sleep(2)
        if not running_flag[0]:
            return None, 0
        c      = await client.get_contract_status(contract_id)
        profit = float(c.get("profit", 0))
        if c.get("is_sold") or c.get("status") == "sold":
            return ("win" if profit > 0 else "loss"), profit
        if c.get("is_expired") or c.get("is_settleable"):
            return ("win" if profit > 0 else "loss"), profit
    return None, 0

# ══════════════════════════════════════════════════════════════
# TRADING ENGINE
# ══════════════════════════════════════════════════════════════
active_tasks: dict = {}

class TradingEngine:
    def __init__(self, uid, send_fn):
        self.uid     = uid
        self.send    = send_fn
        self.running = [True]   # mutable flag for wait_for_result
        self.client  = None

    async def stop(self):
        self.running[0] = False
        await upsert_active_session(self.uid, is_running=False)
        if self.client:
            await self.client.disconnect()

    async def start(self):
        user     = await get_user(self.uid)
        settings = await get_settings(self.uid)

        if not user or not settings:
            await self.send("❌ Account not found. Send /start first.")
            return
        if not user["deriv_token"]:
            await self.send("❌ Connect your Deriv account first — tap Connect Deriv.")
            return
        if not settings["pair"] and settings["pair_mode"] == "single":
            await self.send("❌ No pair selected. Go to Settings → Pair.")
            return

        self.client = DerivClient(user["deriv_token"])
        ok, result  = await self.client.authorize()
        if not ok:
            await self.send(f"❌ Deriv token error: {result}")
            return

        # License vs account type check
        is_real_account = (self.client.account_type == "real")
        license_status  = user["license_status"]

        if is_real_account and license_status != "real":
            await self.send(
                "🔒 *Real account detected.*\n\n"
                "Your current license does not allow real account trading.\n"
                "Contact support to upgrade:\n"
                f"👉 [Support]({SUPPORT_URL})",
                parse_mode="Markdown"
            )
            await self.client.disconnect()
            return

        if not is_real_account and license_status == "trial" and user["trial_tokens"] <= 0:
            await self.send(
                "⚠️ *Your trial has ended.*\n\n"
                "Contact support to activate your license:\n"
                f"👉 [Support]({SUPPORT_URL})",
                parse_mode="Markdown"
            )
            await self.client.disconnect()
            return

        ct         = settings["contract_type"]
        base_stake = float(settings["stake"])
        step       = 1
        cycle      = 1
        total_p    = 0.0
        cur_stake  = base_stake

        await upsert_active_session(
            self.uid,
            is_running=True, current_step=1, current_cycle=1,
            total_profit=0, current_stake=base_stake
        )

        await self.send(
            f"🟢 *Bot Running*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Contract : `{ct.replace('_',' ').title()}`\n"
            f"Pair     : `{settings['pair'] or 'Multi-pair'}`\n"
            f"Stake    : `${base_stake}`\n"
            f"Martingale: `{'ON' if settings['martingale_enabled'] else 'OFF'}`\n"
            f"Compound  : `{'ON' if settings['compound_enabled'] else 'OFF'}`",
            parse_mode="Markdown"
        )

        try:
            await self._loop(settings, user, ct, base_stake, cur_stake, step, cycle, total_p)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Engine error uid={self.uid}: {e}")
            await self.send(f"❌ Unexpected error: {e}")
        finally:
            self.running[0] = False
            await upsert_active_session(self.uid, is_running=False)
            if self.client:
                await self.client.disconnect()

    async def _loop(self, settings, user, ct, base_stake, cur_stake, step, cycle, total_p):
        while self.running[0]:
            # Re-read session to check if stopped externally
            session = await get_active_session(self.uid)
            if not session or not session["is_running"]:
                break

            # Pick pair
            if settings["pair_mode"] == "multi" and settings["multi_pairs"]:
                pair, trend_dir = await pick_best_pair(self.client, settings)
            else:
                pair = settings["pair"]
                trend_dir = None

            # Get signal
            if trend_dir:
                direction = trend_dir
            else:
                direction = await get_signal(self.client, pair, ct, settings)

            if not direction:
                await asyncio.sleep(1)
                continue

            # Place trade
            contract_id, err = await place_order(self.client, ct, pair, direction, cur_stake, settings)
            if err or not contract_id:
                await self.send(f"⚠️ Order failed: {err or 'No contract ID'}")
                await asyncio.sleep(3)
                continue

            dir_emoji = "🟢 BUY" if direction in ("BUY", "CALL", "MULTUP", "OVER", "EVEN", "ACCU") else "🔴 SELL"
            await self.send(
                f"⚡ *Trade #{step} · Cycle {cycle}*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Pair    : `{pair}`\n"
                f"Signal  : `{dir_emoji}`\n"
                f"Stake   : `${cur_stake:.2f}`",
                parse_mode="Markdown"
            )

            # Wait for result — immediately after contract closes, loop continues
            result, profit = await wait_for_result(self.client, contract_id, self.running)
            if result is None:
                continue

            # Deduct trial token per completed deal
            if user["license_status"] == "trial":
                await deduct_trial_token(self.uid)
                u2 = await get_user(self.uid)
                if u2["trial_tokens"] <= 0:
                    await self.send(
                        "⚠️ *Trial ended.* Contact support to continue.\n"
                        f"👉 [Support]({SUPPORT_URL})",
                        parse_mode="Markdown"
                    )
                    self.running[0] = False
                    break

            total_p += profit
            await save_trade(self.uid, ct, pair, direction, cur_stake, result, profit, step, cycle)
            await upsert_active_session(
                self.uid, total_profit=total_p,
                current_step=step, current_cycle=cycle, current_stake=cur_stake
            )

            e = "✅ WIN" if result == "win" else "❌ LOSS"
            await self.send(
                f"{e}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Profit  : `${profit:.2f}`\n"
                f"Session : `${total_p:.2f}`",
                parse_mode="Markdown"
            )

            # TP / SL check
            tp_val = _calc_tp_sl(base_stake, settings, "tp")
            sl_val = _calc_tp_sl(base_stake, settings, "sl")

            if total_p >= tp_val:
                await self.send(
                    f"🎯 *Take Profit hit!* `${total_p:.2f}`",
                    parse_mode="Markdown"
                )
                if settings["auto_restart"]:
                    total_p = 0; step = 1; cycle += 1; cur_stake = base_stake
                    continue
                else:
                    self.running[0] = False; break

            if total_p <= -sl_val:
                await self.send(
                    f"🛑 *Stop Loss hit!* `${abs(total_p):.2f}` lost",
                    parse_mode="Markdown"
                )
                self.running[0] = False; break

            # Money management
            if result == "win":
                if settings["compound_enabled"]:
                    cur_stake = round(cur_stake + abs(profit), 2)
                else:
                    cur_stake = base_stake
                step = 1; cycle += 1
            else:
                if settings["martingale_enabled"]:
                    if step < int(settings["martingale_max_steps"]):
                        cur_stake = round(cur_stake * float(settings["martingale_multiplier"]), 2)
                        step += 1
                    else:
                        await self.send(
                            f"⚠️ Martingale max steps reached. Resetting cycle {cycle}.",
                        )
                        cur_stake = base_stake; step = 1; cycle += 1
                else:
                    cur_stake = base_stake; step = 1; cycle += 1

            # No sleep — immediately read next candle

# ══════════════════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════════════════
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start",         callback_data="trade_start"),
         InlineKeyboardButton("🛑 Stop",          callback_data="trade_stop")],
        [InlineKeyboardButton("⚙️ Settings",      callback_data="settings"),
         InlineKeyboardButton("📊 History",       callback_data="history")],
        [InlineKeyboardButton("💰 Balance",       callback_data="balance"),
         InlineKeyboardButton("🔑 Connect Deriv", callback_data="connect_deriv")],
        [InlineKeyboardButton("🎟 Tokens",        callback_data="tokens"),
         InlineKeyboardButton("💬 Support",       url=SUPPORT_URL)],
    ])

def kb_settings(ct="rise_fall"):
    rows = [
        [InlineKeyboardButton("💱 Pair",          callback_data="set_pair"),
         InlineKeyboardButton("📊 Contract",      callback_data="set_contract")],
        [InlineKeyboardButton("💰 Stake",         callback_data="set_stake"),
         InlineKeyboardButton("⏱ Timeframe",     callback_data="set_timeframe")],
        [InlineKeyboardButton("🎯 Take Profit",   callback_data="set_tp"),
         InlineKeyboardButton("🛑 Stop Loss",     callback_data="set_sl")],
        [InlineKeyboardButton("📈 Martingale",    callback_data="set_martingale"),
         InlineKeyboardButton("🔄 Compound",      callback_data="set_compound")],
        [InlineKeyboardButton("🌍 Pair Mode",     callback_data="set_pair_mode"),
         InlineKeyboardButton("🔁 Auto Restart",  callback_data="set_auto_restart")],
    ]
    # Contract-specific settings
    if ct == "multiplier":
        rows.append([InlineKeyboardButton("✖️ Multiplier Value", callback_data="set_multiplier_value")])
    elif ct == "accumulator":
        rows.append([InlineKeyboardButton("📊 Growth Rate", callback_data="set_accumulator_growth")])
    elif ct == "digit_over_under":
        rows.append([InlineKeyboardButton("🔢 Digit Barrier", callback_data="set_digit_barrier")])
    elif ct == "digit_match_diff":
        rows.append([InlineKeyboardButton("🎯 Target Digit", callback_data="set_digit_target")])
    elif ct == "turbo":
        rows.append([InlineKeyboardButton("📐 Turbo Settings", callback_data="set_turbo")])
    elif ct == "touch":
        rows.append([InlineKeyboardButton("👆 Touch Settings", callback_data="set_touch")])
    elif ct == "vanilla":
        rows.append([InlineKeyboardButton("🏛 Vanilla Settings", callback_data="set_vanilla")])
    rows.append([InlineKeyboardButton("« Back", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def kb_contract():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Rise / Fall",         callback_data="ct_rise_fall")],
        [InlineKeyboardButton("✖️ Multipliers",          callback_data="ct_multiplier")],
        [InlineKeyboardButton("🔢 Digits Over/Under",   callback_data="ct_digit_over_under")],
        [InlineKeyboardButton("🎯 Digits Match/Diff",   callback_data="ct_digit_match_diff")],
        [InlineKeyboardButton("⚡ Digits Even/Odd",     callback_data="ct_digit_even_odd")],
        [InlineKeyboardButton("📊 Accumulators",        callback_data="ct_accumulator")],
        [InlineKeyboardButton("🌀 Turbos",              callback_data="ct_turbo")],
        [InlineKeyboardButton("👆 Touch / No Touch",    callback_data="ct_touch")],
        [InlineKeyboardButton("🏛 Vanillas",            callback_data="ct_vanilla")],
        [InlineKeyboardButton("« Back",                 callback_data="settings")],
    ])

def kb_timeframe(ct):
    ticks = [
        [InlineKeyboardButton("1t", callback_data="tf_1"),
         InlineKeyboardButton("2t", callback_data="tf_2"),
         InlineKeyboardButton("3t", callback_data="tf_3"),
         InlineKeyboardButton("4t", callback_data="tf_4"),
         InlineKeyboardButton("5t", callback_data="tf_5")],
    ]
    mins = [
        [InlineKeyboardButton("1m",  callback_data="tf_1m"),
         InlineKeyboardButton("2m",  callback_data="tf_2m"),
         InlineKeyboardButton("3m",  callback_data="tf_3m")],
        [InlineKeyboardButton("5m",  callback_data="tf_5m"),
         InlineKeyboardButton("10m", callback_data="tf_10m"),
         InlineKeyboardButton("15m", callback_data="tf_15m")],
    ]
    if ct in ("digit_over_under", "digit_match_diff", "digit_even_odd"):
        rows = ticks
    elif ct == "rise_fall":
        rows = ticks + mins
    elif ct in ("turbo", "touch", "vanilla", "multiplier"):
        rows = mins
    elif ct == "accumulator":
        rows = [[InlineKeyboardButton("Continuous (tick-based)", callback_data="tf_1")]]
    else:
        rows = mins
    rows.append([InlineKeyboardButton("« Back", callback_data="settings")])
    return InlineKeyboardMarkup(rows)

def kb_martingale(on, mul, steps):
    s = "✅ ON" if on else "OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Toggle — {s}", callback_data="mg_toggle")],
        [InlineKeyboardButton("×1.5", callback_data="mg_1.5"),
         InlineKeyboardButton("×2.0", callback_data="mg_2.0"),
         InlineKeyboardButton("×2.2", callback_data="mg_2.2"),
         InlineKeyboardButton("×2.6", callback_data="mg_2.6"),
         InlineKeyboardButton("×3.0", callback_data="mg_3.0")],
        [InlineKeyboardButton("Max 3", callback_data="mgs_3"),
         InlineKeyboardButton("Max 4", callback_data="mgs_4"),
         InlineKeyboardButton("Max 5", callback_data="mgs_5"),
         InlineKeyboardButton("Max 7", callback_data="mgs_7")],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_tp_sl(which):
    label = "Take Profit" if which == "tp" else "Stop Loss"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("% of Stake", callback_data=f"{which}_type_percent"),
         InlineKeyboardButton("Fixed $",    callback_data=f"{which}_type_fixed")],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_back(cb="settings"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data=cb)]])

def kb_multiplier_val():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("×10",  callback_data="mv_10"),
         InlineKeyboardButton("×20",  callback_data="mv_20"),
         InlineKeyboardButton("×40",  callback_data="mv_40")],
        [InlineKeyboardButton("×50",  callback_data="mv_50"),
         InlineKeyboardButton("×100", callback_data="mv_100")],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_acc_growth():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("0.01%", callback_data="ag_0.01"),
         InlineKeyboardButton("0.02%", callback_data="ag_0.02"),
         InlineKeyboardButton("0.03%", callback_data="ag_0.03")],
        [InlineKeyboardButton("0.04%", callback_data="ag_0.04"),
         InlineKeyboardButton("0.05%", callback_data="ag_0.05")],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_digit_barrier():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"db_{i}") for i in range(5)],
        [InlineKeyboardButton(str(i), callback_data=f"db_{i}") for i in range(5, 10)],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users",        callback_data="admin_users")],
        [InlineKeyboardButton("🔑 Set License",  callback_data="admin_license")],
        [InlineKeyboardButton("🎟 Add Tokens",   callback_data="admin_tokens")],
        [InlineKeyboardButton("📢 Broadcast",    callback_data="admin_broadcast")],
        [InlineKeyboardButton("« Back",          callback_data="menu")],
    ])

# ══════════════════════════════════════════════════════════════
# WELCOME MESSAGE
# ══════════════════════════════════════════════════════════════
WELCOME = """⚡ *EVALON — Automated Deriv Trading*
━━━━━━━━━━━━━━━━━━━━━

The market doesn't wait. Neither do we.

EVALON connects directly to your Deriv account and trades in real time — Rise/Fall, Multipliers, Digits, Accumulators, Turbos, Touch, Vanillas — all with your own rules.

Set your stake. Define your risk. Let it run.

━━━━━━━━━━━━━━━━━━━━━
⚠️ Trading involves risk. Only trade what you can afford to lose."""

# ══════════════════════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════════════════════
async def _reply(query, text, **kw):
    """Delete old message and send fresh one — keeps chat clean."""
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.message.answer(text, **kw) if hasattr(query.message, 'answer') else None

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await create_user(u.id, u.username or "", u.full_name or "")
    db_user = await get_user(u.id)

    ls = db_user["license_status"]
    tk = db_user["trial_tokens"]
    if ls == "trial":   status = f"\n🎟 Trial tokens: *{tk}/20*"
    elif ls == "demo":  status = "\n🎮 License: *Demo — Unlimited*"
    elif ls == "real":  status = "\n💰 License: *Real Account ✅*"
    else:               status = ""

    buttons = list(kb_main().inline_keyboard)
    if u.id == ADMIN_ID:
        buttons = buttons + [[InlineKeyboardButton("🔐 Admin", callback_data="admin_panel")]]

    await update.effective_message.reply_text(
        WELCOME + status,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ══════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d   = q.data


    # MENU
    if d == "menu":
        await cmd_start(update, context)
        return

    # SETTINGS OVERVIEW
    if d == "settings":
        s = await get_settings(uid)
        ct = s["contract_type"]
        tp_label = f"{s['tp_value']}%" if s['tp_type'] == 'percent' else f"${s['tp_value']}"
        sl_label = f"{s['sl_value']}%" if s['sl_type'] == 'percent' else f"${s['sl_value']}"
        await send_clean(context, uid, 
            f"⚙️ *Settings*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Contract  : `{ct.replace('_',' ').title()}`\n"
            f"Pair      : `{s['pair'] or 'Not set'}`\n"
            f"Timeframe : `{s['timeframe']}`\n"
            f"Stake     : `${s['stake']}`\n"
            f"Take Profit: `{tp_label}`\n"
            f"Stop Loss  : `{sl_label}`\n"
            f"Martingale : `{'ON ✅' if s['martingale_enabled'] else 'OFF'}`  ×{s['martingale_multiplier']} max {s['martingale_max_steps']}\n"
            f"Compound   : `{'ON ✅' if s['compound_enabled'] else 'OFF'}`\n"
            f"Pair Mode  : `{s['pair_mode'].title()}`\n"
            f"Auto Restart: `{'ON' if s['auto_restart'] else 'OFF'}`",
            parse_mode="Markdown",
            reply_markup=kb_settings(ct)
        )
        return

    # TRADE START
    if d == "trade_start":
        session = await get_active_session(uid)
        if session and session["is_running"]:
            await send_clean(context, uid, 
                "⚠️ Bot is already running. Press Stop first.",
                reply_markup=kb_main()
            )
            return
        async def send_fn(text, **kw):
            await send_clean(context, uid, text, **kw)
        engine = TradingEngine(uid, send_fn)
        task   = asyncio.create_task(engine.start())
        active_tasks[uid] = (engine, task)
        await send_clean(context, uid, "🚀 Starting...", reply_markup=kb_main())
        return

    # TRADE STOP
    if d == "trade_stop":
        if uid in active_tasks:
            engine, task = active_tasks.pop(uid)
            await engine.stop()
            task.cancel()
        else:
            session = await get_active_session(uid)
            if session:
                await upsert_active_session(uid, is_running=False)
        await send_clean(context, uid, "🛑 *Bot stopped.*", parse_mode="Markdown", reply_markup=kb_main())
        return

    # CONNECT DERIV
    if d == "connect_deriv":
        await set_user_state(uid, "awaiting_token")
        text = (
            "🔑 *Connect Your Deriv Account*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Go to `app.deriv.com`\n"
            "2️⃣ Profile → Security & Safety → API Token\n"
            "3️⃣ Create token with permissions:\n"
            "   ☑️ Read  ☑️ Trade  ☑️ Trading info  ☑️ Payments\n"
            "4️⃣ Copy and paste the token here ⬇️\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Never share your token with anyone."
        )
        video_id = await get_config("deriv_tutorial_video")
        if video_id:
            await q.message.reply_video(video=video_id, caption=text,
                                        parse_mode="Markdown", reply_markup=kb_back("menu"))
            await q.message.delete()
        else:
            await send_clean(context, uid, text, parse_mode="Markdown", reply_markup=kb_back("menu"))
        return

    # BALANCE
    if d == "balance":
        user = await get_user(uid)
        if not user or not user["deriv_token"]:
            await send_clean(context, uid, "❌ Connect Deriv first.", reply_markup=kb_back("menu"))
            return
        client = DerivClient(user["deriv_token"])
        ok, _  = await client.authorize()
        if not ok:
            await send_clean(context, uid, "❌ Token error. Reconnect.", reply_markup=kb_back("menu"))
            await client.disconnect()
            return
        bal = await client.get_balance()
        await client.disconnect()
        await send_clean(context, uid, 
            f"💰 *Balance*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Amount  : `{bal.get('balance','N/A')} {bal.get('currency','USD')}`\n"
            f"Account : `{'Demo 🎮' if bal.get('is_virtual') else 'Real 💰'}`",
            parse_mode="Markdown", reply_markup=kb_back("menu")
        )
        return

    # HISTORY
    if d == "history":
        trades = await get_trade_history(uid)
        if not trades:
            await send_clean(context, uid, "📊 No trades yet.", reply_markup=kb_back("menu"))
            return
        wins  = sum(1 for t in trades if t["result"] == "win")
        total = sum(float(t["profit"]) for t in trades)
        text  = (
            f"📊 *Trade History — Last 10*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Wins: `{wins}` / Losses: `{len(trades)-wins}`\n"
            f"P&L : `${total:.2f}`\n\n"
        )
        for t in trades[:5]:
            e = "✅" if t["result"] == "win" else "❌"
            text += f"{e} `{t['contract_type']}` | `{t['pair']}` | `${float(t['profit']):.2f}`\n"
        await send_clean(context, uid, text, parse_mode="Markdown", reply_markup=kb_back("menu"))
        return

    # TOKENS
    if d == "tokens":
        user = await get_user(uid)
        ls, tk = user["license_status"], user["trial_tokens"]
        if ls == "trial":
            msg = (f"🎟 *Trial Tokens*\n"
                   f"━━━━━━━━━━━━━━━\n"
                   f"Remaining: `{tk}/20`\n\n"
                   f"1 token = 1 completed trade.\n"
                   f"Contact support to upgrade.")
        elif ls == "demo":
            msg = "🎮 *Demo License* — Unlimited demo trading."
        else:
            msg = "💰 *Real License* — Full access."
        await send_clean(context, uid, msg, parse_mode="Markdown", reply_markup=kb_back("menu"))
        return

    # SETTINGS — PAIR
    if d == "set_pair":
        s = await get_settings(uid)
        if s["pair_mode"] == "multi":
            await set_user_state(uid, "awaiting_multi_pairs")
            await send_clean(context, uid, 
                "🌐 *Multi Pair*\n"
                "━━━━━━━━━━━━━━━\n"
                "Enter pairs separated by commas:\n\n"
                "`R_100, R_75, frxEURUSD`",
                parse_mode="Markdown", reply_markup=kb_back()
            )
        else:
            await set_user_state(uid, "awaiting_pair")
            await send_clean(context, uid, 
                "💱 *Enter Pair*\n"
                "━━━━━━━━━━━━━━━\n"
                "Type the pair name:\n\n"
                "• `Volatility 100`\n• `EURUSD`\n• `GBPUSD OTC`\n• `Boom 1000`",
                parse_mode="Markdown", reply_markup=kb_back()
            )
        return

    # SETTINGS — CONTRACT
    if d == "set_contract":
        await send_clean(context, uid, "📊 *Select Contract Type:*", parse_mode="Markdown", reply_markup=kb_contract())
        return

    if d.startswith("ct_"):
        ct = d[3:]
        await update_settings(uid, contract_type=ct)
        await send_clean(context, uid, 
            f"✅ Contract: `{ct.replace('_',' ').title()}`",
            parse_mode="Markdown", reply_markup=kb_settings(ct)
        )
        return

    # SETTINGS — TIMEFRAME
    if d == "set_timeframe":
        s = await get_settings(uid)
        await send_clean(context, uid, "⏱ *Select Timeframe:*", parse_mode="Markdown",
                                   reply_markup=kb_timeframe(s["contract_type"]))
        return

    if d.startswith("tf_"):
        tf = d[3:]
        await update_settings(uid, timeframe=tf)
        await send_clean(context, uid, f"✅ Timeframe: `{tf}`", parse_mode="Markdown", reply_markup=kb_back())
        return

    # SETTINGS — STAKE
    if d == "set_stake":
        await set_user_state(uid, "awaiting_stake")
        await send_clean(context, uid, 
            "💰 *Stake Amount*\n\nEnter amount in USD (e.g. `10`, `0.5`, `100`):",
            parse_mode="Markdown", reply_markup=kb_back()
        )
        return

    # SETTINGS — TAKE PROFIT
    if d == "set_tp":
        s = await get_settings(uid)
        tp_label = f"{s['tp_value']}%" if s['tp_type'] == 'percent' else f"${s['tp_value']}"
        await send_clean(context, uid, 
            f"🎯 *Take Profit*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Current: `{tp_label}`\n\n"
            f"Choose type first, then enter value:",
            parse_mode="Markdown", reply_markup=kb_tp_sl("tp")
        )
        return

    if d == "tp_type_percent":
        await update_settings(uid, tp_type="percent")
        await set_user_state(uid, "awaiting_tp")
        await send_clean(context, uid, 
            "🎯 Enter Take Profit as *% of stake*\n(e.g. `110` = 110% of stake):",
            parse_mode="Markdown", reply_markup=kb_back("set_tp")
        )
        return

    if d == "tp_type_fixed":
        await update_settings(uid, tp_type="fixed")
        await set_user_state(uid, "awaiting_tp")
        await send_clean(context, uid, 
            "🎯 Enter Take Profit as *fixed USD amount*\n(e.g. `50`):",
            parse_mode="Markdown", reply_markup=kb_back("set_tp")
        )
        return

    # SETTINGS — STOP LOSS
    if d == "set_sl":
        s = await get_settings(uid)
        sl_label = f"{s['sl_value']}%" if s['sl_type'] == 'percent' else f"${s['sl_value']}"
        await send_clean(context, uid, 
            f"🛑 *Stop Loss*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Current: `{sl_label}`\n\n"
            f"Choose type first, then enter value:",
            parse_mode="Markdown", reply_markup=kb_tp_sl("sl")
        )
        return

    if d == "sl_type_percent":
        await update_settings(uid, sl_type="percent")
        await set_user_state(uid, "awaiting_sl")
        await send_clean(context, uid, 
            "🛑 Enter Stop Loss as *% of stake*\n(e.g. `100` = 100% of stake):",
            parse_mode="Markdown", reply_markup=kb_back("set_sl")
        )
        return

    if d == "sl_type_fixed":
        await update_settings(uid, sl_type="fixed")
        await set_user_state(uid, "awaiting_sl")
        await send_clean(context, uid, 
            "🛑 Enter Stop Loss as *fixed USD amount*\n(e.g. `30`):",
            parse_mode="Markdown", reply_markup=kb_back("set_sl")
        )
        return

    # SETTINGS — MARTINGALE
    if d == "set_martingale":
        s = await get_settings(uid)
        await send_clean(context, uid, 
            f"📈 *Martingale*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Status     : `{'ON ✅' if s['martingale_enabled'] else 'OFF'}`\n"
            f"Multiplier : `×{s['martingale_multiplier']}`\n"
            f"Max Steps  : `{s['martingale_max_steps']}`",
            parse_mode="Markdown",
            reply_markup=kb_martingale(s["martingale_enabled"], s["martingale_multiplier"], s["martingale_max_steps"])
        )
        return

    if d == "mg_toggle":
        s   = await get_settings(uid)
        val = not s["martingale_enabled"]
        await update_settings(uid, martingale_enabled=val)
        s   = await get_settings(uid)
        await send_clean(context, uid, 
            f"📈 *Martingale* — `{'ON ✅' if val else 'OFF'}`",
            parse_mode="Markdown",
            reply_markup=kb_martingale(val, s["martingale_multiplier"], s["martingale_max_steps"])
        )
        return

    if d.startswith("mg_") and not d.startswith("mgs_"):
        mul = float(d[3:])
        await update_settings(uid, martingale_multiplier=mul)
        s   = await get_settings(uid)
        await send_clean(context, uid, 
            f"✅ Multiplier: `×{mul}`",
            parse_mode="Markdown",
            reply_markup=kb_martingale(s["martingale_enabled"], mul, s["martingale_max_steps"])
        )
        return

    if d.startswith("mgs_"):
        steps = int(d[4:])
        await update_settings(uid, martingale_max_steps=steps)
        s = await get_settings(uid)
        await send_clean(context, uid, 
            f"✅ Max Steps: `{steps}`",
            parse_mode="Markdown",
            reply_markup=kb_martingale(s["martingale_enabled"], s["martingale_multiplier"], steps)
        )
        return

    # SETTINGS — COMPOUND
    if d == "set_compound":
        s = await get_settings(uid)
        await send_clean(context, uid, 
            f"🔄 *Compound*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Status: `{'ON ✅' if s['compound_enabled'] else 'OFF'}`\n\n"
            f"ON: profit is added to the next stake.\n"
            f"Example: $10 stake, win $9 → next stake = $19",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"Toggle — {'✅ ON' if s['compound_enabled'] else 'OFF'}",
                    callback_data="cp_toggle"
                )],
                [InlineKeyboardButton("« Back", callback_data="settings")],
            ])
        )
        return

    if d == "cp_toggle":
        s   = await get_settings(uid)
        val = not s["compound_enabled"]
        await update_settings(uid, compound_enabled=val)
        await send_clean(context, uid, 
            f"✅ Compound: `{'ON ✅' if val else 'OFF'}`",
            parse_mode="Markdown", reply_markup=kb_back()
        )
        return

    # SETTINGS — PAIR MODE
    if d == "set_pair_mode":
        await send_clean(context, uid, 
            "🌍 *Pair Mode*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 Single", callback_data="pm_single"),
                 InlineKeyboardButton("🌐 Multi",  callback_data="pm_multi")],
                [InlineKeyboardButton("« Back", callback_data="settings")],
            ])
        )
        return

    if d.startswith("pm_"):
        mode = d[3:]
        await update_settings(uid, pair_mode=mode)
        await send_clean(context, uid, f"✅ Pair Mode: `{mode.title()}`", parse_mode="Markdown", reply_markup=kb_back())
        return

    # SETTINGS — AUTO RESTART
    if d == "set_auto_restart":
        s = await get_settings(uid)
        val = s["auto_restart"]
        await send_clean(context, uid, 
            f"🔁 *Auto Restart after TP/SL*\nCurrent: `{'ON' if val else 'OFF'}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Toggle — {'ON' if val else 'OFF'}", callback_data="ar_toggle")],
                [InlineKeyboardButton("« Back", callback_data="settings")],
            ])
        )
        return

    if d == "ar_toggle":
        s   = await get_settings(uid)
        val = not s["auto_restart"]
        await update_settings(uid, auto_restart=val)
        await send_clean(context, uid, f"✅ Auto Restart: `{'ON' if val else 'OFF'}`",
                                   parse_mode="Markdown", reply_markup=kb_back())
        return

    # SETTINGS — MULTIPLIER VALUE
    if d == "set_multiplier_value":
        await send_clean(context, uid, "✖️ *Multiplier Value:*", parse_mode="Markdown", reply_markup=kb_multiplier_val())
        return

    if d.startswith("mv_"):
        val = int(d[3:])
        await update_settings(uid, multiplier_value=val)
        await send_clean(context, uid, f"✅ Multiplier: `×{val}`", parse_mode="Markdown", reply_markup=kb_back())
        return

    # SETTINGS — ACCUMULATOR GROWTH
    if d == "set_accumulator_growth":
        await send_clean(context, uid, "📊 *Growth Rate:*", parse_mode="Markdown", reply_markup=kb_acc_growth())
        return

    if d.startswith("ag_"):
        val = float(d[3:])
        await update_settings(uid, accumulator_growth=val)
        await send_clean(context, uid, f"✅ Growth Rate: `{val}%`", parse_mode="Markdown", reply_markup=kb_back())
        return

    # SETTINGS — DIGIT BARRIER
    if d == "set_digit_barrier":
        await send_clean(context, uid, 
            "🔢 *Digit Barrier*\n\nSelect digit (Over/Under this digit):",
            parse_mode="Markdown", reply_markup=kb_digit_barrier()
        )
        return

    if d.startswith("db_"):
        val = d[3:]
        await update_settings(uid, digit_barrier=val)
        await send_clean(context, uid, f"✅ Digit Barrier: `{val}`", parse_mode="Markdown", reply_markup=kb_back())
        return

    # SETTINGS — DIGIT TARGET (Match/Diff)
    if d == "set_digit_target":
        await set_user_state(uid, "awaiting_digit_target")
        await send_clean(context, uid, 
            "🎯 *Target Digit*\n\nEnter digit 0–9:",
            parse_mode="Markdown", reply_markup=kb_back()
        )
        return

    # SETTINGS — TURBO
    if d == "set_turbo":
        await set_user_state(uid, "awaiting_turbo")
        await send_clean(context, uid, 
            "🌀 *Turbo Settings*\n\nEnter: `duration barrier_pct`\nExample: `1 0.1` (1min, 0.1% barrier)",
            parse_mode="Markdown", reply_markup=kb_back()
        )
        return

    # SETTINGS — TOUCH
    if d == "set_touch":
        await set_user_state(uid, "awaiting_touch")
        await send_clean(context, uid, 
            "👆 *Touch Settings*\n\nEnter: `duration barrier_pct`\nExample: `5 0.2`",
            parse_mode="Markdown", reply_markup=kb_back()
        )
        return

    # SETTINGS — VANILLA
    if d == "set_vanilla":
        await set_user_state(uid, "awaiting_vanilla")
        await send_clean(context, uid, 
            "🏛 *Vanilla Settings*\n\nEnter: `duration barrier_pct`\nExample: `5 0.0`",
            parse_mode="Markdown", reply_markup=kb_back()
        )
        return

    # ADMIN
    if d == "admin_panel":
        if uid != ADMIN_ID: return
        users = await get_all_users()
        await send_clean(context, uid, 
            f"🔐 *Admin Panel*\n━━━━━━━━━━━━━━━\n👥 Total Users: `{len(users)}`",
            parse_mode="Markdown", reply_markup=kb_admin()
        )
        return

    if d == "admin_users":
        if uid != ADMIN_ID: return
        users = await get_all_users()
        text  = "👥 *Users:*\n━━━━━━━━━━━━━━━\n"
        for u in users[:20]:
            text += f"• `{u['user_id']}` {u['full_name']} — `{u['license_status']}` — 🎟{u['trial_tokens']}\n"
        await send_clean(context, uid, text, parse_mode="Markdown", reply_markup=kb_back("admin_panel"))
        return

    if d == "admin_license":
        if uid != ADMIN_ID: return
        await set_user_state(uid, "admin_license")
        await send_clean(context, uid, 
            "🔑 Send: `USER_ID LICENSE`\nLicenses: `trial` `demo` `real`\nExample: `123456789 real`",
            parse_mode="Markdown", reply_markup=kb_back("admin_panel")
        )
        return

    if d == "admin_tokens":
        if uid != ADMIN_ID: return
        await set_user_state(uid, "admin_tokens")
        await send_clean(context, uid, 
            "🎟 Send: `USER_ID AMOUNT`\nExample: `123456789 50`",
            parse_mode="Markdown", reply_markup=kb_back("admin_panel")
        )
        return

    if d == "admin_broadcast":
        if uid != ADMIN_ID: return
        await set_user_state(uid, "admin_broadcast")
        await send_clean(context, uid, 
            "📢 Type your broadcast message:",
            reply_markup=kb_back("admin_panel")
        )
        return

# ══════════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ══════════════════════════════════════════════════════════════
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    text  = update.message.text.strip()
    state = await get_user_state(uid)

    # Clear state first
    await set_user_state(uid, "")

    # Delete user message for cleanliness
    try:
        await update.message.delete()
    except Exception:
        pass

    if state == "awaiting_token":
        msg = await context.bot.send_message(uid, "🔄 Verifying token...")
        client = DerivClient(text)
        ok, result = await client.authorize()
        await client.disconnect()
        if not ok:
            await set_user_state(uid, "awaiting_token")
            await msg.edit_text(
                f"❌ Token invalid: {result}\n\nPaste a valid token:",
                reply_markup=kb_back("connect_deriv")
            )
            return
        acc_type = "Demo 🎮" if client.account_type == "demo" else "Real 💰"
        bal      = result.get("balance", "N/A")
        cur      = result.get("currency", "USD")
        await update_user(uid, deriv_token=text)
        await msg.edit_text(
            f"✅ *Connected!*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Account : `{acc_type}`\n"
            f"Balance : `{bal} {cur}`",
            parse_mode="Markdown", reply_markup=kb_main()
        )

    elif state == "awaiting_pair":
        msg  = await context.bot.send_message(uid, "🔄 Checking pair...")
        user = await get_user(uid)
        if not user or not user["deriv_token"]:
            await msg.edit_text("❌ Connect Deriv first.", reply_markup=kb_back("menu"))
            return
        client = DerivClient(user["deriv_token"])
        ok, _  = await client.authorize()
        if not ok:
            await msg.edit_text("❌ Token error. Reconnect.", reply_markup=kb_back("menu"))
            await client.disconnect()
            return
        found, symbol, display, market = await client.validate_pair(text)
        await client.disconnect()
        if not found:
            await set_user_state(uid, "awaiting_pair")
            await msg.edit_text(
                f"❌ Pair `{text}` not found on Deriv.\n\nTry again:",
                parse_mode="Markdown", reply_markup=kb_back("set_pair")
            )
            return
        mkt_label = "OTC 🔄" if market == "OTC" else "Real Market 🌍"
        await update_settings(uid, pair=symbol)
        await msg.edit_text(
            f"✅ *Pair Set*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Name   : `{display}`\n"
            f"Market : `{mkt_label}`\n"
            f"Symbol : `{symbol}`",
            parse_mode="Markdown", reply_markup=kb_back()
        )

    elif state == "awaiting_multi_pairs":
        await update_settings(uid, multi_pairs=text)
        await context.bot.send_message(
            uid,
            f"✅ Multi pairs set:\n`{text}`",
            parse_mode="Markdown", reply_markup=kb_back()
        )

    elif state == "awaiting_stake":
        try:
            amt = float(text)
            if amt <= 0: raise ValueError
            await update_settings(uid, stake=amt)
            await context.bot.send_message(
                uid, f"✅ Stake: `${amt}`",
                parse_mode="Markdown", reply_markup=kb_back()
            )
        except ValueError:
            await set_user_state(uid, "awaiting_stake")
            await context.bot.send_message(uid, "❌ Invalid amount. Enter a number (e.g. `10.5`):",
                                            parse_mode="Markdown")

    elif state == "awaiting_tp":
        try:
            val = float(text)
            await update_settings(uid, tp_value=val)
            s = await get_settings(uid)
            label = f"{val}%" if s["tp_type"] == "percent" else f"${val}"
            await context.bot.send_message(uid, f"✅ Take Profit: `{label}`",
                                            parse_mode="Markdown", reply_markup=kb_back())
        except ValueError:
            await set_user_state(uid, "awaiting_tp")
            await context.bot.send_message(uid, "❌ Invalid number. Try again:")

    elif state == "awaiting_sl":
        try:
            val = float(text)
            await update_settings(uid, sl_value=val)
            s = await get_settings(uid)
            label = f"{val}%" if s["sl_type"] == "percent" else f"${val}"
            await context.bot.send_message(uid, f"✅ Stop Loss: `{label}`",
                                            parse_mode="Markdown", reply_markup=kb_back())
        except ValueError:
            await set_user_state(uid, "awaiting_sl")
            await context.bot.send_message(uid, "❌ Invalid number. Try again:")

    elif state == "awaiting_digit_target":
        try:
            d = int(text)
            if d < 0 or d > 9: raise ValueError
            await update_settings(uid, digit_target=str(d))
            await context.bot.send_message(uid, f"✅ Target Digit: `{d}`",
                                            parse_mode="Markdown", reply_markup=kb_back())
        except ValueError:
            await set_user_state(uid, "awaiting_digit_target")
            await context.bot.send_message(uid, "❌ Enter a digit 0–9:")

    elif state == "awaiting_turbo":
        try:
            parts = text.split()
            dur, pct = int(parts[0]), float(parts[1])
            await update_settings(uid, turbo_duration=dur, turbo_barrier_pct=pct)
            await context.bot.send_message(uid, f"✅ Turbo: `{dur}m` barrier `{pct}%`",
                                            parse_mode="Markdown", reply_markup=kb_back())
        except Exception:
            await set_user_state(uid, "awaiting_turbo")
            await context.bot.send_message(uid, "❌ Format: `duration barrier_pct` e.g. `1 0.1`",
                                            parse_mode="Markdown")

    elif state == "awaiting_touch":
        try:
            parts = text.split()
            dur, pct = int(parts[0]), float(parts[1])
            await update_settings(uid, touch_duration=dur, touch_barrier_pct=pct)
            await context.bot.send_message(uid, f"✅ Touch: `{dur}m` barrier `{pct}%`",
                                            parse_mode="Markdown", reply_markup=kb_back())
        except Exception:
            await set_user_state(uid, "awaiting_touch")
            await context.bot.send_message(uid, "❌ Format: `duration barrier_pct` e.g. `5 0.2`",
                                            parse_mode="Markdown")

    elif state == "awaiting_vanilla":
        try:
            parts = text.split()
            dur, pct = int(parts[0]), float(parts[1])
            await update_settings(uid, vanilla_duration=dur, vanilla_barrier_pct=pct)
            await context.bot.send_message(uid, f"✅ Vanilla: `{dur}m` barrier `{pct}%`",
                                            parse_mode="Markdown", reply_markup=kb_back())
        except Exception:
            await set_user_state(uid, "awaiting_vanilla")
            await context.bot.send_message(uid, "❌ Format: `duration barrier_pct` e.g. `5 0.0`",
                                            parse_mode="Markdown")

    elif state == "admin_license":
        if uid != ADMIN_ID: return
        parts = text.split()
        if len(parts) != 2 or parts[1] not in ("trial", "demo", "real"):
            await set_user_state(uid, "admin_license")
            await context.bot.send_message(uid, "❌ Format: `USER_ID LICENSE`\nLicenses: trial demo real")
            return
        target, lic = int(parts[0]), parts[1]
        await update_user(target, license_status=lic)
        await context.bot.send_message(uid, f"✅ User `{target}` → `{lic}`",
                                        parse_mode="Markdown", reply_markup=kb_back("admin_panel"))

    elif state == "admin_tokens":
        if uid != ADMIN_ID: return
        parts = text.split()
        if len(parts) != 2:
            await set_user_state(uid, "admin_tokens")
            await context.bot.send_message(uid, "❌ Format: `USER_ID AMOUNT`")
            return
        target, tokens = int(parts[0]), int(parts[1])
        await update_user(target, trial_tokens=tokens)
        await context.bot.send_message(uid, f"✅ User `{target}` → `{tokens}` tokens",
                                        parse_mode="Markdown", reply_markup=kb_back("admin_panel"))

    elif state == "admin_broadcast":
        if uid != ADMIN_ID: return
        users = await get_all_users()
        ok = 0
        for u in users:
            try:
                await context.bot.send_message(chat_id=u["user_id"], text=f"📢 {text}")
                ok += 1
            except Exception:
                pass
        await context.bot.send_message(uid, f"✅ Sent to {ok}/{len(users)} users.",
                                        reply_markup=kb_back("admin_panel"))
    else:
        await context.bot.send_message(uid, "Use the buttons below.", reply_markup=kb_main())

# ══════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════
async def cmd_setvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.video:
        await update.message.reply_text(
            "Reply to a video with /setvideo to set the Deriv tutorial video."
        )
        return
    file_id = update.message.reply_to_message.video.file_id
    await set_config("deriv_tutorial_video", file_id)
    try:
        await update.message.delete()
    except Exception:
        pass
    await context.bot.send_message(update.effective_user.id, "✅ Tutorial video saved.")

async def cmd_clearvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await set_config("deriv_tutorial_video", "")
    try:
        await update.message.delete()
    except Exception:
        pass
    await context.bot.send_message(update.effective_user.id, "✅ Tutorial video removed.")

# ══════════════════════════════════════════════════════════════
# HEALTH CHECK (Render requires HTTP server)
# ══════════════════════════════════════════════════════════════
async def _health(request):
    return web.Response(text="EVALON OK")

async def _start_web():
    wa = web.Application()
    wa.router.add_get("/", _health)
    runner = web.AppRunner(wa)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check running on port {port}")

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
async def _main():
    await init_db()
    await _start_web()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("setvideo",   cmd_setvideo))
    app.add_handler(CommandHandler("clearvideo", cmd_clearvideo))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("EVALON Bot v2 started")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Polling active")
        await asyncio.Event().wait()

def main():
    asyncio.run(_main())

if __name__ == "__main__":
    main()

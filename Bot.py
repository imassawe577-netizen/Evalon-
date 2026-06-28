"""
╔══════════════════════════════════════════════════════╗
║         EVALON DERIV AUTO-TRADING BOT                ║
║         Single-file version | All features           ║
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

# ══════════════════════════════════════════════════════════════
# DATABASE  (pg8000 — pure Python, works on any Python version)
# ══════════════════════════════════════════════════════════════
import urllib.parse as _urlparse

def _get_conn_params():
    """Parse DATABASE_URL into pg8000 params"""
    u = _urlparse.urlparse(DATABASE_URL)
    return {
        "host":     u.hostname,
        "port":     u.port or 5432,
        "database": u.path.lstrip("/"),
        "user":     u.username,
        "password": u.password,
        "ssl_context": True,
    }

def _run(sql, params=(), fetch="none"):
    p = _get_conn_params()
    con = pg8000.native.Connection(**p)
    try:
        result = con.run(sql, **{f"p{i+1}": v for i, v in enumerate(params)}) if params else con.run(sql)
        if fetch == "one":
            cols = [c["name"] for c in con.columns]
            return dict(zip(cols, result[0])) if result else None
        if fetch == "all":
            cols = [c["name"] for c in con.columns]
            return [dict(zip(cols, row)) for row in result]
    finally:
        con.close()

async def _db(sql, params=(), fetch="none"):
    # pg8000 uses :p1 :p2 style — convert %s to :p1, :p2...
    idx = 0
    new_sql = ""
    for ch in sql:
        if ch == "%":
            new_sql += f":p{idx+1}"
            idx += 1
        elif ch == "s" and new_sql.endswith(f":p{idx}"):
            pass  # already replaced
        else:
            new_sql += ch
    # Actually easier: just replace %s sequentially
    count = sql.count("%s")
    new_sql = sql
    for i in range(count):
        new_sql = new_sql.replace("%s", f":p{i+1}", 1)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _run(new_sql, params, fetch))

async def init_db():
    await _db("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            license_status TEXT DEFAULT 'trial',
            trial_tokens INTEGER DEFAULT 20,
            deriv_token TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
            contract_type TEXT DEFAULT 'rise_fall',
            pair TEXT DEFAULT '',
            market_type TEXT DEFAULT 'real',
            timeframe TEXT DEFAULT '1',
            stake NUMERIC DEFAULT 1.0,
            martingale_enabled BOOLEAN DEFAULT FALSE,
            martingale_multiplier NUMERIC DEFAULT 2.0,
            martingale_max_steps INTEGER DEFAULT 5,
            compound_enabled BOOLEAN DEFAULT FALSE,
            tp_amount NUMERIC DEFAULT 50.0,
            sl_amount NUMERIC DEFAULT 30.0,
            multiplier_value INTEGER DEFAULT 40,
            accumulator_growth NUMERIC DEFAULT 0.03,
            pair_mode TEXT DEFAULT 'single',
            multi_pairs TEXT DEFAULT '',
            auto_restart BOOLEAN DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS trade_sessions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            contract_type TEXT, pair TEXT, direction TEXT,
            stake NUMERIC, result TEXT, profit NUMERIC DEFAULT 0,
            step INTEGER DEFAULT 1, cycle INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await _db("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
            is_running BOOLEAN DEFAULT FALSE,
            current_direction TEXT, current_stake NUMERIC,
            current_step INTEGER DEFAULT 1, current_cycle INTEGER DEFAULT 1,
            total_profit NUMERIC DEFAULT 0, contract_id TEXT,
            started_at TIMESTAMP DEFAULT NOW()
        )
    """)
    logger.info("✅ Database initialized")

async def get_user(user_id: int):
    return await _db("SELECT * FROM users WHERE user_id=%s", (user_id,), fetch="one")

async def create_user(user_id: int, username: str, full_name: str):
    await _db("""
        INSERT INTO users (user_id,username,full_name)
        VALUES (%s,%s,%s) ON CONFLICT (user_id) DO NOTHING
    """, (user_id, username, full_name))
    await _db("""
        INSERT INTO user_settings (user_id)
        VALUES (%s) ON CONFLICT (user_id) DO NOTHING
    """, (user_id,))

async def update_user(user_id: int, **kwargs):
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    await _db(f"UPDATE users SET {sets} WHERE user_id=%s", vals)

async def get_settings(user_id: int):
    return await _db("SELECT * FROM user_settings WHERE user_id=%s", (user_id,), fetch="one")

async def update_settings(user_id: int, **kwargs):
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    await _db(f"UPDATE user_settings SET {sets}, updated_at=NOW() WHERE user_id=%s", vals)

async def get_active_session(user_id: int):
    return await _db("SELECT * FROM active_sessions WHERE user_id=%s", (user_id,), fetch="one")

async def upsert_active_session(user_id: int, **kwargs):
    row = await _db("SELECT user_id FROM active_sessions WHERE user_id=%s", (user_id,), fetch="one")
    if row:
        sets = ", ".join(f"{k}=%s" for k in kwargs)
        vals = list(kwargs.values()) + [user_id]
        await _db(f"UPDATE active_sessions SET {sets} WHERE user_id=%s", vals)
    else:
        kwargs["user_id"] = user_id
        cols = ", ".join(kwargs.keys())
        phs  = ", ".join(["%s"] * len(kwargs))
        await _db(f"INSERT INTO active_sessions ({cols}) VALUES ({phs})", list(kwargs.values()))

async def save_trade(user_id, contract_type, pair, direction, stake, result, profit, step, cycle):
    await _db("""
        INSERT INTO trade_sessions
          (user_id,contract_type,pair,direction,stake,result,profit,step,cycle)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (user_id, contract_type, pair, direction, stake, result, profit, step, cycle))

async def get_trade_history(user_id: int, limit: int = 10):
    return await _db("""
        SELECT * FROM trade_sessions WHERE user_id=%s
        ORDER BY created_at DESC LIMIT %s
    """, (user_id, limit), fetch="all")

async def deduct_trial_token(user_id: int):
    await _db("""
        UPDATE users SET trial_tokens=trial_tokens-1
        WHERE user_id=%s AND trial_tokens>0
    """, (user_id,))

async def get_all_users():
    return await _db("SELECT * FROM users ORDER BY created_at DESC", fetch="all")

# ══════════════════════════════════════════════════════════════
# DERIV CLIENT
# ══════════════════════════════════════════════════════════════
class DerivClient:
    def __init__(self, token: str):
        self.token        = token
        self.ws           = None
        self.authorized   = False
        self.account_type = None

    async def connect(self):
        self.ws = await websockets.connect(DERIV_WS_URL)

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def _send(self, payload: dict):
        await self.ws.send(json.dumps(payload))

    async def _recv(self):
        return json.loads(await self.ws.recv())

    async def authorize(self):
        await self.connect()
        await self._send({"authorize": self.token})
        resp = await self._recv()
        if "error" in resp:
            await self.disconnect()
            return False, resp["error"]["message"]
        self.authorized   = True
        acc = resp.get("authorize", {})
        self.account_type = "demo" if acc.get("is_virtual") else "real"
        return True, acc

    async def validate_pair(self, pair: str):
        try:
            await self._send({"active_symbols": "brief", "product_type": "basic"})
            resp    = await self._recv()
            symbols = resp.get("active_symbols", [])
            query   = pair.upper().replace(" ", "")
            for s in symbols:
                disp = s.get("display_name","").upper().replace(" ","")
                sym  = s.get("symbol","").upper()
                if query in disp or query == sym:
                    mtype = s.get("market","")
                    is_otc = "otc" in s.get("symbol","").lower()
                    market_label = "OTC" if is_otc else mtype
                    return True, s["symbol"], s["display_name"], market_label
            return False, None, None, None
        except Exception as e:
            logger.error(f"validate_pair: {e}")
            return False, None, None, None

    async def get_candles(self, symbol: str, granularity: int, count: int = 2):
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

    async def get_last_tick(self, symbol: str):
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

    async def _buy(self, params: dict, price: float):
        try:
            await self._send({"buy": 1, "price": price, "parameters": params})
            resp = await self._recv()
            if "error" in resp:
                return None, resp["error"]["message"]
            return resp.get("buy",{}).get("contract_id"), None
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
            params["barrier"] = barrier
        return await self._buy(params, stake)

    async def buy_multiplier(self, symbol, direction, stake, multiplier, tp=None, sl=None):
        params = {
            "amount": stake, "basis": "stake",
            "contract_type": direction, "currency": "USD",
            "duration": 0, "duration_unit": "d",
            "symbol": symbol, "multiplier": multiplier, "cancellation": "0"
        }
        if tp or sl:
            params["limit_order"] = {}
            if tp: params["limit_order"]["take_profit"] = tp
            if sl: params["limit_order"]["stop_loss"]   = sl
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

    async def get_contract_status(self, contract_id: str):
        try:
            await self._send({"proposal_open_contract": 1, "contract_id": contract_id})
            return (await self._recv()).get("proposal_open_contract", {})
        except Exception as e:
            logger.error(f"get_contract_status: {e}")
            return {}

# ══════════════════════════════════════════════════════════════
# TRADING ENGINE
# ══════════════════════════════════════════════════════════════
GRANULARITY = {"1":"60","2":"120","3":"180","5":"300","10":"600","15":"900",
               "1m":"60","2m":"120","3m":"180","5m":"300","10m":"600","15m":"900"}

active_tasks: dict = {}

class TradingEngine:
    def __init__(self, user_id: int, send_fn):
        self.user_id     = user_id
        self.send        = send_fn
        self.running     = False
        self.client      = None

    async def start(self):
        user     = await get_user(self.user_id)
        settings = await get_settings(self.user_id)

        if not user or not settings:
            await self.send("❌ Setup account first — /start"); return
        if not user["deriv_token"]:
            await self.send("❌ Connect Deriv token first (Settings → Connect Deriv)"); return
        if user["license_status"] == "trial" and user["trial_tokens"] <= 0:
            await self.send(
                "⚠️ *Trial tokens finished!*\n\nContact support:\n"
                "👉 [Support 💬](http://t.me/evalonwinnersbot)",
                parse_mode="Markdown"); return
        if not settings["pair"]:
            await self.send("❌ Select a pair first — Settings → Pair"); return

        self.running = True
        await upsert_active_session(self.user_id, is_running=True,
                                    current_step=1, current_cycle=1, total_profit=0)

        self.client = DerivClient(user["deriv_token"])
        ok, result  = await self.client.authorize()
        if not ok:
            await self.send(f"❌ Token error: {result}")
            self.running = False; return

        await self.send(
            f"🚀 *Bot Started!*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Contract: `{settings['contract_type'].upper()}`\n"
            f"💱 Pair: `{settings['pair']}`\n"
            f"💰 Stake: `${settings['stake']}`\n"
            f"📈 Martingale: `{'ON ✅' if settings['martingale_enabled'] else 'OFF ❌'}`\n"
            f"🔄 Compound: `{'ON ✅' if settings['compound_enabled'] else 'OFF ❌'}`\n"
            f"🎯 TP: `${settings['tp_amount']}` | 🛑 SL: `${settings['sl_amount']}`",
            parse_mode="Markdown"
        )

        try:
            await self._loop(settings, user)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Engine error uid={self.user_id}: {e}")
            await self.send(f"❌ Error: {e}")
        finally:
            self.running = False
            await upsert_active_session(self.user_id, is_running=False)
            if self.client:
                await self.client.disconnect()

    async def stop(self):
        self.running = False
        await upsert_active_session(self.user_id, is_running=False)

    async def _loop(self, settings, user):
        step          = 1
        cycle         = 1
        base_stake    = float(settings["stake"])
        current_stake = base_stake
        total_profit  = 0.0
        ctype         = settings["contract_type"]

        while self.running:
            session = await get_active_session(self.user_id)
            if not session or not session["is_running"]:
                break

            pair      = self._pick_pair(settings)
            direction = await self._signal(pair, settings)
            if not direction:
                await asyncio.sleep(2); continue

            contract_id, err = await self._place(ctype, pair, direction, current_stake, settings)
            if err:
                await self.send(f"⚠️ Trade error: {err}")
                await asyncio.sleep(3); continue

            dir_label = "🟢 UP/RISE" if direction in ("UP","CALL","MULTUP","OVER","EVEN","ACCU") else "🔴 DOWN/FALL"
            await self.send(
                f"⚡ *Trade #{step} | Cycle {cycle}*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💱 Pair: `{pair}`\n"
                f"📍 Signal: `{dir_label}`\n"
                f"💰 Stake: `${current_stake:.2f}`\n"
                f"🔢 Step: `{step}`",
                parse_mode="Markdown"
            )

            result, profit = await self._wait(contract_id)
            if result is None:
                await asyncio.sleep(2); continue

            # Trial token deduction
            if user["license_status"] == "trial":
                await deduct_trial_token(self.user_id)
                u2 = await get_user(self.user_id)
                if u2["trial_tokens"] <= 0:
                    await self.send(
                        "⚠️ Trial tokens finished!\n"
                        "👉 [Support 💬](http://t.me/evalonwinnersbot)",
                        parse_mode="Markdown"
                    )
                    self.running = False; break

            total_profit += profit
            await save_trade(self.user_id, ctype, pair, direction,
                             current_stake, result, profit, step, cycle)
            await upsert_active_session(self.user_id, total_profit=total_profit,
                                        current_step=step, current_cycle=cycle)

            emoji = "✅ WIN" if result == "win" else "❌ LOSS"
            await self.send(
                f"{emoji}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💵 Profit: `${profit:.2f}`\n"
                f"📊 Session Total: `${total_profit:.2f}`",
                parse_mode="Markdown"
            )

            # TP check
            if total_profit >= float(settings["tp_amount"]):
                await self.send(
                    f"🎯 *Take Profit Reached!*\n💰 Total: `${total_profit:.2f}`",
                    parse_mode="Markdown"
                )
                if settings["auto_restart"]:
                    total_profit  = 0; step = 1; cycle += 1
                    current_stake = base_stake; continue
                else:
                    self.running = False; break

            # SL check
            if total_profit <= -float(settings["sl_amount"]):
                await self.send(
                    f"🛑 *Stop Loss Reached!*\n💸 Loss: `${abs(total_profit):.2f}`",
                    parse_mode="Markdown"
                )
                self.running = False; break

            # Money management
            if result == "win":
                if settings["compound_enabled"]:
                    current_stake = current_stake + profit
                else:
                    current_stake = base_stake
                step = 1; cycle += 1
            else:
                if settings["martingale_enabled"]:
                    if step < int(settings["martingale_max_steps"]):
                        current_stake *= float(settings["martingale_multiplier"])
                        step += 1
                    else:
                        await self.send(f"⚠️ Max martingale steps. Resetting cycle {cycle}.")
                        current_stake = base_stake; step = 1; cycle += 1
                else:
                    current_stake = base_stake; step = 1; cycle += 1

            await asyncio.sleep(1)

    def _pick_pair(self, settings):
        if settings["pair_mode"] == "multi" and settings["multi_pairs"]:
            pairs = [p.strip() for p in settings["multi_pairs"].split(",") if p.strip()]
            return random.choice(pairs) if pairs else settings["pair"]
        return settings["pair"]

    async def _signal(self, pair, settings):
        ct = settings["contract_type"]
        if ct in ("rise_fall","multiplier","turbo","touch","vanilla"):
            tf = str(settings["timeframe"])
            gran = int(GRANULARITY.get(tf, 60))
            candles = await self.client.get_candles(pair, gran, count=2)
            if not candles: return None
            last = candles[-1]
            o, c = float(last.get("open",0)), float(last.get("close",0))
            if c > o: return "UP"
            if c < o: return "DOWN"
            return None  # doji — skip
        elif ct == "digit_over_under":
            tick  = await self.client.get_last_tick(pair)
            digit = int(str(tick.get("quote","0"))[-1])
            return "OVER" if digit < 5 else "UNDER"
        elif ct == "digit_match_diff":
            tick  = await self.client.get_last_tick(pair)
            digit = int(str(tick.get("quote","0"))[-1])
            return str(digit)
        elif ct == "digit_even_odd":
            tick  = await self.client.get_last_tick(pair)
            digit = int(str(tick.get("quote","0"))[-1])
            return "EVEN" if digit % 2 == 0 else "ODD"
        elif ct == "accumulator":
            return "ACCU"
        return None

    async def _place(self, ct, pair, direction, stake, settings):
        tf = str(settings["timeframe"])
        dur = int(tf.replace("m","")) if tf.replace("m","").isdigit() else 1

        if ct == "rise_fall":
            dc   = "CALL" if direction == "UP" else "PUT"
            unit = "t" if dur <= 5 and "m" not in tf else "m"
            return await self.client.buy_rise_fall(pair, dc, stake, dur, unit)
        elif ct == "multiplier":
            dc = "MULTUP" if direction == "UP" else "MULTDOWN"
            return await self.client.buy_multiplier(
                pair, dc, stake, int(settings["multiplier_value"]),
                float(settings["tp_amount"]) or None,
                float(settings["sl_amount"]) or None
            )
        elif ct == "digit_over_under":
            dt = "DIGITOVER" if direction == "OVER" else "DIGITUNDER"
            return await self.client.buy_digit(pair, dt, stake, dur, barrier="5")
        elif ct == "digit_match_diff":
            return await self.client.buy_digit(pair, "DIGITMATCH", stake, dur, barrier=direction)
        elif ct == "digit_even_odd":
            dt = "DIGITEVEN" if direction == "EVEN" else "DIGITODD"
            return await self.client.buy_digit(pair, dt, stake, dur)
        elif ct == "accumulator":
            return await self.client.buy_accumulator(pair, stake, float(settings["accumulator_growth"]))
        elif ct == "turbo":
            dc   = "TURBOSLONG" if direction == "UP" else "TURBOSSHORT"
            tick = await self.client.get_last_tick(pair)
            p    = float(tick.get("quote", 0))
            bar  = f"+{p*0.001:.5f}" if direction == "UP" else f"-{p*0.001:.5f}"
            return await self.client.buy_turbo(pair, dc, stake, dur, bar)
        elif ct == "touch":
            tick = await self.client.get_last_tick(pair)
            p    = float(tick.get("quote", 0))
            bar  = f"+{p*0.002:.5f}"
            return await self.client.buy_touch(pair, "ONETOUCH", stake, dur, bar)
        elif ct == "vanilla":
            dc   = "VANILLALONGCALL" if direction == "UP" else "VANILLALONGPUT"
            tick = await self.client.get_last_tick(pair)
            p    = float(tick.get("quote", 0))
            return await self.client.buy_vanilla(pair, dc, stake, dur, f"{p:.5f}")
        return None, "Unknown contract type"

    async def _wait(self, contract_id):
        for _ in range(150):          # max ~5 minutes
            await asyncio.sleep(2)
            if not self.running:
                return None, 0
            c      = await self.client.get_contract_status(contract_id)
            profit = float(c.get("profit", 0))
            if c.get("is_sold") or c.get("status") == "sold":
                return ("win" if profit > 0 else "loss"), profit
            if c.get("is_expired") or c.get("is_settleable"):
                return ("win" if profit > 0 else "loss"), profit
        return None, 0

# ══════════════════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════════════════
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Trading", callback_data="trade_start"),
         InlineKeyboardButton("🛑 Stop",          callback_data="trade_stop")],
        [InlineKeyboardButton("⚙️ Settings",      callback_data="settings"),
         InlineKeyboardButton("📊 History",       callback_data="history")],
        [InlineKeyboardButton("💰 Balance",       callback_data="balance"),
         InlineKeyboardButton("🔑 Connect Deriv", callback_data="connect_deriv")],
        [InlineKeyboardButton("🎟️ Tokens",        callback_data="tokens"),
         InlineKeyboardButton("Support 💬",       url=SUPPORT_URL)],
    ])

def kb_settings():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 Pair",           callback_data="set_pair"),
         InlineKeyboardButton("📊 Contract Type",  callback_data="set_contract")],
        [InlineKeyboardButton("⏱️ Timeframe",      callback_data="set_timeframe"),
         InlineKeyboardButton("💰 Stake",          callback_data="set_stake")],
        [InlineKeyboardButton("📈 Martingale",     callback_data="set_martingale"),
         InlineKeyboardButton("🔄 Compound",       callback_data="set_compound")],
        [InlineKeyboardButton("🎯 Take Profit",    callback_data="set_tp"),
         InlineKeyboardButton("🛑 Stop Loss",      callback_data="set_sl")],
        [InlineKeyboardButton("🌍 Pair Mode",      callback_data="set_pair_mode"),
         InlineKeyboardButton("🔁 Auto Restart",   callback_data="set_auto_restart")],
        [InlineKeyboardButton("« Back",            callback_data="menu")],
    ])

def kb_contract():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Rise/Fall",           callback_data="ct_rise_fall")],
        [InlineKeyboardButton("✖️ Multipliers",          callback_data="ct_multiplier")],
        [InlineKeyboardButton("🔢 Digits Over/Under",   callback_data="ct_digit_over_under")],
        [InlineKeyboardButton("🎯 Digits Match/Diff",   callback_data="ct_digit_match_diff")],
        [InlineKeyboardButton("⚡ Digits Even/Odd",     callback_data="ct_digit_even_odd")],
        [InlineKeyboardButton("📊 Accumulators",        callback_data="ct_accumulator")],
        [InlineKeyboardButton("🌀 Turbos",              callback_data="ct_turbo")],
        [InlineKeyboardButton("👆 Touch/No Touch",      callback_data="ct_touch")],
        [InlineKeyboardButton("🏛️ Vanillas",            callback_data="ct_vanilla")],
        [InlineKeyboardButton("« Back",                callback_data="settings")],
    ])

def kb_timeframe(ct: str):
    ticks = [
        [InlineKeyboardButton("1 Tick",  callback_data="tf_1"),
         InlineKeyboardButton("2 Ticks", callback_data="tf_2"),
         InlineKeyboardButton("3 Ticks", callback_data="tf_3")],
        [InlineKeyboardButton("4 Ticks", callback_data="tf_4"),
         InlineKeyboardButton("5 Ticks", callback_data="tf_5")],
    ]
    mins = [
        [InlineKeyboardButton("1 Min",  callback_data="tf_1m"),
         InlineKeyboardButton("2 Min",  callback_data="tf_2m"),
         InlineKeyboardButton("3 Min",  callback_data="tf_3m")],
        [InlineKeyboardButton("5 Min",  callback_data="tf_5m"),
         InlineKeyboardButton("10 Min", callback_data="tf_10m"),
         InlineKeyboardButton("15 Min", callback_data="tf_15m")],
    ]
    if ct in ("digit_over_under","digit_match_diff","digit_even_odd"):
        rows = ticks
    elif ct == "rise_fall":
        rows = ticks + mins
    elif ct in ("turbo","touch","vanilla","multiplier"):
        rows = mins
    elif ct == "accumulator":
        rows = [[InlineKeyboardButton("Tick-based (continuous)", callback_data="tf_1")]]
    else:
        rows = mins
    rows.append([InlineKeyboardButton("« Back", callback_data="settings")])
    return InlineKeyboardMarkup(rows)

def kb_martingale(on: bool):
    s = "✅ ON" if on else "❌ OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Toggle: {s}", callback_data="mg_toggle")],
        [InlineKeyboardButton("x1.5", callback_data="mg_1.5"),
         InlineKeyboardButton("x2.2", callback_data="mg_2.2"),
         InlineKeyboardButton("x2.6", callback_data="mg_2.6"),
         InlineKeyboardButton("x3.0", callback_data="mg_3.0")],
        [InlineKeyboardButton("Max 3", callback_data="mgs_3"),
         InlineKeyboardButton("Max 4", callback_data="mgs_4"),
         InlineKeyboardButton("Max 5", callback_data="mgs_5")],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_compound(on: bool):
    s = "✅ ON" if on else "❌ OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Toggle: {s}", callback_data="cp_toggle")],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_pair_mode():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 Single Pair", callback_data="pm_single")],
        [InlineKeyboardButton("🌐 Multi Pair",  callback_data="pm_multi")],
        [InlineKeyboardButton("« Back",        callback_data="settings")],
    ])

def kb_auto_restart(on: bool):
    s = "✅ ON" if on else "❌ OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Auto Restart: {s}", callback_data="ar_toggle")],
        [InlineKeyboardButton("« Back", callback_data="settings")],
    ])

def kb_multiplier_val():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("x10",  callback_data="mv_10"),
         InlineKeyboardButton("x20",  callback_data="mv_20"),
         InlineKeyboardButton("x40",  callback_data="mv_40")],
        [InlineKeyboardButton("x50",  callback_data="mv_50"),
         InlineKeyboardButton("x100", callback_data="mv_100")],
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

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 All Users",     callback_data="admin_users")],
        [InlineKeyboardButton("🔑 Give License",  callback_data="admin_license")],
        [InlineKeyboardButton("🎟️ Add Tokens",    callback_data="admin_tokens")],
        [InlineKeyboardButton("📢 Broadcast",     callback_data="admin_broadcast")],
        [InlineKeyboardButton("« Back",           callback_data="menu")],
    ])

def kb_back(cb="menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data=cb)]])

# ══════════════════════════════════════════════════════════════
# USER STATE (in-memory)
# ══════════════════════════════════════════════════════════════
user_states: dict = {}

# ══════════════════════════════════════════════════════════════
# HANDLERS — /start
# ══════════════════════════════════════════════════════════════
WELCOME = """
🤖 *Welcome to EVALON Deriv Trader!*
━━━━━━━━━━━━━━━━━━━━━

⚡ *Fully automated trading on Deriv*

✅ Rise/Fall  ✅ Multipliers
✅ Digits     ✅ Accumulators
✅ Turbos     ✅ Touch/No Touch
✅ Vanillas

📊 *Smart Features:*
• Martingale & Compound system
• Single & Multi-pair trading
• Auto Take Profit / Stop Loss
• 20 free trial tokens (demo)

━━━━━━━━━━━━━━━━━━━━━
⚠️ *Risk Disclaimer:* Trading carries risk.
Only trade what you can afford to lose.

👆 Use the buttons below to get started!
"""

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await create_user(u.id, u.username or "", u.full_name or "")
    db_user = await get_user(u.id)

    ls = db_user["license_status"]
    tk = db_user["trial_tokens"]
    if ls == "trial":    status = f"\n🎟️ Trial tokens: *{tk}/20*"
    elif ls == "demo":   status = "\n🎮 Access: *Demo Licensed*"
    elif ls == "real":   status = "\n💰 Access: *Real Account* ✅"
    else:                status = ""

    # Admin shortcut row
    buttons = kb_main().inline_keyboard
    if u.id == ADMIN_ID:
        buttons = buttons + [[InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")]]
    kb = InlineKeyboardMarkup(buttons)

    await update.effective_message.reply_text(
        WELCOME + status, parse_mode="Markdown", reply_markup=kb
    )

# ══════════════════════════════════════════════════════════════
# HANDLERS — callback_query
# ══════════════════════════════════════════════════════════════
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q       = update.callback_query
    await q.answer()
    uid     = q.from_user.id
    data    = q.data

    # ── MENU ────────────────────────────────────────────────
    if data == "menu":
        await cmd_start(update, context)

    elif data == "settings":
        s = await get_settings(uid)
        await q.edit_message_text(
            f"⚙️ *Settings*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💱 Pair: `{s['pair'] or 'Not set'}`\n"
            f"📊 Contract: `{s['contract_type'].upper()}`\n"
            f"⏱️ Timeframe: `{s['timeframe']}`\n"
            f"💰 Stake: `${s['stake']}`\n"
            f"📈 Martingale: `{'ON ✅' if s['martingale_enabled'] else 'OFF ❌'}` "
            f"(x{s['martingale_multiplier']}, max {s['martingale_max_steps']})\n"
            f"🔄 Compound: `{'ON ✅' if s['compound_enabled'] else 'OFF ❌'}`\n"
            f"🎯 TP: `${s['tp_amount']}` | 🛑 SL: `${s['sl_amount']}`\n"
            f"🌍 Mode: `{s['pair_mode'].upper()}`\n"
            f"🔁 Auto Restart: `{'ON' if s['auto_restart'] else 'OFF'}`",
            parse_mode="Markdown", reply_markup=kb_settings()
        )

    # ── TRADING ─────────────────────────────────────────────
    elif data == "trade_start":
        session = await get_active_session(uid)
        if session and session["is_running"]:
            await q.edit_message_text(
                "⚠️ Bot is already running!\nPress 🛑 Stop first.",
                reply_markup=kb_main()
            ); return

        async def send_fn(text, **kw):
            await context.bot.send_message(chat_id=uid, text=text, **kw)

        engine = TradingEngine(uid, send_fn)
        task   = asyncio.create_task(engine.start())
        active_tasks[uid] = (engine, task)
        await q.edit_message_text("🚀 Starting bot...", reply_markup=kb_main())

    elif data == "trade_stop":
        if uid in active_tasks:
            engine, task = active_tasks.pop(uid)
            await engine.stop()
            task.cancel()
        else:
            await upsert_active_session(uid, is_running=False)
        await q.edit_message_text(
            "🛑 *Bot stopped.*", parse_mode="Markdown", reply_markup=kb_main()
        )

    # ── CONNECT DERIV ───────────────────────────────────────
    elif data == "connect_deriv":
        user_states[uid] = "awaiting_token"
        await q.edit_message_text(
            "🔑 *Connect Deriv Account*\n"
            "━━━━━━━━━━━━━━━\n"
            "1. Go to: `app.deriv.com/account/api-token`\n"
            "2. Create token with scopes:\n"
            "   Read, Trade, Trading info, Payments\n"
            "3. Send your token here:",
            parse_mode="Markdown", reply_markup=kb_back("menu")
        )

    # ── BALANCE ─────────────────────────────────────────────
    elif data == "balance":
        user = await get_user(uid)
        if not user or not user["deriv_token"]:
            await q.edit_message_text("❌ Connect Deriv first.", reply_markup=kb_back()); return
        client = DerivClient(user["deriv_token"])
        ok, _  = await client.authorize()
        if not ok:
            await q.edit_message_text("❌ Token error.", reply_markup=kb_back())
            await client.disconnect(); return
        bal = await client.get_balance()
        await client.disconnect()
        await q.edit_message_text(
            f"💰 *Balance*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Amount: `{bal.get('balance','N/A')} {bal.get('currency','USD')}`\n"
            f"Account: `{'Demo 🎮' if bal.get('is_virtual') else 'Real 💰'}`",
            parse_mode="Markdown", reply_markup=kb_back()
        )

    # ── HISTORY ─────────────────────────────────────────────
    elif data == "history":
        trades = await get_trade_history(uid)
        if not trades:
            await q.edit_message_text("📊 No trades yet.", reply_markup=kb_back()); return
        wins  = sum(1 for t in trades if t["result"] == "win")
        total = sum(float(t["profit"]) for t in trades)
        text  = (f"📊 *Trade History (Last 10)*\n"
                 f"━━━━━━━━━━━━━━━\n"
                 f"✅ Wins: `{wins}` | ❌ Losses: `{len(trades)-wins}`\n"
                 f"💵 Total P&L: `${total:.2f}`\n\n")
        for t in trades[:5]:
            e = "✅" if t["result"] == "win" else "❌"
            text += f"{e} `{t['contract_type']}` | `{t['pair']}` | `${float(t['profit']):.2f}`\n"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_back())

    # ── TOKENS ──────────────────────────────────────────────
    elif data == "tokens":
        user = await get_user(uid)
        ls   = user["license_status"]
        tk   = user["trial_tokens"]
        if ls == "trial":
            msg = (f"🎟️ *Trial Tokens*\n"
                   f"━━━━━━━━━━━━━━━\n"
                   f"Remaining: `{tk}/20`\n\n"
                   f"Each trade on demo uses 1 token.\n"
                   f"Contact support for a license.")
        elif ls == "demo":
            msg = "🎮 *Demo License* — Unlimited demo trading!"
        else:
            msg = "💰 *Real License* — Full access!"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())

    # ── SETTINGS: PAIR ──────────────────────────────────────
    elif data == "set_pair":
        s = await get_settings(uid)
        if s["pair_mode"] == "multi":
            user_states[uid] = "awaiting_multi_pairs"
            await q.edit_message_text(
                "🌐 *Multi Pair Mode*\n"
                "━━━━━━━━━━━━━━━\n"
                "Enter pairs separated by comma:\n"
                "Example: `R_100, R_75, frxEURUSD`",
                parse_mode="Markdown", reply_markup=kb_back("settings")
            )
        else:
            user_states[uid] = "awaiting_pair"
            await q.edit_message_text(
                "💱 *Enter Pair*\n"
                "━━━━━━━━━━━━━━━\n"
                "Type the pair you want:\n\n"
                "Examples:\n"
                "• `Volatility 100`\n"
                "• `Volatility 75 (1s)`\n"
                "• `EURUSD`\n"
                "• `GBPUSD OTC`\n"
                "• `Boom 1000`\n"
                "• `Crash 500`",
                parse_mode="Markdown", reply_markup=kb_back("settings")
            )

    elif data == "set_contract":
        await q.edit_message_text(
            "📊 *Select Contract Type:*",
            parse_mode="Markdown", reply_markup=kb_contract()
        )

    elif data.startswith("ct_"):
        ct = data[3:]
        await update_settings(uid, contract_type=ct)
        await q.edit_message_text(
            f"✅ Contract type set: `{ct.upper()}`",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif data == "set_timeframe":
        s = await get_settings(uid)
        await q.edit_message_text(
            "⏱️ *Select Timeframe:*",
            parse_mode="Markdown", reply_markup=kb_timeframe(s["contract_type"])
        )

    elif data.startswith("tf_"):
        tf = data[3:]
        await update_settings(uid, timeframe=tf)
        await q.edit_message_text(
            f"✅ Timeframe set: `{tf}`",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif data == "set_stake":
        user_states[uid] = "awaiting_stake"
        await q.edit_message_text(
            "💰 *Set Stake Amount:*\n\nEnter amount in USD (e.g. 1, 5, 10.5):",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif data == "set_martingale":
        s = await get_settings(uid)
        await q.edit_message_text(
            f"📈 *Martingale Settings*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Status: `{'ON ✅' if s['martingale_enabled'] else 'OFF ❌'}`\n"
            f"Multiplier: `x{s['martingale_multiplier']}`\n"
            f"Max Steps: `{s['martingale_max_steps']}`",
            parse_mode="Markdown", reply_markup=kb_martingale(s["martingale_enabled"])
        )

    elif data == "mg_toggle":
        s   = await get_settings(uid)
        val = not s["martingale_enabled"]
        await update_settings(uid, martingale_enabled=val)
        await q.edit_message_text(
            f"✅ Martingale: `{'ON ✅' if val else 'OFF ❌'}`",
            parse_mode="Markdown", reply_markup=kb_martingale(val)
        )

    elif data.startswith("mg_") and not data.startswith("mgs_"):
        mul = float(data[3:])
        await update_settings(uid, martingale_multiplier=mul)
        s   = await get_settings(uid)
        await q.edit_message_text(
            f"✅ Multiplier: `x{mul}`",
            parse_mode="Markdown", reply_markup=kb_martingale(s["martingale_enabled"])
        )

    elif data.startswith("mgs_"):
        steps = int(data[4:])
        await update_settings(uid, martingale_max_steps=steps)
        s = await get_settings(uid)
        await q.edit_message_text(
            f"✅ Max Steps: `{steps}`",
            parse_mode="Markdown", reply_markup=kb_martingale(s["martingale_enabled"])
        )

    elif data == "set_compound":
        s = await get_settings(uid)
        await q.edit_message_text(
            f"🔄 *Compound Settings*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Status: `{'ON ✅' if s['compound_enabled'] else 'OFF ❌'}`\n\n"
            f"When ON: profit is added to next stake\n"
            f"Example: $10 stake → win $9 → next stake = $19",
            parse_mode="Markdown", reply_markup=kb_compound(s["compound_enabled"])
        )

    elif data == "cp_toggle":
        s   = await get_settings(uid)
        val = not s["compound_enabled"]
        await update_settings(uid, compound_enabled=val)
        await q.edit_message_text(
            f"✅ Compound: `{'ON ✅' if val else 'OFF ❌'}`",
            parse_mode="Markdown", reply_markup=kb_compound(val)
        )

    elif data == "set_tp":
        user_states[uid] = "awaiting_tp"
        await q.edit_message_text(
            "🎯 *Set Take Profit:*\n\nEnter USD amount (e.g. 50):",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif data == "set_sl":
        user_states[uid] = "awaiting_sl"
        await q.edit_message_text(
            "🛑 *Set Stop Loss:*\n\nEnter USD amount (e.g. 30):",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif data == "set_pair_mode":
        await q.edit_message_text(
            "🌍 *Select Pair Mode:*",
            parse_mode="Markdown", reply_markup=kb_pair_mode()
        )

    elif data.startswith("pm_"):
        mode = data[3:]
        await update_settings(uid, pair_mode=mode)
        await q.edit_message_text(
            f"✅ Pair Mode: `{mode.upper()}`",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif data == "set_auto_restart":
        s = await get_settings(uid)
        await q.edit_message_text(
            "🔁 *Auto Restart after TP/SL:*",
            parse_mode="Markdown", reply_markup=kb_auto_restart(s["auto_restart"])
        )

    elif data == "ar_toggle":
        s   = await get_settings(uid)
        val = not s["auto_restart"]
        await update_settings(uid, auto_restart=val)
        await q.edit_message_text(
            f"✅ Auto Restart: `{'ON' if val else 'OFF'}`",
            parse_mode="Markdown", reply_markup=kb_auto_restart(val)
        )

    elif data == "set_multiplier_value":
        await q.edit_message_text(
            "✖️ *Select Multiplier Value:*",
            parse_mode="Markdown", reply_markup=kb_multiplier_val()
        )

    elif data.startswith("mv_"):
        val = int(data[3:])
        await update_settings(uid, multiplier_value=val)
        await q.edit_message_text(
            f"✅ Multiplier: `x{val}`",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif data == "set_accumulator_growth":
        await q.edit_message_text(
            "📊 *Select Growth Rate:*",
            parse_mode="Markdown", reply_markup=kb_acc_growth()
        )

    elif data.startswith("ag_"):
        val = float(data[3:])
        await update_settings(uid, accumulator_growth=val)
        await q.edit_message_text(
            f"✅ Growth Rate: `{val}%`",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    # ── ADMIN ────────────────────────────────────────────────
    elif data == "admin_panel":
        if uid != ADMIN_ID: return
        users = await get_all_users()
        await q.edit_message_text(
            f"🔐 *Admin Panel*\n━━━━━━━━━━━━━━━\n👥 Total Users: `{len(users)}`",
            parse_mode="Markdown", reply_markup=kb_admin()
        )

    elif data == "admin_users":
        if uid != ADMIN_ID: return
        users = await get_all_users()
        text  = "👥 *All Users:*\n━━━━━━━━━━━━━━━\n"
        for u in users[:20]:
            text += f"• `{u['user_id']}` {u['full_name']} — `{u['license_status']}` — 🎟️{u['trial_tokens']}\n"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_back("admin_panel"))

    elif data == "admin_license":
        if uid != ADMIN_ID: return
        user_states[uid] = "admin_license"
        await q.edit_message_text(
            "🔑 Send: `USER_ID LICENSE`\nExample: `123456789 real`\nLicenses: trial, demo, real",
            parse_mode="Markdown", reply_markup=kb_back("admin_panel")
        )

    elif data == "admin_tokens":
        if uid != ADMIN_ID: return
        user_states[uid] = "admin_tokens"
        await q.edit_message_text(
            "🎟️ Send: `USER_ID AMOUNT`\nExample: `123456789 50`",
            parse_mode="Markdown", reply_markup=kb_back("admin_panel")
        )

    elif data == "admin_broadcast":
        if uid != ADMIN_ID: return
        user_states[uid] = "admin_broadcast"
        await q.edit_message_text(
            "📢 Send the message to broadcast to all users:",
            reply_markup=kb_back("admin_panel")
        )

# ══════════════════════════════════════════════════════════════
# HANDLERS — text messages
# ══════════════════════════════════════════════════════════════
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    text  = update.message.text.strip()
    state = user_states.get(uid)

    if state == "awaiting_token":
        user_states.pop(uid, None)
        msg = await update.message.reply_text("🔄 Verifying token...")
        client = DerivClient(text)
        ok, result = await client.authorize()
        await client.disconnect()
        if not ok:
            await msg.edit_text(
                f"❌ Token invalid: {result}\n\nTry again or /menu",
                reply_markup=kb_back("connect_deriv")
            )
            return
        acc_type = "Demo 🎮" if client.account_type == "demo" else "Real 💰"
        bal      = result.get("balance","N/A")
        cur      = result.get("currency","USD")
        await update_user(uid, deriv_token=text)
        await msg.edit_text(
            f"✅ *Token Verified!*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Account: `{acc_type}`\n"
            f"Balance: `{bal} {cur}`",
            parse_mode="Markdown", reply_markup=kb_main()
        )

    elif state == "awaiting_pair":
        user_states.pop(uid, None)
        msg  = await update.message.reply_text("🔄 Checking pair on Deriv...")
        user = await get_user(uid)
        if not user or not user["deriv_token"]:
            await msg.edit_text("❌ Connect Deriv first."); return
        client = DerivClient(user["deriv_token"])
        ok, _  = await client.authorize()
        if not ok:
            await msg.edit_text("❌ Token error. Reconnect Deriv.")
            await client.disconnect(); return
        found, symbol, display, market = await client.validate_pair(text)
        await client.disconnect()
        if not found:
            await msg.edit_text(
                f"❌ Pair `{text}` not found on Deriv.\n\nTry again:",
                parse_mode="Markdown", reply_markup=kb_back("set_pair")
            )
            user_states[uid] = "awaiting_pair"; return
        mkt_label = f"{'OTC 🔄' if market == 'OTC' else 'Real Market 🌍'}"
        await update_settings(uid, pair=symbol, market_type=market)
        await msg.edit_text(
            f"✅ *Pair Confirmed!*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 Name: `{display}`\n"
            f"🌍 Market: `{mkt_label}`\n"
            f"🔑 Symbol: `{symbol}`",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif state == "awaiting_multi_pairs":
        user_states.pop(uid, None)
        await update_settings(uid, multi_pairs=text)
        await update.message.reply_text(
            f"✅ Multi pairs set:\n`{text}`",
            parse_mode="Markdown", reply_markup=kb_back("settings")
        )

    elif state == "awaiting_stake":
        user_states.pop(uid, None)
        try:
            amt = float(text)
            if amt <= 0: raise ValueError
            await update_settings(uid, stake=amt)
            await update.message.reply_text(
                f"✅ Stake set: `${amt}`",
                parse_mode="Markdown", reply_markup=kb_back("settings")
            )
        except ValueError:
            await update.message.reply_text("❌ Enter a valid number (e.g. 10.5)")
            user_states[uid] = "awaiting_stake"

    elif state == "awaiting_tp":
        user_states.pop(uid, None)
        try:
            amt = float(text)
            await update_settings(uid, tp_amount=amt)
            await update.message.reply_text(
                f"✅ Take Profit: `${amt}`",
                parse_mode="Markdown", reply_markup=kb_back("settings")
            )
        except ValueError:
            await update.message.reply_text("❌ Enter a valid number")
            user_states[uid] = "awaiting_tp"

    elif state == "awaiting_sl":
        user_states.pop(uid, None)
        try:
            amt = float(text)
            await update_settings(uid, sl_amount=amt)
            await update.message.reply_text(
                f"✅ Stop Loss: `${amt}`",
                parse_mode="Markdown", reply_markup=kb_back("settings")
            )
        except ValueError:
            await update.message.reply_text("❌ Enter a valid number")
            user_states[uid] = "awaiting_sl"

    elif state == "admin_license":
        if uid != ADMIN_ID: return
        user_states.pop(uid, None)
        parts = text.split()
        if len(parts) != 2 or parts[1] not in ("trial","demo","real"):
            await update.message.reply_text("Format: USER_ID LICENSE\nExample: 123456789 real"); return
        target, lic = int(parts[0]), parts[1]
        await update_user(target, license_status=lic)
        await update.message.reply_text(f"✅ User {target} → license: `{lic}`", parse_mode="Markdown")

    elif state == "admin_tokens":
        if uid != ADMIN_ID: return
        user_states.pop(uid, None)
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("Format: USER_ID AMOUNT\nExample: 123456789 50"); return
        target, tokens = int(parts[0]), int(parts[1])
        await update_user(target, trial_tokens=tokens)
        await update.message.reply_text(f"✅ User {target} → tokens: `{tokens}`", parse_mode="Markdown")

    elif state == "admin_broadcast":
        if uid != ADMIN_ID: return
        user_states.pop(uid, None)
        users = await get_all_users()
        ok = 0
        for u in users:
            try:
                await context.bot.send_message(chat_id=u["user_id"], text=f"📢 {text}")
                ok += 1
            except Exception:
                pass
        await update.message.reply_text(f"✅ Broadcast sent to {ok}/{len(users)} users.")

    else:
        await update.message.reply_text("👆 Use the buttons below.", reply_markup=kb_main())

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    import asyncio
    asyncio.run(_main())

async def _main():
    await init_db()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler(["start","menu"], cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("🤖 EVALON Bot started!")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("✅ Polling started")
        await asyncio.Event().wait()  # run forever

if __name__ == "__main__":
    main()

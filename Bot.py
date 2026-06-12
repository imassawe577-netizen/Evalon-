#!/usr/bin/env python3
"""
EVALON SIGNAL BOT — SuperTrend + Fractal
"""

import os
import asyncio
import logging
import time
import threading
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CHAT_ID    = os.environ.get("CHAT_ID", "8054370971")
PORT       = int(os.environ.get("PORT", 8080))
SCAN_SECS  = 60
COOLDOWN_SECS = 180   # dakika 3

BUY_IMAGE  = os.environ.get("BUY_IMAGE",  "")
SELL_IMAGE = os.environ.get("SELL_IMAGE", "")

PAIRS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "AUD/CAD": "AUDCAD=X",
    "AUD/JPY": "AUDJPY=X",
}

_COOLDOWN = {}

# ─── HEALTH SERVER (Render ping) ──────────────────────────────────────────────
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok","bot":"EVALON Signal Bot"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", PORT), _H).serve_forever(),
    daemon=True
).start()
print("Health server port {} started.".format(PORT), flush=True)

# ─── FETCH CANDLES ────────────────────────────────────────────────────────────
def fetch_candles(symbol):
    try:
        df = yf.download(symbol, interval="1m", period="1d",
                         auto_adjust=True, progress=False)
        if df is None or len(df) < 30:
            return None
        df = df[["Open", "High", "Low", "Close"]].copy()
        df.columns = ["open", "high", "low", "close"]
        df.dropna(inplace=True)
        return df.astype(float)
    except Exception as e:
        logging.warning("fetch_candles {} failed: {}".format(symbol, e))
        return None

# ─── SUPERTREND ───────────────────────────────────────────────────────────────
def calc_supertrend(df, period=10, multiplier=3.0):
    df   = df.copy()
    high = df["high"]; low = df["low"]; close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    hl2        = (high + low) / 2
    upper_band = (hl2 + multiplier * atr).copy()
    lower_band = (hl2 - multiplier * atr).copy()

    n = len(df)
    trend = [1] * n

    for i in range(1, n):
        ub_prev = upper_band.iloc[i-1]
        lb_prev = lower_band.iloc[i-1]
        c_prev  = close.iloc[i-1]

        if upper_band.iloc[i] < ub_prev or c_prev > ub_prev:
            pass
        else:
            upper_band.iloc[i] = ub_prev

        if lower_band.iloc[i] > lb_prev or c_prev < lb_prev:
            pass
        else:
            lower_band.iloc[i] = lb_prev

        c = close.iloc[i]
        if trend[i-1] == 1 and c < lower_band.iloc[i]:
            trend[i] = -1
        elif trend[i-1] == -1 and c > upper_band.iloc[i]:
            trend[i] = 1
        else:
            trend[i] = trend[i-1]

    return "BUY" if trend[-1] == 1 else "SELL"

# ─── FRACTAL ──────────────────────────────────────────────────────────────────
def calc_fractal(df):
    highs = df["high"].values
    lows  = df["low"].values
    close = float(df["close"].iloc[-1])
    n     = len(df)

    recent_bull = []
    recent_bear = []

    for i in range(2, n - 2):
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            recent_bull.append(lows[i])
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            recent_bear.append(highs[i])

    last_bull = recent_bull[-1] if recent_bull else None
    last_bear = recent_bear[-1] if recent_bear else None

    bull_ok = last_bull is not None and close > last_bull
    bear_ok = last_bear is not None and close < last_bear

    if bull_ok and bear_ok:
        return "BUY" if abs(close - last_bull) < abs(close - last_bear) else "SELL"
    elif bull_ok:
        return "BUY"
    elif bear_ok:
        return "SELL"
    return None

# ─── MARKET HOURS ─────────────────────────────────────────────────────────────
def is_market_open():
    now = datetime.utcnow()
    wd  = now.weekday()
    if wd == 5: return False
    if wd == 4 and now.hour >= 22: return False
    return True

# ─── NEXT CANDLE OPEN ─────────────────────────────────────────────────────────
def next_candle_info():
    now          = datetime.utcnow()
    next_min     = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    secs_to_open = max(0, (next_min - now).total_seconds())
    entry_str    = next_min.strftime("%H:%M UTC")
    return entry_str, secs_to_open, secs_to_open + 60  # +60 = candle inafunga

# ─── RESULT CHECK ─────────────────────────────────────────────────────────────
async def check_result(bot, pair, symbol, direction, entry_price, wait_secs):
    """Subiri candle ifunge kisha angalia win/loss/doji."""
    logging.info("RESULT WAIT {}: {:.0f}s".format(pair, wait_secs))
    await asyncio.sleep(wait_secs)

    result = None
    for attempt in range(3):
        try:
            df = yf.download(symbol, interval="1m", period="1d",
                             auto_adjust=True, progress=False)
            if df is not None and len(df) >= 2:
                c_open  = float(df["Open"].squeeze().iloc[-2])
                c_close = float(df["Close"].squeeze().iloc[-2])
                c_high  = float(df["High"].squeeze().iloc[-2])
                c_low   = float(df["Low"].squeeze().iloc[-2])
                body    = abs(c_close - c_open)
                c_range = c_high - c_low

                if c_range > 1e-8 and body / c_range < 0.10:
                    result = "doji"
                elif c_close == c_open:
                    result = "doji"
                else:
                    is_green = c_close > c_open
                    result = (direction == "BUY" and is_green) or (direction == "SELL" and not is_green)
                break
        except Exception as e:
            logging.warning("check_result {} attempt {}: {}".format(pair, attempt, e))
            await asyncio.sleep(5)

    # Fallback: price diff
    if result is None and entry_price is not None:
        try:
            df2 = yf.download(symbol, interval="1m", period="1d",
                              auto_adjust=True, progress=False)
            if df2 is not None and len(df2) >= 1:
                exit_p = float(df2["Close"].squeeze().iloc[-1])
                diff   = exit_p - entry_price
                if abs(diff) > 1e-8:
                    result = (diff > 0) if direction == "BUY" else (diff < 0)
        except Exception:
            pass

    # Format result message
    dir_label = "BUY \U0001f7e2" if direction == "BUY" else "SELL \U0001f534"
    dir_arrow = "\U0001f4c8" if direction == "BUY" else "\U0001f4c9"

    if result == "doji":
        result_label  = "DOJI \U0000301c\ufe0f"
        result_footer = "\U0000301c\ufe0f Candle closed as Doji \u2014 no clear winner.\n\U0001f501 Wait for next signal."
    elif result is True:
        result_label  = "WIN \u2705"
        result_footer = "\U0001f4b0 Congratulations! Another profit secured!\n\U0001f525 Stay focused \u2014 more signals coming!"
    elif result is False:
        result_label  = "LOSS \u274c"
        result_footer = "\U0001f4c9 Not every trade wins \u2014 stay disciplined!\n\U0001f501 Next signal coming soon."
    else:
        return

    text = (
        "\U0001f3c6 *EVALON WINNERS* \U0001f3c6\n\n"
        "\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n"
        "\U0001f4ca PAIR      : *{}*\n"
        "\u23f1 EXPIRY    : *1 MIN*\n"
        "{} DIRECTION : *{}*\n"
        "\U0001f3c6 RESULT    : *{}*\n"
        "\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n\n"
        "{}"
    ).format(pair, dir_arrow, dir_label, result_label, result_footer)

    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
        logging.info("RESULT SENT {}: {} {}".format(pair, direction, result_label))
    except TelegramError as e:
        logging.warning("Result send failed {}: {}".format(pair, e))

# ─── COMMANDS ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *EVALON Signal Bot*\n\n"
        "📡 Bot inafanya kazi — inascan pairs zote.\n"
        "⚡ Signal itatumwa moja kwa moja ukifika.\n\n"
        "📌 Commands:\n"
        "/start — maelezo\n"
        "/status — hali ya pairs\n"
        "/getid — tuma picha upate file\\_id yake",
        parse_mode="Markdown"
    )

async def cmd_getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Tuma picha yako sasa — nitakurudishia file\\_id yake.",
        parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mtumiaji anapotuma picha, rudisha file_id yake."""
    photo = update.message.photo[-1]  # Pata resolution kubwa zaidi
    file_id = photo.file_id
    await update.message.reply_text(
        "✅ *File ID yako:*\n\n`{}`\n\n"
        "Copy hii uweke kwenye Render Environment Variables kama `BUY_IMAGE` au `SELL_IMAGE`.".format(file_id),
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs_ready = []
    for pair in PAIRS:
        last = _COOLDOWN.get(pair, 0)
        remaining = COOLDOWN_SECS - (time.time() - last)
        if remaining <= 0:
            pairs_ready.append("🟢 {}".format(pair))
        else:
            pairs_ready.append("🔴 {} ({}s)".format(pair, int(remaining)))
    text = "📊 *Bot Status*\n\n" + "\n".join(pairs_ready)
    await update.message.reply_text(text, parse_mode="Markdown")

# ─── SCAN LOOP (runs as background task) ──────────────────────────────────────
async def scan_loop(bot: Bot):
    logging.info("Scan loop started.")
    while True:
        if not is_market_open():
            logging.info("Market closed — waiting 5min...")
            await asyncio.sleep(300)
            continue

        for pair, symbol in PAIRS.items():
            if time.time() - _COOLDOWN.get(pair, 0) < COOLDOWN_SECS:
                continue
            try:
                df = fetch_candles(symbol)
                if df is None or len(df) < 30:
                    continue

                st_dir   = calc_supertrend(df)
                frac_dir = calc_fractal(df)
                logging.info("{} ST={} Fractal={}".format(pair, st_dir, frac_dir))

                if not st_dir or not frac_dir or st_dir != frac_dir:
                    continue

                direction   = st_dir
                entry_price = float(df["close"].iloc[-1])
                entry_str, secs_to_open, secs_to_close = next_candle_info()

                ib        = direction == "BUY"
                dir_arrow = "📈" if ib else "📉"
                dir_label = "BUY 🟢" if ib else "SELL 🔴"
                img       = BUY_IMAGE if ib else SELL_IMAGE

                caption = (
                    "🏆 *EVALON WINNERS* 🏆\n\n"
                    "──────────────\n"
                    "📊 PAIR      : *{}*\n"
                    "⏱ EXPIRY    : *1 MIN*\n"
                    "🕐 ENTRY     : *{}*\n"
                    "{} DIRECTION : *{}*\n"
                    "──────────────\n\n"
                    "⚡ Open at next candle\n"
                    "Signal confirmed_"
                ).format(pair, entry_str, dir_arrow, dir_label)

                if img:
                    await bot.send_photo(
                        chat_id=CHAT_ID,
                        photo=img,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                else:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=caption,
                        parse_mode="Markdown"
                    )
                _COOLDOWN[pair] = time.time()
                logging.info("SIGNAL: {} {} @ {}".format(pair, direction, entry_price))

                asyncio.create_task(
                    check_result(bot, pair, symbol, direction, entry_price, secs_to_close + 5)
                )
                await asyncio.sleep(2)

            except TelegramError as te:
                logging.warning("Telegram error {}: {}".format(pair, te))
            except Exception as e:
                logging.warning("Error {}: {}".format(pair, e))

        await asyncio.sleep(SCAN_SECS)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN haijawekwa kwenye env vars.")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    from telegram.ext import MessageHandler, filters
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("getid",  cmd_getid))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message"])

    me = await app.bot.get_me()
    logging.info("Bot connected: @{}".format(me.username))

    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "✅ *EVALON Signal Bot Started*\n"
            "📡 Scanning {} pairs...\n"
            "_SuperTrend + Fractal_"
        ).format(len(PAIRS)),
        parse_mode="Markdown"
    )

    # Anza scan loop background
    asyncio.create_task(scan_loop(app.bot))

    # Keep alive
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())

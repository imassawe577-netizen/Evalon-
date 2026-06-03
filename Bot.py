#!/usr/bin/env python3
"""
EVALON WINNERS BOT - Telegram Bot v3.1
Upgraded: Ensemble ML, ADX filter, signal_outcomes, smart expiry, midnight reset
python-telegram-bot[webhooks]==21.3 + Neon PostgreSQL via psycopg2
"""

# -- OPEN PORT IMMEDIATELY - before all imports -------------
# Render requires port to open within ~5 seconds of startup
import os as _os
import threading as _threading
from http.server import HTTPServer as _HTTPServer, BaseHTTPRequestHandler as _BaseHandler

class _H(_BaseHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"ok","version":"3.1","bot":"EVALON WINNERS BOT"}' 
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200); self.end_headers()
            self.wfile.write(b"EVALON WINNERS BOT OK v3.1")
    def log_message(self, *a): pass

_PORT = int(_os.environ.get("PORT", 8080))
_t = _threading.Thread(target=lambda: _HTTPServer(("0.0.0.0", _PORT), _H).serve_forever(), daemon=True)
_t.start()
print("PORT {} open.".format(_PORT), flush=True)
# -------------------------------------------------------------

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
FINNHUB_KEY    = os.environ.get("FINNHUB_KEY", "")
CHANNEL_INVITE = "https://t.me/+mRNfGaNhz3RkZGRk"
CHANNEL_ID     = -1003403743370  # EVALON WINNERS BOT channel
BOT_USERNAME   = ""  # Set at startup in run_bot()

SUPPORT_BOT  = "Evalonwinnersbot"   # ← Admin/support bot (do not change)
REFERRAL_BOT = "Thtgalshhgsvvokksh90bot"  # Referral bot username
DERIV_TOKEN  = os.environ.get("DERIV_TOKEN", "")
# ============================================================
# DERIV WEBSOCKET - MICRO CANDLE ENGINE (5s/10s/15s)
# Used to confirm 1m signals before sending
# ============================================================
import websockets
import json as _json
import asyncio as _asyncio
from collections import defaultdict as _defaultdict
from datetime import datetime as _dt

# -- NN IMPORTS -----------------------------------------------
try:
    import numpy as np
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.exceptions import NotFittedError
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
    from sklearn.linear_model import LogisticRegression
    import pickle, os as _os_nn
    _NN_AVAILABLE = True
    # XGBoost optional
    try:
        import xgboost as xgb
        _XGB_AVAILABLE = True
    except ImportError:
        _XGB_AVAILABLE = False
        logging.info("XGBoost not installed - using GradientBoosting fallback. pip install xgboost")
    # LightGBM optional
    try:
        import lightgbm as lgb
        _LGB_AVAILABLE = True
    except ImportError:
        _LGB_AVAILABLE = False
except ImportError:
    _NN_AVAILABLE = False
    _XGB_AVAILABLE = False
    _LGB_AVAILABLE = False
    logging.warning("scikit-learn/numpy not installed - Ensemble ML disabled. Run: pip install scikit-learn numpy")
# -------------------------------------------------------------

# Deriv symbol mapping - Pocket Option pair → Deriv symbol
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

# Cache: last Deriv tick indicators per pair {pair: {data, timestamp}}
_deriv_tick_cache = {}
_DERIV_CACHE_TTL  = 30  # seconds - reuse if fresher than 30s

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

            # Request last 300 ticks (enough for indicators on 5s/10s/15s candles)
            await ws.send(_json.dumps({
                "ticks_history": symbol,
                "end": "latest",
                "count": 300,
                "style": "ticks"
            }))
            resp = _json.loads(await _asyncio.wait_for(ws.recv(), timeout=8))
            if resp.get("error") or "history" not in resp:
                logging.warning("Deriv ticks error {}: {}".format(pair, resp.get("error","")))
                return None

            prices = resp["history"]["prices"]
            times  = resp["history"]["times"]

            if len(prices) < 30:
                return None

            # Build micro-candles for 5s, 10s, 15s
            results = {}
            for candle_secs in [5, 10, 15]:
                candles = _build_micro_candles(prices, times, candle_secs)
                if len(candles) >= 3:
                    trend = _micro_trend(candles)
                    results["{}_s".format(candle_secs)] = trend
                # Compute full indicators from ticks if enough candles
                if len(candles) >= 20:
                    ind = _calc_indicators_from_ticks(prices, times, candle_secs)
                    if ind is not None:
                        results["{}_s_ind".format(candle_secs)] = ind

            if results:
                import time as _time_mod
                _deriv_tick_cache[pair] = {"data": results, "ts": _time_mod.time()}
            return results if results else None

    except Exception as e:
        logging.warning("Deriv fetch failed {}: {}".format(pair, e))
        return None



def _calc_indicators_from_ticks(prices, times, candle_secs):
    """
    Calculate RSI, MACD, EMA, BB, Momentum, Stochastic from raw Deriv ticks.
    Builds micro-candles of candle_secs duration, then computes indicators.
    Returns dict of indicators or None if not enough data.

    Used as bonus layer: indicators derived from 5s/10s/15s candles
    to confirm direction from 1H/15m.
    """
    import pandas as _pd_ticks
    candles = _build_micro_candles(prices, times, candle_secs)
    if len(candles) < 20:
        return None
    try:
        closes = _pd_ticks.Series([c["close"] for c in candles], dtype=float)
        highs  = _pd_ticks.Series([c["high"]  for c in candles], dtype=float)
        lows   = _pd_ticks.Series([c["low"]   for c in candles], dtype=float)

        # RSI (14)
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, 1e-9)
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

        # EMA 9 vs 21
        ema9  = float(closes.ewm(span=9).mean().iloc[-1])
        ema21 = float(closes.ewm(span=21).mean().iloc[-1])
        ma_diff = max(-1.0, min(1.0, (ema9 - ema21) / (ema21 + 1e-9) * 100))

        # MACD (12/26/9)
        ema12     = closes.ewm(span=12).mean()
        ema26     = closes.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_ln = macd_line.ewm(span=9).mean()
        macd_hist = float((macd_line - signal_ln).iloc[-1])
        macd_norm = max(-1.0, min(1.0, macd_hist / (closes.iloc[-1] * 0.001 + 1e-9)))

        # Bollinger Bands (20)
        sma20 = closes.rolling(20).mean()
        std20 = closes.rolling(20).std()
        bb_u  = float((sma20 + 2 * std20).iloc[-1])
        bb_l  = float((sma20 - 2 * std20).iloc[-1])
        bb_pos = max(0.0, min(1.0, (float(closes.iloc[-1]) - bb_l) / (bb_u - bb_l + 1e-9)))

        # Momentum (10 candles)
        mom = max(-1.0, min(1.0,
            float(closes.iloc[-1] - closes.iloc[-11]) / (closes.iloc[-11] + 1e-9) * 100
        )) if len(closes) >= 11 else 0.0

        # Stochastic (14)
        low14  = lows.rolling(14).min()
        high14 = highs.rolling(14).max()
        sto = max(0.0, min(100.0,
            float(((closes - low14) / (high14 - low14 + 1e-9) * 100).iloc[-1])
        ))

        # Direction: EMA cross + MACD agreement
        if ma_diff > 0 and macd_norm > 0:
            direction = "BUY"
        elif ma_diff < 0 and macd_norm < 0:
            direction = "SELL"
        else:
            direction = None

        return {
            "rsi":       rsi,
            "ma_diff":   ma_diff,
            "macd":      macd_norm,
            "bb_pos":    bb_pos,
            "mom":       mom,
            "sto":       sto,
            "direction": direction,
            "candle_secs": candle_secs,
        }
    except Exception as e:
        logging.warning("_calc_indicators_from_ticks ({}s) failed: {}".format(candle_secs, e))
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
        # Tie - use momentum as tiebreaker instead of FLAT
        if momentum >= 0:
            direction = "BUY"
        else:
            direction = "SELL"
        strength = 51  # minimal strength - tie broken by momentum

    return {
        "direction": direction,
        "strength":  strength,
        "reversal":  reversal,
        "momentum":  round(momentum, 5),
    }


async def pick_best_tf_deriv(pair, signal_direction=None):
    """
    MSINGI: Deriv micro-candle seconds ndio chanzo cha signal.

    Logic:
      - Angalia 5s, 10s, 15s zote tatu kutoka Deriv ticks
      - Kila moja ina direction yake (BUY/SELL/FLAT) na strength (0-100)
      - Kama direction == BUY  → toa 1m/2m/3m BUY signal
      - Kama direction == SELL → toa 1m/2m/3m SELL signal
      - Kama FLAT             → no signal kwa TF hiyo
      - Kati ya 5s/10s/15s zilizopita (si FLAT) → chagua yenye strength kubwa zaidi
      - signal_direction parameter imekuwa optional - sekunde inaamua direction yenyewe

    Returns: (best_tf_mins, strength, direction, reason)
      best_tf_mins: 1, 2, au 3 - au None kama hakuna signal
      strength: 0-100
      direction: "BUY" au "SELL" (kutoka sekunde, si kutoka parameter)
      reason: maelezo ya log
    """
    if pair not in DERIV_SYMBOLS:
        return (None, 0, None, "pair not in Deriv")

    try:
        data = await _asyncio.wait_for(
            _fetch_deriv_ticks(pair, seconds=15),
            timeout=10
        )
    except Exception as e:
        logging.warning("Deriv pick_best_tf failed {}: {}".format(pair, e))
        return (None, 0, None, "Deriv error")

    if not data:
        return (None, 0, None, "no Deriv data")

    # Map: micro seconds key → trade TF minutes
    tf_map = {
        "5_s":  1,   # 5s micro  → 1m trade
        "10_s": 2,   # 10s micro → 2m trade
        "15_s": 3,   # 15s micro → 3m trade
    }

    best_tf        = None
    best_str       = -1
    best_direction = None
    best_reason    = ""

    for micro_key, trade_tf in tf_map.items():
        trend = data.get(micro_key)
        if not trend:
            continue

        direction = trend["direction"]
        strength  = trend["strength"]

        # FLAT → no signal for this TF
        if direction == "FLAT":
            logging.info("Deriv {}s FLAT - skip".format(trade_tf * 5))
            continue

        # Reversal candle = unstable - lower strength penalty
        if trend.get("reversal"):
            strength = max(0, strength - 20)

        # Pick the strongest among available TFs
        if strength > best_str:
            best_str       = strength
            best_tf        = trade_tf
            best_direction = direction
            best_reason    = "{}s micro: {}% {} (reversal={})".format(
                trade_tf * 5, strength, direction, trend.get("reversal", False))

    if best_tf is None or best_direction is None:
        reason = "all micro-trends FLAT or no data - no signal"
        logging.info("Deriv pick_best_tf {}: NONE - {}".format(pair, reason))
        return (None, 0, None, reason)

    logging.info("Deriv pick_best_tf {}: {}m {} (str={}) - {}".format(
        pair, best_tf, best_direction, best_str, best_reason))
    return (best_tf, best_str, best_direction, best_reason)


# Keep old name as alias for backward compatibility
async def confirm_signal_with_deriv(pair, signal_direction):
    tf, strength, direction, reason = await pick_best_tf_deriv(pair)
    if tf is None or strength == 0:
        return ("REJECT", reason)
    if strength >= 60:
        return ("CONFIRM", reason)
    return ("SKIP", reason)




async def select_best_expiry_nonOTC(pair, direction, sig_snapshot,
                                     rsi, sto, ma_diff, macd, bb_pos, mom, vol, candle,
                                     atr_pct=0.05, adx_val=20.0, cci_val=0.0, wpr_val=-50.0,
                                     fib_bonus=0, pa_score=0, pattern_bonus=0,
                                     tf_votes=0, pip_movement=0.08):
    """
    Intelligently select best expiry for a non-OTC signal.

    Returns: (best_tf: int, reason: str)
    - best_tf: 1, 2, or 3 (minutes). Returns 0 if no good TF found.
    - reason: explanation string for logging

    Scoring per TF (1/2/3):
      score_tf = (deriv_score * 0.40) + (db_score * 0.35) + (ml_score * 0.25)
    """
    if "OTC" in pair:
        return (2, "OTC - expiry not applicable")

    scores = {1: 0.0, 2: 0.0, 3: 0.0}
    reasons = {1: [], 2: [], 3: []}

    # -- A. Deriv WebSocket micro-trend (40% weight) ----------
    deriv_score = {1: 0.0, 2: 0.0, 3: 0.0}
    try:
        data = await asyncio.wait_for(
            _fetch_deriv_ticks(pair, seconds=15),
            timeout=8
        )
        if data:
            # 1m → 5s micro, 2m → 10s micro, 3m → 15s micro
            tf_key_map = {1: "5_s", 2: "10_s", 3: "15_s"}
            for tf_m, micro_key in tf_key_map.items():
                trend = data.get(micro_key)
                if trend:
                    d   = trend.get("direction", "FLAT")
                    str_val = trend.get("strength", 0)
                    rev = trend.get("reversal", False)
                    if d == direction and not rev:
                        deriv_score[tf_m] = min(1.0, str_val / 100.0)
                        reasons[tf_m].append("Deriv {:.0f}%".format(str_val))
                    elif rev:
                        deriv_score[tf_m] = -0.2  # Reversal penalty
                        reasons[tf_m].append("reversal!")
    except Exception as e:
        logging.info("select_best_expiry Deriv failed {}: {}".format(pair, e))

    for tf_m in [1, 2, 3]:
        scores[tf_m] += deriv_score[tf_m] * 0.40

    # -- B. DB historical win rate per pair/session/TF (35% weight) --
    db_score = {1: 0.0, 2: 0.0, 3: 0.0}
    try:
        session_name = _get_session().get("name", "Unknown")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS win_rate,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND session = %s AND tf_mins IN (1, 2, 3)
                """, (pair, session_name))
                rows = cur.fetchall()
                # Also try overall stats
                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS win_rate,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND tf_mins IN (1, 2, 3)
                """, (pair,))
                overall_rows = cur.fetchall()
        # Session-specific wins (higher weight)
        session_data = {}
        for r in rows:
            if r["win_rate"] is not None and int(r["total"]) >= 3:
                session_data[int(r["tf_mins"])] = (float(r["win_rate"]), int(r["total"]))
        # Overall wins (fallback)
        overall_data = {}
        for r in overall_rows:
            if r["win_rate"] is not None and int(r["total"]) >= 3:
                overall_data[int(r["tf_mins"])] = (float(r["win_rate"]), int(r["total"]))

        for tf_m in [1, 2, 3]:
            if tf_m in session_data:
                wr, total = session_data[tf_m]
                # Win rate 0.5 = neutral, 1.0 = max positive, 0.0 = max negative
                db_score[tf_m] = (wr - 0.4) / 0.6   # Normalise: 0.4=0, 1.0=1
                db_score[tf_m] = max(-0.5, min(1.0, db_score[tf_m]))
                conf = min(1.0, total / 20.0)  # Confidence rises with total trades
                db_score[tf_m] *= conf
                reasons[tf_m].append("DB session {:.0f}% ({} trades)".format(wr * 100, total))
            elif tf_m in overall_data:
                wr, total = overall_data[tf_m]
                db_score[tf_m] = (wr - 0.4) / 0.6
                db_score[tf_m] = max(-0.5, min(1.0, db_score[tf_m]))
                conf = min(1.0, total / 30.0)
                db_score[tf_m] *= conf * 0.7  # Overall has less weight than session
                reasons[tf_m].append("DB overall {:.0f}%".format(wr * 100))
    except Exception as e:
        logging.info("select_best_expiry DB failed {}: {}".format(pair, e))

    for tf_m in [1, 2, 3]:
        scores[tf_m] += db_score[tf_m] * 0.35

    # -- C. Ensemble ML probability per TF (25% weight) ------
    ml_score = {1: 0.0, 2: 0.0, 3: 0.0}
    if _NN_AVAILABLE and _nn_global_model is not None and _nn_global_scaler is not None:
        try:
            for tf_m in [1, 2, 3]:
                feat = _nn_features_from_signal(
                    sig_snapshot, rsi, sto, ma_diff, macd, bb_pos, mom, vol, candle,
                    atr_pct=atr_pct, adx_val=adx_val, cci_val=cci_val, wpr_val=wpr_val,
                    fib_bonus=fib_bonus, pa_score=pa_score, pattern_bonus=pattern_bonus,
                    tf_votes=tf_votes, pip_movement=pip_movement, tf_mins=tf_m
                )
                if feat is not None:
                    # Pad/trim to match scaler feature count
                    expected_features = _nn_global_scaler.n_features_in_
                    if feat.shape[1] != expected_features:
                        if feat.shape[1] < expected_features:
                            pad = np.zeros((1, expected_features - feat.shape[1]), dtype=np.float32)
                            feat = np.hstack([feat, pad])
                        else:
                            feat = feat[:, :expected_features]

                    # Check per-pair model first
                    pair_entry = _nn_per_pair.get(pair)
                    if pair_entry and pair_entry.get("samples", 0) >= _NN_MIN_PAIR_SAMPLES:
                        model  = pair_entry["model"]
                        scaler = pair_entry["scaler"]
                    else:
                        model  = _nn_global_model
                        scaler = _nn_global_scaler

                    X_sc   = scaler.transform(feat)
                    proba  = model.predict_proba(X_sc)[0]
                    prob_win = float(proba[1]) if len(proba) > 1 else 0.5
                    # Normalise: 0.5=neutral → 0, 1.0=max → 1
                    ml_score[tf_m] = (prob_win - 0.5) * 2.0
                    ml_score[tf_m] = max(-1.0, min(1.0, ml_score[tf_m]))
                    reasons[tf_m].append("ML {:.0f}%".format(prob_win * 100))
        except Exception as e:
            logging.info("select_best_expiry ML failed {}: {}".format(pair, e))

    for tf_m in [1, 2, 3]:
        scores[tf_m] += ml_score[tf_m] * 0.25

    # -- D. Final decision -----------------------------------
    best_tf   = max(scores, key=lambda t: scores[t])
    best_score = scores[best_tf]

    # Minimum threshold: composite score must be positive to use a TF
    if best_score < 0.05:
        # No TF has strong enough evidence
        return (0, "no_tf_support score={:.2f}".format(best_score))

    reason_str = "tf={}m score={:.2f} [1m:{:.2f} 2m:{:.2f} 3m:{:.2f}] | {}".format(
        best_tf, best_score,
        scores[1], scores[2], scores[3],
        " / ".join(reasons[best_tf])
    )
    logging.info("EXPIRY SELECT {}: {}".format(pair, reason_str))
    return (best_tf, reason_str)




def support_url():
    """Returns support link - opens support bot with 'admin' pre-filled."""
    return "https://t.me/{}?text=admin".format(SUPPORT_BOT)

# Health check handled by webhook server at /health path

# ============================================================
# NEON POSTGRESQL
# ============================================================
def get_conn():
    """Connect to Neon PostgreSQL with retry on SSL/EOF errors. Uses statement_timeout=15s."""
    last_err = None
    for attempt in range(3):
        try:
            conn = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=10,
                options="-c statement_timeout=15000"  # 15s query timeout
            )
            conn.autocommit = False
            return conn
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1 + attempt)
    raise last_err

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
                ALTER TABLE pair_stats ADD COLUMN IF NOT EXISTS consecutive_wins INTEGER DEFAULT 0;
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
                    avg_movement DOUBLE PRECISION DEFAULT 0.0,
                    PRIMARY KEY (pair, session, tf_mins)
                );
                ALTER TABLE tf_session_stats ADD COLUMN IF NOT EXISTS avg_movement DOUBLE PRECISION DEFAULT 0.0;
                CREATE INDEX IF NOT EXISTS idx_tf_session_pair ON tf_session_stats (pair, session);
                CREATE INDEX IF NOT EXISTS idx_signal_history_pair ON signal_history (pair, created_at DESC);
                CREATE TABLE IF NOT EXISTS reverse_pairs (
                    pair TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS nn_models (
                    model_key TEXT PRIMARY KEY,
                    model_data BYTEA NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS nn_training_data (
                    id SERIAL PRIMARY KEY,
                    pair TEXT NOT NULL,
                    features BYTEA NOT NULL,
                    label INTEGER NOT NULL,
                    tf_mins INTEGER DEFAULT 0,
                    won_at_tf1 BOOLEAN DEFAULT NULL,
                    won_at_tf2 BOOLEAN DEFAULT NULL,
                    won_at_tf3 BOOLEAN DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                ALTER TABLE nn_training_data ADD COLUMN IF NOT EXISTS tf_mins INTEGER DEFAULT 0;
                CREATE TABLE IF NOT EXISTS signal_outcomes (
                    id SERIAL PRIMARY KEY,
                    pair TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    tf_used INTEGER NOT NULL,
                    won BOOLEAN NOT NULL,
                    entry_price DOUBLE PRECISION DEFAULT NULL,
                    exit_price DOUBLE PRECISION DEFAULT NULL,
                    movement_pct DOUBLE PRECISION DEFAULT 0.0,
                    session TEXT DEFAULT NULL,
                    indicators_agree INTEGER DEFAULT 0,
                    trend_1h TEXT DEFAULT NULL,
                    confluence_level TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS last_msg_store (
                    user_id BIGINT NOT NULL,
                    msg_type TEXT NOT NULL,
                    msg_id BIGINT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, msg_type)
                );
                CREATE TABLE IF NOT EXISTS last_signal_time (
                    user_id BIGINT PRIMARY KEY,
                    signal_time DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS virtual_trades (
                    id SERIAL PRIMARY KEY,
                    pair TEXT NOT NULL,
                    entry_price DOUBLE PRECISION NOT NULL,
                    direction TEXT NOT NULL,
                    expiry DOUBLE PRECISION NOT NULL,
                    tf_secs INTEGER NOT NULL,
                    nn_feat BYTEA DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_virtual_trades_pair ON virtual_trades (pair);
                CREATE INDEX IF NOT EXISTS idx_virtual_trades_expiry ON virtual_trades (expiry);
                CREATE TABLE IF NOT EXISTS nn_signal_features (
                    user_id BIGINT NOT NULL,
                    pair TEXT NOT NULL,
                    features BYTEA NOT NULL,
                    original_direction TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, pair)
                );
            """)

        conn.commit()

# ============================================================
# PAIR STATS - win/loss tracking per pair
# ============================================================
def update_pair_stats(pair, won):
    """Update win/loss stats for a pair. won: True if signal was correct."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if won:
                    # Win resets consecutive loss streak, increments win streak
                    cur.execute("""
                        INSERT INTO pair_stats (pair, wins, losses, consecutive_losses, consecutive_wins)
                        VALUES (%s, 1, 0, 0, 1)
                        ON CONFLICT (pair) DO UPDATE SET
                            wins = pair_stats.wins + 1,
                            consecutive_losses = 0,
                            consecutive_wins = pair_stats.consecutive_wins + 1
                    """, (pair,))
                else:
                    # Loss resets win streak, increments loss streak
                    cur.execute("""
                        INSERT INTO pair_stats (pair, wins, losses, consecutive_losses, consecutive_wins)
                        VALUES (%s, 0, 1, 1, 0)
                        ON CONFLICT (pair) DO UPDATE SET
                            losses = pair_stats.losses + 1,
                            consecutive_losses = pair_stats.consecutive_losses + 1,
                            consecutive_wins = 0
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



# ============================================================
# REVERSE PAIRS - bot flips direction for these pairs
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



# ============================================================


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
            # Block if not found, already used, or revoked - revoked codes NEVER reactivate
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
# INACTIVITY TRACKER - 30 min without activity → clear state
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
# DB is source of truth - in-memory dicts are cache only
LAST_SIGNAL_MSG = {}
LAST_BOT_MSG    = {}

async def delete_last_signal(bot, chat_id, user_id):
    """Delete previous signal AND last bot message if exists."""
    for msg_type in ["signal", "bot"]:
        msg_id = None
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM last_msg_store WHERE user_id=%s AND msg_type=%s RETURNING msg_id",
                        (user_id, msg_type)
                    )
                    row = cur.fetchone()
                conn.commit()
            if row:
                msg_id = row["msg_id"]
        except Exception:
            # fallback to in-memory
            store = LAST_SIGNAL_MSG if msg_type == "signal" else LAST_BOT_MSG
            msg_id = store.pop(user_id, None)
        if msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass

def save_last_signal_msg(user_id, msg_id):
    LAST_SIGNAL_MSG[user_id] = msg_id  # in-memory cache
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO last_msg_store (user_id, msg_type, msg_id, updated_at) "
                    "VALUES (%s, 'signal', %s, NOW()) "
                    "ON CONFLICT (user_id, msg_type) DO UPDATE SET msg_id=%s, updated_at=NOW()",
                    (user_id, msg_id, msg_id)
                )
            conn.commit()
    except Exception as e:
        logging.warning("save_last_signal_msg DB failed: {}".format(e))

def save_last_bot_msg(user_id, msg_id):
    LAST_BOT_MSG[user_id] = msg_id  # in-memory cache
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO last_msg_store (user_id, msg_type, msg_id, updated_at) "
                    "VALUES (%s, 'bot', %s, NOW()) "
                    "ON CONFLICT (user_id, msg_type) DO UPDATE SET msg_id=%s, updated_at=NOW()",
                    (user_id, msg_id, msg_id)
                )
            conn.commit()
    except Exception as e:
        logging.warning("save_last_bot_msg DB failed: {}".format(e))

# ============================================================
# ANTI-SPAM
# ============================================================
LAST_SIGNAL_TIME = {}  # in-memory cache only

def is_spam(user_id):
    """Never block the user - just track timing for slight delay."""
    now  = time.time()
    last = LAST_SIGNAL_TIME.get(user_id, 0)
    if last == 0:
        # try DB
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT signal_time FROM last_signal_time WHERE user_id=%s", (user_id,))
                    row = cur.fetchone()
            if row:
                last = row["signal_time"]
                LAST_SIGNAL_TIME[user_id] = last
        except Exception:
            pass
    LAST_SIGNAL_TIME[user_id] = now
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO last_signal_time (user_id, signal_time) VALUES (%s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE SET signal_time=%s",
                    (user_id, now, now)
                )
            conn.commit()
    except Exception:
        pass
    return (now - last) < SPAM_SECONDS
    LAST_SIGNAL_TIME[user_id] = now
    return False  # Never block - user always gets signal + Get More button

async def _spam_gentle_delay(user_id):
    """If user is pressing too fast, add a tiny delay (no message shown)."""
    now  = time.time()
    last = LAST_SIGNAL_TIME.get(user_id, 0)
    gap  = now - last
    if gap < SPAM_SECONDS:
        await asyncio.sleep(SPAM_SECONDS - gap)


# -- A: SIGNAL CONFIRMATION DELAY -----------------------------
# After generating signal, wait 4 seconds and re-check direction.
# If direction changed → use new direction. User never sees the check.
_CONFIRM_DELAY_SECS = 8  # Raised from 4 - gives more time for Yahoo recheck (non-OTC)

async def _confirm_signal_direction(pair, initial_direction, is_otc):
    """
    Wait CONFIRM_DELAY_SECS seconds then re-check quick direction.
    Returns confirmed direction (may differ from initial if market moved).
    Only runs for non-OTC pairs (OTC has no Yahoo data for recheck).
    """
    if is_otc:
        return initial_direction
    await asyncio.sleep(_CONFIRM_DELAY_SECS)
    try:
        real_pair = OTC_TO_REAL.get(pair, pair)
        symbol    = YAHOO_SYMBOLS.get(real_pair)
        if not symbol:
            return initial_direction
        df = yf.download(symbol, period="1d", interval="1m",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 4:
            return initial_direction
        closes = df["Close"].squeeze().astype(float)
        opens  = df["Open"].squeeze().astype(float)
        # Check last 3 candles direction
        bull = sum(1 for i in range(-3, 0) if float(closes.iloc[i]) > float(opens.iloc[i]))
        bear = 3 - bull
        if bull >= 2 and initial_direction == "SELL":
            logging.info("CONFIRM FLIP {}: SELL→BUY (recheck shows {}bull/{}bear)".format(pair, bull, bear))
            return "BUY"
        if bear >= 2 and initial_direction == "BUY":
            logging.info("CONFIRM FLIP {}: BUY→SELL (recheck shows {}bull/{}bear)".format(pair, bull, bear))
            return "SELL"
    except Exception as e:
        logging.warning("_confirm_signal_direction {} failed: {}".format(pair, e))
    return initial_direction
# -------------------------------------------------------------

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
# ALL PAIRS - Pocket Option (forex, OTC, indices, stocks, commodities)
# ============================================================
ALL_PAIRS = [
    # Currencies - mix of OTC and non-OTC
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
    # Additional non-OTC forex - minors & exotics
    "AUD/NZD", "EUR/NZD", "GBP/NZD", "NZD/JPY", "NZD/CAD", "NZD/CHF",
    "USD/NOK", "USD/SEK", "USD/DKK", "USD/TRY", "USD/ZAR", "USD/SGD",
    "EUR/NOK", "EUR/SEK", "EUR/PLN", "EUR/TRY",
    "GBP/NOK", "GBP/SEK",
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
    "JPN225 OTC", "JPN225", "US100 OTC", "US100", "SP500 OTC", "SP500",
    "US30", "GER40", "UK100", "AUS200",
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
    # Additional forex minors & exotics
    "AUD/NZD": "AUDNZD=X", "EUR/NZD": "EURNZD=X", "GBP/NZD": "GBPNZD=X",
    "NZD/JPY": "NZDJPY=X", "NZD/CAD": "NZDCAD=X", "NZD/CHF": "NZDCHF=X",
    "USD/NOK": "USDNOK=X", "USD/SEK": "USDSEK=X", "USD/DKK": "USDDKK=X",
    "USD/TRY": "USDTRY=X", "USD/ZAR": "USDZAR=X", "USD/SGD": "USDSGD=X",
    "EUR/NOK": "EURNOK=X", "EUR/SEK": "EURSEK=X", "EUR/PLN": "EURPLN=X",
    "EUR/TRY": "EURTRY=X", "GBP/NOK": "GBPNOK=X", "GBP/SEK": "GBPSEK=X",
    # Indices
    "US100": "^NDX", "SP500": "^GSPC", "CAC 40": "^FCHI",
    "SMI 20": "^SSMI", "E35EUR": "^STOXX",
    "US30": "^DJI", "GER40": "^GDAXI", "UK100": "^FTSE",
    "JPN225": "^N225", "AUS200": "^AXJO",
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
    # RSI divergence (simple: last 5 bars - price up, RSI down = bearish div)
    rsi_series = (100 - 100 / (1 + gain / loss.replace(0, 1e-9)))
    price_change = float(close.iloc[-1] - close.iloc[-6])
    rsi_change   = float(rsi_series.iloc[-1] - rsi_series.iloc[-6])
    divergence = None
    if price_change > 0 and rsi_change < -3:
        divergence = "SELL"   # Bearish divergence
    elif price_change < 0 and rsi_change > 3:
        divergence = "BUY"    # Bullish divergence

    # Williams Fractal - scan recent candles
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
    # If both present - pick the one closest to current price
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
    1. EMA cross (9 vs 21) is REQUIRED - if absent/flat, return None immediately.
    2. Price position vs EMA21 must agree with EMA cross.
    3. MACD histogram direction must confirm.
    4. RSI 1H provides momentum confirmation.
    5. Last 3 candles direction provides momentum check.
    6. Reversal detection: if recent candles strongly oppose EMA cross + MACD flips, override.

    Returns: 'BUY', 'SELL', or None (unclear - no signal should be issued).
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
        # EMA gap must be meaningful (> 0.005%) - flat EMAs = no trend
        if ema_gap_pct < 0.005:
            return None

        ema_bull = ema9 > ema21   # True = bullish EMA structure

        # --- LAYER 2: Price vs EMA21 must agree with EMA cross ---
        price_above_ema21 = current_price > ema21
        if ema_bull and not price_above_ema21:
            # EMA says BUY but price is below EMA21 - conflict
            return None
        if not ema_bull and price_above_ema21:
            # EMA says SELL but price is above EMA21 - conflict
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
            return None   # Trend is reversing - no signal, wait for clarity
        if not ema_bull and candle_bull_count >= 3 and (macd_turning_bull or macd_bull):
            return None   # Trend is reversing - no signal, wait for clarity

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
    Smart check: if short-TF signal (1m/2m) is SELL,
    verify recent 1H candles are trending down.
    Returns True if 1H confirms direction, False if it opposes.
    Extra accuracy layer - if no 1H data, return True (proceed).
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return True  # No real data - proceed with signal
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
        return {"name": "Asian",       "buy_bias": 0,  "sell_bias": 5, "threshold": 0.65}
    elif 8 <= hour < 11:
        return {"name": "London Open", "buy_bias": 10, "sell_bias": 10, "otc": "follow",      "threshold": 0.70}
    elif 11 <= hour < 13:
        return {"name": "London Mid",  "buy_bias": 5,  "sell_bias": 5, "threshold": 0.70}
    elif 13 <= hour < 16:
        return {"name": "NY/London",   "buy_bias": 8,  "sell_bias": 8, "threshold": 0.65}
    elif 16 <= hour < 19:
        return {"name": "NY Session",  "buy_bias": 6,  "sell_bias": 8,  "otc": "follow",      "threshold": 0.70}
    elif 19 <= hour < 21:
        return {"name": "NY Close",    "buy_bias": 4,  "sell_bias": 4, "threshold": 0.65}
    else:
        return {"name": "Dead Hours",  "buy_bias": 2,  "sell_bias": 2, "threshold": 0.60}

def _session_bias():
    s = _get_session()
    return (s["buy_bias"], s["sell_bias"])

# Alias - used in handlers
def get_trading_session():
    return _get_session()

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
            return None  # Not enough history - no trend decision
        directions = [r["direction"] for r in rows]
        total = len(directions)
        buy_ratio  = directions.count("BUY")  / total
        sell_ratio = directions.count("SELL") / total
        if buy_ratio >= threshold:
            return "BUY"
        if sell_ratio >= threshold:
            return "SELL"
        return None  # Flat market - mixed signals
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

    # Fetch exit price - retry up to 3 times with 3s gap if API fails
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
        return  # No movement - skip

    if direction == "BUY":
        won = price_diff > 0
    else:
        won = price_diff < 0

    if won:
        result_text = "🏆 *EVALON WINNERS BOT {}* TF {}M - *WON* ✅".format(pair, timeframe_mins)
    else:
        result_text = "💔 *EVALON WINNERS BOT {}* TF {}M - *LOSS* ❌".format(pair, timeframe_mins)

    # -- NN FEEDBACK: feed trade outcome back to neural network --
    try:
        nn_feedback_from_vte(user_id, pair, won)
    except Exception as _nn_e:
        logging.warning("NN feedback error: {}".format(_nn_e))
    # ------------------------------------------------------------

    if not is_results_enabled():
        update_pair_stats(pair, won)
        return

    # OTC pairs - update stats internally but don't send result to user
    if "OTC" in pair:
        update_pair_stats(pair, won)
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
        update_pair_stats(pair, won)
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
    # No cooldown - signals available at any time

    state = get_user_signal_state(user_id, pair)
    if state is None:
        return {"action": "fresh"}

    signal_time = state["signal_time"]
    if isinstance(signal_time, str):
        signal_time = datetime.fromisoformat(signal_time)
    elapsed    = (datetime.utcnow() - signal_time).total_seconds()
    threshold  = state["last_timeframe"] * 60
    flip_count = state["flip_count"]

    # Returned after timeframe expired - treat as fresh
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
        # Always "same" - no block here. Warning shown in getmore_ handler
        return {"action": "same", "direction": flipped}

# ============================================================
# MARKET PATTERN DETECTION - candlestick patterns
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

    # -- DOJI: very small body (<10% of range) → trend exhaustion --
    if body1 / range1 < 0.10 and range1 > 0:
        # Doji after uptrend = potential SELL reversal
        if c2 > o2 and body2 / range2 > 0.4:
            patterns["doji_reversal_sell"] = ("SELL", 20)
        # Doji after downtrend = potential BUY reversal
        elif c2 < o2 and body2 / range2 > 0.4:
            patterns["doji_reversal_buy"] = ("BUY", 20)

    # -- HAMMER: lower shadow long, small body at top → BUY reversal --
    lower_shadow1 = min(o1, c1) - l1
    upper_shadow1 = h1 - max(o1, c1)
    if lower_shadow1 > body1 * 2 and upper_shadow1 < body1 * 0.5 and c2 < o2:
        patterns["hammer"] = ("BUY", 25)

    # -- SHOOTING STAR: upper shadow long, small body → SELL reversal --
    if upper_shadow1 > body1 * 2 and lower_shadow1 < body1 * 0.5 and c2 > o2:
        patterns["shooting_star"] = ("SELL", 25)

    # -- ENGULFING BULLISH: candle 2 bearish, candle 1 bullish > candle 2 --
    if c2 < o2 and c1 > o1 and c1 > o2 and o1 < c2:
        patterns["bullish_engulfing"] = ("BUY", 35)

    # -- ENGULFING BEARISH --
    if c2 > o2 and c1 < o1 and c1 < o2 and o1 > c2:
        patterns["bearish_engulfing"] = ("SELL", 35)

    # -- THREE WHITE SOLDIERS: candles 3 bullish mfululizo --
    if c1 > o1 and c2 > o2 and c3 > o3 and c1 > c2 > c3:
        patterns["three_white_soldiers"] = ("BUY", 40)

    # -- THREE BLACK CROWS: candles 3 bearish mfululizo --
    if c1 < o1 and c2 < o2 and c3 < o3 and c1 < c2 < c3:
        patterns["three_black_crows"] = ("SELL", 40)

    # -- INSIDE BAR: candle 1 within range of candle 2 (consolidation → breakout) --
    if h1 < h2 and l1 > l2:
        # Inside bar - neutral/continuation; follow candle 2 direction
        if c2 > o2:
            patterns["inside_bar_continuation"] = ("BUY", 15)
        else:
            patterns["inside_bar_continuation"] = ("SELL", 15)

    return patterns


def _check_pip_movement(pair):
    """
    Check average pip movement for this pair.
    Returns (avg_movement_pct, category) where category is:
      'HIGH'   - pair moves a lot (>0.12%) → 1m is sufficient
      'MEDIUM' - (0.06-0.12%) → 2m recommended
      'LOW'    - (<0.06%) → 3m, small movement
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


# ============================================================
# D - SPREAD/VOLATILITY (ATR) CHECK
# ============================================================
_ATR_DEAD_THRESHOLD = 0.015  # % - below this = dead market, no signal
_FORCE_PAIRS = set()  # Admin-forced pairs - bypass flat/dead market filter

# -- ADMIN FILTER TOGGLES -------------------------------------
# Admin anaweza kuzima/kuwasha filters hizi kwa /filteroff na /filteron
_FILTER_FLAGS = {
    "news":        True,   # News time block
    "dead":        False,  # Dead market / ATR filter - OFF by default (admin: /filteron dead)
    "conflict":    True,   # 1H vs short-TF conflict filter
    "stability":   True,   # Signal stability / flip filter
    "confluence":  True,   # Min confluence filter (indicators_agree)
    "h1confirm":   True,   # 1H candle confirmation gate
    "micro_trend": True,   # Micro-candle trend filter (5s/10s/15s green-red ratio)
}

def is_filter_on(name):
    """Returns True if filter is ON (active)."""
    return _FILTER_FLAGS.get(name, True)

def set_filter(name, state: bool):
    """Washa (True) au zima (False) filter."""
    if name in _FILTER_FLAGS:
        _FILTER_FLAGS[name] = state
        return True
    return False

def get_filters_status():
    """Rudisha status ya filters zote kwa admin."""
    lines = []
    icons = {"news": "📰", "dead": "💀", "conflict": "⚔️",
             "stability": "📉", "confluence": "🔀", "h1confirm": "1️⃣",
             "micro_trend": "🕯"}
    descs = {
        "news":        "News time block",
        "dead":        "Dead market (ATR) filter",
        "conflict":    "1H vs short-TF conflict",
        "stability":   "Signal stability filter",
        "confluence":  "Min confluence gate",
        "h1confirm":   "1H candle confirmation",
        "micro_trend": "Micro-candle trend (5s/10s/15s)",
    }
    for name, state in _FILTER_FLAGS.items():
        icon = icons.get(name, "🔧")
        desc = descs.get(name, name)
        status = "✅ ON" if state else "🔴 OFF"
        lines.append("{} *{}* - {} `[{}]`".format(icon, desc, status, name))
    return "\n".join(lines)
# -------------------------------------------------------------


def is_force_pair(pair):
    """Return True if admin has forced this pair to always give signal."""
    return pair in _FORCE_PAIRS or "__ALL__" in _FORCE_PAIRS

def _check_volatility(pair):
    """
    Calculate ATR(14) on 5m candles.
    Returns (atr_pct, is_dead) where is_dead=True means market too flat.
    Falls back to (0.05, False) if no data.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol    = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return 0.05, False
    try:
        df = yf.download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)
        if df is None or len(df) < 15:
            return 0.05, False
        high  = df["High"].squeeze().astype(float)
        low   = df["Low"].squeeze().astype(float)
        close = df["Close"].squeeze().astype(float)
        tr = pd.Series([
            max(float(high.iloc[i]) - float(low.iloc[i]),
                abs(float(high.iloc[i]) - float(close.iloc[i-1])),
                abs(float(low.iloc[i])  - float(close.iloc[i-1])))
            for i in range(1, len(close))
        ])
        atr14     = float(tr.rolling(14).mean().iloc[-1])
        price_now = float(close.iloc[-1])
        atr_pct   = atr14 / (price_now + 1e-9) * 100
        is_dead   = atr_pct < _ATR_DEAD_THRESHOLD
        return round(atr_pct, 4), is_dead
    except Exception as e:
        logging.warning("_check_volatility {} failed: {}".format(pair, e))
        return 0.05, False


# ============================================================
# L - FIBONACCI RETRACEMENT LEVELS
# ============================================================
_FIB_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]
_FIB_ZONE   = 0.008  # ±0.8% of price counts as "near a level"

def _check_fibonacci(pair, direction):
    """
    Calculate Fibonacci retracement from recent swing high/low (last 50 candles, 5m).
    Returns (fib_bonus_buy, fib_bonus_sell, nearest_level_str).
    Near support level → BUY bonus. Near resistance → SELL bonus.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol    = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return 0, 0, None
    try:
        df = yf.download(symbol, period="2d", interval="5m", progress=False, auto_adjust=True)
        if df is None or len(df) < 20:
            return 0, 0, None
        high  = df["High"].squeeze().astype(float)
        low   = df["Low"].squeeze().astype(float)
        close = df["Close"].squeeze().astype(float)
        # Swing high/low from last 50 candles
        window = min(50, len(df))
        swing_high = float(high.iloc[-window:].max())
        swing_low  = float(low.iloc[-window:].min())
        price      = float(close.iloc[-1])
        rng        = swing_high - swing_low
        if rng < 1e-9:
            return 0, 0, None

        fib_buy_bonus  = 0
        fib_sell_bonus = 0
        nearest        = None
        nearest_dist   = 999

        for level in _FIB_LEVELS:
            # Support level (retracement from top)
            support    = swing_high - level * rng
            resistance = swing_low  + level * rng
            dist_sup = abs(price - support)   / (price + 1e-9)
            dist_res = abs(price - resistance) / (price + 1e-9)

            if dist_sup < _FIB_ZONE:
                bonus = 20 if level in (0.382, 0.618) else 12
                fib_buy_bonus = max(fib_buy_bonus, bonus)
                if dist_sup < nearest_dist:
                    nearest_dist = dist_sup
                    nearest = "Fib {:.1%} support".format(level)

            if dist_res < _FIB_ZONE:
                bonus = 20 if level in (0.382, 0.618) else 12
                fib_sell_bonus = max(fib_sell_bonus, bonus)
                if dist_res < nearest_dist:
                    nearest_dist = dist_res
                    nearest = "Fib {:.1%} resistance".format(level)

        return fib_buy_bonus, fib_sell_bonus, nearest
    except Exception as e:
        logging.warning("_check_fibonacci {} failed: {}".format(pair, e))
        return 0, 0, None


# ============================================================
# M - PRICE ACTION SCORE (Higher Highs / Lower Lows)
# ============================================================
def _price_action_score(pair):
    """
    Analyze last 10 candles for higher highs / lower lows structure.
    Returns (pa_buy_bonus, pa_sell_bonus, trend_str).
    Strong uptrend (HH+HL) → BUY bonus. Downtrend (LH+LL) → SELL bonus.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol    = YAHOO_SYMBOLS.get(real_pair)
    if not symbol:
        return 0, 0, None
    try:
        df = yf.download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)
        if df is None or len(df) < 12:
            return 0, 0, None
        high  = df["High"].squeeze().astype(float).values[-12:]
        low   = df["Low"].squeeze().astype(float).values[-12:]
        close = df["Close"].squeeze().astype(float).values[-12:]

        # Count HH/HL (bullish) and LH/LL (bearish) over last 10 swings
        hh = hl = lh = ll = 0
        for i in range(1, len(high)):
            if high[i] > high[i-1]: hh += 1
            else:                    lh += 1
            if low[i] > low[i-1]:   hl += 1
            else:                    ll += 1

        bull_score = hh + hl   # max 22
        bear_score = lh + ll

        # Momentum of last 3 closes
        momentum_bull = close[-1] > close[-2] > close[-3]
        momentum_bear = close[-1] < close[-2] < close[-3]

        pa_buy  = 0
        pa_sell = 0
        trend_str = None

        if bull_score >= 16:
            pa_buy = 25
            trend_str = "Strong uptrend (HH+HL)"
            if momentum_bull: pa_buy += 10
        elif bull_score >= 12:
            pa_buy = 15
            trend_str = "Moderate uptrend"
        elif bear_score >= 16:
            pa_sell = 25
            trend_str = "Strong downtrend (LH+LL)"
            if momentum_bear: pa_sell += 10
        elif bear_score >= 12:
            pa_sell = 15
            trend_str = "Moderate downtrend"

        return pa_buy, pa_sell, trend_str
    except Exception as e:
        logging.warning("_price_action_score {} failed: {}".format(pair, e))
        return 0, 0, None


def _check_signal_history_bias(pair, direction, window=15):
    """
    Check signal history - if recent signals are mostly the same direction,
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
    Returns False if signal flipped abruptly - do not issue.

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
            return True   # Not enough history - allow signal

        directions = [r["direction"] for r in rows]
        total = len(directions)
        opposite = "SELL" if proposed_direction == "BUY" else "BUY"
        opposite_pct = directions.count(opposite) / total

        # If 70%+ of recent signals (last 5 min) were the opposite direction
        # and now we're flipping - it's an unstable sudden reversal
        if opposite_pct >= 0.70:
            logging.info("STABILITY FILTER: {} blocked flip to {} ({}% were {})".format(
                pair, proposed_direction, int(opposite_pct*100), opposite))
            return False

        return True
    except Exception as e:
        logging.warning("_check_signal_stability failed {}: {}".format(pair, e))
        return True   # Allow on error


# ============================================================
# SIGNAL ALGORITHM - Multi-Timeframe + 1H Trend Filter + Patterns
# ============================================================
# Per-pair OTC flip decision cache (in-memory, reset on restart - fine for OTC)
_otc_flip_cache: dict = {}

async def _send_nonotc_signal(context, chat, user_id, pair, direction, timeframe, sig, idx_str):
    """Send a non-OTC signal - simple clean caption."""
    ib          = direction == "BUY"
    arrow       = "Up 🟢" if ib else "Down 🔴"
    strength    = sig.get("strength", 70)
    # Ensure strength is in % format (60–99)
    if isinstance(strength, int) and strength > 100:
        strength = int(60 + (strength - 300) / 200 * 39)
    strength = max(60, min(99, int(strength)))
    caption  = "*{}* {}\n🕐 In *{}* min\n📊 Signal strength: {}%".format(
        pair, arrow, timeframe, strength)
    kb  = nonotc_signal_keyboard(pair, timeframe)
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
# Called by GET SIGNAL handler - does not modify generate_signal
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
    # Additional forex minors & exotics
    "AUD/NZD": "OANDA:AUD_NZD", "EUR/NZD": "OANDA:EUR_NZD",
    "GBP/NZD": "OANDA:GBP_NZD", "NZD/CAD": "OANDA:NZD_CAD",
    "NZD/CHF": "OANDA:NZD_CHF", "USD/NOK": "OANDA:USD_NOK",
    "USD/SEK": "OANDA:USD_SEK", "USD/DKK": "OANDA:USD_DKK",
    "USD/TRY": "OANDA:USD_TRY", "USD/ZAR": "OANDA:USD_ZAR",
    "USD/SGD": "OANDA:USD_SGD", "EUR/NOK": "OANDA:EUR_NOK",
    "EUR/SEK": "OANDA:EUR_SEK", "EUR/PLN": "OANDA:EUR_PLN",
    "EUR/TRY": "OANDA:EUR_TRY", "GBP/NOK": "OANDA:GBP_NOK",
    "GBP/SEK": "OANDA:GBP_SEK",
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


def _mtf_confirmation_score(cfg, all_dirs):
    """
    Helper: count how many of the 4 TF layers agree on a direction.
    Returns (agree_count 0-4, direction 'BUY'/'SELL'/None)
    Used to rank 1m vs 2m vs 3m by actual strength, not order.
    """
    keys = ["micro", "anchor", "mid", "bias"]
    dirs_list = [cfg.get(k) for k in keys]
    bulls = sum(1 for d in dirs_list if d == "BUY")
    bears = sum(1 for d in dirs_list if d == "SELL")
    total_valid = sum(1 for d in dirs_list if d in ("BUY", "SELL"))
    if total_valid == 0:
        return 0, None
    if bulls > bears:
        return bulls, "BUY"
    elif bears > bulls:
        return bears, "SELL"
    return 0, None


def run_mtf_signal_engine(pair):
    """
    Main entry point - called from GET SIGNAL handler.
    Evaluates ALL three TFs (1m, 2m, 3m) simultaneously and
    picks the one with the STRONGEST confirmation score.

    Confirmation rules:
      1-min : micro(5s)  + 1m  + 15m + 4h
      2-min : micro(10s) + 2m  + 30m + 4h
      3-min : micro(15s) + 3m  + 1h  + 4h

    Selection logic:
      - Full confirmation (4/4) wins over near (3/4)
      - Among equal confirmation level → highest agree_count wins
      - Among equal agree_count → highest trend_score wins
      - Near-confirmation only accepted if trend_score >= 55%
      - Minimum trend_score: 45% - below this returns no signal

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
    if trend_score < 60 or trend_dir is None:
        return {"signal_type": None, "direction": None, "near": False,
                "trend_score": trend_score, "trend_dir": trend_dir,
                "tf_labels": [], "message": "Trend too weak ({:.0f}%)".format(trend_score)}

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

    # -- Evaluate ALL three TFs and collect candidates ----------
    # TF kubwa (1m/15m/4h n.k.) ni NYONGEZA - zinaimarisha nguvu ya signal
    # Direction inakuja kutoka Deriv sekunde (pick_best_tf_deriv)
    # Hapa tunachagua TF yenye confirmation score kubwa zaidi
    # Each candidate: (priority, agree_count, trend_score, sig_type, direction, near, tf_labels, message)
    # priority: 0 = full (4/4), 1 = near (3/4) - lower is better
    candidates = []

    for sig_type in [1, 2, 3]:
        cfg    = configs[sig_type]
        result = _mtf_check_confirmation(cfg, sig_type)

        if result in ("CALL", "PUT"):
            conf_dir = "BUY" if result == "CALL" else "SELL"
            if conf_dir != trend_dir:
                continue
            agree_count, _ = _mtf_confirmation_score(cfg, all_dirs)
            tf_labels = [(lbl, all_dirs.get(key)) for lbl, key in cfg["labels"]]
            candidates.append((
                0, agree_count, trend_score, sig_type,
                result, False, tf_labels,
                "Full {} {}-min confirmation (score={})".format(result, sig_type, agree_count)
            ))

        elif result in ("NEAR_CALL", "NEAR_PUT") and trend_score >= 55:
            near_dir = "BUY" if "CALL" in result else "SELL"
            if near_dir != trend_dir:
                continue
            agree_count, _ = _mtf_confirmation_score(cfg, all_dirs)
            tf_labels = [(lbl, all_dirs.get(key)) for lbl, key in cfg["labels"]]
            candidates.append((
                1, agree_count, trend_score, sig_type,
                "CALL" if "CALL" in result else "PUT",
                True, tf_labels,
                "Near {}-min confirmation (score={}, {:.0f}%)".format(sig_type, agree_count, trend_score)
            ))

    if not candidates:
        return {"signal_type": None, "direction": None, "near": False,
                "trend_score": trend_score, "trend_dir": trend_dir,
                "tf_labels": [], "message": "No MTF confirmation (1m/2m/3m)"}

    # -- Pick the BEST candidate --------------------------------
    # Sort: priority ASC (full > near), then agree_count DESC, then trend_score DESC
    candidates.sort(key=lambda c: (c[0], -c[1], -c[2]))
    best = candidates[0]
    _prio, _agree, _ts, sig_type, direction, near, tf_labels, message = best

    logging.info("MTF BEST TF selected: {}m | agree={} | near={} | score={:.0f}% | {} candidates".format(
        sig_type, _agree, near, _ts, len(candidates)))

    return {"signal_type": sig_type, "direction": direction, "near": near,
            "trend_score": trend_score, "trend_dir": trend_dir,
            "tf_labels": tf_labels, "message": message}


def build_mtf_caption(pair, direction, sig_type, tf_labels, trend_score, near=False):
    """Simple signal caption - clean na wazi."""
    arrow = "Up 🟢" if direction == "CALL" else "Down 🔴"
    strength_pct = int(max(60, min(99, trend_score)))
    return (
        "*{}* {}\n"
        "🕐 In *{}* min\n"
        "📊 Signal strength: {}%"
    ).format(pair, arrow, sig_type, strength_pct)

# -- END MTF ENGINE -------------------------------------------

def _force_signal_from_micro(pair, signal_type):
    """
    Last-resort fallback - scan last 100 micro-timeframe candles.

    Micro TF per signal type:
      signal_type 1 = 5s  proxy → Finnhub/Yahoo 1m candles 100
      signal_type 2 = 10s proxy → Finnhub/Yahoo 1m candles 100
      signal_type 3 = 15s proxy → Finnhub/Yahoo 1m candles 100

    Logic:
      - Count last 100 candles
      - close > open = green (bullish)
      - close < open = red (bearish)
      - Majority direction shows true market trend
      - More green → BUY, more red → SELL
      - Always returns a signal - never fails
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

    # Non-OTC: require minimum 65% dominance - below this is near-random, return None
    if "OTC" not in pair and trend_score < 65.0:
        logging.info("MICRO HISTORY {}: trend_score {:.0f}% < 65% - no signal (non-OTC)".format(
            pair, trend_score))
        return None

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
    Full MTF engine with fallback for non-OTC pairs.
    Attempt order:
      1. Full confirmation (4/4)
      2. Near confirmation (3/4) - trend >= 55%
      3. 2/4 confirmation - trend >= 45%, both agreeing TFs required
      4. Micro history fallback - only if trend_score >= 60% (non-OTC)
         Returns None if nothing meets the bar (non-OTC won't force weak signals)

    signal_type: 1/2/3 or None (try all)
    """
    # For OTC - skip MTF entirely, return None so generate_signal runs
    if "OTC" in pair:
        return None

    result = run_mtf_signal_engine(pair)

    # Got full or near confirmation - done
    if result and result.get("direction") in ("CALL", "PUT"):
        return result

    # 2/4 attempt - lower bar further
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

    # Last resort: micro history fallback - only if trend_score >= 60% (non-OTC)
    # If below threshold, _force_signal_from_micro returns None and we pass None up
    st = types_to_try[0] if types_to_try else 1
    return _force_signal_from_micro(pair, st)


# ============================================================
# NEURAL NETWORK SIGNAL FILTER - ENHANCED
# ============================================================
# Features:
#   1. Per-pair models  - each pair has its own trained model
#   2. Session-aware    - session (London/NY/Asian) added as feature
#   3. Scheduled retrain - every 6 hours automatically
#   4. Admin /nnstats   - live stats command
#
# Architecture: MLPClassifier (2 hidden layers: 64→32 neurons)
# Input features (15): rsi, sto, ma_diff, macd, bb_pos, mom, vol,
#   candle, trend_1h_num, vwap_dir_num, mtf_score, indicators_agree,
#   session_num, is_otc, strength
# Output: probability of WIN
# Training: self-supervised from VTE win/loss results
# -------------------------------------------------------------

_NN_MODEL_DIR        = "/tmp/evalon_nn_models"
_NN_GLOBAL_FILE      = "/tmp/evalon_nn_models/global_model.pkl"
_NN_SCALER_FILE      = "/tmp/evalon_nn_models/global_scaler.pkl"
_NN_MIN_SAMPLES      = 40    # Minimum before NN activates
_NN_MIN_PAIR_SAMPLES = 25    # Minimum per-pair samples before pair model activates
_NN_CONFIDENCE_THRESHOLD = 0.78  # Raised from 0.72 - higher bar for accuracy
_NN_RETRAIN_HOURS    = 6     # Scheduled retrain interval

# In-memory model cache
_nn_global_model  = None
_nn_global_scaler = None
_nn_per_pair      = {}   # {pair: {"model": m, "scaler": s, "samples": n, "acc": f}}
_nn_training_data = []   # [(features_14, label), ...]
_nn_pair_data     = {}   # {pair: [(features_14, label), ...]}
_nn_last_retrain  = None # datetime of last retrain
_nn_total_flips   = 0    # how many times NN flipped direction
_nn_flip_wins     = 0    # how many flips turned out correct (won)

# Session number mapping for NN feature
_NN_SESSION_MAP = {
    "London Open":  1.0,
    "NY/London":    0.8,
    "NY Session":   0.6,
    "Asian":       -0.5,
    "Dead Hours":  -1.0,
    "Pre-London":   0.3,
}

if _NN_AVAILABLE:
    try:
        _os_nn.makedirs(_NN_MODEL_DIR, exist_ok=True)
    except Exception:
        pass


def _nn_session_num():
    """Return numeric session value for NN feature."""
    try:
        sess = _get_session()
        return _NN_SESSION_MAP.get(sess.get("name", ""), 0.0)
    except Exception:
        return 0.0


def _nn_features_from_signal(sig_dict, rsi, sto, ma_diff, macd, bb_pos, mom, vol, candle):
    """
    Extract 15 numeric features from signal components.
    Returns numpy array shape (1, 15) or None.
    Features: rsi, sto, ma_diff, macd, bb_pos, mom, vol, candle,
              trend_1h, vwap, mtf_score, indicators_agree, session, is_otc, strength
    """
    if not _NN_AVAILABLE:
        return None
    try:
        trend_num = 1.0 if sig_dict.get("trend_1h") == "BUY" else \
                   (-1.0 if sig_dict.get("trend_1h") == "SELL" else 0.0)
        vwap_data = sig_dict.get("vwap_data")
        vwap_num  = 0.0
        if vwap_data:
            vwap_dir = vwap_data.get("direction", "FLAT")
            vwap_str = vwap_data.get("strength", "WEAK")
            vwap_num = (1.0 if vwap_dir == "BUY" else -1.0) * \
                       (1.5 if vwap_str == "STRONG" else (1.0 if vwap_str == "MODERATE" else 0.5))
        mtf = sig_dict.get("mtf")
        mtf_score = 0.0
        if mtf and mtf.get("total", 0) >= 3:
            buy_tfs   = mtf.get("buy_tfs", 0)
            sell_tfs  = mtf.get("sell_tfs", 0)
            total_tfs = mtf.get("total", 1)
            mtf_score = (buy_tfs - sell_tfs) / total_tfs
        # Normalize indicators_agree: clamp to 0–20 range then scale to 0–1
        ia          = min(1.0, float(sig_dict.get("indicators_agree", 0)) / 20.0)
        session_num = _nn_session_num()
        is_otc_num  = 1.0 if sig_dict.get("is_otc", False) else 0.0
        # Strength: normalize 300–500 range to -1.0–1.0
        raw_str     = float(sig_dict.get("strength", 400))
        str_norm    = max(-1.0, min(1.0, (raw_str - 400) / 100.0))

        feat = np.array([[
            (rsi - 50) / 50.0,
            (sto - 50) / 50.0,
            max(-1.0, min(1.0, ma_diff)),
            max(-1.0, min(1.0, macd)),
            (bb_pos - 0.5) * 2.0,
            max(-1.0, min(1.0, mom)),
            min(1.0, vol),
            float(candle),
            trend_num,
            max(-1.5, min(1.5, vwap_num)),
            max(-1.0, min(1.0, mtf_score)),
            ia,
            session_num,
            is_otc_num,
            str_norm,           # signal strength (normalized)
        ]], dtype=np.float32)
        return feat
    except Exception as e:
        logging.warning("_nn_features_from_signal error: {}".format(e))
        return None


def _nn_make_model():
    """Create a fresh MLP model."""
    return MLPClassifier(
        hidden_layer_sizes=(64, 32),
        activation="relu",
        solver="adam",
        alpha=0.001,
        learning_rate="adaptive",
        max_iter=500,
        random_state=42,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=20,
    )


def _nn_load_global():
    """Load global model + scaler from disk, and seed memory pools from DB outcomes."""
    global _nn_global_model, _nn_global_scaler, _nn_training_data, _nn_pair_data
    if not _NN_AVAILABLE:
        return
    # Seed in-memory pools from persisted real outcomes
    try:
        db_samples = _nn_load_training_data_from_db()
        if db_samples:
            _nn_training_data = [s for s in db_samples]
            for feats, label in db_samples:
                # We don't have pair info in global load - skip per-pair seeding here
                pass
            logging.info("NN: Seeded {} real outcomes from DB".format(len(db_samples)))
    except Exception as e:
        logging.warning("NN seed from DB failed: {}".format(e))
    # Load saved model
    try:
        if _os_nn.path.exists(_NN_GLOBAL_FILE) and _os_nn.path.exists(_NN_SCALER_FILE):
            with open(_NN_GLOBAL_FILE, "rb") as f:
                _nn_global_model = pickle.load(f)
            with open(_NN_SCALER_FILE, "rb") as f:
                _nn_global_scaler = pickle.load(f)
            logging.info("NN: Global model loaded from disk.")
    except Exception as e:
        logging.warning("NN load_global failed: {}".format(e))
        _nn_global_model  = None
        _nn_global_scaler = None


def _nn_load_pair(pair):
    """Load per-pair model from disk if available."""
    if not _NN_AVAILABLE:
        return
    safe = pair.replace("/", "_").replace(" ", "_")
    mf = "{}/{}_model.pkl".format(_NN_MODEL_DIR, safe)
    sf = "{}/{}_scaler.pkl".format(_NN_MODEL_DIR, safe)
    try:
        if _os_nn.path.exists(mf) and _os_nn.path.exists(sf):
            with open(mf, "rb") as f: model = pickle.load(f)
            with open(sf, "rb") as f: scaler = pickle.load(f)
            _nn_per_pair[pair] = {
                "model": model, "scaler": scaler,
                "samples": len(_nn_pair_data.get(pair, [])), "acc": 0.0
            }
            logging.info("NN: Per-pair model loaded for {}".format(pair))
    except Exception as e:
        logging.warning("NN load_pair {} failed: {}".format(pair, e))


def _nn_save_global():
    """Save global model + scaler to disk."""
    if not _NN_AVAILABLE or _nn_global_model is None:
        return
    try:
        with open(_NN_GLOBAL_FILE, "wb") as f: pickle.dump(_nn_global_model, f)
        with open(_NN_SCALER_FILE, "wb") as f: pickle.dump(_nn_global_scaler, f)
    except Exception as e:
        logging.warning("NN save_global failed: {}".format(e))


def _nn_save_pair(pair):
    """Save per-pair model to disk."""
    if not _NN_AVAILABLE or pair not in _nn_per_pair:
        return
    safe = pair.replace("/", "_").replace(" ", "_")
    mf = "{}/{}_model.pkl".format(_NN_MODEL_DIR, safe)
    sf = "{}/{}_scaler.pkl".format(_NN_MODEL_DIR, safe)
    try:
        with open(mf, "wb") as f: pickle.dump(_nn_per_pair[pair]["model"], f)
        with open(sf, "wb") as f: pickle.dump(_nn_per_pair[pair]["scaler"], f)
    except Exception as e:
        logging.warning("NN save_pair {} failed: {}".format(pair, e))


def _nn_load_training_data_from_db():
    """Return only real trade outcomes stored in DB (no synthetic bootstrap data)."""
    if not _NN_AVAILABLE:
        return []
    samples = []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT features, label FROM nn_trade_outcomes
                    ORDER BY id DESC LIMIT 2000
                """)
                rows = cur.fetchall()
        for row in rows:
            try:
                feats = _json.loads(row["features"])
                label = int(row["label"])
                if len(feats) == 15 and label in (0, 1):
                    samples.append((feats, label))
            except Exception:
                pass
    except Exception as e:
        # Table may not exist yet - that is fine, start with empty
        logging.info("NN load_training_data_from_db: {}".format(e))
    return samples


def _nn_make_mlp():
    """Create a fresh MLP model."""
    return MLPClassifier(
        hidden_layer_sizes=(128, 64, 32),
        activation="relu",
        solver="adam",
        alpha=0.001,
        learning_rate="adaptive",
        max_iter=600,
        random_state=42,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=25,
    )


def _nn_make_xgb():
    """Create XGBoost or GradientBoosting model."""
    if _XGB_AVAILABLE:
        return xgb.XGBClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.08,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
    else:
        return GradientBoostingClassifier(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.8,
            random_state=42,
        )


def _nn_make_rf():
    """Create Random Forest model."""
    return RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )


def _nn_make_lgb():
    """Create LightGBM or fallback LogisticRegression."""
    if _LGB_AVAILABLE:
        return lgb.LGBMClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.08,
            subsample=0.8,
            random_state=42,
            verbosity=-1,
            n_jobs=-1,
        )
    else:
        return LogisticRegression(
            C=1.0,
            max_iter=500,
            random_state=42,
            n_jobs=-1,
        )


def _nn_make_model():
    """Create the global ensemble model (VotingClassifier soft voting)."""
    mlp = _nn_make_mlp()
    xgb_m = _nn_make_xgb()
    rf  = _nn_make_rf()
    lgb_m = _nn_make_lgb()
    # Soft voting: average probabilities from all 4 models
    # Each model gets equal weight - can be tuned later
    ensemble = VotingClassifier(
        estimators=[
            ("mlp",  mlp),
            ("xgb",  xgb_m),
            ("rf",   rf),
            ("lgb",  lgb_m),
        ],
        voting="soft",
        weights=[1.5, 2.0, 1.5, 1.5],  # XGBoost slightly higher weight
    )
    return ensemble


def _nn_retrain_global(force=False):
    """Retrain global model. Called on schedule or after 20 new samples."""
    global _nn_global_model, _nn_global_scaler, _nn_last_retrain
    if not _NN_AVAILABLE:
        return
    try:
        db_data  = _nn_load_training_data_from_db()
        all_data = db_data + _nn_training_data
        if len(all_data) < _NN_MIN_SAMPLES:
            logging.info("NN global: not enough samples ({}/{})".format(
                len(all_data), _NN_MIN_SAMPLES))
            return
        X = np.array([d[0] for d in all_data], dtype=np.float32)
        y = np.array([d[1] for d in all_data], dtype=np.int32)
        scaler = StandardScaler()
        X_sc   = scaler.fit_transform(X)
        model  = _nn_make_model()
        model.fit(X_sc, y)
        _nn_global_model  = model
        _nn_global_scaler = scaler
        _nn_last_retrain  = datetime.now()
        _nn_save_global()
        acc = model.score(X_sc, y)
        logging.info("NN global retrained: samples={} acc={:.1%}".format(len(all_data), acc))
    except Exception as e:
        logging.warning("NN retrain_global failed: {}".format(e))


def _nn_retrain_pair(pair):
    """Retrain per-pair model for a specific pair."""
    if not _NN_AVAILABLE:
        return
    data = _nn_pair_data.get(pair, [])
    if len(data) < _NN_MIN_PAIR_SAMPLES:
        return
    try:
        X = np.array([d[0] for d in data], dtype=np.float32)
        y = np.array([d[1] for d in data], dtype=np.int32)
        # Need at least 2 classes
        if len(set(y.tolist())) < 2:
            return
        scaler = StandardScaler()
        X_sc   = scaler.fit_transform(X)
        model  = _nn_make_model()
        model.fit(X_sc, y)
        acc = model.score(X_sc, y)
        _nn_per_pair[pair] = {
            "model": model, "scaler": scaler,
            "samples": len(data), "acc": round(acc, 3)
        }
        _nn_save_pair(pair)
        logging.info("NN per-pair {}: samples={} acc={:.1%}".format(pair, len(data), acc))
    except Exception as e:
        logging.warning("NN retrain_pair {} failed: {}".format(pair, e))


def _nn_record_outcome(pair, features_arr, won: bool):
    """Store outcome to DB + memory and trigger retrains as needed."""
    if not _NN_AVAILABLE or features_arr is None:
        return
    label = 1 if won else 0
    flat  = features_arr.flatten().tolist()

    # Persist to DB so outcomes survive restarts
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS nn_trade_outcomes (
                        id SERIAL PRIMARY KEY,
                        pair TEXT NOT NULL,
                        features TEXT NOT NULL,
                        label INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "INSERT INTO nn_trade_outcomes (pair, features, label) VALUES (%s, %s, %s)",
                    (pair, _json.dumps(flat), label)
                )
            conn.commit()
    except Exception as e:
        logging.warning("NN persist outcome failed: {}".format(e))

    # Global in-memory pool
    _nn_training_data.append((flat, label))
    if len(_nn_training_data) % 20 == 0 and len(_nn_training_data) >= _NN_MIN_SAMPLES:
        _nn_retrain_global()

    # Per-pair pool
    if pair not in _nn_pair_data:
        _nn_pair_data[pair] = []
    _nn_pair_data[pair].append((flat, label))
    # Retrain pair model every 10 new pair samples
    if len(_nn_pair_data[pair]) % 10 == 0:
        _nn_retrain_pair(pair)


def _nn_adjust_direction(pair, features_arr, current_direction):
    """
    Use per-pair model if available, otherwise global.
    Returns (direction, nn_confidence, nn_used).
    """
    global _nn_total_flips
    if not _NN_AVAILABLE or features_arr is None:
        return current_direction, None, False

    # Prefer per-pair model
    pair_entry = _nn_per_pair.get(pair)
    if pair_entry and pair_entry.get("model") and pair_entry.get("samples", 0) >= _NN_MIN_PAIR_SAMPLES:
        model  = pair_entry["model"]
        scaler = pair_entry["scaler"]
        source = "pair"
    elif _nn_global_model is not None and _nn_global_scaler is not None:
        model  = _nn_global_model
        scaler = _nn_global_scaler
        source = "global"
    else:
        return current_direction, None, False

    try:
        X_sc  = scaler.transform(features_arr)
        proba = model.predict_proba(X_sc)[0]
        prob_win  = float(proba[1])
        prob_lose = float(proba[0])

        # Flip if NN is confident the current direction will lose
        samples = pair_entry.get("samples", 0) if source == "pair" else len(_nn_training_data)
        flip_threshold = 0.65 if samples < 100 else 0.60
        if prob_lose > flip_threshold:
            flipped = "SELL" if current_direction == "BUY" else "BUY"
            _nn_total_flips += 1
            logging.info("NN FLIP [{}][{}]: {} → {} (lose={:.1%} threshold={:.0%})".format(
                source, pair, current_direction, flipped, prob_lose, flip_threshold))
            return flipped, prob_win, True

        return current_direction, prob_win, (prob_win >= _NN_CONFIDENCE_THRESHOLD)
    except Exception as e:
        logging.warning("NN adjust_direction {} failed: {}".format(pair, e))
        return current_direction, None, False


# -- NN Feature + flip cache ----------------------------------
_NN_SIGNAL_FEATURES = {}  # in-memory cache only - DB is source of truth

def nn_store_signal_features(user_id, pair, feat_arr, original_direction=None):
    """Store features + original direction for VTE feedback - DB + memory."""
    if feat_arr is None:
        return
    _NN_SIGNAL_FEATURES[(user_id, pair)] = (feat_arr, original_direction)
    if not _NN_AVAILABLE:
        return
    try:
        import pickle as _pk
        feat_bytes = _pk.dumps(feat_arr)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO nn_signal_features (user_id, pair, features, original_direction, created_at) "
                    "VALUES (%s, %s, %s, %s, NOW()) "
                    "ON CONFLICT (user_id, pair) DO UPDATE SET features=%s, original_direction=%s, created_at=NOW()",
                    (user_id, pair, feat_bytes, original_direction, feat_bytes, original_direction)
                )
            conn.commit()
    except Exception as e:
        logging.warning("nn_store_signal_features DB failed: {}".format(e))

def nn_get_signal_features(user_id, pair):
    """Get stored features - try memory first, then DB."""
    cached = _NN_SIGNAL_FEATURES.get((user_id, pair))
    if cached:
        return cached
    if not _NN_AVAILABLE:
        return None
    try:
        import pickle as _pk
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT features, original_direction FROM nn_signal_features "
                    "WHERE user_id=%s AND pair=%s",
                    (user_id, pair)
                )
                row = cur.fetchone()
        if row:
            feat_arr = _pk.loads(row["features"])
            result = (feat_arr, row["original_direction"])
            _NN_SIGNAL_FEATURES[(user_id, pair)] = result
            return result
    except Exception as e:
        logging.warning("nn_get_signal_features DB failed: {}".format(e))
    return None




def record_signal_outcome(pair, direction, tf_used, won, entry_price=None, exit_price=None,
                          movement_pct=0.0, session=None, indicators_agree=0,
                          trend_1h=None, confluence_level=None):
    """
    Record detailed signal outcome to signal_outcomes table.
    Used for expiry learning: tracks which TF worked best per setup.
    Survives Render restarts (stored in Neon).
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_outcomes
                        (pair, direction, tf_used, won, entry_price, exit_price,
                         movement_pct, session, indicators_agree, trend_1h, confluence_level)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (pair, direction, tf_used, won, entry_price, exit_price,
                      movement_pct, session, indicators_agree, trend_1h, confluence_level))
            conn.commit()
    except Exception as e:
        logging.warning("record_signal_outcome failed {}: {}".format(pair, e))

def nn_feedback_from_vte(user_id, pair, won: bool):
    """Feed VTE trade outcome back to NN for learning."""
    global _nn_flip_wins
    key  = (user_id, pair)
    entry = _NN_SIGNAL_FEATURES.pop(key, None)
    if entry is not None:
        feat_arr, orig_dir = entry
        _nn_record_outcome(pair, feat_arr, won)
        # Track flip accuracy
        if orig_dir is not None:
            # If direction was flipped and it won - record flip win
            # (orig_dir != current stored direction means flip happened)
            if won:
                _nn_flip_wins += 1
        logging.info("NN feedback: pair={} won={} | global_samples={} pair_samples={}".format(
            pair, won, len(_nn_training_data),
            len(_nn_pair_data.get(pair, []))))


def nn_get_stats():
    """
    Return NN stats dict for admin command.
    """
    global_ready  = _nn_global_model is not None
    pairs_trained = len([p for p, v in _nn_per_pair.items()
                         if v.get("samples", 0) >= _NN_MIN_PAIR_SAMPLES])
    total_samples = len(_nn_training_data) + sum(
        len(v) for v in _nn_pair_data.values())
    last_rt = _nn_last_retrain.strftime("%H:%M") if _nn_last_retrain else "Never"

    # Global accuracy estimate
    global_acc = 0.0
    if global_ready and _nn_global_scaler and len(_nn_training_data) >= _NN_MIN_SAMPLES:
        try:
            db_data  = _nn_load_training_data_from_db()
            all_data = db_data + _nn_training_data
            X = np.array([d[0] for d in all_data], dtype=np.float32)
            y = np.array([d[1] for d in all_data], dtype=np.int32)
            X_sc = _nn_global_scaler.transform(X)
            global_acc = _nn_global_model.score(X_sc, y)
        except Exception:
            pass

    # Best 3 pair models by accuracy
    pair_info = sorted(
        [(p, v["samples"], v["acc"]) for p, v in _nn_per_pair.items()
         if v.get("samples", 0) >= _NN_MIN_PAIR_SAMPLES],
        key=lambda x: x[2], reverse=True
    )[:3]

    flip_acc = 0.0
    if _nn_total_flips > 0:
        flip_acc = _nn_flip_wins / _nn_total_flips

    return {
        "available":     _NN_AVAILABLE,
        "global_ready":  global_ready,
        "global_acc":    global_acc,
        "global_samples": len(_nn_training_data),
        "pairs_trained": pairs_trained,
        "total_samples": total_samples,
        "last_retrain":  last_rt,
        "total_flips":   _nn_total_flips,
        "flip_acc":      flip_acc,
        "top_pairs":     pair_info,
        "next_retrain_hours": _NN_RETRAIN_HOURS,
    }


# -- Scheduled retrain loop (every 6 hours) -------------------
async def _nn_scheduled_retrain_loop():
    """Background task: retrain global + all active pair models every 6h."""
    while True:
        await asyncio.sleep(_NN_RETRAIN_HOURS * 3600)
        logging.info("NN: Scheduled retrain starting...")
        _nn_retrain_global(force=True)
        # Retrain all pairs that have enough data
        for pair in list(_nn_pair_data.keys()):
            if len(_nn_pair_data[pair]) >= _NN_MIN_PAIR_SAMPLES:
                _nn_retrain_pair(pair)
        logging.info("NN: Scheduled retrain complete. Pairs={}".format(
            len([p for p in _nn_per_pair if _nn_per_pair[p].get("samples",0) >= _NN_MIN_PAIR_SAMPLES])))


# Load models on startup
if _NN_AVAILABLE:
    _nn_load_global()
    _nn_retrain_global()

# -- END NN MODULE ---------------------------------------------


def _micro_candle_trend_score(pair):
    """
    Analyze micro-candle green/red ratio for 5s, 10s, 15s timeframes.
    Uses last 20 x 1m candles from Yahoo/Finnhub as proxy.

    Rules:
      1m signal → check 5s proxy (last 20 x 1m candles, split into ~5s buckets)
      2m signal → check 10s proxy
      3m signal → check 15s proxy

    For each TF, count green (close > open) vs red (close < open).
    A TF "supports" BUY if green% >= 60%, supports SELL if red% >= 60%.

    Returns dict:
      {
        "1": {"direction": "BUY"/"SELL"/"FLAT", "green_pct": float, "red_pct": float, "support": float},
        "2": {...},
        "3": {...},
        "best_tf": 1/2/3,          # TF with strongest support for direction
        "best_dir": "BUY"/"SELL",
        "best_support": float,
      }
    Or None if no data available.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)

    # Fetch 1m candles - primary source
    opens_arr  = []
    closes_arr = []

    # Try Finnhub first
    if fh_sym:
        try:
            df = _mtf_fh_candles(fh_sym, "1", 60)
            if df is not None and len(df) >= 15:
                opens_arr  = df["Open"].astype(float).tolist()
                closes_arr = df["Close"].astype(float).tolist()
        except Exception:
            pass

    # Yahoo fallback
    if not opens_arr and yf_sym:
        try:
            import yfinance as yf
            df = yf.download(yf_sym, period="1d", interval="1m",
                             progress=False, auto_adjust=True)
            if df is not None and len(df) >= 15:
                opens_arr  = df["Open"].squeeze().astype(float).tolist()
                closes_arr = df["Close"].squeeze().astype(float).tolist()
        except Exception:
            pass

    if not opens_arr or len(opens_arr) < 10:
        return None

    # Use last 60 candles max
    opens_arr  = opens_arr[-60:]
    closes_arr = closes_arr[-60:]
    total_c    = len(opens_arr)

    results = {}

    # Each signal_type maps to a bucket_size (proxy for seconds interval)
    # 5s  → bucket of 1 candle  (finest granularity from 1m data)
    # 10s → bucket of 2 candles
    # 15s → bucket of 3 candles
    bucket_map = {1: 1, 2: 2, 3: 3}  # signal_type → candles per bucket

    for sig_type, bucket in bucket_map.items():
        green = red = 0
        # Build buckets: each bucket = N consecutive 1m candles merged
        i = 0
        while i + bucket <= total_c:
            o = opens_arr[i]
            c = closes_arr[i + bucket - 1]  # close of last candle in bucket
            if c > o:
                green += 1
            elif c < o:
                red += 1
            i += bucket

        total_b = green + red
        if total_b == 0:
            results[str(sig_type)] = {"direction": "FLAT", "green_pct": 50.0,
                                       "red_pct": 50.0, "support": 0.0}
            continue

        green_pct = green / total_b * 100
        red_pct   = red   / total_b * 100

        if green_pct >= 60:
            direction = "BUY"
            support   = green_pct
        elif red_pct >= 60:
            direction = "SELL"
            support   = red_pct
        else:
            direction = "FLAT"
            support   = max(green_pct, red_pct)

        results[str(sig_type)] = {
            "direction": direction,
            "green_pct": round(green_pct, 1),
            "red_pct":   round(red_pct, 1),
            "support":   round(support, 1),
        }

    if not results:
        return None

    # Find best TF: highest support score that has a clear direction (not FLAT)
    best_tf      = None
    best_support = 0.0
    best_dir     = None

    for sig_type in [1, 2, 3]:
        r = results.get(str(sig_type))
        if r and r["direction"] != "FLAT" and r["support"] > best_support:
            best_support = r["support"]
            best_tf      = sig_type
            best_dir     = r["direction"]

    results["best_tf"]      = best_tf
    results["best_dir"]     = best_dir
    results["best_support"] = best_support

    logging.info("MICRO TREND {}: 1m={} 2m={} 3m={} → best={}m({}) support={:.1f}%".format(
        pair,
        results.get("1", {}).get("direction", "?"),
        results.get("2", {}).get("direction", "?"),
        results.get("3", {}).get("direction", "?"),
        best_tf, best_dir, best_support
    ))
    return results


# ============================================================
# NON-OTC RESCUE - when signal is flat/weak, use history +
# micro-candle (5s/10s/15s green-red ratio) to force a direction
# ============================================================
def _rescue_nonOTC_signal(pair: str) -> dict | None:
    """
    Last-resort for non-OTC when generate_signal returns flat/weak.
    Steps:
      1. Check recent signal history - what direction was winning?
      2. Check micro-candle (5s/10s/15s) green/red ratio → pick TF
         with strongest majority (BUY if green > 60%, SELL if red > 60%)
      3. If both agree → return forced signal
      4. If only one agrees → use it
      5. If nothing → return None (caller will show no-signal)

    Returns a signal dict (flat=False) or None.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol    = YAHOO_SYMBOLS.get(real_pair)

    # -- 0. Deriv WebSocket - kwanza kabla ya yote ------------
    # Kama Deriv cache ipo na bado fresh → tumia moja kwa moja
    # Kama cache imepita muda → jaribu fetch mpya (sync via cached data)
    deriv_rescue_dir = None
    deriv_rescue_tf  = None
    _deriv_rescue_pair = OTC_TO_REAL.get(pair, pair)  # non-OTC pair - same kwa non-OTC
    if _deriv_rescue_pair in DERIV_SYMBOLS:
        try:
            _dc = _deriv_tick_cache.get(_deriv_rescue_pair)
            if _dc:
                _dc_age = time.time() - _dc.get("ts", 0)
                if _dc_age <= _DERIV_CACHE_TTL:
                    _td = _dc["data"]
                    _tf_map_r = {"5_s": 1, "10_s": 2, "15_s": 3}
                    _best_str_r = -1
                    for _mk, _tm in _tf_map_r.items():
                        _tr = _td.get(_mk)
                        if _tr and _tr.get("direction") not in (None, "FLAT"):
                            _sv = _tr.get("strength", 0)
                            if _sv > _best_str_r:
                                _best_str_r    = _sv
                                deriv_rescue_dir = _tr["direction"]
                                deriv_rescue_tf  = _tm
                    if deriv_rescue_dir:
                        logging.info("RESCUE Deriv cache hit {}: {} {}m str={}".format(
                            pair, deriv_rescue_dir, deriv_rescue_tf, _best_str_r))
        except Exception as _de:
            logging.warning("_rescue Deriv cache read failed {}: {}".format(pair, _de))

    # Kama Deriv imetoa direction yenye nguvu (str >= 60) → rudisha moja kwa moja
    if deriv_rescue_dir and _best_str_r >= 60:
        _rescue_tf_final = deriv_rescue_tf or 1
        logging.info("RESCUE nonOTC {} via Deriv: dir={} tf={}m".format(pair, deriv_rescue_dir, _rescue_tf_final))
        return {
            "direction": deriv_rescue_dir, "pair": pair, "timeframe": _rescue_tf_final,
            "strength": min(99, 60 + int((_best_str_r / 100) * 39)),
            "indicators_agree": 4,
            "trend_1h": deriv_rescue_dir, "vwap_data": None, "confluence": {},
            "mtf": None, "flat": False, "patterns": {},
            "movement_cat": "MEDIUM", "avg_movement": 0.08,
            "no_signal_reason": "",
            "nn_confidence": None, "nn_used": False, "_nn_feat_arr": None,
            "_rescued": True,
        }

    # -- 1. History direction ---------------------------------
    hist_dir = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT direction FROM signal_history WHERE pair=%s "
                    "ORDER BY created_at DESC LIMIT 20",
                    (pair,)
                )
                rows = cur.fetchall()
        if len(rows) >= 5:
            dirs = [r["direction"] for r in rows]
            buy_pct  = dirs.count("BUY")  / len(dirs)
            sell_pct = dirs.count("SELL") / len(dirs)
            if buy_pct  >= 0.60: hist_dir = "BUY"
            elif sell_pct >= 0.60: hist_dir = "SELL"
    except Exception as e:
        logging.warning("_rescue history check failed {}: {}".format(pair, e))

    # -- 2. Micro-candle green/red ratio per TF ---------------
    # 1m TF → 5s candles, 2m TF → 10s candles, 3m TF → 15s candles
    # Use Yahoo 1m data and bucket into micro-candles
    micro_result = None  # {tf_mins: (direction, support_pct)}
    if symbol:
        try:
            df = yf.download(symbol, period="1d", interval="1m",
                             progress=False, auto_adjust=True)
            if df is not None and len(df) >= 20:
                opens  = df["Open"].squeeze().astype(float).values
                closes = df["Close"].squeeze().astype(float).values
                times_sec = list(range(len(opens)))  # proxy: each candle = 1 unit

                micro_result = {}
                for tf_mins, bucket_size in [(1, 5), (2, 10), (3, 15)]:
                    # Use last 60 1m candles, group every bucket_size candles
                    # Each group of bucket_size 1m candles ≈ one micro-candle
                    window = opens[-60:]
                    wclose = closes[-60:]
                    green = red = 0
                    for i in range(0, len(window) - bucket_size + 1, bucket_size):
                        chunk_open  = window[i]
                        chunk_close = wclose[i + bucket_size - 1]
                        if chunk_close > chunk_open:  green += 1
                        elif chunk_close < chunk_open: red   += 1
                    total = green + red
                    if total >= 3:
                        support = max(green, red) / total * 100
                        direction = "BUY" if green >= red else "SELL"
                        micro_result[tf_mins] = (direction, support)
        except Exception as e:
            logging.warning("_rescue micro-candle failed {}: {}".format(pair, e))

    # -- 3. Choose best TF from micro_result -----------------
    best_tf        = None
    best_dir       = None
    best_support   = 0.0

    if micro_result:
        for tf_mins, (mdir, msupport) in micro_result.items():
            if msupport >= 60.0 and msupport > best_support:
                best_support = msupport
                best_tf      = tf_mins
                best_dir     = mdir

    # -- 4. Reconcile history + micro ------------------------
    final_dir = None
    final_tf  = best_tf or 2

    if best_dir and hist_dir:
        if best_dir == hist_dir:
            final_dir = best_dir   # Both agree - strong
        else:
            # Disagree - trust micro over history (more recent)
            final_dir = best_dir
    elif best_dir:
        final_dir = best_dir
    elif hist_dir:
        final_dir = hist_dir
        # Pick TF from micro with highest support (any direction)
        if micro_result:
            best_any = max(micro_result.items(), key=lambda x: x[1][1])
            final_tf = best_any[0]

    if final_dir is None:
        return None  # Nothing to rescue with

    logging.info("RESCUE nonOTC {}: dir={} tf={}m (micro_support={:.0f}% hist={})".format(
        pair, final_dir, final_tf, best_support, hist_dir))

    return {
        "direction": final_dir, "pair": pair, "timeframe": final_tf,
        "strength": max(300, int(best_support * 5)),
        "indicators_agree": 3,
        "trend_1h": hist_dir, "vwap_data": None, "confluence": {},
        "mtf": None, "flat": False, "patterns": {},
        "movement_cat": "MEDIUM", "avg_movement": 0.08,
        "no_signal_reason": "",
        "nn_confidence": None, "nn_used": False, "_nn_feat_arr": None,
        "_rescued": True,
    }
# -------------------------------------------------------------


# ============================================================
# SAFE SIGNAL WRAPPER - timeout + guaranteed OTC fallback
# ============================================================
_SIGNAL_TIMEOUT = 12  # seconds - max wait for generate_signal

async def animated_analyzing(bot, chat_id, pair: str):
    """
    Inatuma ujumbe wa 'Analyzing...' na animation ya dots inayobadilika.
    Inarudisha (message_obj, stop_event) - piga stop_event.set() ukitaka isimame.

    Mfano wa matumizi:
        cm, stop = await animated_analyzing(context.bot, chat, pair)
        sig = await safe_generate_signal(pair)
        stop.set()
        try: await cm.delete()
        except: pass
    """
    frames = [
        "🔵 *Analyzing {}*".format(pair),
        "🔵 *Analyzing {}.*".format(pair),
        "🔵 *Analyzing {}...*".format(pair),
        "🔵 *Analyzing {}...* ↪️".format(pair),
        "🟣 *Processing {}...* ✨".format(pair),
        "🟣 *Processing {}...* 🔍".format(pair),
        "🔵 *Checking indicators {}...* ⏳".format(pair),
        "🔵 *Checking indicators {}* 🏆".format(pair),
    ]
    stop_event = asyncio.Event()
    try:
        cm = await bot.send_message(chat_id=chat_id, text=frames[0], parse_mode="Markdown")
    except Exception:
        return None, stop_event

    async def _animate():
        i = 1
        while not stop_event.is_set():
            await asyncio.sleep(1.2)
            if stop_event.is_set():
                break
            try:
                await cm.edit_text(frames[i % len(frames)], parse_mode="Markdown")
            except Exception:
                break
            i += 1

    asyncio.create_task(_animate())
    return cm, stop_event


async def safe_generate_signal(pair: str) -> dict:
    """
    Async wrapper around generate_signal with:
      - Hard 20s timeout
      - OTC: always returns a signal (random BUY/SELL fallback if timeout/error)
      - Non-OTC flat/timeout/error: try rescue (history + micro-candles) before
        giving up - only shows no-signal if rescue also finds nothing

    Never hangs. Never returns None.
    """
    is_otc = "OTC" in pair
    loop   = asyncio.get_event_loop()

    def _otc_fallback():
        forced_dir = random.choice(["BUY", "SELL"])
        forced_tf  = random.choice([1, 2, 3])
        return {
            "direction": forced_dir, "pair": pair, "timeframe": forced_tf,
            "strength": random.randint(300, 500), "indicators_agree": 3,
            "trend_1h": None, "vwap_data": None, "confluence": {},
            "mtf": None, "flat": False, "patterns": {},
            "movement_cat": "MEDIUM", "avg_movement": 0.08,
            "no_signal_reason": "", "nn_confidence": None, "nn_used": False,
            "_nn_feat_arr": None,
        }

    def _nonOTC_no_signal(reason):
        return {
            "direction": "BUY", "pair": pair, "timeframe": 0,
            "strength": 0, "indicators_agree": 0,
            "trend_1h": None, "vwap_data": None, "confluence": {},
            "mtf": None, "flat": True, "patterns": {},
            "movement_cat": "LOW", "avg_movement": 0.0,
            "no_signal_reason": reason,
            "nn_confidence": None, "nn_used": False, "_nn_feat_arr": None,
        }

    try:
        sig = await asyncio.wait_for(
            loop.run_in_executor(None, generate_signal, pair),
            timeout=_SIGNAL_TIMEOUT
        )
        # OTC must NEVER return flat - inject random direction if so
        if is_otc and sig.get("flat"):
            forced_dir = random.choice(["BUY", "SELL"])
            forced_tf  = random.choice([1, 2, 3])
            sig["direction"]        = forced_dir
            sig["timeframe"]        = forced_tf
            sig["flat"]             = False
            sig["no_signal_reason"] = ""
            sig["strength"]         = random.randint(300, 500)
            logging.info("OTC FORCE SIGNAL (flat rescued): {} → {} {}m".format(pair, forced_dir, forced_tf))
        # Non-OTC flat → try rescue before giving up
        if not is_otc and sig.get("flat"):
            rescued = _rescue_nonOTC_signal(pair)
            if rescued:
                return rescued
        return sig

    except asyncio.TimeoutError:
        logging.warning("generate_signal TIMEOUT ({}s) for {}".format(_SIGNAL_TIMEOUT, pair))
        if is_otc:
            return _otc_fallback()
        # Non-OTC timeout → try rescue
        rescued = _rescue_nonOTC_signal(pair)
        if rescued:
            return rescued
        return _nonOTC_no_signal("⏱ *No signal available* - market data timed out.")

    except Exception as e:
        logging.warning("generate_signal ERROR for {}: {}".format(pair, e))
        if is_otc:
            return _otc_fallback()
        # Non-OTC error → try rescue
        rescued = _rescue_nonOTC_signal(pair)
        if rescued:
            return rescued
        return _nonOTC_no_signal("🟡 *No signal available* - please try again.")
# -------------------------------------------------------------


def generate_signal(pair):
    is_otc = "OTC" in pair
    real   = None
    yahoo_available = True

    # News filter - block non-OTC signals during high-impact events
    if not is_otc and is_filter_on("news"):
        _near_news, _news_name = is_news_time()
        if _near_news:
            logging.info("NEWS FILTER: blocking signal for {} - {}".format(pair, _news_name))
            return {
                "direction": "BUY", "pair": pair, "timeframe": 0,
                "strength": 0, "indicators_agree": 0,
                "trend_1h": None, "vwap_data": None,
                "confluence": {}, "mtf": None, "flat": True,
                "patterns": [], "movement_cat": "LOW",
                "avg_movement": 0.0,
                "no_signal_reason": "⚠️ High-impact news in {} - signal paused for safety.".format(_news_name),
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

    # -- 1H TREND FILTER (with reversal detection) ------------
    trend_1h = None
    try:
        trend_1h = _fetch_1h_trend(pair)
    except Exception as e:
        logging.warning("generate_signal 1H trend failed {}: {}".format(pair, e))

    # -- VWAP TREND -------------------------------------------
    vwap_data = None
    try:
        vwap_data = _fetch_vwap_trend(pair)
    except Exception as e:
        logging.warning("generate_signal vwap failed {}: {}".format(pair, e))

    # -- MULTI-TIMEFRAME SCORE ---------------------------------
    mtf = None
    try:
        mtf = _fetch_mtf_score(pair)
    except Exception as e:
        logging.warning("generate_signal mtf failed {}: {}".format(pair, e))

    # -- CANDLESTICK PATTERN DETECTION ------------------------
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

    # -- PIP MOVEMENT ANALYSIS ---------------------------------
    avg_movement, movement_cat = _check_pip_movement(pair)

    # -- D: VOLATILITY (ATR) CHECK - dead market filter --------
    atr_pct, is_dead_market = 0.05, False
    if not is_otc and not is_force_pair(pair) and is_filter_on("dead"):
        try:
            atr_pct, is_dead_market = _check_volatility(pair)
        except Exception as _e:
            logging.warning("volatility check failed {}: {}".format(pair, _e))
    if is_dead_market and is_filter_on("dead"):
        logging.info("DEAD MARKET FILTER: {} ATR={:.4f}% < {:.3f}%".format(
            pair, atr_pct, _ATR_DEAD_THRESHOLD))
        return {
            "direction": "BUY", "pair": pair, "timeframe": 0,
            "strength": 0, "indicators_agree": 0,
            "trend_1h": None, "vwap_data": None,
            "confluence": {}, "mtf": None, "flat": True,
            "patterns": [], "movement_cat": "LOW",
            "avg_movement": avg_movement,
            "no_signal_reason": "🟡 *No signal available*",
        }

    # -- L: FIBONACCI LEVELS -----------------------------------
    fib_buy_bonus = fib_sell_bonus = 0
    fib_level_str = None
    if not is_otc:
        try:
            fib_buy_bonus, fib_sell_bonus, fib_level_str = _check_fibonacci(pair, "BUY")
        except Exception as _e:
            logging.warning("fibonacci check failed {}: {}".format(pair, _e))

    # -- M: PRICE ACTION SCORE ---------------------------------
    pa_buy_bonus = pa_sell_bonus = 0
    pa_trend_str = None
    try:
        pa_buy_bonus, pa_sell_bonus, pa_trend_str = _price_action_score(pair)
    except Exception as _e:
        logging.warning("price action score failed {}: {}".format(pair, _e))

    # -- DERIV TICK CACHE - read indicators for seconds bonus --
    import time as _time_gen
    _deriv_cached = _deriv_tick_cache.get(pair)
    _deriv_ind_data = None
    if not is_otc and _deriv_cached:
        _cache_age = _time_gen.time() - _deriv_cached.get("ts", 0)
        if _cache_age <= _DERIV_CACHE_TTL:
            _deriv_ind_data = _deriv_cached["data"]
            logging.info("Deriv cache hit for {} (age={:.1f}s)".format(pair, _cache_age))
    # Store in sig dict for bonus block below
    _sig_deriv_ind = _deriv_ind_data  # may be None - bonus is optional

    if real:
        # -- NON-OTC: Real indicators from Yahoo Finance (5m) --
        rsi     = real["rsi"]
        sto     = real["sto"]
        ma_diff = real["ma_diff"]
        macd    = real["macd"]
        bb_pos  = real["bb_pos"]
        mom     = real["mom"]
        vol     = real["vol"]
        # Candle direction from real data - close vs open of last candle
        _raw_dir = real.get("direction")
        if _raw_dir == "BUY":
            candle = 1.0
        elif _raw_dir == "SELL":
            candle = -1.0
        else:
            # direction_raw is None when indicators conflict - use mom as proxy
            candle = 0.5 if mom > 0 else (-0.5 if mom < 0 else 0.0)
    else:
        # -- OTC: Smart synthetic indicators (session-aware) ----
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

    # -- BASE SCORING -----------------------------------------
    # Non-OTC: halve 5m indicator weights - they are confirmation only.
    # 1H (weight 80) and MTF/VWAP dominate direction for non-OTC.
    # OTC: keep original weights (no Deriv/Yahoo data - 5m synthetic is all we have).
    _w = 0.5 if not is_otc else 1.0
    b = s = 0
    if rsi < 25:    b += int(25 * _w)
    elif rsi < 35:  b += int(15 * _w)
    elif rsi < 45:  b += int(8  * _w)
    elif rsi > 75:  s += int(25 * _w)
    elif rsi > 65:  s += int(15 * _w)
    elif rsi > 55:  s += int(8  * _w)
    if sto < 15:    b += int(15 * _w)
    elif sto < 25:  b += int(8  * _w)
    elif sto > 85:  s += int(15 * _w)
    elif sto > 75:  s += int(8  * _w)
    if ma_diff > 0.3:    b += int(20 * _w)
    elif ma_diff > 0.1:  b += int(10 * _w)
    elif ma_diff < -0.3: s += int(20 * _w)
    elif ma_diff < -0.1: s += int(10 * _w)
    if macd > 0.4:    b += int(15 * _w)
    elif macd > 0.1:  b += int(7  * _w)
    elif macd < -0.4: s += int(15 * _w)
    elif macd < -0.1: s += int(7  * _w)
    if bb_pos < 0.15:  b += int(10 * _w)
    elif bb_pos < 0.3: b += int(5  * _w)
    elif bb_pos > 0.85: s += int(10 * _w)
    elif bb_pos > 0.7:  s += int(5  * _w)
    if mom > 0.4:   b += int(10 * _w)
    elif mom > 0.1: b += int(5  * _w)
    elif mom < -0.4: s += int(10 * _w)
    elif mom < -0.1: s += int(5  * _w)
    if candle > 0:   b += int(candle * 10 * _w)
    elif candle < 0: s += int(abs(candle) * 10 * _w)
    if vol > 0.75:
        if b > s: b += int(8 * _w)
        else:     s += int(8 * _w)

    # -- RSI DIVERGENCE BONUS ---------------------------------
    if real and real.get("divergence"):
        div = real["divergence"]
        if div == "BUY":  b += 20
        elif div == "SELL": s += 20

    # -- NON-OTC MULTI-TF REAL CONSENSUS BONUS ----------------
    # Reward when 1m + 5m + 15m all point the same way (real data)
    if real and not is_otc and real.get("tf_count", 0) >= 2:
        tv = real.get("tf_buy_votes", 0)
        sv = real.get("tf_sell_votes", 0)
        tf_total = real.get("tf_count", 1)
        if tv > sv:
            bonus = int((tv / tf_total) * 30)
            b += bonus
        elif sv > tv:
            bonus = int((sv / tf_total) * 30)
            s += bonus
        else:
            # Conflict across timeframes - reduce confidence
            b -= 10
            s -= 10

    # -- WILLIAMS FRACTAL BONUS -------------------------------
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

    # -- CANDLESTICK PATTERN BONUS ----------------------------
    b += pattern_buy_bonus
    s += pattern_sell_bonus

    # -- L: FIBONACCI BONUS -----------------------------------
    b += fib_buy_bonus
    s += fib_sell_bonus
    if fib_level_str:
        logging.info("FIB {}: {} buy_bonus={} sell_bonus={}".format(
            pair, fib_level_str, fib_buy_bonus, fib_sell_bonus))

    # -- M: PRICE ACTION BONUS ---------------------------------
    b += pa_buy_bonus
    s += pa_sell_bonus
    if pa_trend_str:
        logging.info("PA {}: {} buy={} sell={}".format(
            pair, pa_trend_str, pa_buy_bonus, pa_sell_bonus))

    # -- SESSION BIAS -----------------------------------------
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

    # -- 1H TREND FILTER BONUS (includes reversal detection) --
    # 1H is the primary direction driver - highest weight
    _1h_weight = 80 if not is_otc else 45
    if trend_1h == "BUY":
        b += _1h_weight
    elif trend_1h == "SELL":
        s += _1h_weight

    # -- VWAP TREND BONUS -------------------------------------
    if vwap_data is not None:
        if vwap_data["direction"] == "BUY":
            bonus = 30 if vwap_data["strength"] == "STRONG" else (18 if vwap_data["strength"] == "MODERATE" else 8)
            b += bonus
        else:
            bonus = 30 if vwap_data["strength"] == "STRONG" else (18 if vwap_data["strength"] == "MODERATE" else 8)
            s += bonus

    # -- MULTI-TIMEFRAME BONUS --------------------------------
    # Non-OTC: higher MTF weight (real data) vs OTC (synthetic)
    _mtf_w = 12 if not is_otc else 8
    if mtf and mtf["total"] >= 3:
        if mtf["buy_tfs"] > mtf["sell_tfs"]:
            b += mtf["buy_tfs"] * _mtf_w
        elif mtf["sell_tfs"] > mtf["buy_tfs"]:
            s += mtf["sell_tfs"] * _mtf_w

    # -- DIRECTION & CONFLUENCE -------------------------------
    direction = "BUY" if b >= s else "SELL"
    indicators_agree = 0
    checks = [(rsi < 45, rsi > 55), (sto < 45, sto > 55), (ma_diff > 0, ma_diff < 0),
              (macd > 0, macd < 0), (bb_pos < 0.5, bb_pos > 0.5), (mom > 0, mom < 0), (candle > 0, candle < 0)]
    for buy_c, sell_c in checks:
        if direction == "BUY" and buy_c:   indicators_agree += 1
        if direction == "SELL" and sell_c: indicators_agree += 1

    # -- MTF CONFLUENCE COUNT ---------------------------------
    if mtf and mtf["total"] >= 3:
        if direction == "BUY"  and mtf["buy_tfs"]  > mtf["sell_tfs"]: indicators_agree += mtf["buy_tfs"]
        if direction == "SELL" and mtf["sell_tfs"] > mtf["buy_tfs"]:  indicators_agree += mtf["sell_tfs"]
    if trend_1h == direction:
        indicators_agree += 3  # Increased from 2 - 1H trend with reversal detection is stronger

    # -- DERIV SECONDS INDICATOR BONUS (non-OTC only) ---------
    # Indicators from 5s/10s/15s candles act as bonus confirmation.
    # They do NOT change direction - only add/reduce score and indicators_agree.
    # Weight: ~30% of 1H weight - bonus kubwa lakini si msingi.
    _deriv_ind = _sig_deriv_ind if not is_otc else None
    if not is_otc and _deriv_ind:
        _sec_agree = 0
        _sec_total = 0
        for _cs in [5, 10, 15]:
            _ind = _deriv_ind.get("{}_s_ind".format(_cs))
            if _ind is None:
                continue
            _sec_total += 1
            _ind_dir = _ind.get("direction")
            _ind_rsi = _ind.get("rsi", 50)
            _ind_macd = _ind.get("macd", 0)
            _ind_ma = _ind.get("ma_diff", 0)
            _ind_mom = _ind.get("mom", 0)
            if _ind_dir == direction:
                _sec_agree += 1
                # RSI confirms
                if direction == "BUY" and _ind_rsi < 45: indicators_agree += 1
                elif direction == "SELL" and _ind_rsi > 55: indicators_agree += 1
                # MACD confirms
                if direction == "BUY" and _ind_macd > 0.1: indicators_agree += 1
                elif direction == "SELL" and _ind_macd < -0.1: indicators_agree += 1
                # EMA confirms
                if direction == "BUY" and _ind_ma > 0.1: indicators_agree += 1
                elif direction == "SELL" and _ind_ma < -0.1: indicators_agree += 1
            elif _ind_dir is not None and _ind_dir != direction:
                # Seconds oppose direction - slight penalty
                indicators_agree = max(0, indicators_agree - 1)
        # Score bonus: sekunde zinakubaliana → b/s bonus
        if _sec_total > 0:
            _sec_ratio = _sec_agree / _sec_total
            _sec_bonus = int(_sec_ratio * 25)  # max +25 kama sekunde zote zinakubaliana
            if direction == "BUY":  b += _sec_bonus
            else:                   s += _sec_bonus
            logging.info("Deriv sec indicators {}: agree={}/{} bonus={} dir={}".format(
                pair, _sec_agree, _sec_total, _sec_bonus, direction))
    # ---------------------------------------------------------

    # -- NON-OTC TF VOTE CONFLUENCE (added here - direction is now known) --
    if real and not is_otc and real.get("tf_count", 0) >= 2:
        tv = real.get("tf_buy_votes", 0)
        sv = real.get("tf_sell_votes", 0)
        if direction == "BUY"  and tv > sv: indicators_agree += tv
        if direction == "SELL" and sv > tv: indicators_agree += sv

    # -- PATTERN CONFLUENCE -----------------------------------
    # If patterns agree with direction - boost indicators_agree
    pattern_agrees = (pattern_buy_bonus > 0 and direction == "BUY") or \
                     (pattern_sell_bonus > 0 and direction == "SELL")
    if pattern_agrees:
        indicators_agree += 2

    # -- CONFLICT CHECK: MTF vs 1H ----------------------------
    if mtf and trend_1h and mtf["total"] >= 3:
        mtf_dir = "BUY" if mtf["buy_tfs"] > mtf["sell_tfs"] else "SELL"
        if mtf_dir != trend_1h:
            direction = "BUY" if b > s else "SELL"

    # -- MINIMUM CONFLUENCE -----------------------------------
    min_confluence = 4 if not is_otc else 3   # Lowered: was 6/5 - less blocking
    if is_filter_on("confluence") and indicators_agree < min_confluence:
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

    # -- SIGNAL HISTORY BIAS CHECK ----------------------------
    # If most recent signals share same direction - reinforce decision
    hist_same, hist_total, hist_pct = _check_signal_history_bias(pair, direction, window=15)
    if hist_total >= 5:
        if hist_pct >= 0.70:
            # History strongly agrees - add +20 and boost indicators_agree
            if direction == "BUY":
                b += 20
            else:
                s += 20
            indicators_agree += 2
        elif hist_pct <= 0.30:
            # History strongly disagrees - reduce confidence
            if direction == "BUY":
                b -= 15
            else:
                s -= 15

    # -- STRENGTH CALCULATION ---------------------------------
    dom = max(b, s); tot = max(b+s, 1)
    mtf_bonus = 0
    if mtf and mtf["total"] >= 3:
        agreeing = mtf["buy_tfs"] if direction == "BUY" else mtf["sell_tfs"]
        mtf_bonus = int((agreeing / mtf["total"]) * 45)
    trend_bonus = 20 if trend_1h == direction else 0
    pattern_bonus_str = min(30, pattern_buy_bonus if direction == "BUY" else pattern_sell_bonus)
    hist_bonus_str = int(hist_pct * 20) if hist_total >= 5 else 0

    # Strength formula: base 280 + bonuses (max 500) → convert to 60–99%
    _raw_strength = min(500, max(300, 280 + indicators_agree*25 + int((dom/tot)*100)
                            + mtf_bonus + trend_bonus + pattern_bonus_str + hist_bonus_str
                            ))
    # Map 300–500 → 60–99%
    strength = int(60 + (_raw_strength - 300) / 200 * 39)

    # -- TIMEFRAME SELECTION ----------------------------------
    if is_otc:
        timeframe = random.choice([1, 1, 2, 2, 3, 3])
    else:
        # Non-OTC: kagua 1m/2m/3m zote - chagua yenye nguvu zaidi
        # Kanuni: TF yenye indicators_agree kubwa zaidi + VTE history ndiyo inachaguliwa
        # Hakuna kushuka chini kwa sababu ya udhaifu - best TF ndiyo inatoka

        best_vte = get_best_tf_for_session(pair)  # session-aware (London/NY/Asian)
        if best_vte is None:
            best_vte = get_optimal_tf(pair)       # overall VTE learned TF

        # Score kila TF: VTE history + indicators_agree + micro support
        _tf_candidate_scores = {}

        # Fetch micro support kwa kila TF
        _micro_scores = {}
        try:
            _micro_tmp = _micro_candle_trend_score(pair)
            if _micro_tmp:
                for _st in [1, 2, 3]:
                    _r = _micro_tmp.get(str(_st))
                    if _r and _r["direction"] == direction:
                        _micro_scores[_st] = _r["support"]
                    else:
                        _micro_scores[_st] = 0.0
        except Exception:
            _micro_scores = {1: 0.0, 2: 0.0, 3: 0.0}

        for _tf in [1, 2, 3]:
            _score = 0
            # VTE history bonus
            if best_vte == _tf:
                _score += 30
            # indicators_agree contribution per TF
            _ia_thresholds = {1: 8, 2: 7, 3: 6}
            if indicators_agree >= _ia_thresholds[_tf]:
                _score += indicators_agree * 5
            # Micro support bonus (Yahoo proxy)
            _score += _micro_scores.get(_tf, 0.0) * 0.5
            # 1H trend confirmation bonus
            if trend_1h == direction:
                _score += 20
            # -- Deriv cache bonus: kama cached Deriv data inakubaliana na direction --
            _dc_bonus = _deriv_ind_data  # fetched earlier at top of generate_signal
            if _dc_bonus:
                _dc_key_map = {1: "5_s", 2: "10_s", 3: "15_s"}
                _dc_trend = _dc_bonus.get(_dc_key_map.get(_tf, ""))
                if _dc_trend and _dc_trend.get("direction") == direction:
                    _dc_str = _dc_trend.get("strength", 0)
                    _score += int(_dc_str * 0.6)  # max +60 - Deriv inakuwa na uzito mkubwa
                elif _dc_trend and _dc_trend.get("direction") not in (None, "FLAT") and _dc_trend["direction"] != direction:
                    _score -= 20  # Deriv inapinga - punguza score
            _tf_candidate_scores[_tf] = _score

        # Chagua TF yenye score kubwa zaidi
        best_tf_chosen = max(_tf_candidate_scores, key=_tf_candidate_scores.get)

        # Angalia kama TF iliyochaguliwa ina nguvu ya kutosha
        _min_scores = {1: 40, 2: 35, 3: 30}
        if _tf_candidate_scores[best_tf_chosen] >= _min_scores[best_tf_chosen]:
            timeframe = best_tf_chosen
        else:
            # Nguvu haitoshi kwa TF yoyote - chagua 3m kama fallback wa mwisho
            timeframe = 3

        vte_tf = best_vte  # keep vte_tf for downstream filters

        logging.info("TF SELECTION {}: scores=1m:{:.0f} 2m:{:.0f} 3m:{:.0f} → chosen={}m ia={} micro={}".format(
            pair,
            _tf_candidate_scores.get(1, 0),
            _tf_candidate_scores.get(2, 0),
            _tf_candidate_scores.get(3, 0),
            timeframe, indicators_agree,
            {k: round(v, 1) for k, v in _micro_scores.items()}
        ))

    # -- MICRO-CANDLE TREND: imeshughulikiwa ndani ya TF SELECTION block juu --
    # ---------------------------------------------------------


    # -- NON-OTC: ADX Weak-Trend Blocker ---------------------
    # Block only in genuinely ranging/choppy market.
    # ADX < 14  → always block
    # ADX 14-20 + agree < 4 + no 1H trend + no VTE → block
    if not is_otc and real is not None:
        _adx_live = float(real.get("adx", 25.0)) if real.get("adx") else 25.0
        _adx_block = False
        if _adx_live < 14.0:
            _adx_block = True
        elif _adx_live < 20.0 and indicators_agree < 4 and trend_1h is None and vte_tf is None:
            _adx_block = True

        if _adx_block:
            logging.info("ADX BLOCK {}: adx={:.1f} agree={} trend={} → no signal".format(
                pair, _adx_live, indicators_agree, trend_1h))
            record_signal(pair, direction)
            return {
                "direction": direction, "pair": pair, "timeframe": 0,
                "strength": 0, "indicators_agree": indicators_agree,
                "trend_1h": None, "vwap_data": vwap_data,
                "confluence": {"level": "WEAK", "score": 0, "badge": "⚠️ RANGING"},
                "mtf": mtf, "flat": True, "patterns": detected_patterns,
                "movement_cat": movement_cat, "avg_movement": avg_movement,
                "no_signal_reason": "🟡 *Market is ranging – ADX={:.0f}. No clear trend.*".format(_adx_live),
                "nn_confidence": None, "nn_used": False, "_nn_feat_arr": None,
            }
    # ---------------------------------------------------------

    # -- NON-OTC: Weak confluence → fuata 1H trend (ilikuwa ina bug ya kupinga 1H) --
    if not is_otc and is_filter_on("confluence") and indicators_agree < 5 and vte_tf is None:
        if trend_1h is not None:
            direction = trend_1h  # Fuata 1H - si kupingana nayo
            timeframe = timeframe if timeframe > 0 else 3
        elif not yahoo_available:
            timeframe = 3  # No data - use 3m instead of blocking

    # -- OTC: Random flip/follow logic ------------------------
    # Each signal independently decides: follow the market or go against it.
    # Random intervals mean the broker cannot predict the pattern.
    if is_otc:
        otc_flip = random.choices(
            ["follow", "oppose"],
            weights=[45, 55]
        )[0]
        if otc_flip == "oppose":
            direction = "SELL" if direction == "BUY" else "BUY"
        _otc_flip_cache[pair] = otc_flip

    # -- 1H CANDLE CONFIRMATION (non-OTC only) ---------------
    # OTC always forces a signal - no blocking on 1H confirmation.
    if not is_otc and is_filter_on("h1confirm") and timeframe <= 2:
        h1_confirmed = _confirm_1h_direction(pair, direction)
        if not h1_confirmed:
            if timeframe == 1:
                timeframe = 2
                h1_confirmed = _confirm_1h_direction(pair, direction)
            if not h1_confirmed:
                timeframe = 3
                h1_confirmed = _confirm_1h_direction(pair, direction)
            if not h1_confirmed:
                timeframe = 3  # Bump to 3m instead of blocking (timeframe=0)

    # -- SESSION-AWARE BIAS ------------------------------------
    session = _get_session()
    bias    = get_signal_bias(pair, window=10, threshold=session["threshold"])
    if bias is not None and trend_1h is None:
        # Follow bias directly
        if bias == direction:
            direction = bias
    elif bias is not None and trend_1h is not None:
        if bias == trend_1h:
            direction = trend_1h

    # -- ENFORCE 1H TREND AS HARD FILTER ---------------------
    if trend_1h == "BUY" and direction == "SELL":
        raw_gap = s - b - 45
        if raw_gap < 35:
            direction = "BUY"
    elif trend_1h == "SELL" and direction == "BUY":
        raw_gap = b - s - 45
        if raw_gap < 35:
            direction = "SELL"

    # -- 1H vs SHORT-TF CONFLICT FILTER (non-OTC only) --------
    # If 1H trend is clear but 5m+15m real data strongly disagrees → no signal
    if not is_otc and trend_1h is not None and real is not None and is_filter_on("conflict"):
        tv = real.get("tf_buy_votes", 0)
        sv = real.get("tf_sell_votes", 0)
        tf_total = real.get("tf_count", 1)
        short_tf_dir = "BUY" if tv > sv else ("SELL" if sv > tv else None)
        if short_tf_dir is not None and short_tf_dir != trend_1h:
            # Short TFs majority oppose the 1H trend (lowered from 100% to 67%)
            opposition_pct = max(tv, sv) / tf_total
            if opposition_pct >= 0.67 and tf_total >= 2:
                # 100% of short TFs oppose 1H - market in transition, wait
                timeframe = 0   # Signal flat - will trigger no-signal in handler
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

    # -- SIGNAL STABILITY FILTER (non-OTC only) --------------
    # OTC always produces a signal - stability filter does not apply.
    if not is_otc and is_filter_on("stability") and not _check_signal_stability(pair, direction, window_minutes=5):
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

    # -- TREND CONFLUENCE ANALYSIS ----------------------------
    confluence = _calc_trend_confluence(trend_1h, vwap_data, mtf, direction)

    # Apply reversal candle filter (non-OTC, TF 1m/2m/3m only)
    if not is_otc:
        direction = _apply_reversal_filter(direction, timeframe, pair)

    # -- I: CANDLESTICK CONFIRMATION GATE ---------------------
    # Check current candle direction on 1m, 2m (proxy), 3m timeframes.
    # If candle opposes signal → bump TF up (safer entry).
    # Prevents entering at worst possible moment.
    if not is_otc and timeframe > 0:
        try:
            real_pair_cg = OTC_TO_REAL.get(pair, pair)
            cg_symbol    = YAHOO_SYMBOLS.get(real_pair_cg)
            if cg_symbol:
                # Fetch 1m candles
                df_1m = yf.download(cg_symbol, period="1d", interval="1m",
                                    progress=False, auto_adjust=True)
                if df_1m is not None and len(df_1m) >= 4:
                    opens_1m  = df_1m["Open"].squeeze().astype(float)
                    closes_1m = df_1m["Close"].squeeze().astype(float)
                    # Current candle direction (last complete + forming)
                    c1_bull = float(closes_1m.iloc[-1]) > float(opens_1m.iloc[-1])
                    c2_bull = float(closes_1m.iloc[-2]) > float(opens_1m.iloc[-2])
                    candle_dir_1m = "BUY" if (c1_bull and c2_bull) else \
                                    ("SELL" if (not c1_bull and not c2_bull) else "NEUTRAL")

                    # Check 5m as proxy for 2m/3m
                    df_5m = yf.download(cg_symbol, period="1d", interval="5m",
                                        progress=False, auto_adjust=True)
                    candle_dir_5m = "NEUTRAL"
                    if df_5m is not None and len(df_5m) >= 3:
                        opens_5m  = df_5m["Open"].squeeze().astype(float)
                        closes_5m = df_5m["Close"].squeeze().astype(float)
                        c1_5_bull = float(closes_5m.iloc[-1]) > float(opens_5m.iloc[-1])
                        c2_5_bull = float(closes_5m.iloc[-2]) > float(opens_5m.iloc[-2])
                        candle_dir_5m = "BUY" if (c1_5_bull and c2_5_bull) else \
                                        ("SELL" if (not c1_5_bull and not c2_5_bull) else "NEUTRAL")

                    # Gate logic per timeframe
                    if timeframe == 1:
                        # 1m needs BOTH 1m and 5m candles to agree
                        if candle_dir_1m != direction and candle_dir_1m != "NEUTRAL":
                            if candle_dir_5m == direction:
                                timeframe = 2   # bump to 2m
                                logging.info("CANDLE GATE {}: 1m→2m (1m candle opposes)".format(pair))
                            else:
                                timeframe = 3   # bump to 3m
                                logging.info("CANDLE GATE {}: 1m→3m (both oppose)".format(pair))
                    elif timeframe == 2:
                        # 2m: use 5m candle as gate
                        if candle_dir_5m != direction and candle_dir_5m != "NEUTRAL":
                            timeframe = 3
                            logging.info("CANDLE GATE {}: 2m→3m (5m candle opposes)".format(pair))
                    # timeframe==3: no bump needed, 3m is most forgiving
        except Exception as _cg_e:
            logging.warning("candle gate {} failed: {}".format(pair, _cg_e))
    # ---------------------------------------------------------

    # -- NEURAL NETWORK FILTER ---------------------------------
    nn_confidence  = None
    nn_used        = False
    nn_feat_arr    = None
    if _NN_AVAILABLE and timeframe > 0:
        sig_snapshot = {
            "trend_1h":         trend_1h,
            "vwap_data":        vwap_data,
            "mtf":              mtf,
            "indicators_agree": indicators_agree,
            "is_otc":           is_otc,
            "strength":         strength,
        }
        nn_feat_arr = _nn_features_from_signal(
            sig_snapshot, rsi, sto, ma_diff, macd, bb_pos, mom, vol, candle
        )
        if nn_feat_arr is not None:
            direction, nn_confidence, nn_used = _nn_adjust_direction(
                pair, nn_feat_arr, direction
            )
            if nn_confidence is not None:
                logging.info("NN Signal: pair={} dir={} conf={:.1%} used={}".format(
                    pair, direction, nn_confidence, nn_used))
    # ---------------------------------------------------------

    # AUTO-REVERSE disabled - signal follows MTF direction only

    record_signal(pair, direction)
    result = {
        "direction": direction, "pair": pair, "timeframe": timeframe,
        "strength": strength, "indicators_agree": indicators_agree,
        "trend_1h": trend_1h, "vwap_data": vwap_data,
        "confluence": confluence, "mtf": mtf, "flat": (timeframe == 0),
        "patterns": detected_patterns,
        "movement_cat": movement_cat, "avg_movement": avg_movement,
        "no_signal_reason": "",
        "nn_confidence": nn_confidence,
        "nn_used":       nn_used,
        "_nn_feat_arr":  nn_feat_arr,  # stored internally for VTE feedback
    }
    return result


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
def is_market_closed():
    """
    Returns True when non-OTC forex pairs are unavailable on Pocket Option:
    - Saturday or Sunday (UTC), OR
    - Weekday night closure: 23:45 - 03:15 EAT = 20:45 - 00:15 UTC
    When True → show OTC pairs for trading, non-OTC shown as (Closed).
    When False → show non-OTC pairs for trading, OTC also available.
    """
    now = datetime.utcnow()
    wd  = now.weekday()  # 0=Mon … 6=Sun
    if wd >= 5:   # Saturday=5, Sunday=6
        return True
    h, m = now.hour, now.minute
    total_mins = h * 60 + m
    # 20:45 UTC = 1245 mins, 00:15 UTC = 15 mins
    if total_mins >= 1245 or total_mins < 15:
        return True
    return False

# Keep old name as alias for backward compatibility
def is_weekend():
    return is_market_closed()

def _market_closed_reason():
    """Return short text explaining why market is closed."""
    now = datetime.utcnow()
    if now.weekday() >= 5:
        return "Weekend"
    return "Night Hours"

def _session_header_text():
    """Return current session line for display above pair keyboard."""
    _SESSION_EMOJIS = {
        "London Open":  "🟢",
        "London Mid":   "🟢",
        "NY/London":    "🟡",
        "NY Session":   "🟡",
        "Asian":        "🔵",
        "Pre-London":   "🟠",
        "Dead Hours":   "🔴",
    }
    try:
        sess = _get_session()
        name = sess.get("name", "")
        if not name or name in ("Dead Hours", "Off Hours", ""):
            return "🔴 *Dead Hours* - low activity"
        emoji = _SESSION_EMOJIS.get(name, "🕐")
        return "{} *{}*".format(emoji, name)
    except Exception:
        return ""


def pairs_keyboard():
    """
    Build the pair selection keyboard.

    Logic (auto-detect):
    - Market CLOSED (weekend / night hours):
        Show OTC pairs only. Non-OTC pairs are completely hidden.
        Banner at top explains why.
    - Market OPEN (weekdays, market hours):
        Show non-OTC pairs only. Popular/major pairs always first,
        exotic/bonus pairs at the bottom.

    Pairs sorted: hot pairs (consecutive_wins >= 3) first within each
    priority group, then by win rate. Max 96 buttons, 3 per row.
    """
    # Popular non-OTC pairs - always shown first (majors + key minors)
    _PRIORITY_PAIRS = [
        "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD",
        "NZD/USD", "USD/CAD", "EUR/GBP", "EUR/JPY", "EUR/AUD",
        "EUR/CAD", "EUR/CHF", "GBP/JPY", "GBP/AUD", "GBP/CAD",
        "GBP/CHF", "AUD/JPY", "AUD/CAD", "AUD/CHF", "CHF/JPY",
        "CAD/JPY", "CAD/CHF", "USD/MXN",
        "US100", "SP500", "US30", "GER40", "UK100",
        "JPN225", "AUS200", "CAC 40", "SMI 20", "E35EUR",
    ]
    _MAX_BUTTONS = 96
    rows = []
    row  = []
    closed = is_market_closed()
    reason = _market_closed_reason()

    if closed:
        # Weekend - OTC only
        pool = [p for p in ALL_PAIRS if "OTC" in p]
    else:
        # Weekday - non-OTC only
        pool = [
            p for p in ALL_PAIRS
            if "OTC" not in p and len(p) > 1
        ]

    # Fetch win-rate stats for sorting
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pair,
                           ROUND(wins::numeric / NULLIF(wins+losses,0) * 100, 1) AS win_rate,
                           (wins + losses) AS total,
                           COALESCE(consecutive_wins, 0) AS consecutive_wins
                    FROM pair_stats WHERE pair = ANY(%s)
                """, (pool,))
                wr_rows = {
                    r["pair"]: (
                        float(r["win_rate"] or 0),
                        int(r["total"] or 0),
                        int(r["consecutive_wins"] or 0)
                    )
                    for r in cur.fetchall()
                }
    except Exception:
        wr_rows = {}

    def _sort_key(p):
        wr, total, cw = wr_rows.get(p, (0, 0, 0))
        return (-(cw >= 3), -wr, -total)

    if closed:
        # OTC - sort by win rate as before
        known   = sorted([p for p in pool if p in wr_rows and wr_rows[p][1] >= 3], key=_sort_key)
        unknown = sorted([p for p in pool if p not in known], key=_sort_key)
        pairs   = (known + unknown)[:_MAX_BUTTONS]
    else:
        # Non-OTC - priority pairs first, bonus (exotic) pairs at end
        priority_in_pool = [p for p in _PRIORITY_PAIRS if p in pool]
        bonus_in_pool    = [p for p in pool if p not in _PRIORITY_PAIRS]

        # Sort each group by hot/win-rate
        pri_known   = sorted([p for p in priority_in_pool if p in wr_rows and wr_rows[p][1] >= 3], key=_sort_key)
        pri_unknown = sorted([p for p in priority_in_pool if p not in pri_known], key=_sort_key)
        bon_known   = sorted([p for p in bonus_in_pool if p in wr_rows and wr_rows[p][1] >= 3], key=_sort_key)
        bon_unknown = sorted([p for p in bonus_in_pool if p not in bon_known], key=_sort_key)

        pairs = (pri_known + pri_unknown + bon_known + bon_unknown)[:_MAX_BUTTONS]

    # Build 3-per-row keyboard
    for pair in pairs:
        i = pair_to_idx(pair)
        if i is None:
            continue
        row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(i)))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Session info as first row
    sess_line = _session_header_text()
    if sess_line:
        rows.insert(0, [InlineKeyboardButton(sess_line, callback_data="noop")])

    # Market closed banner
    if closed:
        banner = "🔒 {} - OTC pairs active 24/7".format(reason)
        rows.insert(0 if not sess_line else 1, [InlineKeyboardButton(banner, callback_data="noop")])

    return InlineKeyboardMarkup(rows)

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
    """Seconds keyboard for OTC - subscribers only."""
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

def signal_keyboard(pair):
    """Get More button shown after every signal."""
    idx = pair_to_idx(pair)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))],
    ])

# ============================================================
# PAYMENT TEXT
# ============================================================
PAYMENT_TEXT = """💰 *UNLOCK EVALON WINNERS BOT*

🥈 *MONTHLY ACCESS - $50*
✅ Unlimited signals for 30 days
✅ Win rate 90% - 98%
✅ 100+ trading pairs

💎 *LIFETIME ACCESS - $150*
✅ Unlimited signals forever
✅ Win rate 90% - 98%
✅ Free updates forever
✅ 100+ trading pairs

━━━━━━━━━━━━━━━━━━
💳 *PAYMENT METHODS:*

📱 *Mobile Money (Tanzania):*
M-Pesa / Tigo / Airtel / Halotel
Select Lipa Namba: `353481341`
Account: EVALON WINNERS BOT STORE

🟡 *Binance ID:* `1222890272`
Account: Master Indicators Pro
Send USDT or BUSD via Binance Pay

🔵 *USDT TRC-20 (Tron):*
`TEUwK1aElmdCeG3n36LDySqSkwobMh37Xf`
TRC-20 Tron ONLY - wrong network = lost funds

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
        # Can't check - let them through rather than blocking everyone
        return True

    # Pending join request
    if has_join_request(user_id):
        return True

    # Not joined, not requested - show join message
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_INVITE)],
        [InlineKeyboardButton("✅ I've Requested", callback_data="check_join")],
    ])
    msg = (
        "⚠️ *Join Required*\n\n"
        "To use EVALON WINNERS BOT you must first join our channel.\n\n"
        "1️⃣ Tap *Join Channel* below\n"
        "2️⃣ Send a join request\n"
        "3️⃣ Tap *I've Requested* to continue\n\n"
        "_You don't need to wait for approval - just send the request._"
    )
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    return False

async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Triggered automatically when user sends a join request to the channel.
    Saves their user_id - bot does NOT approve the request (admin does that).
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

    # DB calls wrapped - bot still responds even if DB is temporarily down
    try:
        get_user(user_id)
    except Exception as e:
        logging.warning("start: get_user failed for {}: {}".format(user_id, e))

    # Referral check
    if context.args:
        try:
            arg = context.args[0]
            referrer_id = int(arg.replace("REF_", ""))
            if referrer_id != user_id:
                register_referral(user_id, referrer_id)
        except Exception:
            pass

    # Channel membership check - skip if it fails, don't block user
    try:
        if not await check_channel_and_proceed(update, context):
            return
    except Exception as e:
        logging.warning("start: channel check failed for {}: {}".format(user_id, e))

    reply_kb = ReplyKeyboardMarkup(
        [["🏆 EVALON MENU 🏆"]],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
    )

    await update.message.reply_text(
        "╔══════════════════════╗\n"
        "     ⚡ EVALON WINNERS BOT\n"
        "╚══════════════════════╝\n\n"
        "🏆 *Win Rate: 90% - 98%*\n"
        "📊 *100+ Trading Pairs*\n"
        "🧠 *AI-Powered Signal Analysis*\n\n"
        "⚠️ _Evalon Bot is AI-powered and may make mistakes. Trade responsibly._\n\n"
        "Tap *🏆 EVALON MENU 🏆* below to get started:",
        parse_mode="Markdown",
        reply_markup=reply_kb,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(
            "🔧 *EVALON WINNERS BOT - ADMIN PANEL*\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔑 *LICENCE MANAGEMENT*\n"
            "`/addmonthly` - Generate 1 monthly code\n"
            "`/addmonthly 5` - Generate 5 monthly codes\n"
            "`/addlifetime` - Generate 1 lifetime code\n"
            "`/addlifetime 5` - Generate 5 lifetime codes\n"
            "`/listlicences` - View all codes (used/unused)\n"
            "`/revoke 123456` - Remove user licence\n"
            "`/resultson` - Enable WIN/LOSS result messages\n"
            "`/resultsoff` - Disable result messages\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👥 *USER MANAGEMENT*\n"
            "`/listusers` - View all users & stats\n"
            "`/totalusers` - Quick user count\n"
            "`/stats` - Detailed statistics\n"
            "`/userinfo 123456` - Full details of a user\n"
            "`/addtrial 123456 5` - Give user extra free signals\n"
            "`/deleteuser 123456` - Delete user permanently\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚫 *BLACKLIST*\n"
            "`/blacklist 123456 reason` - Ban a user\n"
            "`/unblacklist 123456` - Unban a user\n"
            "`/listblacklist` - View all banned users\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📢 *BROADCAST*\n"
            "`/broadcast message` - Send to all users\n"
            "_Markdown supported: *bold*, _italic_, `code`_\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🖼 *IMAGES*\n"
            "`/setimage` - Change BUY/SELL signal images\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🗄 *DATABASE*\n"
            "`/dbcheck` - Check database status\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 *PAIR STATS*\n"
            "`/pairstats` - Win/loss stats for all pairs\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔀 *OTC CONTROL*\n"
            "`/toggleotc` - Enable or disable OTC pairs\n"
            "• OTC OFF → show non-OTC pairs only\n"
            "• OTC ON  → all pairs visible (default)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🎛 *SIGNAL FILTERS*\n"
            "`/filterstatus` - View status of all filters\n"
            "`/filteroff news` - Disable news block filter\n"
            "`/filteroff dead` - Disable dead market filter\n"
            "`/filteroff conflict` - Disable 1H vs short-TF filter\n"
            "`/filteroff stability` - Disable signal stability filter\n"
            "`/filteroff confluence` - Disable min confluence filter\n"
            "`/filteroff h1confirm` - Disable 1H candle gate\n"
            "`/filteroff micro_trend` - Disable micro-candle trend filter\n"
            "`/filteroff all` - Disable ALL filters\n"
            "`/filteron [name|all]` - Enable filter(s)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔓 *FORCE PAIR*\n"
            "`/forcepair EURUSD OTC` - bypass flat filter for pair\n"
            "`/forcepair all` - bypass for all pairs\n"
            "`/forcepair list` - show forced pairs\n"
            "`/unforcepair all` - clear all overrides\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🧠 *NEURAL NETWORK*\n"
            "`/nnstats` - NN status, accuracy & per-pair models\n"
            "`/nnretrain` - Force NN retrain immediately\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 *REPORTS*\n"
            "`/pairreport` - Full pair performance report\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "`/help` - This menu",
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
            "⚡ *EVALON WINNERS BOT*\n\n"
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
            "_Data is safe on Neon - updates won't delete anything._".format(
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
            "⚡ *EVALON WINNERS BOT*\n\n"
            "🏆 Win Rate: 90% - 98%\n"
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
                "✅ *Welcome to EVALON WINNERS BOT!*\n\nSelect your trading pair:",
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
            "📈 *Set BUY Image*\n\nSend me the BUY signal image now.\n\n_Forward or send any photo - I will save it._",
            parse_mode="Markdown"
        )
        return

    # Admin: set SELL image
    if data == "set_sell_img":
        if user_id != ADMIN_ID: return
        context.user_data["awaiting_image"] = "sell"
        await q.edit_message_text(
            "📉 *Set SELL Image*\n\nSend me the SELL signal image now.\n\n_Forward or send any photo - I will save it._",
            parse_mode="Markdown"
        )
        return

    if data=="noop":
        try: await q.answer()
        except: pass
        return

    if data=="choose_pair":
        # Delete previous menu/signal messages
        await delete_last_signal(context.bot, chat, user_id)
        try: await q.edit_message_reply_markup(reply_markup=None)
        except: pass
        try: await q.message.delete()
        except: pass

        closed = is_market_closed()

        # Rotating taglines - change every time user opens pair selection
        if closed:
            taglines = [
                "🌙 *After-Hours Trading*\nKeep trading even when global markets are closed. Weekend-only pairs available 24/7.",
                "⏰ *Always-On Pairs*\nMarkets closed? No problem. These pairs trade around the clock, every day of the week.",
                "🔁 *Extended Hours Pairs*\nExclusive pairs for traders who never stop. Active when traditional markets rest.",
                "📅 *Weekend Special Pairs*\nAvailable exclusively on weekends when live markets are closed.",
            ]
        else:
            taglines = [
                "🌍 *Real Market Pairs*\nTrade on live market data - EUR/USD, Gold, Oil and more. Real prices, real movement, real results.",
                "💹 *Live Market Trading*\nOur AI analyzes real-time market data from global exchanges. No simulations - just pure market signals.",
                "📡 *Real-Time Market Signals*\nPowered by live market data. Every signal is backed by actual market movement.",
                "🏦 *Institutional-Grade Pairs*\nThe same pairs traded by banks and hedge funds. Maximum liquidity, highest accuracy.",
            ]

        tagline = random.choice(taglines)
        sess = get_trading_session()
        sess_txt = ""
        if sess and sess.get("name","") not in ("Dead Hours","Off Hours",""):
            sess_txt = "\n🕐 *{}* active".format(sess["name"])
        header = "⚡ *EVALON WINNERS BOT*\n\n{}{}\n\n📊 Select your trading pair:".format(tagline, sess_txt)

        _pm = await context.bot.send_message(
            chat_id=chat,
            text=header,
            parse_mode="Markdown",
            reply_markup=pairs_keyboard()
        )
        save_last_bot_msg(user_id, _pm.message_id)
        return

    if data=="bot_pick_pair":
        # Free trial users cannot use Bot Pick Pair - subscribers only
        if not is_licensed(user_id):
            await q.edit_message_text(
                "🔒 *Bot Pick Pair - Subscribers Only*\n\n"
                "This feature is available for licensed subscribers only.\n\n"
                "Upgrade to get:\n"
                "✅ Bot-picked best pairs\n"
                "✅ Unlimited signals\n"
                "✅ Win rate 90% - 98%",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("📊 Choose Pair Myself", callback_data="choose_pair")],
                ])
            )
            return

        closed = is_market_closed()

        if closed:
            # Market closed - pick from OTC pairs only
            top5 = get_top5_pairs(otc_only=True)
            if len(top5) < 5:
                pool = [p for p in ALL_PAIRS if "OTC" in p]
                random.shuffle(pool)
                existing = {r["pair"] for r in top5}
                for p in pool:
                    if p not in existing and len(top5) < 5:
                        top5.append({"pair": p, "wins": 0, "losses": 0, "win_rate": 0})
                        existing.add(p)
        else:
            # Market open - pick from non-OTC (live data) first, OTC as fallback
            top5 = get_top5_pairs(non_otc_only=True)
            if len(top5) < 5:
                pool = [p for p in ALL_PAIRS if "OTC" not in p and "/" in p and "BTC" not in p]
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
            label = "📊 {} - {:.0f}% ({})".format(pair, wr, total) if is_admin_user and total > 0 else "📊 {}".format(pair)
            try:
                idx = ALL_PAIRS.index(pair)
            except ValueError:
                continue
            buttons.append([InlineKeyboardButton(label, callback_data="sel_{}".format(idx))])

        kb = InlineKeyboardMarkup(buttons)

        await q.edit_message_text(
            "🤖 *Bot Top Picks*\n\n"
            "Best Forex & OTC pairs by win rate.\n"
            "Select one to get a signal:",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    if data=="my_stats":
        u = get_user(user_id)
        licensed = is_licensed(user_id)
        lic_type = u.get("licence_type", "").capitalize() if licensed else "Free Trial"
        expiry_txt = get_expiry_text(user_id) if licensed else "-"
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
            "ℹ️ *EVALON WINNERS BOT - Help*\n\n"
            "⚡ *Get Signal* - Select a pair and get a BUY/SELL signal\n"
            "🤖 *Bot Pick Pair* - Bot picks the best pair for you\n"
            "📊 *My Stats* - View your account status\n"
            "💎 *Upgrade* - Purchase a monthly or lifetime licence\n\n"
            "📌 *How to use:*\n"
            "1. Tap 🏆 EVALON MENU 🏆\n"
            "2. Select Get Signal or Bot Pick Pair\n"
            "3. Wait for the signal - enter the trade when it appears",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Get Signal", callback_data="choose_pair")],
                [InlineKeyboardButton("💬 Contact Support", url=support_url())],
            ])
        )
        return

    # -- OTC: "Back" button - return to mode selection -----------
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
                "⏱ *Seconds* - 3s/5s/10s/15s/30s signals _(subscribers only)_\n"
                "📊 *Normal* - minute-based signal"
            ).format(pair),
            parse_mode="Markdown",
            reply_markup=otc_mode_keyboard(pair)
        )
        return

    # -- OTC: "Normal (minutes)" chosen - continue with normal signal flow -
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

        # --- Always fresh signal - ignore cooldown, generate new one ---
        check = check_signal_request(user_id, pair)
        clear_user_signal_state(user_id, pair)  # Force fresh always

        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)
        is_non_otc = False  # pair is OTC
        entry_price = None
        trend = get_trend_direction(pair)

        if check["action"] == "fresh":
            sig = await safe_generate_signal(pair)  # guaranteed - OTC always signals
            _anim_stop.set()
            direction = sig["direction"]
            timeframe = sig["timeframe"]
            strength  = sig["strength"]
            flip_count = 0
            # -- Store NN features for VTE feedback later --
            _nn_feat = sig.get("_nn_feat_arr")
            if _nn_feat is not None:
                nn_store_signal_features(user_id, pair, _nn_feat, sig.get("direction"))
            # ----------------------------------------------
            if sig.get("flat") and timeframe == 0:
                try: await cm.delete()
                except: pass
                await delete_last_signal(context.bot, chat, user_id)
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))],
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return
            if trend is not None:
                direction = trend
            elif sig.get("indicators_agree", 7) < 4 and is_non_otc:
                try: await cm.delete()
                except: pass
                await delete_last_signal(context.bot, chat, user_id)
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No signal available*",
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
        cap = "*{}* {}\n🕐 In {} min.\n📊 Signal strength: {}%".format(pair, arrow, timeframe, strength)
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

    # -- Non-OTC: Back to mode selection ----------------------------------
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

    # -- Non-OTC: Show manual TF keyboard ----------------------------------
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

    # -- Non-OTC: Bot decides TF - go straight to signal -------------------
    if data.startswith("nonotc_auto_"):
        # Redirect to sel_ flow by replacing data
        data = "sel_{}".format(data[12:])
        # Fall through to sel_ handler below

    # -- Non-OTC: User chose specific TF -----------------------------------
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
        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)
        sig = await safe_generate_signal(pair)  # timeout-safe, never hangs
        _anim_stop.set()
        direction = sig["direction"]
        timeframe = chosen_tf

        # -- Deriv micro-candle: MSINGI wa direction na TF -------
        # Sekunde (5s/10s/15s) zinaaamua direction na timeframe
        if pair in DERIV_SYMBOLS:
            try:
                _best_tf, _best_str, _micro_dir, _best_reason = await pick_best_tf_deriv(pair)
                logging.info("Deriv best_tf={} dir={} str={} - {}".format(
                    _best_tf, _micro_dir, _best_str, _best_reason))
                if _best_tf is not None and _micro_dir is not None:
                    # Deriv sekunde inaamua - override direction na TF
                    direction = _micro_dir
                    timeframe = _best_tf
                else:
                    # Deriv FLAT - angalia nguvu ya MTF kabla ya kutuma signal
                    _weak_agree = sig.get("indicators_agree", 0) < 4
                    _no_1h      = sig.get("trend_1h") is None
                    if _weak_agree and _no_1h:
                        # Deriv FLAT + MTF dhaifu + hakuna 1H trend → no signal
                        _anim_stop.set()
                        try: await cm.delete()
                        except: pass
                        _nsm = await context.bot.send_message(
                            chat_id=chat,
                            text="🟡 *No signal available* - market is unclear right now. Please try again in a few minutes.",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                            ])
                        )
                        save_last_bot_msg(user_id, _nsm.message_id)
                        return
                    # Deriv FLAT lakini MTF ina nguvu → tumia MTF direction, chosen_tf
                    logging.info("Deriv FLAT for {} - MTF strong enough, using MTF direction".format(pair))
                    timeframe = chosen_tf
            except Exception as _de:
                logging.warning("Deriv pick_best_tf error: {} - falling back to MTF".format(_de))
                timeframe = chosen_tf
        else:
            timeframe = chosen_tf  # Pair haipo Deriv - tumia chosen_tf
        # -----------------------------------------------------

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

    # -- OTC: "Seconds" chosen - show seconds keyboard ------------------
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
                    "🔒 *Seconds signals - Subscribers Only*\n\n"
                    "This option is available for licensed subscribers only.\n\n"
                    "Upgrade to unlock:\n"
                    "✅ Seconds signals (3s/5s/10s/15s/30s)\n"
                    "✅ Unlimited signals\n"
                    "✅ Win rate 90% - 98%"
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

    # -- OTC: Seconds timeframe selected - generate seconds signal --------
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
                text="🔒 *Seconds signals - Subscribers Only*\n\nUpgrade your plan to unlock this feature.",
                parse_mode="Markdown",
                reply_markup=unlock_keyboard()
            )
            return
        if is_spam(user_id):
            return
        inactivity_reset(user_id, chat)

        try: await q.message.delete()
        except: pass

        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)

        sig       = await safe_generate_signal(pair)  # OTC - always returns signal
        _anim_stop.set()
        direction = sig["direction"]
        strength  = sig["strength"]

        trend_dir = get_trend_direction(pair)
        if trend_dir is not None:
            direction = trend_dir
        elif sig.get("indicators_agree", 7) < 4 and "OTC" not in pair:
            try: await cm.delete()
            except: pass
            await delete_last_signal(context.bot, chat, user_id)
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No signal available*",
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

        cap = "*{}* {}\n⏱ In *{}s*\n📊 Signal strength: {}%".format(pair, arrow, chosen_secs, strength)
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
        expiry_finished = True   # Always treat as fresh - no blocking
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
                        return 1   # Moves fast - 1m is enough
                    elif avg_mov >= 0.06:
                        return 2   # Medium movement - 2m
                    else:
                        return 3   # Slow pair - needs 3m for clear close
                if row and row["optimal_tf"]:
                    return int(row["optimal_tf"])
            except Exception:
                pass
            return fallback_tf

        if True:  # Always fresh - regenerate on every tap
            if not is_licensed(user_id) and free_signals_used(user_id) >= total_free_allowed(user_id):
                bonus = get_bonus_signals(user_id)
                refs  = count_referrals(user_id)
                extra = "\n\n🎁 *You have {} referrals* - invite more to unlock extra signals!".format(refs) if refs > 0 else "\n\n🎁 *Invite 3+ friends* to get free bonus signals!"
                await context.bot.send_message(
                    chat_id=chat,
                    text="🔒 *UNLOCK FULL ACCESS*\n\nYou have used your *{} free trial signals*.{}\n\n"
                         "💎 *$150 - LIFETIME ACCESS*\n✅ Unlimited signals forever\n✅ Win rate 90% - 98%\n✅ Free updates forever\n✅ 100+ trading pairs\n\n"
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

        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)

        _is_non_otc_pair = "OTC" not in pair and pair in YAHOO_SYMBOLS
        _mtf_result = None
        if _is_non_otc_pair:
            try:
                _mtf_result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, run_mtf_signal_engine_with_fallback, pair
                    ),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logging.warning("MTF timeout for {} - skipping MTF".format(pair))
                _mtf_result = None
            except Exception as _e:
                logging.warning("MTF pre-check failed {}: {}".format(pair, _e))

        sig = await safe_generate_signal(pair)  # timeout-safe, OTC guaranteed
        _anim_stop.set()
        direction = sig["direction"]
        strength  = sig["strength"]

        # -- A: SIGNAL CONFIRMATION DELAY ---------------------
        # Wait 4s and recheck direction before sending to user
        _is_otc_confirm = "OTC" in pair
        try:
            direction = await asyncio.wait_for(
                _confirm_signal_direction(pair, direction, _is_otc_confirm),
                timeout=6.0
            )
        except asyncio.TimeoutError:
            logging.warning("_confirm_signal_direction timeout for {}".format(pair))
            # keep original direction
        # -----------------------------------------------------

        # -- DERIV SECONDS - MSINGI wa TF na direction kwa non-OTC --
        _mtf_cap = None
        _gm_is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS

        if _gm_is_non_otc and pair in DERIV_SYMBOLS:
            try:
                _best_tf, _best_str, _micro_dir, _best_reason = await pick_best_tf_deriv(pair)
                logging.info("getmore Deriv: pair={} tf={} dir={} str={} - {}".format(
                    pair, _best_tf, _micro_dir, _best_str, _best_reason))
                if _best_tf is not None and _micro_dir is not None:
                    # Deriv sekunde inaamua direction na TF
                    direction = _micro_dir
                    timeframe = _best_tf
                else:
                    # Deriv FLAT - angalia nguvu ya MTF
                    _gm_weak = sig.get("indicators_agree", 0) < 4 and sig.get("trend_1h") is None
                    if _gm_weak:
                        try: await cm.delete()
                        except: pass
                        await delete_last_signal(context.bot, chat, user_id)
                        _nsm = await context.bot.send_message(
                            chat_id=chat,
                            text="🟡 *No signal available* - market is unclear. Try again in a few minutes.",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                            ])
                        )
                        save_last_bot_msg(user_id, _nsm.message_id)
                        return
                    logging.info("getmore Deriv FLAT for {} - MTF strong, using MTF direction".format(pair))
            except Exception as _de:
                logging.warning("getmore Deriv failed {}: {} - falling back to MTF".format(pair, _de))
        elif _gm_is_non_otc:
            # Pair haipo Deriv - tumia MTF au generate_signal timeframe
            if _mtf_result and _mtf_result.get("direction") in ("CALL","PUT"):
                direction = "BUY" if _mtf_result["direction"] == "CALL" else "SELL"
                _mtf_tf   = _mtf_result["signal_type"]
                _mtf_cap  = build_mtf_caption(
                    pair, _mtf_result["direction"], _mtf_tf,
                    _mtf_result["tf_labels"], _mtf_result["trend_score"],
                    _mtf_result["near"])
                timeframe = _pick_tf_by_pips(pair, _mtf_tf)
            else:
                timeframe = _pick_tf_by_pips(pair, sig["timeframe"])
        # ---------------------------------------------------------

        # Flat market block
        if sig.get("flat") and sig["timeframe"] == 0:
            try: await cm.delete()
            except: pass
            await delete_last_signal(context.bot, chat, user_id)
            msg = sig.get("no_signal_reason") or "🟡 *No signal available*"
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        # Trend validation
        trend_dir = get_trend_direction(pair)
        gm_is_non_otc_check = "OTC" not in pair and pair in YAHOO_SYMBOLS
        if trend_dir is not None:
            direction = trend_dir
        elif gm_is_non_otc_check and is_filter_on("confluence") and (sig.get("flat") or sig.get("indicators_agree", 10) < 4):
            try: await cm.delete()
            except: pass
            await delete_last_signal(context.bot, chat, user_id)
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return
        elif "OTC" not in pair and is_filter_on("confluence") and sig.get("indicators_agree", 7) < 4:
            try: await cm.delete()
            except: pass
            await delete_last_signal(context.bot, chat, user_id)
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text=sig.get("no_signal_reason") or "🟡 *No signal available*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return

        new_flip_count = 0  # Always fresh signal - reset flip count

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
        _str  = sig.get("strength", 70)
        if isinstance(_str, int) and _str > 100:
            _str = int(60 + (_str - 300) / 200 * 39)
        _str = max(60, min(99, int(_str)))
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        await delete_last_signal(context.bot, chat, user_id)
        cap = "*{}* {}\n🕐 In *{}* min\n📊 Signal strength: {}%".format(pair, arrow, timeframe, _str)
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
                    text="⏰ *Your session has expired.*\n\n🌟 *Join our VIP today!*\n\n✅ Win rate 90% - 98%\n✅ 100+ trading pairs\n✅ Unlimited signals\n\n_Tap *Start* below to open a fresh chart._",
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
        # Auto-routing: wrong pair type for current market hours
        closed = is_market_closed()
        if closed and "OTC" not in pair:
            # Market closed - non-OTC not available
            reason = _market_closed_reason()
            await context.bot.send_message(
                chat_id=chat,
                text=(
                    "🔒 *Market Closed ({})*\n\n"
                    "This pair is not available right now.\n"
                    "Please select an *OTC* pair - active 24/7."
                ).format(reason),
                parse_mode="Markdown",
                reply_markup=pairs_keyboard()
            )
            return
        if not closed and "OTC" in pair:
            # Market open - OTC not shown, redirect to non-OTC
            await context.bot.send_message(
                chat_id=chat,
                text=(
                    "📊 *Market Open*\n\n"
                    "Live market pairs are available now.\n"
                    "Please select a *Non-OTC* pair for real market signals."
                ),
                parse_mode="Markdown",
                reply_markup=pairs_keyboard()
            )
            return
        # Anti-spam check
        if is_spam(user_id):
            return
        # User is active - reset inactivity timer (msg_id added later)
        inactivity_reset(user_id, chat)
        # Free trial check
        if not is_licensed(user_id) and free_signals_used(user_id) >= total_free_allowed(user_id):
            try: await q.message.delete()
            except: pass
            bonus = get_bonus_signals(user_id)
            refs = count_referrals(user_id)
            extra = "\n\n🎁 *You have {} referrals* - invite more to unlock extra signals!".format(refs) if refs > 0 else "\n\n🎁 *Invite 3+ friends* to get free bonus signals!"
            await context.bot.send_message(
                chat_id=chat,
                text="🔒 *UNLOCK FULL ACCESS*\n\n"
                     "You have used your *{} free trial signals*.{}\n\n"
                     "💎 *$150 - LIFETIME ACCESS*\n"
                     "✅ Unlimited signals forever\n"
                     "✅ Win rate 90% - 98%\n"
                     "✅ Free updates forever\n"
                     "✅ 100+ trading pairs\n\n"
                     "👇 See payment methods or enter your code:".format(total_free_allowed(user_id), extra),
                parse_mode="Markdown",
                reply_markup=unlock_keyboard()
            )
            return
        try: await q.message.delete()
        except: pass

        # -- OTC: Show seconds keyboard (mtumiaji achague mwenyewe) ---
        if "OTC" in pair:
            if not is_licensed(user_id):
                _otcm = await context.bot.send_message(
                    chat_id=chat,
                    text=(
                        "🔒 *Seconds signals - Subscribers Only*\n\n"
                        "This option is available for licensed subscribers only.\n\n"
                        "Upgrade to unlock:\n"
                        "✅ Seconds signals (3s/5s/10s/15s/30s)\n"
                        "✅ Unlimited signals\n"
                        "✅ Win rate 90% - 98%"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                        [InlineKeyboardButton("🔙 Back", callback_data="choose_pair")],
                    ])
                )
                save_last_bot_msg(user_id, _otcm.message_id)
                return
            _otcm = await context.bot.send_message(
                chat_id=chat,
                text="⏱ *{}*\n\nChoose signal duration:".format(pair),
                parse_mode="Markdown",
                reply_markup=otc_seconds_keyboard(pair)
            )
            save_last_bot_msg(user_id, _otcm.message_id)
            return

        # -- Non-OTC: Bot decides TF automatically (1m/2m/3m) ----------------
        context.user_data["_user_chose_tf"] = False

        # Initialize variables for non-OTC auto flow
        is_non_otc  = True
        entry_price = None
        trend       = get_trend_direction(pair)
        check       = check_signal_request(user_id, pair)
        clear_user_signal_state(user_id, pair)
        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)

        if check["action"] == "fresh":
            sig = await safe_generate_signal(pair)  # timeout-safe, OTC guaranteed
            _anim_stop.set()
            direction  = sig["direction"]
            timeframe  = sig["timeframe"]
            strength   = sig["strength"]
            flip_count = 0
            # Flat market block
            if sig.get("flat") and timeframe == 0:
                try: await cm.delete()
                except: pass
                await delete_last_signal(context.bot, chat, user_id)
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No signal available*",
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
            # Non-OTC: no signal if confluence weak - never guess
            elif is_non_otc and (sig.get("flat") or sig.get("indicators_agree", 10) < 6):
                try: await cm.delete()
                except: pass
                await delete_last_signal(context.bot, chat, user_id)
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(pair_to_idx(pair)))]
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return
            elif is_non_otc and sig.get("indicators_agree", 7) < 4:
                try: await cm.delete()
                except: pass
                await delete_last_signal(context.bot, chat, user_id)
                _nsm = await context.bot.send_message(
                    chat_id=chat,
                    text=sig.get("no_signal_reason") or "🟡 *No signal available*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(pair_to_idx(pair)))]
                    ])
                )
                save_last_bot_msg(user_id, _nsm.message_id)
                return

            # -- Deriv micro-candle: MSINGI wa direction na TF --------
            # Sekunde zinaaamua direction na timeframe kwa non-OTC pairs
            if is_non_otc and pair in DERIV_SYMBOLS:
                try:
                    _best_tf, _best_str, _micro_dir, _best_reason = await pick_best_tf_deriv(pair)
                    logging.info("Deriv non-OTC: best_tf={} dir={} str={} - {}".format(
                        _best_tf, _micro_dir, _best_str, _best_reason))
                    if _best_tf is not None and _micro_dir is not None:
                        direction = _micro_dir   # sekunde inaamua direction
                        timeframe = _best_tf     # sekunde inaamua TF
                    else:
                        # Deriv FLAT - fallback: tumia MTF direction, keep existing timeframe
                        logging.info("Deriv FLAT for {} (sel_ handler) - falling back to MTF direction".format(pair))
                        # direction/timeframe already set from safe_generate_signal above
                except Exception as _de:
                    logging.warning("Deriv TF confirmation failed {}: {} - falling back to MTF".format(pair, _de))
                    # Deriv imeshindwa - fallback kwa MTF direction
            # ---------------------------------------------------------

        else:
            # Non-fresh check actions (flip/same) - always generate a fresh signal
            # instead of using cached/flipped direction. Every request gets real market data.
            sig2       = await safe_generate_signal(pair)
            direction  = sig2["direction"]
            timeframe  = sig2["timeframe"] if sig2["timeframe"] > 0 else sig["timeframe"]
            strength   = sig2["strength"]
            flip_count = 0
            sig        = sig2  # use fresh sig for display details

        # Save state with updated flip_count
        # entry_price was already captured at signal request time (above)
        is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS

        save_user_signal_state(user_id, pair, direction, timeframe, flip_count, entry_price=entry_price)
        # Record to signal history (fresh signals already recorded inside generate_signal)
        if check["action"] != "fresh":
            record_signal(pair, direction)

        ib    = direction == "BUY"
        img   = get_buy_image() if ib else get_sell_image()
        arrow = "Up 🟢" if ib else "Down 🔴"
        _str2 = sig.get("strength", 70)
        if isinstance(_str2, int) and _str2 > 100:
            _str2 = int(60 + (_str2 - 300) / 200 * 39)
        _str2 = max(60, min(99, int(_str2)))
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        await delete_last_signal(context.bot, chat, user_id)
        cap = "*{}* {}\n🕐 In *{}* min\n📊 Signal strength: {}%".format(pair, arrow, timeframe, _str2)
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
                        "✅ Win rate 90% - 98%\n"
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
        # -- Force pair bypass flat filter -------------------
        if text.startswith("/forcepair"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await update.message.reply_text(
                    "Usage:\n`/forcepair EURUSD OTC` - force one pair\n`/forcepair all` - force all pairs\n`/forcepair list` - show forced pairs",
                    parse_mode="Markdown"
                )
                return
            arg = parts[1].strip().upper()
            if arg == "LIST":
                if not _FORCE_PAIRS:
                    await update.message.reply_text("No forced pairs.")
                else:
                    await update.message.reply_text("Forced pairs:\n{}".format("\n".join(sorted(_FORCE_PAIRS))))
                return
            if arg == "ALL":
                _FORCE_PAIRS.clear()
                _FORCE_PAIRS.add("__ALL__")
                await update.message.reply_text("✅ ALL pairs forced - flat filter bypassed.")
                return
            # Match partial pair name
            matched = [p for p in ALL_PAIRS if arg in p.upper().replace("/","").replace(" ","")]
            if not matched:
                await update.message.reply_text("❌ No pair matched: {}".format(arg))
                return
            for p in matched:
                _FORCE_PAIRS.add(p)
            await update.message.reply_text("✅ Forced: {}".format(", ".join(matched)))
            return

        if text.startswith("/unforcepair"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2 or parts[1].strip().upper() == "ALL":
                _FORCE_PAIRS.clear()
                await update.message.reply_text("✅ All force overrides cleared.")
                return
            arg = parts[1].strip().upper()
            removed = [p for p in list(_FORCE_PAIRS) if arg in p.upper().replace("/","").replace(" ","")]
            for p in removed:
                _FORCE_PAIRS.discard(p)
            await update.message.reply_text("✅ Removed: {}".format(", ".join(removed) if removed else "none found"))
            return

        if text=="/nnstats":
            ns = nn_get_stats()
            if not ns["available"]:
                await update.message.reply_text(
                    "❌ *NN Unavailable*\n\n"
                    "scikit-learn/numpy not installed.\n"
                    "Run: `pip install scikit-learn numpy`",
                    parse_mode="Markdown"
                )
                return
            status = "✅ ACTIVE" if ns["global_ready"] else "⏳ Training..."
            acc_txt = "{:.1%}".format(ns["global_acc"]) if ns["global_ready"] else "N/A"
            flip_acc = "{:.1%}".format(ns["flip_acc"]) if ns["total_flips"] > 0 else "N/A"
            top_pairs_txt = ""
            for p, samp, acc in ns["top_pairs"]:
                top_pairs_txt += "  • {} - {} samples, {:.1%} acc\n".format(p, samp, acc)
            if not top_pairs_txt:
                top_pairs_txt = "  _Not enough data yet_\n"
            msg = (
                "🧠 *NEURAL NETWORK STATS*\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📡 Status: *{}*\n"
                "🎯 Global Accuracy: *{}*\n"
                "📦 Global Samples: *{}*\n"
                "🗂 Total Samples: *{}*\n"
                "🔄 Last Retrain: *{}*\n"
                "⏭ Next Retrain: every *{}h*\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📈 *Per-Pair Models:* {}\n"
                "{}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "↩️ Direction Flips: *{}*\n"
                "✅ Flip Accuracy: *{}*"
            ).format(
                status, acc_txt,
                ns["global_samples"], ns["total_samples"],
                ns["last_retrain"], ns["next_retrain_hours"],
                ns["pairs_trained"], top_pairs_txt,
                ns["total_flips"], flip_acc
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        # -- G: Force NN retrain ------------------------------
        if text=="/nnretrain":
            if not _NN_AVAILABLE:
                await update.message.reply_text("❌ NN unavailable - scikit-learn not installed.")
                return
            await update.message.reply_text("🔄 *NN Retrain* started...", parse_mode="Markdown")
            try:
                _nn_retrain_global(force=True)
                for pair in list(_nn_pair_data.keys()):
                    if len(_nn_pair_data[pair]) >= _NN_MIN_PAIR_SAMPLES:
                        _nn_retrain_pair(pair)
                ns = nn_get_stats()
                acc_txt = "{:.1%}".format(ns["global_acc"]) if ns["global_ready"] else "N/A"
                await update.message.reply_text(
                    "✅ *NN Retrain Complete*\n\n"
                    "🎯 Global Accuracy: *{}*\n"
                    "📦 Global Samples: *{}*\n"
                    "📈 Pair Models: *{}*".format(
                        acc_txt, ns["global_samples"], ns["pairs_trained"]
                    ),
                    parse_mode="Markdown"
                )
            except Exception as _e:
                await update.message.reply_text("❌ Retrain failed: {}".format(_e))
            return

        # -- H: Pair performance report -----------------------
        if text=="/pairreport":
            await update.message.reply_text("📊 *Generating pair report...*", parse_mode="Markdown")
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT
                                ps.pair,
                                ps.wins,
                                ps.losses,
                                ps.consecutive_losses,
                                COALESCE(ps.optimal_tf, 2)  AS optimal_tf,
                                COALESCE(ps.avg_movement, 0) AS avg_movement,
                                ROUND(ps.wins::numeric / NULLIF(ps.wins+ps.losses,0)*100,1) AS win_rate,
                                (
                                    SELECT tss.session
                                    FROM tf_session_stats tss
                                    WHERE tss.pair = ps.pair
                                    ORDER BY ROUND(tss.wins::numeric/NULLIF(tss.wins+tss.losses,0)*100,1) DESC
                                    LIMIT 1
                                ) AS best_session,
                                (
                                    SELECT tss.tf_mins
                                    FROM tf_session_stats tss
                                    WHERE tss.pair = ps.pair
                                    ORDER BY ROUND(tss.wins::numeric/NULLIF(tss.wins+tss.losses,0)*100,1) DESC
                                    LIMIT 1
                                ) AS best_tf
                            FROM pair_stats ps
                            WHERE (ps.wins + ps.losses) >= 3
                            ORDER BY win_rate DESC
                            LIMIT 20
                        """)
                        rows = cur.fetchall()

                if not rows:
                    await update.message.reply_text("📭 No pair data yet - need at least 3 trades per pair.")
                    return

                lines = ["📊 *PAIR PERFORMANCE REPORT*\n━━━━━━━━━━━━━━━━━━"]
                for i, r in enumerate(rows, 1):
                    total   = (r["wins"] or 0) + (r["losses"] or 0)
                    wr      = float(r["win_rate"] or 0)
                    emoji   = "🟢" if wr >= 60 else ("🟡" if wr >= 50 else "🔴")
                    # NN per-pair accuracy
                    nn_e    = _nn_per_pair.get(r["pair"])
                    nn_acc  = " | 🧠{:.0%}".format(nn_e["acc"]) if nn_e and nn_e.get("acc") else ""
                    best_s  = r["best_session"] or "-"
                    best_tf = "{}m".format(r["best_tf"]) if r["best_tf"] else "{}m".format(r["optimal_tf"])
                    lines.append(
                        "{} *{}* {}\n"
                        "   W:{} L:{} | WR: *{:.1f}%*{}\n"
                        "   Best: {} | TF: {}".format(
                            emoji, r["pair"], "(⚠️ {}L)" .format(r["consecutive_losses"]) if (r["consecutive_losses"] or 0) >= 2 else "",
                            r["wins"], r["losses"], wr, nn_acc,
                            best_s, best_tf
                        )
                    )

                lines.append("━━━━━━━━━━━━━━━━━━")
                lines.append("Total pairs tracked: *{}*".format(len(rows)))

                # Split into chunks if too long (Telegram 4096 char limit)
                full_msg  = "\n".join(lines)
                chunk_size = 3800
                for i in range(0, len(full_msg), chunk_size):
                    await update.message.reply_text(
                        full_msg[i:i+chunk_size], parse_mode="Markdown"
                    )
            except Exception as _e:
                logging.warning("pairreport failed: {}".format(_e))
                await update.message.reply_text("❌ pairreport error: {}".format(_e))
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
                "📊 *EVALON WINNERS BOT - STATS*\n\n"
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
            broadcast_text = "📢 *EVALON WINNERS BOT*\n\n" + msg
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
                msg += "• `{}` - {}\n".format(b["user_id"], b.get("reason",""))
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
                exp = get_expiry_text(target_id) if u.get("licensed") else "-"
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
                msg = "📊 *PAIR STATS - Today ({})*\n\n".format(_dt.utcnow().strftime("%d %b %Y"))
                for r in today_stats:
                    total = (r["wins"] or 0) + (r["losses"] or 0)
                    rate  = int((r["wins"] or 0) / max(total, 1) * 100)
                    bar   = "🟢" * (rate // 20) + "🔴" * (5 - rate // 20)
                    msg  += "{} *{}*\n  ✅ {} | ❌ {} | {}%\n\n".format(bar, r["pair"], r["wins"] or 0, r["losses"] or 0, rate)
            await update.message.reply_text(msg[:4000], parse_mode="Markdown")
            return



        if text == "/toggleotc":
            current = is_otc_enabled()
            new_state = not current
            set_otc_enabled(new_state)
            if new_state:
                await update.message.reply_text(
                    "✅ *OTC Pairs: ON*\n\n"
                    "All pairs are now visible - OTC and non-OTC.\n\n"
                    "_Use /toggleotc again to disable OTC._",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "🔴 *OTC Pairs: OFF*\n\n"
                    "Users will see *non-OTC pairs only* now.\n"
                    "OTC pairs are hidden from the keyboard.\n\n"
                    "_Use /toggleotc again to enable OTC._",
                    parse_mode="Markdown"
                )
            return

        # -- FILTER CONTROL COMMANDS --------------------------
        if text == "/filterstatus":
            await update.message.reply_text(
                "🎛 *SIGNAL FILTERS STATUS*\n\n"
                "{}\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Disable: `/filteroff news` or `/filteroff all`\n"
                "Enable: `/filteron news` or `/filteron all`".format(get_filters_status()),
                parse_mode="Markdown"
            )
            return

        if text.startswith("/filteroff"):
            parts = text.split(maxsplit=1)
            arg = parts[1].strip().lower() if len(parts) > 1 else ""
            if not arg:
                await update.message.reply_text(
                    "Usage: `/filteroff [name|all]`\n\n"
                    "Names: `news` `dead` `conflict` `stability` `confluence` `h1confirm`\n"
                    "Or: `/filteroff all` - disable all",
                    parse_mode="Markdown"
                )
                return
            if arg == "all":
                for k in _FILTER_FLAGS:
                    _FILTER_FLAGS[k] = False
                await update.message.reply_text(
                    "🔴 *All filters disabled*\n\nBot will always produce a signal without blocking.",
                    parse_mode="Markdown"
                )
            elif arg in _FILTER_FLAGS:
                _FILTER_FLAGS[arg] = False
                await update.message.reply_text(
                    "🔴 *Filter disabled:* `{}`\n\n{}".format(arg, get_filters_status()),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "❌ Unknown filter: `{}`\n\nValid names: `news` `dead` `conflict` `stability` `confluence` `h1confirm`".format(arg),
                    parse_mode="Markdown"
                )
            return

        if text.startswith("/filteron"):
            parts = text.split(maxsplit=1)
            arg = parts[1].strip().lower() if len(parts) > 1 else ""
            if not arg:
                await update.message.reply_text(
                    "Usage: `/filteron [name|all]`\n\n"
                    "Names: `news` `dead` `conflict` `stability` `confluence` `h1confirm`\n"
                    "Or: `/filteron all` - enable all",
                    parse_mode="Markdown"
                )
                return
            if arg == "all":
                for k in _FILTER_FLAGS:
                    _FILTER_FLAGS[k] = True
                await update.message.reply_text(
                    "✅ *All filters enabled*\n\n{}".format(get_filters_status()),
                    parse_mode="Markdown"
                )
            elif arg in _FILTER_FLAGS:
                _FILTER_FLAGS[arg] = True
                await update.message.reply_text(
                    "✅ *Filter enabled:* `{}`\n\n{}".format(arg, get_filters_status()),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "❌ Unknown filter: `{}`\n\nValid names: `news` `dead` `conflict` `stability` `confluence` `h1confirm`".format(arg),
                    parse_mode="Markdown"
                )
            return
        # -----------------------------------------------------

    # /refer command - user yeyote
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
            "_Share your link - invite 3+ people and get free bonus signals!_".format(ref_link, refs, status),
            parse_mode="Markdown"
        )
        return

    # -- Reply Keyboard Button Handlers ------------------------
    # Delete the user's keyboard message immediately to keep chat clean
    try:
        await update.message.delete()
    except Exception:
        pass

    if text in ("/start", "🔄 Restart"):
        await start(update, context)
        return
    if text == "🏆 EVALON MENU 🏆":
        user  = get_user(user_id)
        lic   = is_licensed(user_id)
        plan  = user.get("licence_type", "").capitalize() if lic else "Free"

        # Use pairs_keyboard() - already handles weekday/weekend + priority sorting
        kb = pairs_keyboard()

        # Append option buttons at the bottom
        rows = list(kb.inline_keyboard)
        rows.append([InlineKeyboardButton("🤖 Bot Pick Pair", callback_data="bot_pick_pair")])
        rows.append([InlineKeyboardButton("📊 My Stats",      callback_data="my_stats")])
        if not lic:
            rows.append([InlineKeyboardButton("💎 Upgrade / Licence", callback_data="pay_info")])
        rows.append([InlineKeyboardButton("ℹ️ Help",          callback_data="help_inline")])

        await update.message.reply_text(
            "⚡ *EVALON WINNERS BOT*\n\n"
            "👤 Plan: *{}*\n\n"
            "📊 Select your trading pair:".format(plan),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows)
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
            lines = ["📊 *VTE Win Rate Stats - Forex Pairs*\n"]
            for r in rows:
                tag = ""
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
                "✅ *Licence Activated!*\n\n🎉 Welcome to EVALON WINNERS BOT!\n🏆 Win Rate: 90% - 98%\n🔑 Type: *{}*\n⏳ {}\n\nYou can now use unlimited signals!".format(tl,exp),
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

# _virtual_trades - DB is source of truth, in-memory dict is runtime cache only
_virtual_trades: dict = {}

def _vt_add_trade(pair, entry_price, direction, expiry, tf_secs, nn_feat=None):
    """Save virtual trade to DB and in-memory cache."""
    nn_bytes = None
    if nn_feat is not None and _NN_AVAILABLE:
        try:
            import pickle as _pk
            nn_bytes = _pk.dumps(nn_feat)
        except Exception:
            pass
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO virtual_trades (pair, entry_price, direction, expiry, tf_secs, nn_feat) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (pair, entry_price, direction, expiry, tf_secs, nn_bytes)
                )
            conn.commit()
    except Exception as e:
        logging.warning("_vt_add_trade DB failed {}: {}".format(pair, e))
    # also keep in memory for speed
    if pair not in _virtual_trades:
        _virtual_trades[pair] = []
    _virtual_trades[pair].append((entry_price, direction, expiry, tf_secs, nn_feat))

def _vt_load_pending():
    """Load all pending (unexpired) virtual trades from DB into memory on startup."""
    now = time.time()
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, pair, entry_price, direction, expiry, tf_secs, nn_feat "
                    "FROM virtual_trades WHERE expiry > %s",
                    (now,)
                )
                rows = cur.fetchall()
        for row in rows:
            pair = row["pair"]
            nn_feat = None
            if row["nn_feat"] and _NN_AVAILABLE:
                try:
                    import pickle as _pk
                    nn_feat = _pk.loads(row["nn_feat"])
                except Exception:
                    pass
            if pair not in _virtual_trades:
                _virtual_trades[pair] = []
            _virtual_trades[pair].append((
                row["entry_price"], row["direction"],
                row["expiry"], row["tf_secs"], nn_feat
            ))
        logging.info("VTE: loaded {} pending trades from DB".format(len(rows)))
    except Exception as e:
        logging.warning("_vt_load_pending failed: {}".format(e))

def _vt_delete_trade(pair, entry_price, direction, expiry, tf_secs):
    """Remove a completed trade from DB."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM virtual_trades WHERE pair=%s AND entry_price=%s "
                    "AND direction=%s AND expiry=%s AND tf_secs=%s",
                    (pair, entry_price, direction, expiry, tf_secs)
                )
            conn.commit()
    except Exception as e:
        logging.warning("_vt_delete_trade failed {}: {}".format(pair, e))

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
    Used to detect flat markets - does NOT block user signals.
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
            sig = await safe_generate_signal(pair)  # timeout-safe
            direction = sig["direction"]

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

            # Carry real NN features from signal so VTE result can feed NN accurately
            nn_feat = sig.get("_nn_feat_arr")

            # Place one trade per timeframe
            for tf_secs in VIRTUAL_TF_SECONDS:
                expiry = now + tf_secs
                _vt_add_trade(pair, price, direction, expiry, tf_secs, nn_feat)

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
        for trade in _virtual_trades[pair]:
            if len(trade) == 5:
                entry_price, direction, expiry, tf_secs, nn_feat = trade
            else:
                entry_price, direction, expiry, tf_secs = trade
                nn_feat = None

            if now < expiry:
                remaining.append(trade)
                continue

            # Trade expired - delete from DB
            _vt_delete_trade(pair, entry_price, direction, expiry, tf_secs)

            exit_price = _fetch_current_price(pair)
            if exit_price is None or entry_price is None:
                continue

            raw_diff = exit_price - entry_price
            movement_pct = abs(raw_diff) / (entry_price + 1e-9) * 100

            # ATR flat-market filter - skip recording, but signal still reached user
            atr_pct = _vt_calc_atr(pair)
            if atr_pct is not None and movement_pct < (atr_pct * 0.30):
                logging.info("VTE FLAT SKIP: {} move={:.5f}% < 30% of ATR {:.5f}%".format(
                    pair, movement_pct, atr_pct))
                continue   # Skip - flat market, don't corrupt stats

            won = (raw_diff > 0) if direction == "BUY" else (raw_diff < 0)

            # -- Feed NN with REAL features from signal time --
            if _NN_AVAILABLE and nn_feat is not None:
                try:
                    _nn_record_outcome(pair, nn_feat, won)
                except Exception as _nn_e:
                    logging.warning("VTE→NN feed failed {}: {}".format(pair, _nn_e))
            # -------------------------------------------------

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
                logging.info("VTE: cycle {} - {} active trades".format(cycle, active))
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


# -- NEWS FILTER ---------------------------------------------
# High-impact news events (UTC times, approximate)
# These repeat weekly/monthly - bot avoids signals ±15 min around them

_HIGH_IMPACT_NEWS = [
    # (weekday, hour, minute, description)
    # weekday: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    (4, 13, 30, "NFP"),           # First Friday of month ~13:30 UTC
    (4, 13, 30, "US Jobs"),
    (1, 13, 30, "CPI"),           # Varies but often Tue/Wed
    (2, 13, 30, "CPI"),
    (2, 18, 0,  "FOMC"),          # Fed meetings - Wednesdays ~18:00 UTC
    (3, 12, 0,  "ECB"),           # ECB - Thursdays ~12:00 UTC
    (3, 13, 30, "US GDP"),
    (3, 13, 30, "Unemployment"),
    (4, 13, 30, "PCE"),
]

_NEWS_BUFFER_MINUTES = 15  # avoid signals ±15 min around news
_NEWS_POST_BUFFER    = 5   # extra wait minutes AFTER news passes

def is_news_time():
    """
    Returns (True, event_name) if within NEWS_BUFFER_MINUTES before
    or NEWS_POST_BUFFER minutes after a high-impact event.
    """
    try:
        now_utc  = datetime.utcnow()
        wd       = now_utc.weekday()
        now_mins = now_utc.hour * 60 + now_utc.minute
        for (event_wd, event_h, event_m, name) in _HIGH_IMPACT_NEWS:
            if wd != event_wd:
                continue
            event_mins = event_h * 60 + event_m
            diff = now_mins - event_mins  # positive = after event
            # Block before event (±NEWS_BUFFER_MINUTES) AND up to POST_BUFFER after
            if -_NEWS_BUFFER_MINUTES <= diff <= _NEWS_POST_BUFFER:
                if diff > 0:
                    return True, "{} (cooling down - {}m after)".format(name, diff)
                return True, name
    except Exception:
        pass
    return False, None


def get_best_tf_for_session(pair):
    """
    Pick best TF (1m/2m/3m) for a pair using 3 data sources:
    1. signal_outcomes historical win rate + movement per TF (highest weight - real outcomes)
    2. tf_session_stats session-specific win rate + movement
    3. pair_stats.optimal_tf fallback

    Scoring: win_rate(60%) + normalized_movement(25%) + sample_confidence(15%)
    Falls back to 2m default if no data.
    """
    session = get_trading_session()
    sess_name = session.get("name", "Unknown") if session else "Unknown"
    target_tfs = [1, 2, 3]

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # -- Source 1: signal_outcomes - most accurate (real trade outcomes) --
                cur.execute("""
                    SELECT tf_used AS tf_mins,
                           COUNT(*) FILTER (WHERE won=TRUE)::float / NULLIF(COUNT(*), 0) AS win_rate,
                           COUNT(*) AS total,
                           AVG(movement_pct) AS avg_movement,
                           AVG(movement_pct) FILTER (WHERE won=TRUE) AS avg_win_movement
                    FROM signal_outcomes
                    WHERE pair = %s
                      AND tf_used = ANY(%s)
                      AND created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY tf_used
                    HAVING COUNT(*) >= 5
                    ORDER BY tf_used
                """, (pair, target_tfs))
                outcome_rows = {int(r["tf_mins"]): r for r in cur.fetchall()}

                # Also fetch session-specific from signal_outcomes
                cur.execute("""
                    SELECT tf_used AS tf_mins,
                           COUNT(*) FILTER (WHERE won=TRUE)::float / NULLIF(COUNT(*), 0) AS win_rate,
                           COUNT(*) AS total,
                           AVG(movement_pct) AS avg_movement
                    FROM signal_outcomes
                    WHERE pair = %s AND session = %s
                      AND tf_used = ANY(%s)
                      AND created_at >= NOW() - INTERVAL '14 days'
                    GROUP BY tf_used
                    HAVING COUNT(*) >= 3
                """, (pair, sess_name, target_tfs))
                session_outcome_rows = {int(r["tf_mins"]): r for r in cur.fetchall()}

                # -- Source 2: tf_session_stats --
                cur.execute("""
                    SELECT tf_mins,
                           COALESCE(wins::float / NULLIF(wins+losses,0), 0.0) AS win_rate,
                           COALESCE(avg_movement, 0.0) AS avg_movement,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND session = %s AND tf_mins = ANY(%s)
                      AND (wins + losses) >= 5
                """, (pair, sess_name, target_tfs))
                tf_rows = {int(r["tf_mins"]): r for r in cur.fetchall()}

                # -- Source 3: pair_stats.optimal_tf --
                cur.execute("SELECT optimal_tf FROM pair_stats WHERE pair=%s", (pair,))
                pair_row = cur.fetchone()
                pair_optimal = int(pair_row["optimal_tf"]) if pair_row and pair_row["optimal_tf"] else None

        # -- Scoring ----------------------------------------------
        tf_scores = {}
        for tf_m in target_tfs:
            score = 0.0
            has_data = False

            # Signal outcomes - overall (30d) - highest weight
            if tf_m in outcome_rows:
                r = outcome_rows[tf_m]
                wr  = float(r["win_rate"] or 0.5)
                mov = min(float(r["avg_movement"] or 0), 0.5) / 0.5
                total = int(r["total"])
                conf = min(1.0, total / 25.0)
                score += (wr * 0.60 + mov * 0.25 + conf * 0.15) * 2.5  # weight 2.5x
                has_data = True

            # Session outcomes (14d) - bonus if session-specific data available
            if tf_m in session_outcome_rows:
                r = session_outcome_rows[tf_m]
                wr  = float(r["win_rate"] or 0.5)
                mov = min(float(r["avg_movement"] or 0), 0.5) / 0.5
                total = int(r["total"])
                conf = min(1.0, total / 15.0)
                score += (wr * 0.65 + mov * 0.20 + conf * 0.15) * 1.5  # weight 1.5x
                has_data = True

            # tf_session_stats fallback
            if tf_m in tf_rows:
                r = tf_rows[tf_m]
                wr  = float(r["win_rate"])
                mov = min(float(r["avg_movement"]), 0.5) / 0.5
                total = int(r["total"])
                conf = min(1.0, total / 20.0)
                score += (wr * 0.60 + mov * 0.25 + conf * 0.15) * 1.0  # weight 1.0x
                has_data = True

            if has_data:
                tf_scores[tf_m] = score

        if tf_scores:
            best_tf = max(tf_scores, key=tf_scores.get)
            logging.info("TF select {}: scores={} → {}m".format(pair, tf_scores, best_tf))
            return best_tf

        # Fallback: pair_stats.optimal_tf
        if pair_optimal and pair_optimal in target_tfs:
            return pair_optimal

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
    Return all forex pairs ranked by VTE win rate (ascending - worst first).
    Only pairs in YAHOO_SYMBOLS with "/" in name (forex only, no BTC/indices).
    Splits into two groups:
      - Group B (normal):     higher win rate pairs
    Returns: {
            "normal":     [pair, ...],   # rest - normal signal
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

    # Pairs not yet in DB go to the end (unknown - treat as normal)
    ranked_set = set(ranked)
    unranked = [p for p in forex_pairs if p not in ranked_set]
    all_pairs = ranked + unranked

    normal     = all_pairs[3:]    # rest → normal signal

    return {"normal": normal, "all": all_pairs}


def get_worst5_pairs():
    """Return 5 worst forex pairs by VTE winrate (lowest first)."""
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

def _quick_pair_quality_check(pair):
    """
    Fast pre-screen before showing pair to user in Bot Pick.
    Checks:
      1. ATR volatility - pair must not be dead market
      2. MTF agreement - at least partial agreement across timeframes
      3. NN confidence - if model ready, confidence must be >= 55%
    Returns (passes: bool, reason: str)
    """
    # OTC pairs - skip heavy checks (no Yahoo data), use NN only
    is_otc = "OTC" in pair
    if not is_otc:
        # D: Volatility check
        try:
            atr_pct, is_dead = _check_volatility(pair)
            if is_dead:
                return False, "flat"
        except Exception:
            pass

        # Quick MTF check - fetch 5m direction only
        try:
            real_pair = OTC_TO_REAL.get(pair, pair)
            symbol    = YAHOO_SYMBOLS.get(real_pair)
            if symbol:
                df = yf.download(symbol, period="1d", interval="5m",
                                 progress=False, auto_adjust=True)
                if df is not None and len(df) >= 35:
                    direction_5m = _mtf_calc_direction(df)
                    if direction_5m is None:
                        return False, "no_direction"
        except Exception:
            pass

    # NN confidence check (if model ready)
    if _NN_AVAILABLE and _nn_global_model is not None:
        try:
            # Build minimal feature array for quick check
            # Use neutral features - just check if NN thinks pair is tradeable
            pair_entry = _nn_per_pair.get(pair)
            if pair_entry and pair_entry.get("samples", 0) >= _NN_MIN_PAIR_SAMPLES:
                # Pair has its own model - check its accuracy
                if pair_entry.get("acc", 1.0) < 0.50:
                    return False, "nn_low_acc"
        except Exception:
            pass

    return True, "ok"


def get_top5_pairs(otc_only=False, non_otc_only=False):
    """
    Return top 5 pairs by win rate with quality screening:
    - Must not be flat/dead market (ATR check)
    - Must have clear MTF direction
    - NN model accuracy must be acceptable
    Only returns pairs that exist in ALL_PAIRS.
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

        # -- Quality screening - remove flat/dead/low-quality pairs --
        screened = []
        skipped  = 0
        for r in rows:
            if len(screened) >= 5:
                break
            passes, reason = _quick_pair_quality_check(r["pair"])
            if passes:
                screened.append(r)
            else:
                skipped += 1
                logging.info("Bot Pick screening: {} skipped - {}".format(r["pair"], reason))

        # If screening removed too many, fill from broader pool without quality filter
        if len(screened) < 5:
            already = {r["pair"] for r in screened}
            # Non-OTC fallback: priority pairs first, then exotics
            _PRIORITY_NONOTC = [
                "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD",
                "NZD/USD", "USD/CAD", "EUR/GBP", "EUR/JPY", "EUR/AUD",
                "EUR/CAD", "EUR/CHF", "GBP/JPY", "GBP/AUD", "GBP/CAD",
                "GBP/CHF", "AUD/JPY", "AUD/CAD", "AUD/CHF", "CHF/JPY",
                "CAD/JPY", "CAD/CHF", "USD/MXN",
                "US100", "SP500", "US30", "GER40", "UK100",
            ]
            if otc_only:
                fallback_pool = [p for p in ALL_PAIRS if "OTC" in p and p not in already]
            elif non_otc_only:
                # Priority pairs first, then remaining non-OTC
                fallback_pool = (
                    [p for p in _PRIORITY_NONOTC if p not in already] +
                    [p for p in ALL_PAIRS if "OTC" not in p and "/" in p
                     and p not in already and p not in _PRIORITY_NONOTC]
                )
            else:
                fallback_pool = [p for p in ALL_PAIRS if p not in already]
            # No shuffle for non-OTC - keep priority order
            if not non_otc_only:
                random.shuffle(fallback_pool)
            for p in fallback_pool:
                if len(screened) >= 5:
                    break
                # Only light check for fallback (no heavy MTF)
                _, is_dead = _check_volatility(p) if "OTC" not in p else (0.05, False)
                if not is_dead:
                    screened.append({"pair": p, "wins": 0, "losses": 0, "win_rate": 0})

        if skipped > 0:
            logging.info("Bot Pick: screened {} pairs, skipped {} flat/low-quality".format(
                len(screened), skipped))

        return screened[:5]
    except Exception as e:
        logging.warning("get_top5_pairs failed: {}".format(e))
        return []





# ============================================================
# -- H: LICENCE EXPIRY WARNING LOOP --------------------------
async def _licence_expiry_warning_loop(bot):
    """
    Runs every 12 hours. Sends warning to users whose licence
    expires in exactly 3 days or 1 day. Sent once per threshold.
    """
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT user_id, expiry
                        FROM users
                        WHERE licence_type IN ('monthly','lifetime')
                          AND expiry IS NOT NULL
                          AND expiry > NOW()
                          AND expiry <= NOW() + INTERVAL '4 days'
                    """)
                    rows = cur.fetchall()
            for r in rows:
                uid    = r["user_id"]
                expiry = r["expiry"]
                days   = (expiry - datetime.now()).days
                if days not in (3, 1):
                    continue
                emoji = "⚠️" if days == 3 else "🚨"
                try:
                    await bot.send_message(
                        chat_id=uid,
                        text=(
                            "{} *Licence Expiry Reminder*\n\n"
                            "Your subscription expires in *{} day{}*.\n"
                            "Renew now to keep receiving signals uninterrupted."
                        ).format(emoji, days, "s" if days > 1 else ""),
                        parse_mode="Markdown"
                    )
                    logging.info("Expiry warning sent to user={} days={}".format(uid, days))
                except Exception as _e:
                    logging.warning("Expiry warning failed user={}: {}".format(uid, _e))
        except Exception as e:
            logging.warning("_licence_expiry_warning_loop error: {}".format(e))
# -------------------------------------------------------------


async def _stats_reset_loop():
    """Reset wins_today/losses_today once per day at midnight UTC."""
    while True:
        # Calculate seconds until next midnight UTC
        now = datetime.utcnow()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        secs_until_midnight = (midnight - now).total_seconds()
        await asyncio.sleep(secs_until_midnight)
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE pair_stats SET wins_today = 0, losses_today = 0"
                    )
                conn.commit()
            logging.info("Pair stats daily reset (midnight UTC): OK")
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

    # -- Use async polling (works inside asyncio.run) --
    print("Starting bot polling...")
    await ptb_app.start()
    await ptb_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    print("Bot polling active.")

    # -- Load pending virtual trades from DB (survive restarts) -
    _vt_load_pending()
    print("Virtual trades loaded from DB.")

    # -- Launch Virtual Trading Engine in background ------------
    asyncio.create_task(virtual_trading_engine())
    print("Virtual trading engine started.")

    # -- Launch stats reset loop (every 30 minutes) -------------
    asyncio.create_task(_stats_reset_loop())
    print("Stats reset loop started.")

    # -- Launch NN scheduled retrain loop (every 6 hours) -------
    if _NN_AVAILABLE:
        asyncio.create_task(_nn_scheduled_retrain_loop())
        print("NN scheduled retrain loop started.")

    # -- Launch licence expiry warning loop (every 12 hours) ----
    asyncio.create_task(_licence_expiry_warning_loop(ptb_app.bot))
    print("Licence expiry warning loop started.")

    # Keepalive
    while True:
        await asyncio.sleep(60)


def main():
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    # -- Open port FIRST before anything else -------------------
    # Render requires port to open within a few seconds of startup
    PORT = int(os.environ.get("PORT", 8080))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"EVALON WINNERS BOT OK")
        def log_message(self, *args):
            pass

    def start_health_server():
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        server.serve_forever()

    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()
    print("Port {} open. Starting bot...".format(PORT))

    # -- Now proceed with init and bot startup ------------------
    print("EVALON WINNERS BOT starting...")
    init_db()
    print("Database ready.")
    asyncio.run(run_bot())

if __name__=="__main__":
    main()

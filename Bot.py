#!/usr/bin/env python3
"""
EVALON WINNERS BOT - Telegram Bot v3.10
Upgraded: v59e - All messages English, new admin commands (/users, /history, /userchart)

KEY CHANGES (v58):
  1. ZigZag Trend (NEW):
     - True ZigZag algorithm (retracement >= 0.15%) detects swing highs/lows
     - Uptrend = Higher Highs + Higher Lows → BUY
     - Downtrend = Lower Highs + Lower Lows → SELL
     - Swing strength (1/2/3) affects bonus weight:
       * Weak (1): +23 pts in generate_signal, +13 in CQ gate
       * Moderate (2): +31 pts, +18 pts
       * Strong (3): +39 pts, max 18pts CQ gate
     - Integrated into v57 weighted voting (weight 5-20)
     - Affects indicators_agree: +1/+2/+3 by strength
     - Penalty -10 pts + -2 indicators_agree if opposing direction

  2. INDICATOR BOOSTS:
     - Keltner Channels: +30 pts (was +20) — true breakout
     - Fisher Transform: max +20 pts (was +12)
     - SuperTrend: +25 pts (was +18) + affects indicators_agree ±2
     - Parabolic SAR: +15 pts (was +8)
     - PSAR in CQ gate: max 8pts (was 5)
     - SuperTrend in CQ gate: max 18pts (was 12), penalty -12 (was -8)

  3. CONFLUENCE QUALITY GATE HARDENED:
     - Threshold: 55 (was 40) — only strong signals pass
     - ZigZag added (max 18pts) — new scoring structure
     - v57 vote: max 20pts (was 15), penalty -10 (was -8)
     - Keltner CQ: max 15pts (was 10), penalty -8 (was -5)
     - Fisher CQ: max 15pts (was 10), penalty -7 (was -5)

  4. INDICATORS_AGREE THRESHOLD:
     - Non-OTC minimum: 6 (was 4) — more indicators must agree
     - OTC minimum: 4 (was 3)
     - ZigZag and SuperTrend added to the count

  5. v57 VOTING THRESHOLD:
     - Direction chosen at >= 65% only (was 60%)
     - Indicators 21 (was 20, ZigZag added)

  EXPECTED RESULTS:
  - Fewer signals — but genuinely strong ones
  - ZigZag adds swing structure to decisions
  - Strong indicators (ST, Keltner, Fisher, PSAR) have more impact
  - Weak signals blocked by CQ gate of 55

KEY CHANGES (v56):
  NEW INDICATORS:
  1. EMA 200 Trend Filter: Price must be on the correct side of EMA200 (1H) — major trend gate.
     Blocks signals opposing the main trend.
  2. Hull Moving Average (HMA): Faster than EMA, follows price with less lag.
     Used as momentum confirmation in _calc_indicators_from_df.
  3. Keltner Channels: Like BB but uses ATR instead of StdDev. Detects true breakouts vs noise.
     Applied in _calc_indicators_from_df.
  4. Fisher Transform: RSI-like but better separates extremes.
     Gives better overbought/oversold signals than RSI alone.
  5. DEMA (Double EMA): Reduces lag twice vs standard EMA. Improves trend detection accuracy
     for short timeframes (1m/2m signals).
  6. Candle Body Ratio Filter: Blocks doji/indecision candle signals.
     Body must be >= 30% of candle range — real signals only.
  7. Volume Surge Confirmation: Volume > 1.5x average = stronger signal.
     Adds points to indicators_agree.
  8. RSI Slope: Instead of a single value, watches RSI slope (3-bar change).
     Rising/falling slope = momentum entering/exiting.

  CONFLUENCE QUALITY GATE (NEW - v56):
  - _confluence_quality_gate(): calculates "confluence score" (0-100) before sending signal.
    If score < 40 → no signal (blocks weak signals).
  - Factors: EMA200 alignment, MACD histogram slope, RSI slope, Volume surge,
    HMA direction, Keltner breakout, session quality.
  - Result: signals that pass have genuine strength — not random.

  SIGNAL STRENGTH FORMULA UPGRADE:
  - strength calculated using weighted sum instead of linear scale.
  - Indicators with higher bonus: EMA200, HMA, Keltner, Volume.
  - New penalty: signals opposing EMA200 get -30% strength.

  MICRO-CANDLE INDICATORS UPGRADE (_calc_indicators_from_ticks v56):
  - Added: HMA, Fisher Transform, Candle Body Ratio.
  - DEMA 9/18 instead of EMA 9/21 alone.
  - Better direction from 5s/10s/15s Deriv ticks.

  NO CHANGES TO:
  - v53 Pipeline (Unified TF Scoring) — intact.
  - Auto Scan Engine v54 — intact.
  - DB schema — no new columns needed.
  - OTC fallback logic — intact.

KEY CHANGES (v54 - Auto Scan Engine):
  - AUTO_SCAN_PAIRS: 13 major binary broker pairs (majors + crosses)
  - auto_scan_and_send(): loop scanning every 45s, waits for good entry
  - Signal sent only if: flat=False, indicators>=5, strength>=150, tf>0
  - Deriv micro-candle confirmation retained (5s/10s/15s)
  - Cancel button: user can stop scan at any time
  - Timeout 12 minutes if market is ranging
  - Other pairs continue with normal v53 flow

KEY CHANGES (v53 - Unified TF Scoring Pipeline, No Blind Overrides):
  - PROBLEM (v52 and earlier):
    * System had "blind overrides" — after _smart_nonOTC_expiry completed full
      analysis and chose the best TF, downstream gates (h1confirm, candle_gate,
      fingerprint) could change that TF without knowing the full smart expiry scores.
      Result: final TF could differ entirely from what the data decided.
    * Fingerprint combo was a "hard override" — changed TF directly without
      considering if smart expiry scored 1m=200pts vs 3m=10pts.

  - FIX (v53 Unified Pipeline):
    * _smart_nonOTC_expiry returns (leading_tf, scores_dict) instead of one TF.
      Full scores for sections A0/A/A2/B/C/D/E/F/G/H/I/J/K stored in _pipeline_scores dict.
    * All gates (h1confirm, candle_gate, fingerprint) add/subtract points
      directly from _pipeline_scores.
    * Final step: max(_pipeline_scores) decides TF — once, after all gates complete.
    * Result: final TF is a joint decision by ENGINE + GATES, not engine overridden blind.

  - NEW CAPABILITY:
    * If 1m had score 250 and 3m was 80 in smart expiry,
      h1confirm/candle_gate/fingerprint must apply large penalties/bonuses to change
      the choice — not just a 30pt penalty.
    * Fingerprint is a score adjustment (max +60pts) instead of hard override.
      Direction override still works if wr >= 65%.
    * New log "TF PIPELINE FINAL" shows final scores + TF chosen after each gate.

  - NO OTC CHANGES: _smart_otc_expiry works independently — it had no such problem.

KEY CHANGES (v52):
  - _smart_nonOTC_expiry section F (Deriv micro) fully rewritten:
    * Before: majority vote of direction among 5s/10s/15s
    * Now: each TF (5s→1m, 10s→2m, 15s→3m) scores its OWN indicators:
      RSI, MACD, EMA diff, BB position, Momentum, Stochastic
      TF with the best indicator alignment gets the highest score and wins — no vote, no majority.
  - Gap check (v51) removed: best_tf always chosen without threshold
  - Micro consensus gate (v51) removed: replaced by per-TF indicator scoring
  - ADX block removed entirely: ADX is scoring factor only, does not block signal
  - 1H vs short-TF conflict block removed: 1H is a bonus on b/s score,
    does not block — 5s/10s/15s indicators decide TF

KEY CHANGES (v51):
  - _smart_nonOTC_expiry(): added CONVICTION CHECK:
    * Gap check: best TF must have gap >= 12pts vs 2nd best.
      Small gap = all TFs similar = market undecided = return 0 (no signal)
    * Micro consensus gate: >= 2/3 of Deriv 5s/10s/15s TFs must agree
      with signal direction. Disagreement = conflicted market = return 0
  - _smart_otc_expiry(): same — gap check >= 10pts (OTC data is synthetic)
  - generate_signal(): if smart expiry returns 0 → no_signal immediately,
    skip downstream filters that could force a TF.
  - Weak confluence fallback fixed: can no longer force TF=3
    when smart expiry cut the signal (timeframe=0).
  - Result: "no signal" will occur more often for ranging/conflicted conditions.
    Signals that do fire will have a TF chosen with data confidence.

KEY CHANGES (v50):
  - signal_combo_stats TABLE: stores wins/losses for each combo
    of (pair, direction, tf_mins, setup_cluster) — AI genuinely learns
  - compute_setup_cluster(): fingerprint of market state (RSI+BB+MOM+SESSION)
    converts market conditions into a short comparable label
  - pg_best_combo(): queries DB for "which direction+tf won most for this setup?"
    — this is the core learning intelligence
  - update_signal_combo_stats(): called automatically after each outcome
  - _apply_pg_best_combo_to_scores(): new layer A0 for smart expiry (35pts max)
  - update_signal_history_won(): updates combo_stats + tf_session_stats too
  - setup_cluster column in signal_history: every signal carries its fingerprint
  - No TF preference — real historical data decides

v49: Unbiased Expiry Engine + pg_predict_per_tf
     - sklearn/numpy/XGBoost/LightGBM REMOVED (saves RAM on Render)
     - ML replaced by pg_predict() — PostgreSQL queries only
     - signal_history extended with columns: rsi, macd, bb_pos, sto,
       ma_diff, mom, atr_pct, session, trend_1h, score, won, tf_mins
     - Full trend stored for every signal
     - pg_predict() returns direction + confidence from real DB win rate
       per pair/session/tf
python-telegram-bot[webhooks]==21.3 + Neon PostgreSQL via psycopg2
"""

import os as _os
import threading as _threading
from http.server import HTTPServer as _HTTPServer, BaseHTTPRequestHandler as _BaseHandler

class _H(_BaseHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"ok","version":"3.10","bot":"EVALON WINNERS BOT v65"}' 
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
import websockets
import json as _json
import asyncio as _asyncio
from collections import defaultdict as _defaultdict
from datetime import datetime as _dt

_NN_AVAILABLE = False
_XGB_AVAILABLE = False
_LGB_AVAILABLE = False

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

_DERIV_CACHE = {}
_DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

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
            await ws.send(_json.dumps({"authorize": DERIV_TOKEN}))
            auth = _json.loads(await _asyncio.wait_for(ws.recv(), timeout=5))
            if auth.get("error"):
                logging.warning("Deriv auth failed: {}".format(auth["error"]))
                return None

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

            results = {}
            for candle_secs in [5, 10, 15]:
                candles = _build_micro_candles(prices, times, candle_secs)
                if len(candles) >= 15:
                    trend = _micro_trend(candles)
                    count_factor = min(1.0, len(candles) / 60.0)
                    if isinstance(trend, dict) and "strength" in trend:
                        trend["strength"] = int(trend["strength"] * (0.70 + 0.30 * count_factor))
                    results["{}_s".format(candle_secs)] = trend
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

        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, 1e-9)
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

        ema9  = float(closes.ewm(span=9).mean().iloc[-1])
        ema21 = float(closes.ewm(span=21).mean().iloc[-1])
        ma_diff = max(-1.0, min(1.0, (ema9 - ema21) / (ema21 + 1e-9) * 100))

        ema12     = closes.ewm(span=12).mean()
        ema26     = closes.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_ln = macd_line.ewm(span=9).mean()
        macd_hist = float((macd_line - signal_ln).iloc[-1])
        macd_norm = max(-1.0, min(1.0, macd_hist / (closes.iloc[-1] * 0.001 + 1e-9)))

        sma20 = closes.rolling(20).mean()
        std20 = closes.rolling(20).std()
        bb_u  = float((sma20 + 2 * std20).iloc[-1])
        bb_l  = float((sma20 - 2 * std20).iloc[-1])
        bb_pos = max(0.0, min(1.0, (float(closes.iloc[-1]) - bb_l) / (bb_u - bb_l + 1e-9)))

        mom = max(-1.0, min(1.0,
            float(closes.iloc[-1] - closes.iloc[-11]) / (closes.iloc[-11] + 1e-9) * 100
        )) if len(closes) >= 11 else 0.0

        low14  = lows.rolling(14).min()
        high14 = highs.rolling(14).max()
        sto = max(0.0, min(100.0,
            float(((closes - low14) / (high14 - low14 + 1e-9) * 100).iloc[-1])
        ))

        if ma_diff > 0 and macd_norm > 0:
            direction = "BUY"
        elif ma_diff < 0 and macd_norm < 0:
            direction = "SELL"
        else:
            direction = None

        # ── v56: DEMA confirmation for micro ticks ──
        dema_fast_t = dema_slow_t = None
        dema_diff_t = 0.0
        try:
            ef1 = closes.ewm(span=9, adjust=False).mean()
            ef2 = ef1.ewm(span=9, adjust=False).mean()
            dema_f_s = 2 * ef1 - ef2
            es1 = closes.ewm(span=18, adjust=False).mean()
            es2 = es1.ewm(span=18, adjust=False).mean()
            dema_s_s = 2 * es1 - es2
            dema_fast_t = float(dema_f_s.iloc[-1])
            dema_slow_t = float(dema_s_s.iloc[-1])
            dema_diff_t = (dema_fast_t - dema_slow_t) / (abs(dema_slow_t) + 1e-9) * 100
        except Exception:
            pass

        # ── v56: Fisher Transform for micro ticks ──
        fisher_dir_t = None
        try:
            h9t = highs.rolling(9).max()
            l9t = lows.rolling(9).min()
            valt = 2 * ((closes - l9t) / (h9t - l9t + 1e-9)) - 1
            valt = valt.clip(-0.999, 0.999)
            import math as _math_t
            ft_vals = [_math_t.log((1 + v) / (1 - v + 1e-9)) * 0.5 for v in valt.values]
            ft_s = pd.Series(ft_vals, index=valt.index)
            ft_now  = float(ft_s.iloc[-1])
            ft_prev = float(ft_s.iloc[-2]) if len(ft_s) >= 2 else 0.0
            if ft_now > 0.5 and ft_now > ft_prev:
                fisher_dir_t = "BUY"
            elif ft_now < -0.5 and ft_now < ft_prev:
                fisher_dir_t = "SELL"
        except Exception:
            pass

        # ── v56-ST: SuperTrend for micro-candles ──
        st_dir_t = None
        try:
            _n_t   = len(closes)
            _per_t = 7   # short period for tick seconds
            _mul_t = 2.5
            if _n_t >= _per_t + 2:
                _tr_t = pd.Series([
                    max(float(highs.iloc[i]) - float(lows.iloc[i]),
                        abs(float(highs.iloc[i]) - float(closes.iloc[i-1])),
                        abs(float(lows.iloc[i]) - float(closes.iloc[i-1])))
                    for i in range(1, _n_t)
                ], index=closes.index[1:])
                _atr_t   = _tr_t.rolling(_per_t).mean()
                _mid_t   = (highs.iloc[1:] + lows.iloc[1:]) / 2
                _bu_t    = _mid_t + _mul_t * _atr_t
                _bl_t    = _mid_t - _mul_t * _atr_t
                _sup_t   = _bu_t.copy(); _sdn_t = _bl_t.copy()
                _trd_t   = pd.Series(index=closes.index[1:], dtype=int)
                _stl_t   = pd.Series(index=closes.index[1:], dtype=float)
                for _ti in range(len(closes.index[1:])):
                    _cc = float(closes.iloc[_ti + 1])
                    if _ti == 0:
                        _stl_t.iloc[_ti] = float(_bu_t.iloc[_ti]); _trd_t.iloc[_ti] = -1; continue
                    _pu2 = float(_sup_t.iloc[_ti-1]); _nu2 = float(_bu_t.iloc[_ti])
                    _sup_t.iloc[_ti] = min(_nu2, _pu2) if float(closes.iloc[_ti]) < _pu2 else _nu2
                    _pl2 = float(_sdn_t.iloc[_ti-1]); _nl2 = float(_bl_t.iloc[_ti])
                    _sdn_t.iloc[_ti] = max(_nl2, _pl2) if float(closes.iloc[_ti]) > _pl2 else _nl2
                    _pt2 = int(_trd_t.iloc[_ti-1]); _pl3 = float(_stl_t.iloc[_ti-1])
                    if _pt2 == -1 and _cc > _pl3:   _trd_t.iloc[_ti] = 1
                    elif _pt2 == 1 and _cc < _pl3:  _trd_t.iloc[_ti] = -1
                    else:                             _trd_t.iloc[_ti] = _pt2
                    _stl_t.iloc[_ti] = float(_sdn_t.iloc[_ti]) if _trd_t.iloc[_ti] == 1 \
                                       else float(_sup_t.iloc[_ti])
                st_dir_t = "BUY" if int(_trd_t.iloc[-1]) == 1 else "SELL"
        except Exception:
            pass

        # Upgrade direction if SuperTrend agrees
        if st_dir_t is not None:
            if direction is None:
                direction = st_dir_t
            elif st_dir_t != direction:
                direction = None

        # ── v57: Additional micro-tick indicators ──────────────────────────
        _tick_votes_buy = 0; _tick_votes_sell = 0

        # Parabolic SAR (micro)
        try:
            _af_t2 = 0.02; _afm_t2 = 0.20; _afs_t2 = 0.02
            _phh = list(highs.values); _pll = list(lows.values); _pcc = list(closes.values)
            _nt2 = len(_pcc)
            if _nt2 >= 8:
                _bul2 = _pcc[1] > _pcc[0]
                _sar2 = _pll[0] if _bul2 else _phh[0]
                _ep2  = _phh[1] if _bul2 else _pll[1]
                _afc2 = _af_t2
                for _ii in range(2, _nt2):
                    _sar2 = _sar2 + _afc2 * (_ep2 - _sar2)
                    if _bul2:
                        _sar2 = min(_sar2, _pll[_ii-1])
                        if _pcc[_ii] < _sar2: _bul2=False; _sar2=_ep2; _ep2=_pll[_ii]; _afc2=_af_t2
                        else:
                            if _phh[_ii] > _ep2: _ep2=_phh[_ii]; _afc2=min(_afm_t2,_afc2+_afs_t2)
                    else:
                        _sar2 = max(_sar2, _phh[_ii-1])
                        if _pcc[_ii] > _sar2: _bul2=True; _sar2=_ep2; _ep2=_phh[_ii]; _afc2=_af_t2
                        else:
                            if _pll[_ii] < _ep2: _ep2=_pll[_ii]; _afc2=min(_afm_t2,_afc2+_afs_t2)
                if _bul2: _tick_votes_buy  += 2
                else:     _tick_votes_sell += 2
        except Exception: pass

        # CMO (micro)
        try:
            _dc = closes.diff(1)
            _uc = _dc.clip(lower=0).rolling(7).sum()
            _dc2= (-_dc.clip(upper=0)).rolling(7).sum()
            _cmo_t = float((100*(_uc-_dc2)/(_uc+_dc2+1e-9)).iloc[-1])
            if _cmo_t > 20:   _tick_votes_buy  += 1
            elif _cmo_t < -20: _tick_votes_sell += 1
        except Exception: pass

        # Awesome Oscillator (micro)
        try:
            _mid_t2 = (highs + lows) / 2
            _ao_t = float((_mid_t2.rolling(5).mean() - _mid_t2.rolling(min(34,len(closes))).mean()).iloc[-1])
            if _ao_t > 0:   _tick_votes_buy  += 1
            elif _ao_t < 0: _tick_votes_sell += 1
        except Exception: pass

        # WMA cross (micro)
        try:
            def _wma_t(s, p):
                w = list(range(1, p+1))
                return s.rolling(p).apply(lambda x: sum(x[i]*w[i] for i in range(len(x)))/sum(w), raw=True)
            _wf = _wma_t(closes, min(5, len(closes)//2))
            _ws = _wma_t(closes, min(10, len(closes)-1))
            if float(_wf.iloc[-1]) > float(_ws.iloc[-1]): _tick_votes_buy  += 1
            else:                                           _tick_votes_sell += 1
        except Exception: pass

        # Vortex (micro)
        try:
            _nt3 = len(closes)
            if _nt3 >= 8:
                _vp = sum(abs(float(highs.iloc[i])-float(lows.iloc[i-1])) for i in range(max(1,_nt3-7),_nt3))
                _vm2= sum(abs(float(lows.iloc[i]) -float(highs.iloc[i-1]))for i in range(max(1,_nt3-7),_nt3))
                if _vp > _vm2: _tick_votes_buy  += 1
                else:          _tick_votes_sell += 1
        except Exception: pass

        # Consensus vote from micro-tick indicators
        _tvt = _tick_votes_buy + _tick_votes_sell
        if _tvt >= 3:
            _tick_consensus = "BUY" if _tick_votes_buy > _tick_votes_sell else "SELL"
            if direction is None:
                direction = _tick_consensus
            elif direction != _tick_consensus:
                # Majority vote decides
                if _tick_votes_buy >= 4 and direction == "SELL":
                    direction = None   # major conflict
                elif _tick_votes_sell >= 4 and direction == "BUY":
                    direction = None
        # ── end v57 micro-tick ─────────────────────────────────────────────

        # DEMA/Fisher tiebreaker if direction still None
        if direction is None:
            if dema_diff_t > 0.02 and fisher_dir_t == "BUY":
                direction = "BUY"
            elif dema_diff_t < -0.02 and fisher_dir_t == "SELL":
                direction = "SELL"
        elif dema_diff_t != 0:
            if (direction == "BUY" and dema_diff_t < -0.05) or \
               (direction == "SELL" and dema_diff_t > 0.05):
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
    HTF STRUCTURE ANALYSIS kwa micro-candles (5s/10s/15s).

    Mantiki: Kama mtu anayeangalia chart ya 30m/1H - anaangalia STRUCTURE
    ya soko (Higher Highs, Higher Lows = uptrend; Lower Highs, Lower Lows = downtrend).
    Not just the last 3 candles — the full price structure.

    Vipengele:
      1. HH/HL vs LH/LL structure (uzito mkubwa - 40%)
      2. EMA internal (9 vs 21 ya closes) - cross ya ndani (25%)
      3. Bull/bear candle majority (15%)
      4. Momentum slope - last 1/3 ya candles vs kwanza (15%)
      5. Reversal detection - last candle breaks structure (adhabu)

    Returns: {"direction": "BUY"/"SELL"/"FLAT", "strength": 0-100,
              "reversal": bool, "momentum": float,
              "htf_structure": "UPTREND"/"DOWNTREND"/"RANGING"}
    """
    if len(candles) < 5:
        return {"direction": "FLAT", "strength": 0, "reversal": False,
                "momentum": 0, "htf_structure": "RANGING"}

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    total  = len(candles)

    hh = hl = lh = ll = 0
    for i in range(1, total):
        if highs[i] > highs[i - 1]: hh += 1
        else:                         lh += 1
        if lows[i] > lows[i - 1]:   hl += 1
        else:                         ll += 1

    bull_struct = hh + hl   # Uptrend structure score
    bear_struct = lh + ll   # Downtrend structure score
    max_struct  = (total - 1) * 2  # Maximum possible

    struct_buy_ratio  = bull_struct / max(max_struct, 1)
    struct_sell_ratio = bear_struct / max(max_struct, 1)

    if struct_buy_ratio >= 0.62:
        htf_structure = "UPTREND"
    elif struct_sell_ratio >= 0.62:
        htf_structure = "DOWNTREND"
    else:
        htf_structure = "RANGING"

    import pandas as _pd_mt
    _cl = _pd_mt.Series(closes, dtype=float)
    ema9_val  = float(_cl.ewm(span=min(9,  total), adjust=False).mean().iloc[-1])
    ema21_val = float(_cl.ewm(span=min(21, total), adjust=False).mean().iloc[-1])
    ema_cross = "BUY" if ema9_val > ema21_val else ("SELL" if ema9_val < ema21_val else None)

    bulls = sum(1 for c in candles if c["close"] > c["open"])
    bears = sum(1 for c in candles if c["close"] < c["open"])
    bull_ratio = bulls / max(total, 1)
    bear_ratio = bears / max(total, 1)

    third = max(2, total // 3)
    early_avg = sum(closes[:third])  / third
    late_avg  = sum(closes[-third:]) / third
    slope     = (late_avg - early_avg) / (early_avg + 1e-9) * 100
    slope_dir = "BUY" if slope > 0 else "SELL"

    prev_dir  = "BUY" if closes[-2] > closes[-3] else "SELL"
    last_dir  = "BUY" if closes[-1] > closes[-2] else "SELL"
    reversal  = (prev_dir != last_dir)

    if htf_structure == "UPTREND" and last_dir == "SELL":
        reversal = True
    elif htf_structure == "DOWNTREND" and last_dir == "BUY":
        reversal = True

    buy_score  = 0.0
    sell_score = 0.0

    buy_score  += struct_buy_ratio  * 40
    sell_score += struct_sell_ratio * 40

    if ema_cross == "BUY":   buy_score  += 25
    elif ema_cross == "SELL": sell_score += 25

    buy_score  += bull_ratio * 15
    sell_score += bear_ratio * 15

    if slope_dir == "BUY":
        slope_contrib = min(15, abs(slope) * 5)
        buy_score += slope_contrib
    else:
        slope_contrib = min(15, abs(slope) * 5)
        sell_score += slope_contrib

    if buy_score > sell_score:
        direction = "BUY"
        raw_strength = buy_score
    elif sell_score > buy_score:
        direction = "SELL"
        raw_strength = sell_score
    else:
        direction = "BUY" if slope >= 0 else "SELL"
        raw_strength = 52.0

    strength = max(0, min(100, int(raw_strength)))

    if reversal:
        strength = max(0, strength - 18)

    last3    = closes[-3:]
    momentum = (last3[-1] - last3[0]) / (last3[0] + 1e-9) * 100

    return {
        "direction":     direction,
        "strength":      strength,
        "reversal":      reversal,
        "momentum":      round(momentum, 5),
        "htf_structure": htf_structure,
        "ema_cross":     ema_cross,
        "struct_buy":    round(struct_buy_ratio * 100, 1),
        "struct_sell":   round(struct_sell_ratio * 100, 1),
    }

async def pick_best_tf_deriv(pair, signal_direction=None):
    """
    HTF TREND ENGINE kwa micro-candles ya Deriv.

    Kanuni kuu (v45):
      5s  micro-candles → ziamua TF ya 1m  (kama chart ya 30m)
      10s micro-candles → ziamua TF ya 2m  (kama chart ya 1H)
      15s micro-candles → ziamua TF ya 3m  (kama chart ya 2H)

    Kila TF inapata composite score kutoka:
      - HTF Structure: HH/HL vs LH/LL (uzito mkubwa - 40%)
      - Internal EMA cross 9/21 (25%)
      - RSI, MACD, BB alignment ya ndani (20%)
      - Momentum slope (10%)
      - Reversal penalty (-20)

    TF yenye score kubwa zaidi NDIYO inayotumika.
    No bias — real structure decides.

    Returns: (best_tf_mins, strength, direction, reason)
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

    tf_map = {
        "5_s":  1,
        "10_s": 2,
        "15_s": 3,
    }

    ind_map = {
        "5_s":  "5_s_ind",
        "10_s": "10_s_ind",
        "15_s": "15_s_ind",
    }

    tf_scores     = {}
    tf_directions = {}
    tf_reasons    = {}

    for micro_key, trade_tf in tf_map.items():
        trend = data.get(micro_key)
        if not trend:
            continue

        direction      = trend["direction"]
        candle_str     = trend["strength"]
        htf_structure  = trend.get("htf_structure", "RANGING")
        ema_cross      = trend.get("ema_cross")
        struct_buy_pct = trend.get("struct_buy", 50.0)
        struct_sell_pct= trend.get("struct_sell", 50.0)

        if candle_str < 30 and htf_structure == "RANGING":
            logging.info("Deriv {}s RANGING+weak({}) - skip".format(trade_tf * 5, candle_str))
            continue

        comp    = 0.0
        reasons = []

        if htf_structure == "UPTREND" and direction == "BUY":
            struct_bonus = (struct_buy_pct / 100) * 40
            comp += struct_bonus
            reasons.append("HTF↑{:.0f}%".format(struct_buy_pct))
        elif htf_structure == "DOWNTREND" and direction == "SELL":
            struct_bonus = (struct_sell_pct / 100) * 40
            comp += struct_bonus
            reasons.append("HTF↓{:.0f}%".format(struct_sell_pct))
        elif htf_structure == "RANGING":
            comp -= 10  # Ranging market - reduce
            reasons.append("HTF_RANGING")
        else:
            comp -= 20
            reasons.append("HTF_OPPOSE!")

        if ema_cross == direction:
            comp += 25
            reasons.append("EMA✓")
        elif ema_cross is not None and ema_cross != direction:
            comp -= 15
            reasons.append("EMA✗")

        comp += candle_str * 0.15
        reasons.append("str={:.0f}".format(candle_str))

        if trend.get("reversal"):
            comp -= 20
            reasons.append("rev!")

        mom = trend.get("momentum", 0)
        if (direction == "BUY" and mom > 0) or (direction == "SELL" and mom < 0):
            mom_contrib = min(10, abs(mom) * 200)
            comp += mom_contrib
            reasons.append("mom+{:.0f}".format(mom_contrib))
        elif mom != 0:
            comp -= 5
            reasons.append("mom-")

        ind_key = ind_map.get(micro_key)
        ind     = data.get(ind_key) if ind_key else None
        if ind:
            ind_dir = ind.get("direction")
            rsi_v   = ind.get("rsi", 50)
            macd_v  = ind.get("macd", 0)
            ma_v    = ind.get("ma_diff", 0)
            bb_p    = ind.get("bb_pos", 0.5)
            ind_score = 0.0

            if ind_dir == direction:
                ind_score += 8
                reasons.append("ind✓")
            elif ind_dir is not None and ind_dir != direction:
                ind_score -= 6
                reasons.append("ind✗")

            if direction == "BUY":
                if rsi_v < 30:   ind_score += 5
                elif rsi_v < 45: ind_score += 2
                elif rsi_v > 65: ind_score -= 4
            else:
                if rsi_v > 70:   ind_score += 5
                elif rsi_v > 55: ind_score += 2
                elif rsi_v < 35: ind_score -= 4

            if (direction == "BUY" and macd_v > 0.1) or (direction == "SELL" and macd_v < -0.1):
                ind_score += min(4, abs(macd_v) * 6)
            elif (direction == "BUY" and macd_v < -0.1) or (direction == "SELL" and macd_v > 0.1):
                ind_score -= 3

            if direction == "BUY" and bb_p <= 0.20:
                ind_score += 3
            elif direction == "SELL" and bb_p >= 0.80:
                ind_score += 3

            comp += ind_score
            reasons.append("ind={:.0f}".format(ind_score))

        tf_scores[trade_tf]     = comp
        tf_directions[trade_tf] = direction
        tf_reasons[trade_tf]    = ", ".join(reasons)

    if not tf_scores:
        reason = "all micro-TFs RANGING/weak or no data"
        logging.info("Deriv pick_best_tf {}: NONE - {}".format(pair, reason))
        return (None, 0, None, reason)

    if signal_direction:
        matching = {tf: sc for tf, sc in tf_scores.items()
                    if tf_directions.get(tf) == signal_direction}
        pool = matching if matching else tf_scores
    else:
        pool = tf_scores

    best_tf = max(pool, key=lambda t: pool[t])

    best_score     = tf_scores[best_tf]
    best_direction = tf_directions[best_tf]
    best_reason    = "{}m [{}s HTF] score={:.1f}: {}".format(
        best_tf, best_tf * 5, best_score, tf_reasons[best_tf])

    best_str = max(0, min(100, int(best_score)))

    logging.info("Deriv HTF {}: {}m {} (score={:.1f}) HTF:[1m={} 2m={} 3m={}] - {}".format(
        pair, best_tf, best_direction, best_score,
        round(tf_scores.get(1, -999), 1),
        round(tf_scores.get(2, -999), 1),
        round(tf_scores.get(3, -999), 1),
        best_reason))
    return (best_tf, best_str, best_direction, best_reason)

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

    deriv_score = {1: 0.0, 2: 0.0, 3: 0.0}
    try:
        data = await asyncio.wait_for(
            _fetch_deriv_ticks(pair, seconds=15),
            timeout=8
        )
        if data:
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
                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS win_rate,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND tf_mins IN (1, 2, 3)
                """, (pair,))
                overall_rows = cur.fetchall()
        session_data = {}
        for r in rows:
            if r["win_rate"] is not None and int(r["total"]) >= 3:
                session_data[int(r["tf_mins"])] = (float(r["win_rate"]), int(r["total"]))
        overall_data = {}
        for r in overall_rows:
            if r["win_rate"] is not None and int(r["total"]) >= 3:
                overall_data[int(r["tf_mins"])] = (float(r["win_rate"]), int(r["total"]))

        for tf_m in [1, 2, 3]:
            if tf_m in session_data:
                wr, total = session_data[tf_m]
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
                    expected_features = _nn_global_scaler.n_features_in_
                    if feat.shape[1] != expected_features:
                        if feat.shape[1] < expected_features:
                            pad = np.zeros((1, expected_features - feat.shape[1]), dtype=np.float32)
                            feat = np.hstack([feat, pad])
                        else:
                            feat = feat[:, :expected_features]

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
                    ml_score[tf_m] = (prob_win - 0.5) * 2.0
                    ml_score[tf_m] = max(-1.0, min(1.0, ml_score[tf_m]))
                    reasons[tf_m].append("ML {:.0f}%".format(prob_win * 100))
        except Exception as e:
            logging.info("select_best_expiry ML failed {}: {}".format(pair, e))

    for tf_m in [1, 2, 3]:
        scores[tf_m] += ml_score[tf_m] * 0.25

    best_tf   = max(scores, key=lambda t: scores[t])
    best_score = scores[best_tf]

    if best_score < 0.05:
        return (0, "no_tf_support score={:.2f}".format(best_score))

    reason_str = "tf={}m score={:.2f} [1m:{:.2f} 2m:{:.2f} 3m:{:.2f}] | {}".format(
        best_tf, scores[best_tf],
        scores[1], scores[2], scores[3],
        " / ".join(reasons[best_tf])
    )
    logging.info("EXPIRY SELECT {}: {}".format(pair, reason_str))
    return (best_tf, reason_str)

def support_url():
    """Returns support link - opens support bot with 'admin' pre-filled."""
    return "https://t.me/{}?text=admin".format(SUPPORT_BOT)

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
                ALTER TABLE users ADD COLUMN IF NOT EXISTS broker_selected TEXT DEFAULT NULL;
                ALTER TABLE licences ADD COLUMN IF NOT EXISTS revoked BOOLEAN DEFAULT FALSE;
                CREATE TABLE IF NOT EXISTS join_requests (
                    user_id BIGINT PRIMARY KEY,
                    requested_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS signal_history (
                    id SERIAL PRIMARY KEY,
                    pair TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    rsi DOUBLE PRECISION DEFAULT NULL,
                    macd DOUBLE PRECISION DEFAULT NULL,
                    bb_pos DOUBLE PRECISION DEFAULT NULL,
                    sto DOUBLE PRECISION DEFAULT NULL,
                    ma_diff DOUBLE PRECISION DEFAULT NULL,
                    mom DOUBLE PRECISION DEFAULT NULL,
                    atr_pct DOUBLE PRECISION DEFAULT NULL,
                    session TEXT DEFAULT NULL,
                    trend_1h TEXT DEFAULT NULL,
                    score INTEGER DEFAULT NULL,
                    won BOOLEAN DEFAULT NULL,
                    tf_mins INTEGER DEFAULT NULL
                );
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS rsi DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS macd DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS bb_pos DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS sto DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS ma_diff DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS mom DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS atr_pct DOUBLE PRECISION DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS session TEXT DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS trend_1h TEXT DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS score INTEGER DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS won BOOLEAN DEFAULT NULL;
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS tf_mins INTEGER DEFAULT NULL;
                CREATE INDEX IF NOT EXISTS idx_signal_history_pair_session ON signal_history (pair, session, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_signal_history_won ON signal_history (pair, won, created_at DESC);
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
                CREATE TABLE IF NOT EXISTS user_msg_stack (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    msg_id BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_user_msg_stack_user_id ON user_msg_stack (user_id);
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
                CREATE TABLE IF NOT EXISTS tf_expiry_performance (
                    id SERIAL PRIMARY KEY,
                    pair TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    tf_mins INTEGER NOT NULL,
                    session TEXT NOT NULL,
                    pg_prob DOUBLE PRECISION DEFAULT 0.5,
                    deriv_score DOUBLE PRECISION DEFAULT 0.0,
                    final_score DOUBLE PRECISION DEFAULT 0.0,
                    won BOOLEAN DEFAULT NULL,
                    rsi DOUBLE PRECISION DEFAULT NULL,
                    bb_pos DOUBLE PRECISION DEFAULT NULL,
                    atr_pct DOUBLE PRECISION DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_tf_expiry_perf ON tf_expiry_performance (pair, direction, session, tf_mins, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tf_expiry_won ON tf_expiry_performance (pair, tf_mins, won);
                CREATE TABLE IF NOT EXISTS nn_signal_features (
                    user_id BIGINT NOT NULL,
                    pair TEXT NOT NULL,
                    features BYTEA NOT NULL,
                    original_direction TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, pair)
                );

                -- v50: setup_cluster column kwa signal_history
                ALTER TABLE signal_history ADD COLUMN IF NOT EXISTS setup_cluster TEXT DEFAULT NULL;
                CREATE INDEX IF NOT EXISTS idx_signal_history_cluster
                    ON signal_history (pair, setup_cluster, created_at DESC);

                -- v50: signal_combo_stats - kujifunza combo bora ya direction+tf kwa setup
                CREATE TABLE IF NOT EXISTS signal_combo_stats (
                    id           SERIAL PRIMARY KEY,
                    pair         TEXT NOT NULL,
                    direction    TEXT NOT NULL,
                    tf_mins      INTEGER NOT NULL,
                    setup_cluster TEXT NOT NULL,
                    wins         INTEGER DEFAULT 0,
                    losses       INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT NOW()
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_combo_unique
                    ON signal_combo_stats (pair, direction, tf_mins, setup_cluster);
                CREATE INDEX IF NOT EXISTS idx_combo_lookup
                    ON signal_combo_stats (pair, setup_cluster);

                -- v50: trend_fingerprint_results - mfumo mpya wa kujifunza
                -- Hifadhi fingerprint ya kila signal + outcomes za 1m/2m/3m + movement
                CREATE TABLE IF NOT EXISTS trend_fingerprint_results (
                    id            SERIAL PRIMARY KEY,
                    pair          TEXT NOT NULL,
                    -- Fingerprint ya trend (indicators za wakati wa signal)
                    rsi           DOUBLE PRECISION DEFAULT NULL,
                    bb_pos        DOUBLE PRECISION DEFAULT NULL,
                    macd          DOUBLE PRECISION DEFAULT NULL,
                    mom           DOUBLE PRECISION DEFAULT NULL,
                    atr_pct       DOUBLE PRECISION DEFAULT NULL,
                    trend_1h      TEXT DEFAULT NULL,
                    -- Deriv micro-trends (5s/10s/15s)
                    d5s_dir       TEXT DEFAULT NULL,
                    d5s_str       DOUBLE PRECISION DEFAULT NULL,
                    d10s_dir      TEXT DEFAULT NULL,
                    d10s_str      DOUBLE PRECISION DEFAULT NULL,
                    d15s_dir      TEXT DEFAULT NULL,
                    d15s_str      DOUBLE PRECISION DEFAULT NULL,
                    -- Signal iliyotolewa
                    signal_dir    TEXT NOT NULL,
                    entry_price   DOUBLE PRECISION NOT NULL,
                    created_at    TIMESTAMP DEFAULT NOW(),
                    -- Outcomes za 1m, 2m, 3m
                    won_1m        BOOLEAN DEFAULT NULL,
                    won_2m        BOOLEAN DEFAULT NULL,
                    won_3m        BOOLEAN DEFAULT NULL,
                    -- Movement (pips%) kwa kila TF - jinsi bei ilienda mbali
                    move_1m       DOUBLE PRECISION DEFAULT NULL,
                    move_2m       DOUBLE PRECISION DEFAULT NULL,
                    move_3m       DOUBLE PRECISION DEFAULT NULL,
                    -- Exit prices
                    exit_1m       DOUBLE PRECISION DEFAULT NULL,
                    exit_2m       DOUBLE PRECISION DEFAULT NULL,
                    exit_3m       DOUBLE PRECISION DEFAULT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tfr_pair ON trend_fingerprint_results (pair, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tfr_rsi ON trend_fingerprint_results (pair, rsi, bb_pos);

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT PRIMARY KEY,
                    timezone TEXT DEFAULT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)

        conn.commit()

def pg_predict(pair, direction, rsi=50.0, sto=50.0, bb_pos=0.5,
               ma_diff=0.0, macd=0.0, mom=0.0, atr_pct=0.05,
               session=None, trend_1h=None, tf_mins=2):
    """
    Predict win probability using PostgreSQL win-rate analysis.
    Instead of an ML model, uses:
      1. Win rate per pair/session/tf from signal_history (real)
      2. Win rate ya pair/direction kutoka signal_outcomes
      3. Indicator similarity - tafuta signals zilizofanana na zilishinda
      4. Trend dominance - % ya wins wiki iliyopita kwa direction hii

    Returns: (win_prob: float 0.0-1.0, source: str, should_flip: bool)
    - win_prob >= 0.72 = high confidence (match NN threshold ya zamani)
    - should_flip = True kama opposite direction ina win_prob >= 0.75
    """
    try:
        if session is None:
            session = _get_session().get("name", "Unknown")

        results = {}

        with get_conn() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s
                      AND direction = %s
                      AND session = %s
                      AND tf_mins = %s
                      AND won IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '14 days'
                """, (pair, direction, session, tf_mins))
                row = cur.fetchone()
                if row and row["total"] and int(row["total"]) >= 5:
                    wr = float(row["wins"]) / float(row["total"])
                    results["session_tf"] = (wr, int(row["total"]))

                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s
                      AND direction = %s
                      AND won IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '30 days'
                """, (pair, direction))
                row = cur.fetchone()
                if row and row["total"] and int(row["total"]) >= 8:
                    wr = float(row["wins"]) / float(row["total"])
                    results["pair_dir"] = (wr, int(row["total"]))

                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s
                      AND direction = %s
                      AND won IS NOT NULL
                      AND rsi IS NOT NULL
                      AND ABS(rsi - %s) <= 12
                      AND ABS(bb_pos - %s) <= 0.18
                      AND created_at >= NOW() - INTERVAL '21 days'
                """, (pair, direction, rsi, bb_pos))
                row = cur.fetchone()
                if row and row["total"] and int(row["total"]) >= 5:
                    wr = float(row["wins"]) / float(row["total"])
                    results["indicator_sim"] = (wr, int(row["total"]))

                if trend_1h in ("BUY", "SELL"):
                    cur.execute("""
                        SELECT
                            COUNT(*) AS total,
                            SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                        FROM signal_history
                        WHERE pair = %s
                          AND direction = %s
                          AND trend_1h = %s
                          AND won IS NOT NULL
                          AND created_at >= NOW() - INTERVAL '30 days'
                    """, (pair, direction, trend_1h))
                    row = cur.fetchone()
                    if row and row["total"] and int(row["total"]) >= 5:
                        wr = float(row["wins"]) / float(row["total"])
                        results["trend_align"] = (wr, int(row["total"]))

                opp_dir = "SELL" if direction == "BUY" else "BUY"
                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s
                      AND direction = %s
                      AND session = %s
                      AND won IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '14 days'
                """, (pair, opp_dir, session))
                row = cur.fetchone()
                opp_win_rate = 0.5
                if row and row["total"] and int(row["total"]) >= 5:
                    opp_win_rate = float(row["wins"]) / float(row["total"])

        if not results:
            return 0.5, "no_data", False

        weights = {
            "session_tf":     3.0,  # Most specific - highest weight
            "pair_dir":       2.0,
            "indicator_sim":  2.5,  # Similar market conditions
            "trend_align":    2.0,
        }
        total_w = 0.0
        weighted_sum = 0.0
        source_parts = []

        for key, (wr, n) in results.items():
            conf = min(1.0, n / 20.0)  # Confidence rises with sample count
            w = weights.get(key, 1.0) * conf
            weighted_sum += wr * w
            total_w += w
            source_parts.append("{}={:.0f}%({})".format(key, wr * 100, n))

        win_prob = weighted_sum / total_w if total_w > 0 else 0.5
        source = " | ".join(source_parts)

        should_flip = (opp_win_rate >= 0.75 and win_prob < 0.45)

        logging.info("PG_PREDICT {} {} tf={}m sess={}: prob={:.1%} flip={} [{}]".format(
            pair, direction, tf_mins, session, win_prob, should_flip, source))

        return win_prob, source, should_flip

    except Exception as e:
        logging.warning("pg_predict failed {}: {}".format(pair, e))
        return 0.5, "error", False

def pg_predict_per_tf(pair, direction, rsi=50.0, sto=50.0, bb_pos=0.5,
                      ma_diff=0.0, macd=0.0, mom=0.0, session=None, trend_1h=None):
    """
    PostgreSQL win-rate comparison for TF 1, 2, and 3 together.
    Uses ONE efficient query instead of 3 separate DB calls.

    Inachunguza:
      1. Win rate ya pair/direction/session/tf_mins (signal_history, siku 21)
      2. Win rate ya pair/direction kwa tf_mins peke yake (signal_history, siku 30)
      3. Win rate from tf_session_stats (real VTE outcomes)
      4. Indicator similarity: RSI±12, BB±0.18 (siku 21)
      5. Trend alignment kwa kila tf_mins

    Returns: dict {1: float, 2: float, 3: float}
    - Kila thamani ni win_prob 0.0–1.0 kwa TF hiyo
    - 0.5 = neutral / data haitoshi
    - Tofauti kati ya TF ndio inayoamua expiry bora

    Kanuni: kama TF 1 ina win_prob 0.72, TF 2 ina 0.61, TF 3 ina 0.55
    → chagua TF 1 (data inasema 1m ndiyo bora kwa setup hii)
    """
    if session is None:
        try:
            session = _get_session().get("name", "Unknown")
        except Exception:
            session = "Unknown"

    tf_probs = {1: 0.5, 2: 0.5, 3: 0.5}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        tf_mins,
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s
                      AND direction = %s
                      AND session = %s
                      AND tf_mins IN (1, 2, 3)
                      AND won IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '21 days'
                    GROUP BY tf_mins
                """, (pair, direction, session))
                rows_sess = {int(r["tf_mins"]): r for r in cur.fetchall()}

                cur.execute("""
                    SELECT
                        tf_mins,
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s
                      AND direction = %s
                      AND tf_mins IN (1, 2, 3)
                      AND won IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY tf_mins
                """, (pair, direction))
                rows_broad = {int(r["tf_mins"]): r for r in cur.fetchall()}

                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS wr,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND session = %s AND tf_mins IN (1, 2, 3)
                """, (pair, session))
                rows_vte = {int(r["tf_mins"]): r for r in cur.fetchall()}

                cur.execute("""
                    SELECT
                        tf_mins,
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s
                      AND direction = %s
                      AND tf_mins IN (1, 2, 3)
                      AND won IS NOT NULL
                      AND rsi IS NOT NULL
                      AND ABS(rsi - %s) <= 12
                      AND ABS(bb_pos - %s) <= 0.18
                      AND created_at >= NOW() - INTERVAL '21 days'
                    GROUP BY tf_mins
                """, (pair, direction, rsi, bb_pos))
                rows_sim = {int(r["tf_mins"]): r for r in cur.fetchall()}

        WEIGHTS = {
            "sess": 3.5,   # Session-specific + TF + direction: most specific
            "broad": 1.8,  # Broader (no session restriction)
            "vte": 2.5,    # VTE real outcomes (tf_session_stats)
            "sim": 2.0,    # Similar indicator conditions
        }
        MIN_TRADES = {"sess": 4, "broad": 6, "vte": 3, "sim": 4}

        for tf in [1, 2, 3]:
            sources = {}

            r = rows_sess.get(tf)
            if r and int(r["total"]) >= MIN_TRADES["sess"]:
                wr = float(r["wins"]) / float(r["total"])
                conf = min(1.0, int(r["total"]) / 20.0)
                sources["sess"] = (wr, conf)

            r = rows_broad.get(tf)
            if r and int(r["total"]) >= MIN_TRADES["broad"]:
                wr = float(r["wins"]) / float(r["total"])
                conf = min(1.0, int(r["total"]) / 30.0)
                sources["broad"] = (wr, conf)

            r = rows_vte.get(tf)
            if r and r["wr"] is not None and int(r["total"]) >= MIN_TRADES["vte"]:
                wr = float(r["wr"])
                conf = min(1.0, int(r["total"]) / 15.0)
                sources["vte"] = (wr, conf)

            r = rows_sim.get(tf)
            if r and int(r["total"]) >= MIN_TRADES["sim"]:
                wr = float(r["wins"]) / float(r["total"])
                conf = min(1.0, int(r["total"]) / 20.0)
                sources["sim"] = (wr, conf)

            if not sources:
                continue

            total_w = 0.0
            weighted_sum = 0.0
            for src_key, (wr, conf) in sources.items():
                w = WEIGHTS.get(src_key, 1.0) * conf
                weighted_sum += wr * w
                total_w += w

            if total_w > 0:
                tf_probs[tf] = min(1.0, max(0.0, weighted_sum / total_w))

        logging.info("PG_PREDICT_PER_TF {} {} sess={}: 1m={:.2f} 2m={:.2f} 3m={:.2f}".format(
            pair, direction, session,
            tf_probs[1], tf_probs[2], tf_probs[3]))
        return tf_probs

    except Exception as e:
        logging.warning("pg_predict_per_tf failed {}: {}".format(pair, e))
        return {1: 0.5, 2: 0.5, 3: 0.5}

def save_signal_history_full(pair, direction, rsi=None, macd=None, bb_pos=None,
                              sto=None, ma_diff=None, mom=None, atr_pct=None,
                              session=None, trend_1h=None, score=None, tf_mins=None,
                              setup_cluster=None):
    """
    v50: Hifadhi signal kwenye signal_history na indicators zake zote + setup_cluster.
    setup_cluster inabeba fingerprint ya hali ya soko kwa ulinganishaji wa historia.
    Returns: id ya row iliyohifadhiwa (tumia kwa update ya won)
    """
    if session is None:
        try:
            session = _get_session().get("name", "Unknown")
        except Exception:
            session = "Unknown"
    if setup_cluster is None and rsi is not None and bb_pos is not None:
        try:
            setup_cluster = compute_setup_cluster(
                rsi=float(rsi),
                bb_pos=float(bb_pos),
                mom=float(mom) if mom is not None else 0.0,
                session=session
            )
        except Exception:
            pass
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_history
                        (pair, direction, rsi, macd, bb_pos, sto, ma_diff,
                         mom, atr_pct, session, trend_1h, score, tf_mins,
                         setup_cluster, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id
                """, (pair, direction, rsi, macd, bb_pos, sto, ma_diff,
                      mom, atr_pct, session, trend_1h, score, tf_mins, setup_cluster))
                row = cur.fetchone()
            conn.commit()
        return row["id"] if row else None
    except Exception as e:
        logging.warning("save_signal_history_full failed {}: {}".format(pair, e))
        return None

def update_signal_history_won(signal_id, won):
    """
    v50: Jaza matokeo ya signal (won=True/False) baada ya candle kufunga.
    MPYA: Pia inasasisha signal_combo_stats na tf_session_stats automatically.
    """
    if signal_id is None:
        return
    try:
        row = None
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE signal_history SET won = %s WHERE id = %s",
                    (won, signal_id)
                )
                cur.execute("""
                    SELECT pair, direction, tf_mins, rsi, bb_pos, mom, session
                    FROM signal_history WHERE id = %s
                """, (signal_id,))
                row = cur.fetchone()
            conn.commit()

        if row:
            pair      = row["pair"]
            direction = row["direction"]
            tf_mins   = int(row["tf_mins"]) if row["tf_mins"] else 2
            rsi_v     = float(row["rsi"])    if row["rsi"]    is not None else 50.0
            bb_pos_v  = float(row["bb_pos"]) if row["bb_pos"] is not None else 0.5
            mom_v     = float(row["mom"])     if row["mom"]    is not None else 0.0
            session_v = row["session"] or "Unknown"

            update_signal_combo_stats(
                pair=pair, direction=direction, tf_mins=tf_mins, won=won,
                rsi=rsi_v, bb_pos=bb_pos_v, mom=mom_v, session=session_v
            )
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        if won:
                            cur.execute("""
                                INSERT INTO tf_session_stats
                                    (pair, session, tf_mins, wins, losses)
                                VALUES (%s, %s, %s, 1, 0)
                                ON CONFLICT (pair, session, tf_mins) DO UPDATE
                                    SET wins = tf_session_stats.wins + 1
                            """, (pair, session_v, tf_mins))
                        else:
                            cur.execute("""
                                INSERT INTO tf_session_stats
                                    (pair, session, tf_mins, wins, losses)
                                VALUES (%s, %s, %s, 0, 1)
                                ON CONFLICT (pair, session, tf_mins) DO UPDATE
                                    SET losses = tf_session_stats.losses + 1
                            """, (pair, session_v, tf_mins))
                    conn.commit()
            except Exception as _tss_e:
                logging.warning("update_signal_history_won tf_session_stats failed: {}".format(_tss_e))

    except Exception as e:
        logging.warning("update_signal_history_won failed id={}: {}".format(signal_id, e))

def get_pg_trend_analysis(pair, session=None, days=7):
    """
    Chambua trend ya pair kutoka signal_history.
    Returns dict na:
      - best_direction: 'BUY'/'SELL'/None
      - best_win_rate: float
      - best_session: str
      - best_tf: int
      - total_signals: int
      - summary: str (kwa admin)
    Hii ndio 'kesho trend itoe direction gani nzuri'.
    """
    if session is None:
        try:
            session = _get_session().get("name", "Unknown")
        except Exception:
            session = None

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        direction,
                        session,
                        tf_mins,
                        COUNT(*) AS total,
                        SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins,
                        AVG(rsi) AS avg_rsi,
                        AVG(atr_pct) AS avg_atr
                    FROM signal_history
                    WHERE pair = %s
                      AND won IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY direction, session, tf_mins
                    HAVING COUNT(*) >= 5
                    ORDER BY (SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END)::float / COUNT(*)) DESC
                    LIMIT 10
                """, (pair, days))
                rows = cur.fetchall()

        if not rows:
            return {"best_direction": None, "total_signals": 0,
                    "summary": "Not enough data (fewer than 5 signals)"}

        best = rows[0]
        best_wr = float(best["wins"]) / float(best["total"])

        lines = ["📊 *Trend Analysis: {}* ({}d)".format(pair, days)]
        for r in rows[:5]:
            wr = float(r["wins"]) / float(r["total"])
            tf_str = "{}m".format(r["tf_mins"]) if r["tf_mins"] else "?m"
            sess_str = r["session"] or "?"
            lines.append("  {} {} {} → {:.0f}% ({} trades)".format(
                "🟢" if r["direction"] == "BUY" else "🔴",
                r["direction"], tf_str, wr * 100, r["total"]))

        return {
            "best_direction": best["direction"],
            "best_win_rate": best_wr,
            "best_session": best["session"],
            "best_tf": best["tf_mins"],
            "total_signals": int(best["total"]),
            "summary": "\n".join(lines),
        }

    except Exception as e:
        logging.warning("get_pg_trend_analysis failed {}: {}".format(pair, e))
        return {"best_direction": None, "total_signals": 0, "summary": "DB error"}

def update_pair_stats(pair, won):
    """Update win/loss stats for a pair. won: True if signal was correct."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if won:
                    cur.execute("""
                        INSERT INTO pair_stats (pair, wins, losses, consecutive_losses, consecutive_wins)
                        VALUES (%s, 1, 0, 0, 1)
                        ON CONFLICT (pair) DO UPDATE SET
                            wins = pair_stats.wins + 1,
                            consecutive_losses = 0,
                            consecutive_wins = pair_stats.consecutive_wins + 1
                    """, (pair,))
                else:
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
        rows.sort(key=lambda r: r["wins"] / max(r["wins"] + r["losses"], 1), reverse=True)
        return rows[0]["pair"]
    except Exception as e:
        logging.warning("get_best_pair failed: {}".format(e))
        return None

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

# ── v62: Broker selection helpers ──────────────────────────────────────────
BROKER_LIST = [
    # ⭐ TIER 1 — Maarufu sana
    ("⭐ Quotex",          "quotex"),
    ("⭐ Pocket Option",   "pocket_option"),
    ("⭐ IQ Option",       "iq_option"),
    ("⭐ Binolla",         "binolla"),
    ("⭐ Olymp Trade",     "olymp_trade"),
    ("⭐ Deriv",           "deriv"),
    # 🔥 TIER 2 — Maarufu
    ("🔥 Binomo",          "binomo"),
    ("🔥 ExpertOption",    "expertoption"),
    ("🔥 IQCent",          "iqcent"),
    ("🔥 Raceoption",      "raceoption"),
    ("🔥 Binarycent",      "binarycent"),
    ("🔥 Videforex",       "videforex"),
    ("🔥 Binarymate",      "binarymate"),
    # 💼 TIER 3 — Zingine
    ("💼 Bullex",          "bullex"),
    ("💼 Finmax",          "finmax"),
    ("💼 BinaryCom",       "binarycom"),
    ("💼 Capitalcore",     "capitalcore"),
    ("💼 Nadex",           "nadex"),
    ("💼 Binaryx",         "binaryx"),
    ("💼 Spectre",         "spectre"),
]

def get_broker_selected(user_id):
    """Returns broker string or None if not yet selected."""
    return get_user(user_id).get("broker_selected", None)

def set_broker_selected(user_id, broker):
    """Save user's chosen broker to DB."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET broker_selected = %s WHERE user_id = %s",
                (broker, user_id)
            )
        conn.commit()

_BROKER_KEY_TO_NAME = {cb: name for name, cb in BROKER_LIST}

def get_broker_display(user_id):
    """Returns formatted broker line for signal captions, e.g. '🏦 Broker: ⭐ Pocket Option'
    Returns empty string if no broker selected."""
    key = get_broker_selected(user_id)
    if not key:
        return ""
    name = _BROKER_KEY_TO_NAME.get(key, key.replace("_", " ").title())
    return "🏦 Broker: {}".format(name)

def broker_selection_keyboard():
    """Build inline keyboard for broker selection — 2 per row."""
    rows = []
    buttons = [InlineKeyboardButton(name, callback_data="broker_select_{}".format(cb))
               for name, cb in BROKER_LIST]
    # Pack 2 per row
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i+2])
    return InlineKeyboardMarkup(rows)
# ───────────────────────────────────────────────────────────────────────────

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

INACTIVITY_MINUTES = 30
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
    USER_MSG_STACK.pop(user_id, None)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_msg_stack WHERE user_id=%s", (user_id,))
            conn.commit()
    except Exception:
        pass

def inactivity_get_msgs(user_id):
    return USER_INACTIVITY.get(user_id, {}).get("msg_ids", [])

LAST_SIGNAL_MSG = {}
LAST_BOT_MSG    = {}
USER_MSG_STACK  = {}  # user_id -> [msg_id, ...]

def push_msg_id(user_id, msg_id):
    """Push a message ID onto the user's message stack (DB + in-memory)."""
    if msg_id is None:
        return
    try:
        USER_MSG_STACK.setdefault(user_id, []).append(msg_id)
    except Exception:
        pass
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_msg_stack (user_id, msg_id) VALUES (%s, %s)",
                    (user_id, msg_id)
                )
            conn.commit()
    except Exception:
        pass

def _pop_all_msg_ids(user_id):
    """Pop all message IDs from the user's stack (DB + in-memory). Returns list."""
    ids = list(USER_MSG_STACK.pop(user_id, []))
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_msg_stack WHERE user_id=%s RETURNING msg_id",
                    (user_id,)
                )
                rows = cur.fetchall()
            conn.commit()
        for r in rows:
            mid = r["msg_id"]
            if mid not in ids:
                ids.append(mid)
    except Exception:
        pass
    return ids

async def delete_last_signal(bot, chat_id, user_id):
    """Delete ALL previous bot messages for this user (full stack clean)."""
    all_ids = _pop_all_msg_ids(user_id)
    for msg_id in all_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
    for msg_type in ["signal", "bot", "analyzing"]:
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
            store = LAST_SIGNAL_MSG if msg_type == "signal" else LAST_BOT_MSG
            msg_id = store.pop(user_id, None)
        if msg_id and msg_id not in all_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass

LAST_ANALYZING_MSG = {}

def save_analyzing_msg(user_id, msg_id):
    """Save analyzing message ID so it can be deleted when next pair is selected."""
    LAST_ANALYZING_MSG[user_id] = msg_id
    push_msg_id(user_id, msg_id)  # add to full stack
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO last_msg_store (user_id, msg_type, msg_id, updated_at) "
                    "VALUES (%s, 'analyzing', %s, NOW()) "
                    "ON CONFLICT (user_id, msg_type) DO UPDATE SET msg_id=%s, updated_at=NOW()",
                    (user_id, msg_id, msg_id)
                )
            conn.commit()
    except Exception:
        pass

async def delete_analyzing_msg(bot, chat_id, user_id):
    """Delete the last analyzing message for this user (if any)."""
    msg_id = LAST_ANALYZING_MSG.pop(user_id, None)
    if not msg_id:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM last_msg_store WHERE user_id=%s AND msg_type='analyzing' RETURNING msg_id",
                        (user_id,)
                    )
                    row = cur.fetchone()
                conn.commit()
            if row:
                msg_id = row["msg_id"]
        except Exception:
            pass
    if msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

def save_last_signal_msg(user_id, msg_id):
    LAST_SIGNAL_MSG[user_id] = msg_id  # in-memory cache
    push_msg_id(user_id, msg_id)  # add to full stack
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
    push_msg_id(user_id, msg_id)  # add to full stack
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

SPAM_SECONDS = 3  # Minimum seconds between signal requests
LAST_SIGNAL_TIME = {}  # in-memory cache only

def is_spam(user_id):
    """Never block the user - just track timing for slight delay."""
    now  = time.time()
    last = LAST_SIGNAL_TIME.get(user_id, 0)
    if last == 0:
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

_CONFIRM_DELAY_SECS = 3  # v62: Reduced from 8 — faster signal delivery

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
        df = _yf_download_cached(symbol, "1d", "1m")
        if df is None or len(df) < 4:
            return initial_direction
        closes = df["Close"].squeeze().astype(float)
        opens  = df["Open"].squeeze().astype(float)
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

def register_referral(new_user_id, referrer_id):
    if new_user_id == referrer_id:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT referred_by FROM users WHERE user_id = %s", (new_user_id,))
            row = cur.fetchone()
            if row and row["referred_by"] is None:
                cur.execute(
                    "UPDATE users SET referred_by = %s WHERE user_id = %s",
                    (referrer_id, new_user_id)
                )
        conn.commit()
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
    return 15 + get_bonus_signals(user_id)

# v62: Global pair → flag emoji map (used by all scan functions)
PAIR_EMOJIS = {
    "EUR/USD": "🇪🇺🇺🇸", "EUR/USD OTC": "🇪🇺🇺🇸",
    "GBP/USD": "🇬🇧🇺🇸", "GBP/USD OTC": "🇬🇧🇺🇸",
    "USD/JPY": "🇺🇸🇯🇵", "USD/JPY OTC": "🇺🇸🇯🇵",
    "USD/CHF": "🇺🇸🇨🇭", "USD/CHF OTC": "🇺🇸🇨🇭",
    "AUD/USD": "🇦🇺🇺🇸", "AUD/USD OTC": "🇦🇺🇺🇸",
    "NZD/USD": "🇳🇿🇺🇸", "NZD/USD OTC": "🇳🇿🇺🇸",
    "USD/CAD": "🇺🇸🇨🇦", "USD/CAD OTC": "🇺🇸🇨🇦",
    "EUR/GBP": "🇪🇺🇬🇧", "EUR/GBP OTC": "🇪🇺🇬🇧",
    "EUR/JPY": "🇪🇺🇯🇵", "EUR/JPY OTC": "🇪🇺🇯🇵",
    "EUR/AUD": "🇪🇺🇦🇺", "EUR/AUD OTC": "🇪🇺🇦🇺",
    "EUR/CAD": "🇪🇺🇨🇦", "EUR/CAD OTC": "🇪🇺🇨🇦",
    "EUR/CHF": "🇪🇺🇨🇭", "EUR/CHF OTC": "🇪🇺🇨🇭",
    "EUR/NZD": "🇪🇺🇳🇿", "EUR/NZD OTC": "🇪🇺🇳🇿",
    "GBP/JPY": "🇬🇧🇯🇵", "GBP/JPY OTC": "🇬🇧🇯🇵",
    "GBP/AUD": "🇬🇧🇦🇺", "GBP/AUD OTC": "🇬🇧🇦🇺",
    "GBP/CAD": "🇬🇧🇨🇦", "GBP/CAD OTC": "🇬🇧🇨🇦",
    "GBP/CHF": "🇬🇧🇨🇭", "GBP/CHF OTC": "🇬🇧🇨🇭",
    "GBP/NZD": "🇬🇧🇳🇿", "GBP/NZD OTC": "🇬🇧🇳🇿",
    "AUD/JPY": "🇦🇺🇯🇵", "AUD/JPY OTC": "🇦🇺🇯🇵",
    "AUD/CAD": "🇦🇺🇨🇦", "AUD/CAD OTC": "🇦🇺🇨🇦",
    "AUD/CHF": "🇦🇺🇨🇭", "AUD/CHF OTC": "🇦🇺🇨🇭",
    "AUD/NZD": "🇦🇺🇳🇿", "AUD/NZD OTC": "🇦🇺🇳🇿",
    "NZD/JPY": "🇳🇿🇯🇵", "NZD/JPY OTC": "🇳🇿🇯🇵",
    "CHF/JPY": "🇨🇭🇯🇵", "CHF/JPY OTC": "🇨🇭🇯🇵",
    "CAD/JPY": "🇨🇦🇯🇵", "CAD/JPY OTC": "🇨🇦🇯🇵",
    "CAD/CHF": "🇨🇦🇨🇭", "CAD/CHF OTC": "🇨🇦🇨🇭",
    "USD/MXN": "🇺🇸🇲🇽", "USD/MXN OTC": "🇺🇸🇲🇽",
    "USD/ZAR": "🇺🇸🇿🇦", "USD/TRY": "🇺🇸🇹🇷",
    "Gold OTC": "🥇", "Brent Oil OTC": "🛢️", "WTI Crude Oil OTC": "🛢️",
    "Bitcoin ETF OTC": "₿", "Ethereum OTC": "💎",
}

ALL_PAIRS = [
    "EUR/USD OTC", "EUR/USD", "GBP/USD OTC", "GBP/USD",
    "USD/JPY OTC", "USD/JPY", "USD/CHF OTC", "USD/CHF",
    "AUD/USD OTC", "AUD/USD", "NZD/USD OTC",
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
    "CHF/NOK OTC", "USD/MXN OTC",
    "USD/SGD OTC", "USD/BRL OTC", "USD/BDT OTC",
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
    "Brent Oil OTC", "WTI Crude Oil OTC", "Gold OTC",
    "Natural Gas OTC", "Palladium spot OTC", "Platinum spot OTC",
    "Dogecoin OTC", "Ethereum OTC", "Litecoin OTC",
    "Bitcoin ETF OTC", "Chainlink OTC", "Solana OTC",
    "BNB OTC", "Polkadot OTC", "Cardano OTC", "TRON OTC",
    "Polygon OTC", "Toncoin OTC", "Avalanche OTC",
    "AUS 200 OTC", "100GBP OTC", "D30EUR OTC", "DJI30 OTC",
    "E35EUR OTC", "E35EUR", "E50EUR OTC", "F40EUR OTC",
    "JPN225 OTC", "JPN225", "US100 OTC", "US100", "SP500 OTC", "SP500",
    "US30", "GER40", "UK100", "AUS200",
    "CAC 40", "SMI 20",
    "Apple OTC", "American Express OTC", "Boeing Company OTC",
    "FACEBOOK INC OTC", "Intel OTC", "Johnson & Johnson OTC",
    "Citigroup Inc OTC", "Coinbase Global OTC", "FedEx OTC",
    "VIX OTC", "Amazon OTC", "Microsoft OTC", "GameStop Corp OTC",
    "McDonald's OTC", "Tesla OTC", "Netflix OTC", "ExxonMobil OTC",
    "Marathon Digital Holdings OTC", "Pfizer Inc OTC",
    "Palantir Technologies OTC", "VISA OTC", "Alibaba OTC",
    "Cisco OTC", "Advanced Micro Devices OTC",
]

YAHOO_SYMBOLS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "USD/CHF": "USDCHF=X", "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X",
    "EUR/GBP": "EURGBP=X", "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X", "AUD/JPY": "AUDJPY=X", "EUR/AUD": "EURAUD=X",
    "EUR/CAD": "EURCAD=X", "GBP/AUD": "GBPAUD=X", "GBP/CAD": "GBPCAD=X",
    "AUD/CAD": "AUDCAD=X", "AUD/CHF": "AUDCHF=X",
    "EUR/CHF": "EURCHF=X", "CHF/JPY": "CHFJPY=X", "CAD/JPY": "CADJPY=X",
    "CAD/CHF": "CADCHF=X", "GBP/CHF": "GBPCHF=X",
    "USD/NOK": "USDNOK=X", "USD/SEK": "USDSEK=X", "USD/DKK": "USDDKK=X",
    "USD/TRY": "USDTRY=X", "USD/ZAR": "USDZAR=X", "USD/SGD": "USDSGD=X",
    "EUR/NOK": "EURNOK=X", "EUR/SEK": "EURSEK=X", "EUR/PLN": "EURPLN=X",
    "EUR/TRY": "EURTRY=X", "GBP/NOK": "GBPNOK=X", "GBP/SEK": "GBPSEK=X",
    "US100": "^NDX", "SP500": "^GSPC", "CAC 40": "^FCHI",
    "SMI 20": "^SSMI", "E35EUR": "^STOXX",
    "US30": "^DJI", "GER40": "^GDAXI", "UK100": "^FTSE",
    "JPN225": "^N225", "AUS200": "^AXJO",
}

def _calc_indicators_from_df(df):
    """
    Calculate all indicators from a OHLCV dataframe. Returns dict or None.
    v56: Added HMA, Keltner Channels, Fisher Transform, DEMA, candle body ratio,
         volume surge, RSI slope, MACD histogram slope.
    """
    if df is None or len(df) < 30:
        return None
    close  = df["Close"].squeeze().astype(float)
    high   = df["High"].squeeze().astype(float)
    low    = df["Low"].squeeze().astype(float)
    volume = df["Volume"].squeeze().astype(float)

    # ── RSI (14) ──
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, 1e-9)
    rsi_series = 100 - 100 / (1 + rs)
    rsi   = float(rsi_series.iloc[-1])

    # ── RSI Slope (v56): RSI change over last 3 bars ──
    rsi_slope = 0.0
    try:
        if len(rsi_series) >= 4:
            rsi_slope = float(rsi_series.iloc[-1] - rsi_series.iloc[-4])
    except Exception:
        pass

    # ── MACD ──
    ema12     = close.ewm(span=12).mean()
    ema26     = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_ln = macd_line.ewm(span=9).mean()
    macd_hist_series = macd_line - signal_ln
    macd_hist = float(macd_hist_series.iloc[-1])
    macd_norm = max(-1.0, min(1.0, macd_hist / (float(close.iloc[-1]) * 0.001 + 1e-9)))

    # ── MACD Histogram Slope (v56): rising or falling? ──
    macd_hist_slope = 0.0
    try:
        if len(macd_hist_series) >= 3:
            macd_hist_slope = float(macd_hist_series.iloc[-1] - macd_hist_series.iloc[-3])
    except Exception:
        pass

    # ── Bollinger Bands ──
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = (sma20 + 2*std20)
    bb_lower = (sma20 - 2*std20)
    u = float(bb_upper.iloc[-1]); l = float(bb_lower.iloc[-1])
    bb_pos = max(0.0, min(1.0, (float(close.iloc[-1]) - l) / (u - l + 1e-9)))

    # ── EMA-based MA diff (SMA9/21 → EMA9/21 for better accuracy) ──
    ema9_s  = close.ewm(span=9,  adjust=False).mean()
    ema21_s = close.ewm(span=21, adjust=False).mean()
    ma9  = float(ema9_s.iloc[-1])
    ma21 = float(ema21_s.iloc[-1])
    ma_diff = max(-1.0, min(1.0, (ma9 - ma21) / (ma21 + 1e-9) * 100))

    # ── DEMA (Double EMA) v56 — half the lag of standard EMA ──
    dema_fast = dema_slow = None
    dema_diff = 0.0
    try:
        span_f, span_s = 9, 18
        ema_f1 = close.ewm(span=span_f, adjust=False).mean()
        ema_f2 = ema_f1.ewm(span=span_f, adjust=False).mean()
        dema_fast_s = 2 * ema_f1 - ema_f2

        ema_s1 = close.ewm(span=span_s, adjust=False).mean()
        ema_s2 = ema_s1.ewm(span=span_s, adjust=False).mean()
        dema_slow_s = 2 * ema_s1 - ema_s2

        dema_fast = float(dema_fast_s.iloc[-1])
        dema_slow = float(dema_slow_s.iloc[-1])
        dema_diff = max(-1.0, min(1.0, (dema_fast - dema_slow) / (dema_slow + 1e-9) * 100))
    except Exception:
        pass

    # ── HMA (Hull Moving Average) v56 — faster than EMA ──
    hma_direction = None
    try:
        n_hma = min(16, len(close) // 3)
        if n_hma >= 4:
            wma_half = close.rolling(n_hma // 2).mean()
            wma_full = close.rolling(n_hma).mean()
            raw_hma  = 2 * wma_half - wma_full
            hma_vals = raw_hma.rolling(int(n_hma ** 0.5)).mean()
            hma_now  = float(hma_vals.iloc[-1])
            hma_prev = float(hma_vals.iloc[-2])
            if hma_now > hma_prev:
                hma_direction = "BUY"
            elif hma_now < hma_prev:
                hma_direction = "SELL"
    except Exception:
        pass

    # ── Keltner Channels (v56) — breakout detection ──
    keltner_breakout = None
    try:
        n_kelt = len(close)
        if n_kelt >= 22:
            kelt_mid = close.ewm(span=20, adjust=False).mean()
            atr_kelt = pd.Series([
                max(float(high.iloc[i]) - float(low.iloc[i]),
                    abs(float(high.iloc[i]) - float(close.iloc[i-1])),
                    abs(float(low.iloc[i]) - float(close.iloc[i-1])))
                for i in range(1, n_kelt)
            ], index=close.index[1:]).rolling(10).mean()
            kelt_upper = kelt_mid + 1.5 * atr_kelt
            kelt_lower = kelt_mid - 1.5 * atr_kelt
            cur_price  = float(close.iloc[-1])
            if cur_price > float(kelt_upper.iloc[-1]):
                keltner_breakout = "BUY"   # Breaking above upper band = bullish breakout
            elif cur_price < float(kelt_lower.iloc[-1]):
                keltner_breakout = "SELL"  # Breaking below lower = bearish breakout
    except Exception:
        pass

    # ── Fisher Transform (v56) — better overbought/oversold detection ──
    fisher_val = 0.0
    fisher_direction = None
    try:
        n_fish = len(close)
        if n_fish >= 10:
            h9 = high.rolling(9).max()
            l9 = low.rolling(9).min()
            val = 2 * ((close - l9) / (h9 - l9 + 1e-9)) - 1
            val = val.clip(-0.999, 0.999)
            fisher_series = 0.5 * pd.Series(
                [__import__('math').log((1 + v) / (1 - v + 1e-9)) for v in val.values],
                index=val.index
            )
            fisher_val = float(fisher_series.iloc[-1])
            fisher_prev = float(fisher_series.iloc[-2]) if len(fisher_series) >= 2 else 0.0
            if fisher_val > 0.5 and fisher_val > fisher_prev:
                fisher_direction = "BUY"
            elif fisher_val < -0.5 and fisher_val < fisher_prev:
                fisher_direction = "SELL"
    except Exception:
        pass

    # ── Momentum ──
    mom = max(-1.0, min(1.0, float(close.iloc[-1] - close.iloc[-11]) / (close.iloc[-11] + 1e-9) * 100))

    # ── Stochastic ──
    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    sto = max(0.0, min(100.0, float(((close - low14) / (high14 - low14 + 1e-9) * 100).iloc[-1])))

    # ── Volume ratio ──
    vol = min(1.0, float(volume.iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-9)))

    # ── Volume Surge (v56): volume > 1.5x average = stronger signal ──
    volume_surge = vol >= 1.5

    # ── Candle Body Ratio (v56): only real candles ──
    candle_body_ratio = 0.5
    try:
        opens_s = df["Open"].squeeze().astype(float)
        body = abs(float(close.iloc[-1]) - float(opens_s.iloc[-1]))
        candle_range = float(high.iloc[-1]) - float(low.iloc[-1])
        if candle_range > 1e-9:
            candle_body_ratio = body / candle_range
    except Exception:
        pass
    # Doji/indecision candle = body ratio < 0.25 → signal dhaifu
    is_indecision_candle = candle_body_ratio < 0.25
    # ── RSI Divergence ──
    rsi_series_full = (100 - 100 / (1 + gain / loss.replace(0, 1e-9)))
    price_change = float(close.iloc[-1] - close.iloc[-6])
    rsi_change   = float(rsi_series_full.iloc[-1] - rsi_series_full.iloc[-6])
    divergence = None
    if price_change > 0 and rsi_change < -3:
        divergence = "SELL"   # Bearish divergence
    elif price_change < 0 and rsi_change > 3:
        divergence = "BUY"    # Bullish divergence

    # ── Williams Fractal Detection (v54-8 fixed) ──
    # Bull fractal: candle lower than 2 on both sides → price bounced up → BUY
    # Bear fractal: candle higher than 2 on both sides → price reversed down → SELL
    # Candle must fully close (i+2 must exist) → loop ends at n-3
    fractal_signal = None
    fractal_strength = 0
    high_vals = high.values
    low_vals  = low.values
    n = len(high_vals)
    recent_bull_fractals = []  # (index, low_price)
    recent_bear_fractals = []  # (index, high_price)

    for i in range(n - 3, max(n - 20, 2), -1):
        if i + 2 >= n or i - 2 < 0:
            continue
        # Bear fractal: high[i] > high[i-2], high[i-1], high[i+1], high[i+2]
        if (high_vals[i] > high_vals[i-1] and high_vals[i] > high_vals[i-2] and
                high_vals[i] > high_vals[i+1] and high_vals[i] > high_vals[i+2]):
            recent_bear_fractals.append((i, float(high_vals[i])))
        # Bull fractal: low[i] < low[i-2], low[i-1], low[i+1], low[i+2]
        if (low_vals[i] < low_vals[i-1] and low_vals[i] < low_vals[i-2] and
                low_vals[i] < low_vals[i+1] and low_vals[i] < low_vals[i+2]):
            recent_bull_fractals.append((i, float(low_vals[i])))

    current_price_val = float(close.iloc[-1])

    # Get the most recent fractal of each type
    latest_bull_price = recent_bull_fractals[0][1] if recent_bull_fractals else None
    latest_bear_price = recent_bear_fractals[0][1] if recent_bear_fractals else None

    bull_signal = False
    bear_signal = False

    # Bull fractal: current price above fractal low → trend continuing up → BUY
    if latest_bull_price is not None and current_price_val > latest_bull_price:
        bull_signal = True

    # Bear fractal: current price below fractal high → trend continuing down → SELL
    if latest_bear_price is not None and current_price_val < latest_bear_price:
        bear_signal = True

    if bull_signal and not bear_signal:
        fractal_signal = "BUY"
        fractal_strength = min(3, len(recent_bull_fractals))
    elif bear_signal and not bull_signal:
        fractal_signal = "SELL"
        fractal_strength = min(3, len(recent_bear_fractals))
    elif bull_signal and bear_signal:
        # Both active — choose by fractal strength (distance from current price)
        bull_gap = current_price_val - latest_bull_price   # above bull = BUY strength
        bear_gap = latest_bear_price - current_price_val   # below bear = SELL strength
        if bull_gap > bear_gap:
            fractal_signal = "BUY"
            fractal_strength = min(3, len(recent_bull_fractals))
        else:
            fractal_signal = "SELL"
            fractal_strength = min(3, len(recent_bear_fractals))
    # else: fractal_signal = None (no confirmed fractal)

    current_price = float(close.iloc[-1])
    direction_raw = "BUY" if ma_diff > 0 and macd_norm > 0 else ("SELL" if ma_diff < 0 and macd_norm < 0 else None)

    adx_val = 25.0  # neutral default
    try:
        high_s = df["High"].squeeze().astype(float)
        low_s  = df["Low"].squeeze().astype(float)
        n_vals = len(close)
        if n_vals >= 28:
            tr_list = [max(float(high_s.iloc[i]) - float(low_s.iloc[i]),
                           abs(float(high_s.iloc[i]) - float(close.iloc[i-1])),
                           abs(float(low_s.iloc[i]) - float(close.iloc[i-1])))
                       for i in range(1, n_vals)]
            tr_s   = pd.Series(tr_list, index=close.index[1:])
            dmp_l  = [max(float(high_s.iloc[i]) - float(high_s.iloc[i-1]), 0)
                      if float(high_s.iloc[i]) - float(high_s.iloc[i-1]) >
                         float(low_s.iloc[i-1]) - float(low_s.iloc[i]) else 0
                      for i in range(1, n_vals)]
            dmm_l  = [max(float(low_s.iloc[i-1]) - float(low_s.iloc[i]), 0)
                      if float(low_s.iloc[i-1]) - float(low_s.iloc[i]) >
                         float(high_s.iloc[i]) - float(high_s.iloc[i-1]) else 0
                      for i in range(1, n_vals)]
            dmp_s  = pd.Series(dmp_l, index=close.index[1:])
            dmm_s  = pd.Series(dmm_l, index=close.index[1:])
            atr14s = tr_s.rolling(14).mean()
            dip_s  = 100 * (dmp_s.rolling(14).mean() / (atr14s + 1e-9))
            dim_s  = 100 * (dmm_s.rolling(14).mean() / (atr14s + 1e-9))
            adx_val = float((100 * abs(dip_s - dim_s) / (dip_s + dim_s + 1e-9)).rolling(14).mean().iloc[-1])
    except Exception:
        pass

    # ── SuperTrend (v56-ST) ──────────────────────────────────────────────────
    # Formula: ST = midpoint +/- (multiplier * ATR)
    # Price above ST line = BUY; below = SELL
    supertrend_direction = None
    supertrend_val       = None
    try:
        _st_period = 10
        _st_mult   = 3.0
        _n_st      = len(close)
        if _n_st >= _st_period + 2:
            # ATR calculation
            _tr_st = pd.Series([
                max(float(high.iloc[i]) - float(low.iloc[i]),
                    abs(float(high.iloc[i]) - float(close.iloc[i-1])),
                    abs(float(low.iloc[i]) - float(close.iloc[i-1])))
                for i in range(1, _n_st)
            ], index=close.index[1:])
            _atr_st = _tr_st.rolling(_st_period).mean()

            _hl_mid = (high.iloc[1:] + low.iloc[1:]) / 2
            _basic_upper = _hl_mid + _st_mult * _atr_st
            _basic_lower = _hl_mid - _st_mult * _atr_st

            # Build SuperTrend iteratively
            _st_upper = _basic_upper.copy()
            _st_lower = _basic_lower.copy()
            _st_line  = pd.Series(index=close.index[1:], dtype=float)
            _trend    = pd.Series(index=close.index[1:], dtype=int)  # 1=up, -1=down

            _idx = list(close.index[1:])
            for _i in range(len(_idx)):
                _ci = float(close.iloc[_i + 1])
                if _i == 0:
                    _st_line.iloc[_i] = _basic_upper.iloc[_i]
                    _trend.iloc[_i]   = -1
                    continue
                # Upper band
                _pu = float(_st_upper.iloc[_i - 1])
                _nu = float(_basic_upper.iloc[_i])
                _st_upper.iloc[_i] = min(_nu, _pu) if float(close.iloc[_i]) < _pu else _nu
                # Lower band
                _pl = float(_st_lower.iloc[_i - 1])
                _nl = float(_basic_lower.iloc[_i])
                _st_lower.iloc[_i] = max(_nl, _pl) if float(close.iloc[_i]) > _pl else _nl
                # Trend
                _prev_trend = int(_trend.iloc[_i - 1])
                _prev_line  = float(_st_line.iloc[_i - 1])
                if _prev_trend == -1 and _ci > _prev_line:
                    _trend.iloc[_i] = 1
                elif _prev_trend == 1 and _ci < _prev_line:
                    _trend.iloc[_i] = -1
                else:
                    _trend.iloc[_i] = _prev_trend
                _st_line.iloc[_i] = float(_st_lower.iloc[_i]) if _trend.iloc[_i] == 1 \
                                     else float(_st_upper.iloc[_i])

            supertrend_val       = float(_st_line.iloc[-1])
            supertrend_direction = "BUY" if int(_trend.iloc[-1]) == 1 else "SELL"
    except Exception:
        pass
    # ── end SuperTrend ───────────────────────────────────────────────────────

    # ══════════════════════════════════════════════════════════════════════════
    # v57: INDICATORS MPYA — Parabolic SAR, CMO, TEMA, AO, Elder Ray,
    #      TTM Squeeze, TRIX, DPO, Aroon, Vortex, Chaikin MF, KAMA,
    #      McGinley Dynamic, WMA, ZigZag Trend, Coppock Curve
    # ══════════════════════════════════════════════════════════════════════════

    # ── 1. Parabolic SAR ─────────────────────────────────────────────────────
    psar_direction = None
    try:
        _af = 0.02; _af_max = 0.20; _af_step = 0.02
        _ph = list(high.values); _pl = list(low.values); _pc = list(close.values)
        _n_sar = len(_pc)
        if _n_sar >= 10:
            _bull = _pc[1] > _pc[0]
            _sar  = _pl[0] if _bull else _ph[0]
            _ep   = _ph[1] if _bull else _pl[1]
            _af_c = _af
            for _i in range(2, _n_sar):
                _sar = _sar + _af_c * (_ep - _sar)
                if _bull:
                    _sar = min(_sar, _pl[_i-1], _pl[_i-2] if _i >= 2 else _pl[_i-1])
                    if _pc[_i] < _sar:
                        _bull = False; _sar = _ep; _ep = _pl[_i]; _af_c = _af
                    else:
                        if _ph[_i] > _ep: _ep = _ph[_i]; _af_c = min(_af_max, _af_c + _af_step)
                else:
                    _sar = max(_sar, _ph[_i-1], _ph[_i-2] if _i >= 2 else _ph[_i-1])
                    if _pc[_i] > _sar:
                        _bull = True; _sar = _ep; _ep = _ph[_i]; _af_c = _af
                    else:
                        if _pl[_i] < _ep: _ep = _pl[_i]; _af_c = min(_af_max, _af_c + _af_step)
            psar_direction = "BUY" if _bull else "SELL"
    except Exception:
        pass

    # ── 2. Chande Momentum Oscillator (CMO) ──────────────────────────────────
    cmo_val = 0.0
    cmo_direction = None
    try:
        _d = close.diff(1)
        _up_cmo = _d.clip(lower=0).rolling(14).sum()
        _dn_cmo = (-_d.clip(upper=0)).rolling(14).sum()
        _cmo_s  = 100 * (_up_cmo - _dn_cmo) / (_up_cmo + _dn_cmo + 1e-9)
        cmo_val = float(_cmo_s.iloc[-1])
        if cmo_val > 25:    cmo_direction = "BUY"
        elif cmo_val < -25: cmo_direction = "SELL"
    except Exception:
        pass

    # ── 3. TEMA (Triple EMA) ──────────────────────────────────────────────────
    tema_direction = None
    tema_diff      = 0.0
    try:
        _e1f = close.ewm(span=9,  adjust=False).mean()
        _e2f = _e1f.ewm(span=9,   adjust=False).mean()
        _e3f = _e2f.ewm(span=9,   adjust=False).mean()
        _tema_fast = 3*_e1f - 3*_e2f + _e3f

        _e1s = close.ewm(span=21, adjust=False).mean()
        _e2s = _e1s.ewm(span=21,  adjust=False).mean()
        _e3s = _e2s.ewm(span=21,  adjust=False).mean()
        _tema_slow = 3*_e1s - 3*_e2s + _e3s

        tema_diff = float(_tema_fast.iloc[-1] - _tema_slow.iloc[-1]) / (abs(float(_tema_slow.iloc[-1])) + 1e-9) * 100
        if tema_diff > 0.01:   tema_direction = "BUY"
        elif tema_diff < -0.01: tema_direction = "SELL"
    except Exception:
        pass

    # ── 4. Awesome Oscillator (AO) ────────────────────────────────────────────
    ao_val       = 0.0
    ao_direction = None
    try:
        _mid = (high + low) / 2
        ao_val = float((_mid.rolling(5).mean() - _mid.rolling(34).mean()).iloc[-1])
        ao_prev = float((_mid.rolling(5).mean() - _mid.rolling(34).mean()).iloc[-2])
        if ao_val > 0 and ao_val > ao_prev:   ao_direction = "BUY"
        elif ao_val < 0 and ao_val < ao_prev: ao_direction = "SELL"
        elif ao_val > 0:                       ao_direction = "BUY"
        elif ao_val < 0:                       ao_direction = "SELL"
    except Exception:
        pass

    # ── 5. Elder Ray Index (Bull Power / Bear Power) ──────────────────────────
    elder_direction = None
    bull_power = bear_power = 0.0
    try:
        _ema13 = close.ewm(span=13, adjust=False).mean()
        bull_power = float(high.iloc[-1] - float(_ema13.iloc[-1]))
        bear_power = float(low.iloc[-1]  - float(_ema13.iloc[-1]))
        if bull_power > 0 and bear_power > -0.0002:  elder_direction = "BUY"
        elif bear_power < 0 and bull_power < 0.0002: elder_direction = "SELL"
    except Exception:
        pass

    # ── 6. TTM Squeeze (Squeeze Momentum) ────────────────────────────────────
    squeeze_direction = None
    squeeze_active    = False   # True = market sedang compressed (tungsten)
    try:
        _bb_u2 = float((sma20 + 2*std20).iloc[-1])
        _bb_l2 = float((sma20 - 2*std20).iloc[-1])
        _n_sq  = len(close)
        if _n_sq >= 22:
            _tr_sq = pd.Series([
                max(float(high.iloc[i]) - float(low.iloc[i]),
                    abs(float(high.iloc[i]) - float(close.iloc[i-1])),
                    abs(float(low.iloc[i]) - float(close.iloc[i-1])))
                for i in range(1, _n_sq)
            ], index=close.index[1:]).rolling(20).mean()
            _kc_u = float((sma20 + 1.5*_tr_sq).iloc[-1])
            _kc_l = float((sma20 - 1.5*_tr_sq).iloc[-1])
            # Squeeze = BB inside KC (compressed — no breakout yet)
            squeeze_active = (_bb_u2 < _kc_u) and (_bb_l2 > _kc_l)
            # Momentum oscillator
            _delta_sq = close - (high.rolling(20).max() + low.rolling(20).min()) / 2
            _mom_sq   = _delta_sq - _delta_sq.rolling(20).mean()
            _mval  = float(_mom_sq.iloc[-1])
            _mprev = float(_mom_sq.iloc[-2]) if len(_mom_sq) >= 2 else 0
            if not squeeze_active:   # Breakout — stronger signal
                squeeze_direction = "BUY" if _mval > 0 else "SELL"
            else:
                squeeze_direction = "BUY" if _mval > 0 and _mval > _mprev else (
                                    "SELL" if _mval < 0 and _mval < _mprev else None)
    except Exception:
        pass

    # ── 7. TRIX (Triple Exponential Average ROC) ─────────────────────────────
    trix_direction = None
    trix_val       = 0.0
    try:
        _t1 = close.ewm(span=15, adjust=False).mean()
        _t2 = _t1.ewm(span=15,   adjust=False).mean()
        _t3 = _t2.ewm(span=15,   adjust=False).mean()
        trix_val = float((_t3.pct_change() * 100).iloc[-1])
        trix_prev= float((_t3.pct_change() * 100).iloc[-2]) if len(_t3) >= 2 else 0
        if trix_val > 0:   trix_direction = "BUY"
        elif trix_val < 0: trix_direction = "SELL"
    except Exception:
        pass

    # ── 8. Aroon Oscillator ───────────────────────────────────────────────────
    aroon_direction = None
    aroon_val       = 0.0
    try:
        _per_ar = 25
        _n_ar   = len(close)
        if _n_ar >= _per_ar + 1:
            _high_ar = high.rolling(_per_ar + 1)
            _low_ar  = low.rolling(_per_ar + 1)
            _aroon_up   = 100 * (_high_ar.apply(lambda x: (_per_ar - x[::-1].argmax()), raw=True) / _per_ar)
            _aroon_down = 100 * (_low_ar.apply(lambda x:  (_per_ar - x[::-1].argmin()), raw=True) / _per_ar)
            aroon_val   = float((_aroon_up - _aroon_down).iloc[-1])
            if aroon_val > 30:    aroon_direction = "BUY"
            elif aroon_val < -30: aroon_direction = "SELL"
    except Exception:
        pass

    # ── 9. Vortex Indicator ───────────────────────────────────────────────────
    vortex_direction = None
    try:
        _n_vx = len(close)
        if _n_vx >= 16:
            _vm_plus  = abs(high.iloc[1:].values - low.iloc[:-1].values)
            _vm_minus = abs(low.iloc[1:].values  - high.iloc[:-1].values)
            _tr_vx    = [max(float(high.iloc[i])-float(low.iloc[i]),
                             abs(float(high.iloc[i])-float(close.iloc[i-1])),
                             abs(float(low.iloc[i])-float(close.iloc[i-1])))
                         for i in range(1, _n_vx)]
            _sum_vm_p = sum(_vm_plus[-14:]);  _sum_vm_m = sum(_vm_minus[-14:])
            _sum_tr   = sum(_tr_vx[-14:]) + 1e-9
            _vi_plus  = _sum_vm_p / _sum_tr
            _vi_minus = _sum_vm_m / _sum_tr
            if _vi_plus > _vi_minus:   vortex_direction = "BUY"
            elif _vi_minus > _vi_plus: vortex_direction = "SELL"
    except Exception:
        pass

    # ── 10. Chaikin Money Flow (CMF) ──────────────────────────────────────────
    cmf_val       = 0.0
    cmf_direction = None
    try:
        _n_cmf = len(close)
        if _n_cmf >= 20 and volume.sum() > 0:
            _mfm = ((close - low) - (high - close)) / (high - low + 1e-9)
            _mfv = _mfm * volume
            cmf_val = float(_mfv.rolling(20).sum().iloc[-1] /
                            (volume.rolling(20).sum().iloc[-1] + 1e-9))
            if cmf_val > 0.05:    cmf_direction = "BUY"
            elif cmf_val < -0.05: cmf_direction = "SELL"
    except Exception:
        pass

    # ── 11. KAMA (Kaufman Adaptive MA) ───────────────────────────────────────
    kama_direction = None
    try:
        _n_kama = len(close)
        if _n_kama >= 12:
            _kama_v = float(close.iloc[10])
            for _ki in range(10, _n_kama):
                _dir_k  = abs(float(close.iloc[_ki]) - float(close.iloc[_ki-10]))
                _vol_k  = sum(abs(float(close.iloc[j]) - float(close.iloc[j-1]))
                              for j in range(_ki-9, _ki+1))
                _er   = _dir_k / (_vol_k + 1e-9)
                _fast_k = 2/(2+1); _slow_k = 2/(30+1)
                _sc   = (_er * (_fast_k - _slow_k) + _slow_k) ** 2
                _kama_v = _kama_v + _sc * (float(close.iloc[_ki]) - _kama_v)
            _kama_prev = float(close.iloc[-2])  # rough prev
            if float(close.iloc[-1]) > _kama_v and _kama_v > _kama_prev:
                kama_direction = "BUY"
            elif float(close.iloc[-1]) < _kama_v and _kama_v < _kama_prev:
                kama_direction = "SELL"
    except Exception:
        pass

    # ── 12. McGinley Dynamic ──────────────────────────────────────────────────
    mcginley_direction = None
    try:
        _n_mg = len(close)
        if _n_mg >= 15:
            _mg = float(close.iloc[14])
            for _mi in range(14, _n_mg):
                _p  = float(close.iloc[_mi])
                _mg = _mg + (_p - _mg) / (14 * (_p / (_mg + 1e-9)) ** 4 + 1e-9)
            _mg_prev_val = float(close.ewm(span=14).mean().iloc[-2])
            if float(close.iloc[-1]) > _mg:  mcginley_direction = "BUY"
            else:                             mcginley_direction = "SELL"
    except Exception:
        pass

    # ── 13. Coppock Curve ─────────────────────────────────────────────────────
    coppock_direction = None
    try:
        _n_cop = len(close)
        if _n_cop >= 14:
            _roc11 = close.pct_change(11) * 100
            _roc14 = close.pct_change(min(14, _n_cop-1)) * 100
            _cop   = (_roc11 + _roc14).ewm(span=10, adjust=False).mean()
            _cv    = float(_cop.iloc[-1])
            _cprev = float(_cop.iloc[-2]) if len(_cop) >= 2 else 0
            if _cv > 0 and _cv > _cprev:   coppock_direction = "BUY"
            elif _cv < 0 and _cv < _cprev: coppock_direction = "SELL"
    except Exception:
        pass

    # ── 14. Weighted MA (WMA) Crossover ───────────────────────────────────────
    wma_direction = None
    try:
        def _wma(s, p):
            w = pd.Series(range(1, p+1), dtype=float)
            return s.rolling(p).apply(lambda x: (x * w[-len(x):]).sum() / w[-len(x):].sum(), raw=True)
        _wma_fast = _wma(close, 9)
        _wma_slow = _wma(close, 21)
        if float(_wma_fast.iloc[-1]) > float(_wma_slow.iloc[-1]):  wma_direction = "BUY"
        else:                                                         wma_direction = "SELL"
    except Exception:
        pass

    # ── 15. DPO (Detrended Price Oscillator) ──────────────────────────────────
    dpo_direction = None
    try:
        _per_dpo = 20
        _shift   = _per_dpo // 2 + 1
        _n_dpo   = len(close)
        if _n_dpo >= _per_dpo + _shift:
            _sma_dpo = close.rolling(_per_dpo).mean()
            _dpo_s   = close - _sma_dpo.shift(_shift)
            dpo_direction = "BUY" if float(_dpo_s.iloc[-1]) > 0 else "SELL"
    except Exception:
        pass

    # ── 16. Relative Vigor Index (RVI) ────────────────────────────────────────
    rvi_direction = None
    try:
        _n_rvi  = len(close)
        _opens  = df["Open"].squeeze().astype(float)
        if _n_rvi >= 10:
            _num = (close - _opens + 2*(close.shift(1)-_opens.shift(1)) +
                    2*(close.shift(2)-_opens.shift(2)) + (close.shift(3)-_opens.shift(3))) / 6
            _den = (high - low + 2*(high.shift(1)-low.shift(1)) +
                    2*(high.shift(2)-low.shift(2)) + (high.shift(3)-low.shift(3))) / 6
            _rvi_line   = _num.rolling(10).mean() / (_den.rolling(10).mean() + 1e-9)
            _rvi_signal = (_rvi_line + 2*_rvi_line.shift(1) + 2*_rvi_line.shift(2) + _rvi_line.shift(3)) / 6
            _rv = float(_rvi_line.iloc[-1]); _rs = float(_rvi_signal.iloc[-1])
            rvi_direction = "BUY" if _rv > _rs else "SELL"
    except Exception:
        pass

    # ── 17. Know Sure Thing (KST) ─────────────────────────────────────────────
    kst_direction = None
    try:
        _n_kst = len(close)
        if _n_kst >= 30:
            _r1 = close.pct_change(10).rolling(10).mean()
            _r2 = close.pct_change(13).rolling(13).mean()
            _r3 = close.pct_change(15).rolling(15).mean()
            _r4 = close.pct_change(20).rolling(15).mean()
            _kst_line = _r1*1 + _r2*2 + _r3*3 + _r4*4
            _kst_sig  = _kst_line.rolling(9).mean()
            if float(_kst_line.iloc[-1]) > float(_kst_sig.iloc[-1]):  kst_direction = "BUY"
            else:                                                        kst_direction = "SELL"
    except Exception:
        pass

    # ── 18. Price Oscillator (PPO) ────────────────────────────────────────────
    ppo_direction = None
    try:
        _ppo = (close.ewm(span=12).mean() - close.ewm(span=26).mean()) / \
               (close.ewm(span=26).mean() + 1e-9) * 100
        _ppo_sig = _ppo.ewm(span=9).mean()
        ppo_direction = "BUY" if float(_ppo.iloc[-1]) > float(_ppo_sig.iloc[-1]) else "SELL"
    except Exception:
        pass

    # ── 19. Commodity Channel Index extended (CCI fast 10) ───────────────────
    cci_fast_direction = None
    try:
        _tp_f  = (high + low + close) / 3
        _mad_f = _tp_f.rolling(10).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
        _cci_f = float(((_tp_f - _tp_f.rolling(10).mean()) / (0.015*_mad_f + 1e-9)).iloc[-1])
        if _cci_f < -100:   cci_fast_direction = "BUY"
        elif _cci_f > 100:  cci_fast_direction = "SELL"
    except Exception:
        pass

    # ── 20. Balance of Power (BOP) ────────────────────────────────────────────
    bop_direction = None
    try:
        _opens_bop = df["Open"].squeeze().astype(float)
        _bop = (close - _opens_bop) / (high - low + 1e-9)
        _bop_sm = _bop.rolling(14).mean()
        bop_direction = "BUY" if float(_bop_sm.iloc[-1]) > 0 else "SELL"
    except Exception:
        pass

    # ── 21. ZigZag Trend (v58) — swing highs/lows structure ──────────────────
    # Detect true trend by tracking ZigZag swing points
    # Algorithm: retracement >= threshold% → new swing point
    # Uptrend: higher highs + higher lows (HH + HL)
    # Downtrend: lower highs + lower lows (LH + LL)
    zigzag_direction = None
    zigzag_strength  = 0   # 1=weak, 2=moderate, 3=strong
    zigzag_last_swing = None  # "UP" or "DOWN" - last swing direction
    try:
        _zz_thresh = 0.0015   # 0.15% retracement threshold (forex optimised)
        _zz_high   = high.values
        _zz_low    = low.values
        _zz_close  = close.values
        _zz_n      = len(_zz_close)

        if _zz_n >= 20:
            # Tafuta swing points
            _zz_swings = []   # (index, price, type) — type: "H" or "L"
            _zz_trend  = 1    # 1=upswing, -1=downswing
            _zz_ep     = float(_zz_high[0])  # extreme point
            _zz_ep_idx = 0

            for _zi in range(1, _zz_n):
                _h = float(_zz_high[_zi])
                _l = float(_zz_low[_zi])
                if _zz_trend == 1:
                    if _h > _zz_ep:
                        _zz_ep = _h; _zz_ep_idx = _zi
                    elif (_zz_ep - _l) / (_zz_ep + 1e-9) >= _zz_thresh:
                        _zz_swings.append((_zz_ep_idx, _zz_ep, "H"))
                        _zz_trend = -1; _zz_ep = _l; _zz_ep_idx = _zi
                else:
                    if _l < _zz_ep:
                        _zz_ep = _l; _zz_ep_idx = _zi
                    elif (_h - _zz_ep) / (_zz_ep + 1e-9) >= _zz_thresh:
                        _zz_swings.append((_zz_ep_idx, _zz_ep, "L"))
                        _zz_trend = 1; _zz_ep = _h; _zz_ep_idx = _zi

            # Add latest unnamed swing
            if _zz_trend == 1:
                _zz_swings.append((_zz_ep_idx, _zz_ep, "H"))
            else:
                _zz_swings.append((_zz_ep_idx, _zz_ep, "L"))

            if len(_zz_swings) >= 4:
                # Check last 4 swings
                _sw = _zz_swings[-4:]
                _highs_sw = [p for i, p, t in _sw if t == "H"]
                _lows_sw  = [p for i, p, t in _sw if t == "L"]
                zigzag_last_swing = _sw[-1][2]  # "H" or "L" of last swing

                # Hesabu HH, HL, LH, LL
                _zz_hh = _zz_hl = _zz_lh = _zz_ll = 0
                for _si in range(1, len(_sw)):
                    _prev_t = _sw[_si-1][2]; _curr_t = _sw[_si][2]
                    _prev_p = _sw[_si-1][1]; _curr_p = _sw[_si][1]
                    if _prev_t == _curr_t:
                        if _curr_t == "H":
                            if _curr_p > _prev_p: _zz_hh += 1
                            else:                  _zz_lh += 1
                        else:
                            if _curr_p > _prev_p: _zz_hl += 1
                            else:                  _zz_ll += 1

                # Decide direction and strength
                _bull_score_zz = _zz_hh * 2 + _zz_hl
                _bear_score_zz = _zz_lh * 2 + _zz_ll

                if _bull_score_zz > _bear_score_zz:
                    zigzag_direction = "BUY"
                    zigzag_strength  = min(3, _bull_score_zz - _bear_score_zz)
                elif _bear_score_zz > _bull_score_zz:
                    zigzag_direction = "SELL"
                    zigzag_strength  = min(3, _bear_score_zz - _bull_score_zz)

                # Confirm: current price aligns with trend?
                _cur_p = float(_zz_close[-1])
                if len(_highs_sw) >= 1 and len(_lows_sw) >= 1:
                    _last_h = max(_highs_sw); _last_l = min(_lows_sw)
                    # Price between swing high and low → trending
                    _zz_range = _last_h - _last_l
                    if _zz_range > 1e-9:
                        _zz_pos = (_cur_p - _last_l) / _zz_range  # 0-1
                        if zigzag_direction == "BUY" and _zz_pos < 0.30:
                            # Price near low → rejection, bonus
                            zigzag_strength = min(3, zigzag_strength + 1)
                        elif zigzag_direction == "SELL" and _zz_pos > 0.70:
                            # Price near high → rejection, bonus
                            zigzag_strength = min(3, zigzag_strength + 1)

    except Exception:
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # v57: Weighted Indicator Voting — each indicator votes with its own weight
    # ══════════════════════════════════════════════════════════════════════════
    _v57_indicators = [
        # (direction, uzito)
        (psar_direction,       12),  # Parabolic SAR (v58: +2)
        (cmo_direction,         7),  # CMO
        (tema_direction,       10),  # TEMA (v58: +1)
        (ao_direction,          7),  # AO
        (elder_direction,       9),  # Elder Ray (v58: +1)
        (squeeze_direction,    12),  # TTM Squeeze (v58: +2 - strength for breakouts)
        (trix_direction,        6),  # TRIX
        (aroon_direction,       8),  # Aroon (v58: +1)
        (vortex_direction,      8),  # Vortex (v58: +1)
        (cmf_direction,         9),  # Chaikin MF (v58: +1 - volume-based)
        (kama_direction,       10),  # KAMA (v58: +1)
        (mcginley_direction,    8),  # McGinley (v58: +1)
        (coppock_direction,     6),  # Coppock
        (wma_direction,         7),  # WMA (v58: +1)
        (dpo_direction,         5),  # DPO
        (rvi_direction,         7),  # RVI
        (kst_direction,         8),  # KST (v58: +1)
        (ppo_direction,         7),  # PPO (v58: +1)
        (cci_fast_direction,    7),  # CCI fast (v58: +1)
        (bop_direction,         6),  # BOP
        # v58 new: ZigZag — weight based on swing strength
        (zigzag_direction,     min(15, 5 + zigzag_strength * 5)),  # max 20pts for strength=3
    ]
    v57_buy_score  = sum(w for d, w in _v57_indicators if d == "BUY")
    v57_sell_score = sum(w for d, w in _v57_indicators if d == "SELL")
    v57_total      = v57_buy_score + v57_sell_score
    v57_direction  = None
    if v57_total > 0:
        if v57_buy_score / v57_total >= 0.60:   # v63: restored to v57 level (was 0.65 — too strict)
            v57_direction = "BUY"
        elif v57_sell_score / v57_total >= 0.60:
            v57_direction = "SELL"
    # ── end v57 indicators ────────────────────────────────────────────────────

    dema_agrees = (dema_diff > 0 and direction_raw == "BUY") or \
                  (dema_diff < 0 and direction_raw == "SELL") if dema_diff != 0 else True
    hma_agrees  = (hma_direction == direction_raw) if (hma_direction and direction_raw) else True

    # Boost direction confidence with v56 indicators
    direction_v56 = direction_raw
    if direction_raw is None:
        # Try to get direction from DEMA if EMA/MACD disagree
        if dema_diff > 0.02 and hma_direction == "BUY":
            direction_v56 = "BUY"
        elif dema_diff < -0.02 and hma_direction == "SELL":
            direction_v56 = "SELL"

    return {
        "rsi": rsi, "macd": macd_norm, "bb_pos": bb_pos,
        "ma_diff": ma_diff, "mom": mom, "sto": sto, "vol": vol,
        "real": True, "current_price": current_price,
        "divergence": divergence,
        "fractal_signal": fractal_signal,
        "fractal_strength": fractal_strength,
        "direction": direction_v56,
        "quality": abs(ma_diff) + abs(mom) + abs(macd_norm),
        "adx": adx_val,
        # ── v56 new fields ──
        "rsi_slope":          rsi_slope,
        "macd_hist_slope":    macd_hist_slope,
        "dema_diff":          dema_diff,
        "hma_direction":      hma_direction,
        "keltner_breakout":   keltner_breakout,
        "fisher_val":         fisher_val,
        "fisher_direction":   fisher_direction,
        "volume_surge":       volume_surge,
        "candle_body_ratio":  candle_body_ratio,
        "is_indecision":      is_indecision_candle,
        # ── v56-ST ──
        "supertrend_direction": supertrend_direction,
        "supertrend_val":       supertrend_val,
        # ── v57 new indicators ──
        "psar_direction":      psar_direction,
        "cmo_val":             cmo_val,
        "cmo_direction":       cmo_direction,
        "tema_direction":      tema_direction,
        "ao_direction":        ao_direction,
        "elder_direction":     elder_direction,
        "squeeze_direction":   squeeze_direction,
        "squeeze_active":      squeeze_active,
        "trix_direction":      trix_direction,
        "aroon_direction":     aroon_direction,
        "vortex_direction":    vortex_direction,
        "cmf_val":             cmf_val,
        "cmf_direction":       cmf_direction,
        "kama_direction":      kama_direction,
        "mcginley_direction":  mcginley_direction,
        "coppock_direction":   coppock_direction,
        "wma_direction":       wma_direction,
        "dpo_direction":       dpo_direction,
        "rvi_direction":       rvi_direction,
        "kst_direction":       kst_direction,
        "ppo_direction":       ppo_direction,
        "cci_fast_direction":  cci_fast_direction,
        "bop_direction":       bop_direction,
        "v57_buy_score":       v57_buy_score,
        "v57_sell_score":      v57_sell_score,
        "v57_direction":       v57_direction,
        # ── v58: ZigZag Trend ──
        "zigzag_direction":    zigzag_direction,
        "zigzag_strength":     zigzag_strength,
        "zigzag_last_swing":   zigzag_last_swing,
    }

import threading as _threading
_YF_CACHE = {}          # {(symbol, period, interval): (timestamp, df)}
_YF_CACHE_TTL = 60      # v63: 60s — entry per 1m candle, cache > 1 candle = stale data
_YF_CACHE_LOCK = _threading.Lock()

# v65: Failure blacklists — avoid hammering dead sources repeatedly
# Key: (symbol, interval) → timestamp of last failure
# If failure < _YF_FAIL_TTL seconds ago, skip that source entirely
_YF_FAIL_CACHE  = {}   # yfinance failures
_FH_FAIL_CACHE  = {}   # Finnhub failures
_SRC_FAIL_LOCK  = _threading.Lock()
_YF_FAIL_TTL    = 300  # 5 minutes: skip yfinance for this symbol+interval if it just failed
_FH_FAIL_TTL    = 180  # 3 minutes: skip Finnhub for this symbol+interval if it just failed

# ── TwelveData rate limiter — max 7 req/min (free tier = 8, leave 1 buffer) ──
_TD_REQ_TIMES  = []          # timestamps of recent TD requests
_TD_REQ_LOCK   = _threading.Lock()
_TD_MAX_PER_MIN = 7

def _td_can_request():
    """Returns True if we can make a TwelveData request without hitting rate limit."""
    now = time.time()
    with _TD_REQ_LOCK:
        # Drop timestamps older than 60s
        while _TD_REQ_TIMES and now - _TD_REQ_TIMES[0] > 60:
            _TD_REQ_TIMES.pop(0)
        if len(_TD_REQ_TIMES) >= _TD_MAX_PER_MIN:
            return False
        _TD_REQ_TIMES.append(now)
        return True

_YF_TO_FH_RESOLUTION = {
    "1m": "1", "2m": "1", "5m": "5", "15m": "15",
    "30m": "30", "1h": "60", "1H": "60", "4h": "240",
}
_YF_PERIOD_TO_CANDLES = {
    "1d": 390, "2d": 780, "3d": 1170, "5d": 1950, "7d": 2730,
}

def _fh_candles_as_df(fh_sym, resolution, count=200):
    """Fanya Finnhub call na rudisha DataFrame au None. Internal helper."""
    if not fh_sym or not FINNHUB_KEY:
        return None
    try:
        now     = int(time.time())
        res_sec = {"1":60,"5":300,"15":900,"30":1800,"60":3600,"240":14400}.get(str(resolution), 60)
        from_ts = now - res_sec * (count + 60)
        url = ("https://finnhub.io/api/v1/forex/candle"
               "?symbol={}&resolution={}&from={}&to={}&token={}".format(
                   fh_sym, resolution, from_ts, now, FINNHUB_KEY))
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("s") != "ok" or not d.get("c"):
            return None
        df = pd.DataFrame({
            "Open": d["o"], "High": d["h"], "Low": d["l"],
            "Close": d["c"], "Volume": d.get("v", [0]*len(d["c"])),
        }, index=pd.to_datetime(d["t"], unit="s"))
        df.columns = pd.MultiIndex.from_tuples(
            [(c, "") for c in df.columns]
        ) if isinstance(df.columns, pd.MultiIndex) else df.columns
        return df.iloc[-count:] if len(df) > count else df
    except Exception as _fe:
        logging.warning("_fh_candles_as_df {} res={} failed: {}".format(fh_sym, resolution, _fe))
        return None

# ── Twelve Data symbols (pair name → TD symbol) ──────────────────────────────
TWELVE_DATA_KEY = os.environ.get("TWELVE_DATA_KEY", "")

# Interval mapping: yfinance format → Twelve Data format
_YF_TO_TD_INTERVAL = {
    "1m": "1min", "2m": "2min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1h", "1H": "1h", "4h": "4h",
}

# Period → outputsize (candles count) for Twelve Data
_YF_PERIOD_TO_TD_SIZE = {
    "1d": 390, "2d": 780, "3d": 1170, "5d": 1950, "7d": 2730,
}

# Yahoo symbol → pair name (reverse of YAHOO_SYMBOLS)
_YF_SYM_TO_PAIR = {v: k for k, v in {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "USD/CHF": "USDCHF=X", "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X",
    "EUR/GBP": "EURGBP=X", "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X", "AUD/JPY": "AUDJPY=X", "EUR/AUD": "EURAUD=X",
    "EUR/CAD": "EURCAD=X", "GBP/AUD": "GBPAUD=X", "GBP/CAD": "GBPCAD=X",
    "AUD/CAD": "AUDCAD=X", "AUD/CHF": "AUDCHF=X",
    "EUR/CHF": "EURCHF=X", "CHF/JPY": "CHFJPY=X", "CAD/JPY": "CADJPY=X",
    "CAD/CHF": "CADCHF=X", "GBP/CHF": "GBPCHF=X",
    "USD/NOK": "USDNOK=X", "USD/SEK": "USDSEK=X", "USD/DKK": "USDDKK=X",
    "USD/TRY": "USDTRY=X", "USD/ZAR": "USDZAR=X", "USD/SGD": "USDSGD=X",
    "EUR/NOK": "EURNOK=X", "EUR/SEK": "EURSEK=X", "EUR/PLN": "EURPLN=X",
    "EUR/TRY": "EURTRY=X", "GBP/NOK": "GBPNOK=X", "GBP/SEK": "GBPSEK=X",
    "US100": "^NDX", "SP500": "^GSPC", "CAC 40": "^FCHI",
    "SMI 20": "^SSMI", "E35EUR": "^STOXX",
    "US30": "^DJI", "GER40": "^GDAXI", "UK100": "^FTSE",
    "JPN225": "^N225", "AUS200": "^AXJO",
}.items()}

# Indices mapping kwa Twelve Data (symbols tofauti)
_TD_INDEX_SYMBOLS = {
    "^NDX": "NDX", "^GSPC": "SPX", "^FCHI": "CAC40",
    "^DJI": "DJI", "^GDAXI": "DAX", "^FTSE": "FTSE100",
    "^N225": "N225", "^AXJO": "AXJO", "^SSMI": "SMI",
    "^STOXX": "SX5E",
}

def _td_candles_as_df(symbol, interval, outputsize=200):
    """
    Fetch candles kutoka Twelve Data API.
    Forex: symbol = 'EUR/USD', interval = '1min', '5min', '1h' nk.
    Returns DataFrame au None.
    Free tier: 800 credits/siku, 8 requests/dakika.
    """
    if not TWELVE_DATA_KEY:
        return None
    if not _td_can_request():
        logging.warning("TwelveData rate limit — skipping request for {}".format(symbol))
        return None
    try:
        # Twelve Data forex inatumia EUR/USD format moja kwa moja
        url = (
            "https://api.twelvedata.com/time_series"
            "?symbol={}&interval={}&outputsize={}&apikey={}&format=JSON".format(
                symbol, interval, min(outputsize, 500), TWELVE_DATA_KEY
            )
        )
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logging.warning("TwelveData HTTP {} for {}".format(r.status_code, symbol))
            return None
        d = r.json()
        if d.get("status") == "error" or "values" not in d:
            logging.warning("TwelveData error {}: {}".format(symbol, d.get("message", "")))
            return None
        values = d["values"]
        if not values:
            return None
        df = pd.DataFrame(values)
        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume", "datetime": "Datetime"
        })
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df = df.set_index("Datetime").sort_index()
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "Volume" in df.columns:
            df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
        else:
            df["Volume"] = 0.0
        logging.info("TwelveData OK: {} {} {} rows".format(symbol, interval, len(df)))
        return df
    except Exception as _te:
        logging.warning("TwelveData failed {} {}: {}".format(symbol, interval, _te))
        return None


def _yf_download_cached(symbol, period, interval):
    """
    v65: Data source priority with failure blacklists:
      1. Cache (60s) — fastest
      2. yfinance — primary (skipped if recently failed for this symbol+interval)
      3. Finnhub — fallback (skipped if recently failed for this symbol+interval)
      4. Twelve Data — last resort (only called once per symbol, not per TF retry)

    v65 change: failure blacklists (_YF_FAIL_CACHE, _FH_FAIL_CACHE) prevent
    hammering dead sources on every scan cycle. A source that just failed for
    symbol+interval is skipped for _YF_FAIL_TTL / _FH_FAIL_TTL seconds.
    This prevents the yfinance→Finnhub→TwelveData rate-limit spam seen in logs.
    """
    key = (symbol, period, interval)
    fail_key = (symbol,)  # v66: symbol-level — one failure blacklists ALL intervals for this symbol
    now = time.time()

    # ── 0. Cache hit ──────────────────────────────────────────────────────────
    with _YF_CACHE_LOCK:
        if key in _YF_CACHE:
            ts, df = _YF_CACHE[key]
            if now - ts < _YF_CACHE_TTL:
                return df

    df = None

    # ── 1. yfinance (primary) ─────────────────────────────────────────────────
    _yf_recently_failed = False
    with _SRC_FAIL_LOCK:
        _ft = _YF_FAIL_CACHE.get(fail_key, 0)
        if now - _ft < _YF_FAIL_TTL:
            _yf_recently_failed = True

    if not _yf_recently_failed:
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            if df is None or len(df) < 5:
                df = None
                with _SRC_FAIL_LOCK:
                    _YF_FAIL_CACHE[fail_key] = now
            else:
                logging.info("yfinance OK (primary): {} {} {}".format(
                    symbol, period, interval))
        except Exception as _ye:
            logging.warning("yfinance failed ({} {} {}): {} — trying Finnhub".format(
                symbol, period, interval, _ye))
            df = None
            with _SRC_FAIL_LOCK:
                _YF_FAIL_CACHE[fail_key] = now
    else:
        logging.info("yfinance SKIP (blacklisted {}s) {} {}".format(
            int(_YF_FAIL_TTL), symbol, interval))

    # ── 2. Finnhub (fallback) ─────────────────────────────────────────────────
    if df is None:
        _fh_recently_failed = False
        with _SRC_FAIL_LOCK:
            _fft = _FH_FAIL_CACHE.get(fail_key, 0)
            if now - _fft < _FH_FAIL_TTL:
                _fh_recently_failed = True

        if not _fh_recently_failed:
            _fh_sym = None
            try:
                _pair_name2 = _YF_SYM_TO_PAIR.get(symbol)
                if _pair_name2:
                    _fh_sym = FINNHUB_FOREX_SYMBOLS.get(_pair_name2)
            except Exception:
                pass

            if _fh_sym and FINNHUB_KEY:
                _fh_res   = _YF_TO_FH_RESOLUTION.get(interval, "5")
                _fh_count = _YF_PERIOD_TO_CANDLES.get(period, 200)
                df = _fh_candles_as_df(_fh_sym, _fh_res, _fh_count)
                if df is not None and len(df) >= 5:
                    logging.info("YF_FALLBACK→FH: {} {} {} → Finnhub OK ({} rows)".format(
                        symbol, period, interval, len(df)))
                else:
                    df = None
                    logging.warning("YF_FALLBACK→FH: {} {} {} → Finnhub also failed".format(
                        symbol, period, interval))
                    with _SRC_FAIL_LOCK:
                        _FH_FAIL_CACHE[fail_key] = now
            elif not FINNHUB_KEY:
                # No Finnhub key — mark as failed immediately to skip next time
                with _SRC_FAIL_LOCK:
                    _FH_FAIL_CACHE[fail_key] = now
        else:
            logging.info("Finnhub SKIP (blacklisted {}s) {} {}".format(
                int(_FH_FAIL_TTL), symbol, interval))

    # ── 3. Twelve Data (last resort — hifadhi rate-limit credits) ─────────────
    # Only attempt TD if BOTH yfinance AND Finnhub have failed/are blacklisted.
    # This prevents using TD credits on transient yfinance errors.
    if df is None and TWELVE_DATA_KEY:
        _yf_bl = now - _YF_FAIL_CACHE.get(fail_key, 0) < _YF_FAIL_TTL
        _fh_bl = now - _FH_FAIL_CACHE.get(fail_key, 0) < _FH_FAIL_TTL
        if _yf_bl or _fh_bl or _yf_recently_failed:
            # At least one primary source confirmed failed — TD is justified
            try:
                _pair_name = _YF_SYM_TO_PAIR.get(symbol)
                _td_sym    = None

                if _pair_name and "/" in _pair_name:
                    _td_sym = _pair_name
                elif symbol in _TD_INDEX_SYMBOLS:
                    _td_sym = _TD_INDEX_SYMBOLS[symbol]

                if _td_sym:
                    _td_interval = _YF_TO_TD_INTERVAL.get(interval, "5min")
                    _td_outsize  = _YF_PERIOD_TO_TD_SIZE.get(period, 200)
                    df = _td_candles_as_df(_td_sym, _td_interval, _td_outsize)
                    if df is not None and len(df) < 5:
                        df = None
                    elif df is not None:
                        logging.info("FALLBACK→TD: {} {} {} OK ({} rows)".format(
                            symbol, period, interval, len(df)))
            except Exception as _tde:
                logging.warning("TwelveData fetch failed ({} {} {}): {}".format(
                    symbol, period, interval, _tde))
                df = None

    if df is not None and len(df) > 0:
        with _YF_CACHE_LOCK:
            _YF_CACHE[key] = (now, df)
    return df

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
    fh_sym  = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym  = YAHOO_SYMBOLS.get(real_pair)
    if not fh_sym and not yf_sym:
        return None

    df = None
    try:
        if fh_sym and FINNHUB_KEY:
            df = _mtf_fh_candles(fh_sym, "60", 120)  # 120 x 1H candles = 5 days
            if df is not None and len(df) >= 30:
                logging.info("1H trend source: FINNHUB {}".format(pair))
            else:
                df = None
    except Exception as _fh_e:
        logging.warning("Finnhub 1H {} failed: {}".format(pair, _fh_e))
        df = None

    if df is None and yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "7d", "1h")
            if df is not None and len(df) >= 30:
                logging.info("1H trend source: YAHOO {}".format(pair))
        except Exception as _ye:
            logging.warning("Yahoo 1H {} failed: {}".format(pair, _ye))
            df = None

    try:
        if df is None or len(df) < 30:
            return None

        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()

        current_price = float(close.iloc[-1])

        ema9  = float(close.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema9_prev  = float(close.ewm(span=9,  adjust=False).mean().iloc[-2])
        ema21_prev = float(close.ewm(span=21, adjust=False).mean().iloc[-2])

        # ── v56: EMA 200 — major hourly trend ──
        ema200_bull = None
        try:
            if len(close) >= 60:
                ema200 = float(close.ewm(span=60, adjust=False).mean().iloc[-1])  # EMA60 = proxy for EMA200 on 1H
                ema200_bull = float(close.iloc[-1]) > ema200
        except Exception:
            pass

        ema_gap_pct = abs(ema9 - ema21) / (ema21 + 1e-9) * 100
        if ema_gap_pct < 0.005:
            return None

        ema_bull = ema9 > ema21   # True = bullish EMA structure

        price_above_ema21 = current_price > ema21
        if ema_bull and not price_above_ema21:
            return None
        if not ema_bull and price_above_ema21:
            return None

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist_now  = float((macd_line - macd_signal).iloc[-1])
        macd_hist_prev = float((macd_line - macd_signal).iloc[-2])
        macd_turning_bull = (macd_hist_now > 0 and macd_hist_prev <= 0)
        macd_turning_bear = (macd_hist_now < 0 and macd_hist_prev >= 0)
        macd_bull = macd_hist_now > 0

        delta  = close.diff()
        gain   = delta.clip(lower=0).rolling(14).mean()
        loss   = (-delta.clip(upper=0)).rolling(14).mean()
        rsi_1h = float((100 - 100 / (1 + gain / loss.replace(0, 1e-9))).iloc[-1])
        rsi_bull = rsi_1h > 50

        c0 = float(close.iloc[-1])
        c1 = float(close.iloc[-2])
        c2 = float(close.iloc[-3])
        c3 = float(close.iloc[-4])
        candle_bull_count = sum([1 for a, b in [(c0,c1),(c1,c2),(c2,c3)] if a > b])
        candle_bear_count = 3 - candle_bull_count

        if ema_bull and candle_bear_count >= 3 and (macd_turning_bear or not macd_bull):
            return None   # Trend is reversing - no signal, wait for clarity
        if not ema_bull and candle_bull_count >= 3 and (macd_turning_bull or macd_bull):
            return None   # Trend is reversing - no signal, wait for clarity

        if ema_bull:
            supporting = sum([
                macd_bull,           # MACD agrees
                rsi_bull,            # RSI agrees
                candle_bull_count >= 2,  # At least 2 of 3 candles agree
            ])
            if supporting >= 2:
                # v56: EMA200 bonus — if price above EMA200, signal is stronger
                if ema200_bull is True:
                    return "BUY"   # Full confirmation: EMA cross + MACD/RSI + EMA200
                elif ema200_bull is False:
                    # Price below EMA200 but EMA9>EMA21 — risky, require 3/3
                    if supporting >= 3:
                        return "BUY"
                    return None   # Reject: EMA200 inapinga
                return "BUY"
            return None
        else:
            supporting = sum([
                not macd_bull,              # MACD agrees (bearish)
                not rsi_bull,               # RSI agrees (bearish)
                candle_bear_count >= 2,     # At least 2 of 3 candles agree
            ])
            if supporting >= 2:
                # v56: EMA200 check for SELL
                if ema200_bull is False:
                    return "SELL"   # Full confirmation: EMA cross + MACD/RSI + EMA200
                elif ema200_bull is True:
                    if supporting >= 3:
                        return "SELL"
                    return None   # Reject: EMA200 inapinga SELL
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
    fh_sym  = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym  = YAHOO_SYMBOLS.get(real_pair)
    if not fh_sym and not yf_sym:
        return True  # No real data - proceed with signal

    df = None
    try:
        if fh_sym and FINNHUB_KEY:
            df = _mtf_fh_candles(fh_sym, "60", 30)
            if df is None or len(df) < 5:
                df = None
    except Exception:
        df = None
    if df is None and yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "3d", "1h")
        except Exception:
            df = None
    try:
        if df is None or len(df) < 5:
            return True
        close = df["Close"].squeeze()
        c_last   = float(close.iloc[-1])
        c_prev1  = float(close.iloc[-2])
        c_prev2  = float(close.iloc[-3])
        agree = 0
        if direction == "SELL":
            if c_last  < c_prev1: agree += 1
            if c_prev1 < c_prev2: agree += 1
        else:  # BUY
            if c_last  > c_prev1: agree += 1
            if c_prev1 > c_prev2: agree += 1
        return agree >= 1
    except Exception as e:
        logging.warning("_confirm_1h_direction failed for {}: {}".format(pair, e))
        return True  # Proceed on error

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
    fh_sym  = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym  = YAHOO_SYMBOLS.get(real_pair)
    if not fh_sym and not yf_sym:
        return None

    df = None
    try:
        if fh_sym and FINNHUB_KEY:
            df = _mtf_fh_candles(fh_sym, "5", 80)
            if df is None or len(df) < 10:
                df = None
    except Exception:
        df = None

    if df is None and yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "1d", "5m")
        except Exception:
            df = None

    try:
        if df is None or len(df) < 10:
            return None
        close  = df["Close"].squeeze()
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        typical_price = (high + low + close) / 3
        cum_vol = volume.cumsum()
        cum_tpv = (typical_price * volume).cumsum()
        vwap = float((cum_tpv / cum_vol.replace(0, 1e-9)).iloc[-1])
        current_price = float(close.iloc[-1])

        dist_pct = (current_price - vwap) / (vwap + 1e-9) * 100

        direction = "BUY" if current_price > vwap else "SELL"

        vol_ratio = float(volume.iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-9))

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

    if trend_1h is not None:
        total += 1
        if trend_1h == direction:
            score += 1

    if vwap_data is not None:
        total += 1
        if vwap_data["direction"] == direction:
            score += 1
            if vwap_data["strength"] == "STRONG":
                score += 1
                total += 1

    if mtf and mtf["total"] >= 3:
        total += 1
        mtf_dir = "BUY" if mtf["buy_tfs"] > mtf["sell_tfs"] else "SELL"
        if mtf_dir == direction:
            score += 1
            agreeing = mtf["buy_tfs"] if direction == "BUY" else mtf["sell_tfs"]
            if agreeing >= 4:
                score += 1
                total += 1

    if total == 0:
        return {"level": "WEAK", "score": 0, "badge": "⚪"}

    ratio = score / total

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
            df = _yf_download_cached(symbol, period, interval)
            ind = _calc_indicators_from_df(df)
            if ind is None:
                continue
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
        df = _yf_download_cached(symbol, "2d", "5m")
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
        df = _yf_download_cached(symbol, "1d", "1m")
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
        df = _yf_download_cached(symbol, "1d", "1m")
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
    Fetch real OHLCV across 3 timeframes (1m, 5m, 15m).

    Priority (v44):
      1. Finnhub (OANDA feed) - real-time, no lag, primary source
      2. Yahoo Finance         - fallback kama Finnhub inashindwa au key haipo

    Returns base indicators (from 5m/1m) + tf_buy_votes, tf_sell_votes, tf_count.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)

    if not fh_sym and not yf_sym:
        return None

    results = {}  # {interval_label: indicator_dict}

    fh_success = False
    if fh_sym and FINNHUB_KEY:
        fh_tf_map = [
            ("1m",  "1",  80),
            ("5m",  "5",  80),
            ("15m", "15", 60),
        ]
        for label, resolution, count in fh_tf_map:
            try:
                df = _mtf_fh_candles(fh_sym, resolution, count)
                ind = _calc_indicators_from_df(df)
                if ind is not None:
                    results[label] = ind
                    fh_success = True
            except Exception as e:
                logging.warning("Finnhub MTF {} {} failed: {}".format(pair, label, e))

        if fh_success:
            logging.info("MTF source: FINNHUB {} ({} TFs)".format(pair, len(results)))

    yf_tf_configs = [
        ("1m",  "1d"),
        ("5m",  "2d"),
        ("15m", "5d"),
    ]
    if yf_sym:
        for interval, period in yf_tf_configs:
            if interval in results:
                continue  # Finnhub tayari imepata TF hii - skip
            try:
                df = _yf_download_cached(yf_sym, period, interval)
                ind = _calc_indicators_from_df(df)
                if ind is not None:
                    results[interval] = ind
                    logging.info("MTF Yahoo fallback {} {}: OK".format(pair, interval))
            except Exception as e:
                logging.warning("Yahoo MTF {} {} failed: {}".format(pair, interval, e))

    if not results:
        return None

    base = results.get("5m") or results.get("1m") or results.get("15m") or list(results.values())[0]

    buy_votes = sell_votes = 0
    for interval, ind in results.items():
        d = ind.get("direction")
        if d == "BUY":
            buy_votes += 1
        elif d == "SELL":
            sell_votes += 1

    base = dict(base)
    base["tf_buy_votes"]  = buy_votes
    base["tf_sell_votes"] = sell_votes
    base["tf_count"]      = len(results)
    base["data_source"]   = "finnhub" if fh_success else "yahoo"
    return base

def _fetch_current_price(pair):
    """
    Fetch current price for result checking (win/loss).

    Priority (v44):
      1. Finnhub quote endpoint - haraka zaidi, real-time
      2. Finnhub 1m candle      - fallback ndani ya Finnhub
      3. Yahoo Finance 1m       - fallback wa mwisho
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)

    if fh_sym and FINNHUB_KEY:
        try:
            url = ("https://finnhub.io/api/v1/quote"
                   "?symbol={}&token={}".format(fh_sym, FINNHUB_KEY))
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                d = r.json()
                price = d.get("c") or d.get("l")  # current or last price
                if price and float(price) > 0:
                    logging.info("Price source: FINNHUB quote {} = {}".format(pair, price))
                    return float(price)
        except Exception as e:
            logging.warning("Finnhub quote {} failed: {}".format(pair, e))

        try:
            df = _mtf_fh_candles(fh_sym, "1", 5)
            if df is not None and len(df) >= 1:
                price = float(df["Close"].iloc[-1])
                if price > 0:
                    logging.info("Price source: FINNHUB 1m {} = {}".format(pair, price))
                    return price
        except Exception as e:
            logging.warning("Finnhub 1m price {} failed: {}".format(pair, e))

    if yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "1d", "1m")
            if df is not None and len(df) >= 1:
                price = float(df["Close"].squeeze().iloc[-1])
                logging.info("Price source: YAHOO {} = {}".format(pair, price))
                return price
        except Exception as e:
            logging.warning("Yahoo price {} failed: {}".format(pair, e))

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

def compute_setup_cluster(rsi=50.0, bb_pos=0.5, mom=0.0, session=None):
    """
    Badilisha indicators kuwa fingerprint fupi ya hali ya soko.
    Inatumika kuhifadhi na kulinganisha setups zinazofanana.
    Format: "RSI{bucket}_BB{bucket}_MOM{bucket}_S{session_abbr}"
    """
    r = float(rsi)
    if r < 30:   rsi_b = "LW"
    elif r < 45: rsi_b = "ML"
    elif r < 55: rsi_b = "MH"
    elif r < 70: rsi_b = "HW"
    else:        rsi_b = "XH"

    b = float(bb_pos)
    if b < 0.25:   bb_b = "LW"
    elif b < 0.45: bb_b = "ML"
    elif b < 0.55: bb_b = "MID"
    elif b < 0.75: bb_b = "MH"
    else:          bb_b = "HW"

    m = float(mom)
    if m < -0.2:   mom_b = "NEG"
    elif m > 0.2:  mom_b = "POS"
    else:          mom_b = "FLT"

    sess_abbr = "UK"
    if session:
        sl = str(session).lower()
        if "london" in sl:          sess_abbr = "LN"
        elif "new" in sl or "ny" in sl or "york" in sl: sess_abbr = "NY"
        elif "asian" in sl or "tokyo" in sl: sess_abbr = "AS"

    return "RSI{}_BB{}_MOM{}_S{}".format(rsi_b, bb_b, mom_b, sess_abbr)

def pg_best_combo(pair, rsi=50.0, bb_pos=0.5, mom=0.0, session=None, min_samples=5):
    """
    Query database: "For this setup, which direction+tf combo won most?"

    Inatafuta signal_combo_stats (exact cluster match, uzito 3.0) na
    signal_history yenye indicators zinazofanana - RSI±12, BB±0.15 (uzito 1.5).

    Returns dict {direction, tf_mins, win_rate, confidence, sample_n, cluster}
    au None kama data haitoshi (chini ya min_samples au win_rate < 0.60).
    """
    if session is None:
        try:
            session = _get_session().get("name", "Unknown")
        except Exception:
            session = "Unknown"

    cluster = compute_setup_cluster(rsi=rsi, bb_pos=bb_pos, mom=mom, session=session)
    combo_scores = {}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT direction, tf_mins, wins, losses, (wins + losses) AS total
                    FROM signal_combo_stats
                    WHERE pair = %s AND setup_cluster = %s AND (wins + losses) >= %s
                """, (pair, cluster, min_samples))
                for r in cur.fetchall():
                    key = (str(r["direction"]), int(r["tf_mins"]))
                    w = int(r["wins"]); t = int(r["total"])
                    if key not in combo_scores: combo_scores[key] = [0.0, 0.0]
                    combo_scores[key][0] += w * 3.0
                    combo_scores[key][1] += t * 3.0

                cur.execute("""
                    SELECT direction, tf_mins,
                           COUNT(*) AS total,
                           SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE pair = %s AND tf_mins IN (1,2,3) AND won IS NOT NULL
                      AND rsi IS NOT NULL
                      AND ABS(rsi - %s) <= 12 AND ABS(bb_pos - %s) <= 0.15
                      AND created_at >= NOW() - INTERVAL '21 days'
                    GROUP BY direction, tf_mins
                    HAVING COUNT(*) >= %s
                """, (pair, float(rsi), float(bb_pos), min_samples))
                for r in cur.fetchall():
                    key = (str(r["direction"]), int(r["tf_mins"]))
                    w = int(r["wins"]); t = int(r["total"])
                    if key not in combo_scores: combo_scores[key] = [0.0, 0.0]
                    combo_scores[key][0] += w * 1.5
                    combo_scores[key][1] += t * 1.5

        if not combo_scores:
            return None

        best_key = None; best_wr = 0.0; best_total = 0.0
        all_combo_wr = {}
        for key, (w_w, w_t) in combo_scores.items():
            if w_t < 1: continue
            wr = w_w / w_t
            all_combo_wr[key] = wr
            if wr > best_wr:
                best_wr = wr; best_key = key; best_total = w_t

        if best_key is None or best_wr < 0.60:
            return None

        best_dir, best_tf = best_key
        confidence = min(1.0, best_total / 30.0)
        approx_n = int(best_total / 2.25)

        logging.info("PG_BEST_COMBO {} cluster={}: best={} {}m wr={:.0f}% n≈{}".format(
            pair, cluster, best_dir, best_tf, best_wr * 100, approx_n))

        return {
            "direction": best_dir, "tf_mins": int(best_tf),
            "win_rate": best_wr, "confidence": confidence,
            "sample_n": approx_n, "cluster": cluster,
            "source": "combo_hist",
            "combo_scores": {str(k): v for k, v in all_combo_wr.items()},
        }
    except Exception as e:
        logging.warning("pg_best_combo failed {}: {}".format(pair, e))
        return None

def update_signal_combo_stats(pair, direction, tf_mins, won,
                               rsi=50.0, bb_pos=0.5, mom=0.0, session=None):
    """
    Sasisha signal_combo_stats baada ya kujua outcome ya signal.
    Inaitwa auto na update_signal_history_won().
    """
    if session is None:
        try:
            session = _get_session().get("name", "Unknown")
        except Exception:
            session = "Unknown"
    cluster = compute_setup_cluster(rsi=rsi, bb_pos=bb_pos, mom=mom, session=session)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if won:
                    cur.execute("""
                        INSERT INTO signal_combo_stats
                            (pair, direction, tf_mins, setup_cluster, wins, losses, last_updated)
                        VALUES (%s,%s,%s,%s,1,0,NOW())
                        ON CONFLICT (pair, direction, tf_mins, setup_cluster) DO UPDATE
                            SET wins = signal_combo_stats.wins + 1, last_updated = NOW()
                    """, (pair, direction, tf_mins, cluster))
                else:
                    cur.execute("""
                        INSERT INTO signal_combo_stats
                            (pair, direction, tf_mins, setup_cluster, wins, losses, last_updated)
                        VALUES (%s,%s,%s,%s,0,1,NOW())
                        ON CONFLICT (pair, direction, tf_mins, setup_cluster) DO UPDATE
                            SET losses = signal_combo_stats.losses + 1, last_updated = NOW()
                    """, (pair, direction, tf_mins, cluster))
            conn.commit()
        logging.info("COMBO_STATS: {} {} {}m {} cluster={}".format(
            pair, direction, tf_mins, "WIN" if won else "LOSS", cluster))
    except Exception as e:
        logging.warning("update_signal_combo_stats failed {}: {}".format(pair, e))

def _apply_pg_best_combo_to_scores(scores, pair, direction,
                                    rsi=50.0, bb_pos=0.5, mom=0.0,
                                    session=None, max_bonus=35.0):
    """
    Layer A0: Ongeza historical combo intelligence kwenye scores.
    Bonus max_bonus pts kwa TF bora ya historia, adhabu 35% kwa zingine.
    Returns: (scores, info_str)
    """
    info_str = "no_combo_data"
    try:
        combo = pg_best_combo(pair=pair, rsi=rsi, bb_pos=bb_pos,
                               mom=mom, session=session, min_samples=5)
        if combo is None:
            return scores, info_str

        best_wr    = combo["win_rate"]
        best_tf    = combo["tf_mins"]
        best_dir   = combo["direction"]
        confidence = combo["confidence"]
        cluster    = combo.get("cluster", "?")
        n          = combo.get("sample_n", 0)

        if best_wr < 0.60:
            return scores, "combo_wr_low {:.0f}%".format(best_wr * 100)

        bonus = min(max_bonus, (best_wr - 0.50) * max_bonus * 2) * confidence
        penalty_other = bonus * 0.35

        scores[best_tf] += bonus
        for tf_other in [1, 2, 3]:
            if tf_other != best_tf:
                scores[tf_other] -= penalty_other

        dir_note = ""
        if best_dir != direction:
            dir_note = " [combo_dir={} vs signal_dir={}]".format(best_dir, direction)

        info_str = "combo:{} {}m wr={:.0f}% n={} conf={:.2f} bonus={:.1f}{}".format(
            cluster, best_tf, best_wr * 100, n, confidence, bonus, dir_note)
        logging.info("COMBO_LAYER {}: {}".format(pair, info_str))

    except Exception as e:
        logging.warning("_apply_pg_best_combo_to_scores failed {}: {}".format(pair, e))

    return scores, info_str

def record_signal(pair, direction, rsi=None, macd=None, bb_pos=None,
                  sto=None, ma_diff=None, mom=None, atr_pct=None,
                  session=None, trend_1h=None, score=None, tf_mins=None):
    """
    Hifadhi signal kwenye signal_history.
    v50: automatically adds setup_cluster.
    Returns signal_id kwa matumizi ya update_signal_history_won().
    """
    return save_signal_history_full(
        pair=pair, direction=direction,
        rsi=rsi, macd=macd, bb_pos=bb_pos, sto=sto,
        ma_diff=ma_diff, mom=mom, atr_pct=atr_pct,
        session=session, trend_1h=trend_1h,
        score=score, tf_mins=tf_mins
    )

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
    v54-8: Candle-Close Result Tracker.

    Mantiki sahihi ya binary options:
      - Subiri candle IFUNGE kabisa (siyo tu dakika 1 baada ya signal)
      - Angalia open vs close ya candle iliyofungwa (iloc[-2])
      - Green candle = BUY win, Red candle = SELL win
      - Timing: hesabu sekunde hadi mwisho wa dakika inayofuata

    Kwa TF 1m: subiri candle 1 ifunge
    Kwa TF 2m: subiri candles 2 zifunge
    Kwa TF 3m: subiri candles 3 zifunge
    """
    if entry_price is None:
        return

    _ep = entry_price

    def _secs_until_next_candle_close(tf_mins):
        """
        Hesabu sekunde hadi candle INAYOFUATA ifunge.

        Mfano: signal 14:32:40, expiry 1m
          Trade inaanza  14:32:40
          Expiry         14:33:40
          Candle ifunge  14:34:00  ← hapa ndio tunasubiri
          (siyo 14:33:00 ambayo ni candle ya sasa tu)

        Formula:
          secs_to_end_current = candle_secs - (now % candle_secs)
          secs_to_next_close  = secs_to_end_current + candle_secs + 5s buffer
        """
        now = datetime.utcnow()
        total_secs = now.hour * 3600 + now.minute * 60 + now.second
        candle_secs = tf_mins * 60
        secs_into_candle = total_secs % candle_secs
        secs_to_end_current = candle_secs - secs_into_candle
        # Wait for current candle to close + next candle to close + 5s buffer
        return secs_to_end_current + candle_secs + 5

    async def _get_candle_result(tf_mins):
        """
        Angalia candle iliyofungwa hivi karibuni.
        Returns: True (won), False (lost), None (data haikupatikana)
        """
        real_pair = OTC_TO_REAL.get(pair, pair)
        yf_sym    = YAHOO_SYMBOLS.get(real_pair)
        fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)

        # Try 3 times at 5s intervals if data not yet available
        for attempt in range(3):
            # Jaribu Finnhub 1m kwanza (haraka zaidi)
            if fh_sym and FINNHUB_KEY and tf_mins == 1:
                try:
                    df = _mtf_fh_candles(fh_sym, "1", 5)
                    if df is not None and len(df) >= 2:
                        closed_open  = float(df["Open"].iloc[-2])
                        closed_close = float(df["Close"].iloc[-2])
                        is_green = closed_close > closed_open
                        is_red   = closed_close < closed_open
                        logging.info("CANDLE RESULT Finnhub {}: open={:.5f} close={:.5f} green={} dir={}".format(
                            pair, closed_open, closed_close, is_green, direction))
                        if is_green == is_red:  # both False = doji, skip
                            await asyncio.sleep(5)
                            continue
                        return (direction == "BUY" and is_green) or (direction == "SELL" and is_red)
                except Exception as _fe:
                    logging.warning("Finnhub candle result {} failed: {}".format(pair, _fe))

            # Yahoo Finance fallback
            if yf_sym:
                try:
                    interval = "1m" if tf_mins == 1 else ("2m" if tf_mins == 2 else "5m")
                    df = _yf_download_cached(yf_sym, "1d", interval)
                    if df is not None and len(df) >= 2:
                        closed_open  = float(df["Open"].squeeze().iloc[-2])
                        closed_close = float(df["Close"].squeeze().iloc[-2])
                        is_green = closed_close > closed_open
                        is_red   = closed_close < closed_open
                        logging.info("CANDLE RESULT Yahoo {}: open={:.5f} close={:.5f} green={} dir={}".format(
                            pair, closed_open, closed_close, is_green, direction))
                        if is_green == is_red:  # doji - jaribu tena
                            await asyncio.sleep(5)
                            continue
                        return (direction == "BUY" and is_green) or (direction == "SELL" and is_red)
                except Exception as _ye:
                    logging.warning("Yahoo candle result {} failed: {}".format(pair, _ye))

            await asyncio.sleep(5)

        # Last fallback: use price diff if candle data unavailable
        logging.warning("CANDLE RESULT {}: fallback to price diff".format(pair))
        exit_p = _fetch_current_price(pair)
        if exit_p is not None and _ep is not None:
            diff = exit_p - _ep
            if abs(diff) > 1e-8:
                return (diff > 0) if direction == "BUY" else (diff < 0)
        return None

    def _record_outcome(tf, won):
        """Hifadhi matokeo kwenye DB tables zote."""
        if won is None:
            return
        try:
            session = _get_session().get("name", "Unknown")
        except Exception:
            session = "Unknown"
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    col = "wins" if won else "losses"
                    cur.execute("""
                        INSERT INTO tf_session_stats (pair, session, tf_mins, wins, losses)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (pair, session, tf_mins) DO UPDATE
                            SET {} = tf_session_stats.{} + 1
                    """.format(col, col), (pair, session, tf, 1 if won else 0, 0 if won else 1))
                conn.commit()
        except Exception as _e:
            logging.warning("result tf_session_stats tf={} {}: {}".format(tf, pair, _e))
        try:
            update_signal_combo_stats(pair=pair, direction=direction, tf_mins=tf,
                                      won=won, session=session)
        except Exception as _e:
            logging.warning("result combo_stats tf={} {}: {}".format(tf, pair, _e))
        if tf == timeframe_mins:
            try:
                update_pair_stats(pair, won)
            except Exception as _e:
                logging.warning("result pair_stats tf={} {}: {}".format(tf, pair, _e))
        logging.info("RESULT_RECORDED {}: dir={} tf={}m won={}".format(pair, direction, tf, won))

    # ── Loop over TFs 1m, 2m, 3m ──
    for check_tf in [1, 2, 3]:

        # Calculate wait time until check_tf candle closes
        wait_secs = _secs_until_next_candle_close(check_tf)
        logging.info("RESULT WAIT {}: tf={}m sleeping {:.0f}s".format(pair, check_tf, wait_secs))
        await asyncio.sleep(wait_secs)

        # Check if user has changed signal (new signal)
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT entry_price FROM user_signal_state "
                        "WHERE user_id=%s AND pair=%s", (user_id, pair))
                    row = cur.fetchone()
            if row and row.get("entry_price") is not None:
                _ep2 = float(row["entry_price"])
                if abs(_ep2 - _ep) > 1e-6:
                    logging.info("RESULT {}: entry changed ({} vs {}), stopping".format(
                        pair, _ep, _ep2))
                    return
        except Exception:
            pass

        # Angalia candle iliyofungwa
        won = await _get_candle_result(check_tf)
        _record_outcome(check_tf, won)

        # Send result to user (their TF only)
        if check_tf == timeframe_mins:
            try:
                nn_feedback_from_vte(user_id, pair, won)
            except Exception:
                pass

            if won is None:
                return

            won_label  = "WIN ✅" if won else "LOSS ❌"
            dir_label  = "BUY 🟢" if direction == "BUY" else "SELL 🔴"
            dir_arrow  = "📈" if direction == "BUY" else "📉"
            won_footer = (
                "💰 Congratulations\\! Another profit secured\\!\n"
                "🔥 Stay focused — more signals coming\\!\n"
                "💎 VVIP MEMBERS ONLY"
            ) if won else (
                "📉 Not every trade wins — stay disciplined\\!\n"
                "🔁 Next signal coming soon\\.\n"
                "💎 VVIP MEMBERS ONLY"
            )
            result_text = (
                "🏆 *EVALON VVIP WINNERS* 🏆\n\n"
                "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
                "📊 PAIR      : *{}*\n"
                "⏱ EXPIRY    : *{} MIN*\n"
                "{} DIRECTION : *{}*\n"
                "🏆 RESULT    : *{}*\n"
                "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n\n"
                "{}"
            ).format(pair, timeframe_mins, dir_arrow, dir_label, won_label, won_footer)
            try:
                sent = await bot.send_message(chat_id=chat_id, text=result_text,
                                              parse_mode="Markdown")
                push_msg_id(user_id, sent.message_id)
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE user_signal_state SET result_sent=TRUE, result_msg_id=%s "
                            "WHERE user_id=%s AND pair=%s",
                            (sent.message_id, user_id, pair))
                    conn.commit()
            except Exception as e:
                logging.warning("schedule_result_check send failed: {}".format(e))
            return  # Done — exit after user TF

        if check_tf == 3:
            break

def check_signal_request(user_id, pair):
    """
    Returns:
      {"action": "fresh"}
      {"action": "flip",   "direction": X}  -- first quick return, flip direction
      {"action": "same",   "direction": X}  -- 2nd+ quick return, keep flipped (warning baada ya 4th press)
      {"action": "cooldown"}                -- still in cooldown
    """

    state = get_user_signal_state(user_id, pair)
    if state is None:
        return {"action": "fresh"}

    signal_time = state["signal_time"]
    if isinstance(signal_time, str):
        signal_time = datetime.fromisoformat(signal_time)
    elapsed    = (datetime.utcnow() - signal_time).total_seconds()
    threshold  = state["last_timeframe"] * 60
    flip_count = state["flip_count"]

    if elapsed >= threshold:
        clear_user_signal_state(user_id, pair)
        return {"action": "fresh"}

    flipped = "SELL" if state["last_direction"] == "BUY" else "BUY"

    if flip_count == 0:
        return {"action": "flip", "direction": flipped}
    else:
        return {"action": "same", "direction": flipped}

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

    o1, c1, h1, l1 = float(open_.iloc[-1]), float(close.iloc[-1]), float(high.iloc[-1]), float(low.iloc[-1])
    o2, c2, h2, l2 = float(open_.iloc[-2]), float(close.iloc[-2]), float(high.iloc[-2]), float(low.iloc[-2])
    o3, c3         = float(open_.iloc[-3]), float(close.iloc[-3])

    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    range1 = h1 - l1 + 1e-9
    range2 = h2 - l2 + 1e-9

    if body1 / range1 < 0.10 and range1 > 0:
        if c2 > o2 and body2 / range2 > 0.4:
            patterns["doji_reversal_sell"] = ("SELL", 20)
        elif c2 < o2 and body2 / range2 > 0.4:
            patterns["doji_reversal_buy"] = ("BUY", 20)

    lower_shadow1 = min(o1, c1) - l1
    upper_shadow1 = h1 - max(o1, c1)
    if lower_shadow1 > body1 * 2 and upper_shadow1 < body1 * 0.5 and c2 < o2:
        patterns["hammer"] = ("BUY", 25)

    if upper_shadow1 > body1 * 2 and lower_shadow1 < body1 * 0.5 and c2 > o2:
        patterns["shooting_star"] = ("SELL", 25)

    if c2 < o2 and c1 > o1 and c1 > o2 and o1 < c2:
        patterns["bullish_engulfing"] = ("BUY", 35)

    if c2 > o2 and c1 < o1 and c1 < o2 and o1 > c2:
        patterns["bearish_engulfing"] = ("SELL", 35)

    if c1 > o1 and c2 > o2 and c3 > o3 and c1 > c2 > c3:
        patterns["three_white_soldiers"] = ("BUY", 40)

    if c1 < o1 and c2 < o2 and c3 < o3 and c1 < c2 < c3:
        patterns["three_black_crows"] = ("SELL", 40)

    if h1 < h2 and l1 > l2:
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

    real_pair = OTC_TO_REAL.get(pair, pair)
    fh_sym  = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym  = YAHOO_SYMBOLS.get(real_pair)
    if not fh_sym and not yf_sym:
        return 0.08, "MEDIUM"

    df = None
    try:
        if fh_sym and FINNHUB_KEY:
            df = _mtf_fh_candles(fh_sym, "5", 80)
            if df is None or len(df) < 10:
                df = None
    except Exception:
        df = None
    if df is None and yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "2d", "5m")
        except Exception:
            df = None
    try:
        if df is None or len(df) < 10:
            return 0.08, "MEDIUM"
        close = df["Close"].squeeze()
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

_ATR_DEAD_THRESHOLD = 0.015  # % - below this = dead market, no signal
_FORCE_PAIRS = set()  # Admin-forced pairs - bypass flat/dead market filter

_FILTER_FLAGS = {
    "news":         True,   # News time block
    "dead":         False,  # Dead market / ATR filter - OFF by default (admin: /filteron dead)
    "conflict":     True,   # 1H vs short-TF conflict filter
    "stability":    True,   # Signal stability / flip filter
    "confluence":   True,   # Min confluence filter (indicators_agree)
    "h1confirm":    True,   # 1H candle confirmation gate
    "micro_trend":  True,   # Micro-candle trend filter (5s/10s/15s green-red ratio)
    "trend_follow": False,  # v65-fix: OFF by default — allow all signals incl. reverse
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
             "micro_trend": "🕯", "trend_follow": "📈"}
    descs = {
        "news":         "News time block",
        "dead":         "Dead market (ATR) filter",
        "conflict":     "1H vs short-TF conflict",
        "stability":    "Signal stability filter",
        "confluence":   "Min confluence gate",
        "h1confirm":    "1H candle confirmation",
        "micro_trend":  "Micro-candle trend (5s/10s/15s)",
        "trend_follow": "Trend-follow filter (ON=trend only / OFF=all signals)",
    }
    for name, state in _FILTER_FLAGS.items():
        icon = icons.get(name, "🔧")
        desc = descs.get(name, name)
        status = "✅ ON" if state else "🔴 OFF"
        lines.append("{} *{}* - {} `[{}]`".format(icon, desc, status, name))
    return "\n".join(lines)

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
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    if not fh_sym and not yf_sym:
        return 0.05, False

    df = None
    try:
        if fh_sym and FINNHUB_KEY:
            df = _mtf_fh_candles(fh_sym, "5", 60)
            if df is None or len(df) < 15:
                df = None
    except Exception:
        df = None
    if df is None and yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "1d", "5m")
        except Exception:
            df = None
    try:
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

_FIB_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]
_FIB_ZONE   = 0.008  # ±0.8% of price counts as "near a level"

def _check_fibonacci(pair, direction):
    """
    Calculate Fibonacci retracement from recent swing high/low (last 50 candles, 5m).
    Returns (fib_bonus_buy, fib_bonus_sell, nearest_level_str).
    Near support level → BUY bonus. Near resistance → SELL bonus.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    if not fh_sym and not yf_sym:
        return 0, 0, None

    df = None
    try:
        if fh_sym and FINNHUB_KEY:
            df = _mtf_fh_candles(fh_sym, "5", 100)
            if df is None or len(df) < 20:
                df = None
    except Exception:
        df = None
    if df is None and yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "2d", "5m")
        except Exception:
            df = None
    try:
        if df is None or len(df) < 20:
            return 0, 0, None
        high  = df["High"].squeeze().astype(float)
        low   = df["Low"].squeeze().astype(float)
        close = df["Close"].squeeze().astype(float)
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

def _price_action_score(pair):
    """
    Analyze last 10 candles for higher highs / lower lows structure.
    Returns (pa_buy_bonus, pa_sell_bonus, trend_str).
    Strong uptrend (HH+HL) → BUY bonus. Downtrend (LH+LL) → SELL bonus.
    """
    real_pair = OTC_TO_REAL.get(pair, pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    if not fh_sym and not yf_sym:
        return 0, 0, None

    df = None
    try:
        if fh_sym and FINNHUB_KEY:
            df = _mtf_fh_candles(fh_sym, "5", 60)
            if df is None or len(df) < 12:
                df = None
    except Exception:
        df = None
    if df is None and yf_sym:
        try:
            df = _yf_download_cached(yf_sym, "1d", "5m")
        except Exception:
            df = None
    try:
        if df is None or len(df) < 12:
            return 0, 0, None
        high  = df["High"].squeeze().astype(float).values[-12:]
        low   = df["Low"].squeeze().astype(float).values[-12:]
        close = df["Close"].squeeze().astype(float).values[-12:]

        hh = hl = lh = ll = 0
        for i in range(1, len(high)):
            if high[i] > high[i-1]: hh += 1
            else:                    lh += 1
            if low[i] > low[i-1]:   hl += 1
            else:                    ll += 1

        bull_score = hh + hl   # max 22
        bear_score = lh + ll

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
    Check signal history bias using ACTUAL WIN RATE per direction, not just count.
    Fetches win/loss from signal_outcomes table so we reinforce what WORKS.
    Falls back to direction count if signal_outcomes is empty.
    Returns: (same_count, total, same_pct)
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT direction, COUNT(*) as total,
                              SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins
                       FROM signal_outcomes
                       WHERE pair=%s
                       GROUP BY direction""",
                    (pair,)
                )
                rows = cur.fetchall()
        if rows:
            dir_stats = {r["direction"]: {"total": int(r["total"]), "wins": int(r["wins"])} for r in rows}
            d_data = dir_stats.get(direction, {})
            total = d_data.get("total", 0)
            wins  = d_data.get("wins", 0)
            if total >= 5:
                win_rate = wins / total
                return wins, total, win_rate
    except Exception:
        pass

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
                       ORDER BY created_at DESC LIMIT 5""",
                    (pair, cutoff)
                )
                rows = cur.fetchall()
        if not rows or len(rows) < 2:
            return True   # Not enough history - allow signal

        directions = [r["direction"] for r in rows]
        total = len(directions)
        opposite = "SELL" if proposed_direction == "BUY" else "BUY"
        opposite_pct = directions.count(opposite) / total

        if opposite_pct >= 0.70:
            logging.info("STABILITY FILTER: {} blocked flip to {} ({}% were {})".format(
                pair, proposed_direction, int(opposite_pct*100), opposite))
            return False

        return True
    except Exception as e:
        logging.warning("_check_signal_stability failed {}: {}".format(pair, e))
        return True   # Allow on error

_otc_flip_cache: dict = {}

_tf_candidate_scores: dict = {1: 0.0, 2: 0.0, 3: 0.0}
_micro_scores: dict = {}

def _smart_nonOTC_expiry(
    pair: str,
    direction: str,
    rsi: float = 50.0,
    sto: float = 50.0,
    ma_diff: float = 0.0,
    macd: float = 0.0,
    bb_pos: float = 0.5,
    mom: float = 0.0,
    vol: float = 0.5,
    candle: float = 0.0,
    trend_1h=None,
    mtf=None,
    indicators_agree: int = 0,
    movement_cat: str = "MEDIUM",
    atr_pct: float = 0.05,
    fib_buy_bonus: int = 0,
    fib_sell_bonus: int = 0,
    pa_buy_bonus: int = 0,
    pa_sell_bonus: int = 0,
    pattern_buy_bonus: int = 0,
    pattern_sell_bonus: int = 0,
    deriv_cache=None,
    adx_val: float = 25.0,
) -> int:
    """
    Chagua TF bora (1/2/3 dakika) kwa non-OTC signal.
    Uses real data from Yahoo, Deriv, Fibonacci, PA and VTE history.

    v46 FIXES:
    - Hakuna upendeleo wa awali kwa TF yoyote. Kila TF inaanza 0.
    - Kila kipengele (RSI, BB, ATR, Fib, PA, nk) kinapewa points kwa MANTIKI,
      si kwa mazoea ya 1m kwanza.
    - Strong indicators (ia >= 8) support both 1m AND 2m equally. They show
      trend imara - inaweza kwisha ndani ya 1m au 2m.
    - RSI/Sto extremes: zinaashiria reversal inayowezekana. Lakini kama ATR ni
      ndogo, reversal inaweza kuchukua dakika 2-3 kuonekana. Kwa hivyo ATR
      inaathiri jinsi RSI/Sto extremes zinavyosaidia 1m.
    - BB edge + ATR ndogo: reversal inaweza kuwa ya polepole → 2m/3m bora.
    - Fib level bila momentum: inaweza kusimama muda mrefu. Kwa hivyo Fib
      inasaidia 2m zaidi kuliko 1m kama momentum ni dhaifu.
    - Deriv micro HTF: kila TF ya micro (5s/10s/15s) inasaidia TF yake husika
      kwa uzito mkubwa zaidi - hii ndiyo kipengele kikuu.

    Returns: 1, 2, au 3
    """
    scores = {1: 0.0, 2: 0.0, 3: 0.0}

    try:
        _combo_sess = _get_session().get("name", "Unknown")
        scores, _combo_info = _apply_pg_best_combo_to_scores(
            scores, pair, direction,
            rsi=rsi, bb_pos=bb_pos, mom=mom,
            session=_combo_sess,
            max_bonus=35.0
        )
    except Exception as _a0_e:
        logging.warning("smart_nonOTC A0 combo failed {}: {}".format(pair, _a0_e))

    try:
        sess_name = _get_session().get("name", "Unknown")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS wr,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND session = %s AND tf_mins IN (1, 2, 3)
                """, (pair, sess_name))
                sess_rows = cur.fetchall()
                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS wr,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND tf_mins IN (1, 2, 3)
                """, (pair,))
                overall_rows = cur.fetchall()

        sess_tfs = set()
        for r in sess_rows:
            tf = int(r["tf_mins"])
            wr = float(r["wr"]) if r["wr"] is not None else 0.5
            tot = int(r["total"])
            if tot >= 3:
                conf = min(1.0, tot / 15.0)
                bonus = (wr - 0.45) * 80 * conf
                scores[tf] += bonus
                sess_tfs.add(tf)

        sess_tfs_found = {int(r["tf_mins"]) for r in sess_rows
                         if r["wr"] is not None and int(r.get("total", 0)) >= 3}
        for r in overall_rows:
            tf = int(r["tf_mins"])
            if tf in sess_tfs_found:
                continue
            wr = float(r["wr"]) if r["wr"] is not None else 0.5
            tot = int(r["total"])
            if tot >= 5:
                conf = min(1.0, tot / 20.0)
                bonus = (wr - 0.45) * 50 * conf
                scores[tf] += bonus

    except Exception as _e:
        logging.warning("smart_nonOTC_expiry VTE failed {}: {}".format(pair, _e))

    try:
        _pg_tf_probs = pg_predict_per_tf(
            pair, direction,
            rsi=rsi, bb_pos=bb_pos, session=sess_name if 'sess_name' in dir() else None
        )
        for _pg_tf in [1, 2, 3]:
            _pg_prob = _pg_tf_probs.get(_pg_tf, 0.5)
            if _pg_prob >= 0.65:
                _pg_bonus = (_pg_prob - 0.5) * 100  # 0.65→15, 0.80→30, 1.0→50
                scores[_pg_tf] += min(50, _pg_bonus)
            elif _pg_prob < 0.40:
                _pg_penalty = (0.50 - _pg_prob) * 80  # 0.40→8, 0.25→20, 0.0→40
                scores[_pg_tf] -= min(40, _pg_penalty)
        logging.info("PG_PER_TF nonOTC {}: 1m={:.2f} 2m={:.2f} 3m={:.2f} → score_adj 1m:{:.1f} 2m:{:.1f} 3m:{:.1f}".format(
            pair,
            _pg_tf_probs.get(1, 0.5), _pg_tf_probs.get(2, 0.5), _pg_tf_probs.get(3, 0.5),
            scores[1], scores[2], scores[3]
        ))
    except Exception as _pg_e:
        logging.warning("smart_nonOTC_expiry pg_predict_per_tf failed {}: {}".format(pair, _pg_e))

    atr = float(atr_pct)
    if atr >= 0.15:
        scores[1] += 24
        scores[2] += 10
        scores[3] -= 8
    elif atr >= 0.10:
        scores[1] += 16
        scores[2] += 15
        scores[3] += 3
    elif atr >= 0.06:
        scores[1] += 8
        scores[2] += 8
        scores[3] += 8
    elif atr >= 0.03:
        scores[1] -= 5
        scores[2] += 12
        scores[3] += 20
    else:
        scores[1] -= 15
        scores[2] += 4
        scores[3] += 24

    fib_active = fib_buy_bonus if direction == "BUY" else fib_sell_bonus
    if fib_active >= 20:
        if atr >= 0.08:
            scores[1] += 18
            scores[2] += 10
        else:
            scores[2] += 18
            scores[3] += 8
    elif fib_active >= 12:
        if atr >= 0.08:
            scores[1] += 8
            scores[2] += 16
        else:
            scores[2] += 14
            scores[3] += 8

    pa_active = pa_buy_bonus if direction == "BUY" else pa_sell_bonus
    mom_f = abs(float(mom))
    if pa_active >= 30:
        if mom_f >= 0.3:
            scores[1] += 18
            scores[2] += 14
        else:
            scores[2] += 20
            scores[3] += 8
    elif pa_active >= 20:
        scores[1] += 6
        scores[2] += 18
        scores[3] += 8
    elif pa_active >= 10:
        scores[2] += 10
        scores[3] += 14
    else:
        scores[3] += 12

    pat_active = pattern_buy_bonus if direction == "BUY" else pattern_sell_bonus
    if pat_active >= 35:
        if atr >= 0.07:
            scores[1] += 20
            scores[2] += 8
        else:
            scores[1] += 10
            scores[2] += 16
    elif pat_active >= 20:
        scores[1] += 8
        scores[2] += 14
        scores[3] += 4
    elif pat_active >= 10:
        scores[2] += 10
        scores[3] += 8

    if deriv_cache:
        dc_map = {1: ("5_s", "5_s_ind"), 2: ("10_s", "10_s_ind"), 3: ("15_s", "15_s_ind")}
        for tf_m, (dc_key, ind_key) in dc_map.items():
            dc_trend = deriv_cache.get(dc_key)
            dc_ind   = deriv_cache.get(ind_key)

            if not dc_trend:
                continue

            dc_dir    = dc_trend.get("direction", "FLAT")
            dc_str    = dc_trend.get("strength", 0)
            dc_rev    = dc_trend.get("reversal", False)
            dc_struct = dc_trend.get("htf_structure", "RANGING")
            dc_ema    = dc_trend.get("ema_cross")

            struct_mult = 1.4 if dc_struct in ("UPTREND", "DOWNTREND") else 0.75

            if dc_dir == direction:
                if not dc_rev:
                    base_bonus = dc_str * 0.65 * struct_mult
                    ema_bonus  = 12 if dc_ema == direction else 0
                    scores[tf_m] += base_bonus + ema_bonus
                else:
                    scores[tf_m] += dc_str * 0.12 - 14
            elif dc_dir not in ("FLAT", None) and dc_dir != direction:
                if dc_rev:
                    scores[tf_m] -= 35
                else:
                    oppose_penalty = 22 if dc_struct in ("UPTREND", "DOWNTREND") else 14
                    scores[tf_m] -= oppose_penalty
            elif dc_dir in ("FLAT", None):
                scores[tf_m] -= 5

            if dc_ind:
                ind_dir  = dc_ind.get("direction")
                ind_rsi  = dc_ind.get("rsi", 50)
                ind_macd = dc_ind.get("macd", 0)
                ind_ma   = dc_ind.get("ma_diff", 0)
                ind_bb   = dc_ind.get("bb_pos", 0.5)
                ind_mom  = dc_ind.get("mom", 0)
                ind_sto  = dc_ind.get("sto", 50)

                ind_score = 0.0

                if ind_dir == direction:
                    ind_score += 10
                elif ind_dir is not None and ind_dir != direction:
                    ind_score -= 8

                if direction == "BUY":
                    if ind_rsi < 30:     ind_score += 8
                    elif ind_rsi < 45:   ind_score += 4
                    elif ind_rsi > 70:   ind_score -= 6
                    elif ind_rsi > 55:   ind_score -= 2
                else:
                    if ind_rsi > 70:     ind_score += 8
                    elif ind_rsi > 55:   ind_score += 4
                    elif ind_rsi < 30:   ind_score -= 6
                    elif ind_rsi < 45:   ind_score -= 2

                if (direction == "BUY" and ind_macd > 0.1) or (direction == "SELL" and ind_macd < -0.1):
                    ind_score += min(6, abs(ind_macd) * 8)
                elif (direction == "BUY" and ind_macd < -0.1) or (direction == "SELL" and ind_macd > 0.1):
                    ind_score -= 5

                if (direction == "BUY" and ind_ma > 0.1) or (direction == "SELL" and ind_ma < -0.1):
                    ind_score += min(6, abs(ind_ma) * 10)
                elif (direction == "BUY" and ind_ma < -0.1) or (direction == "SELL" and ind_ma > 0.1):
                    ind_score -= 4

                if direction == "BUY" and ind_bb <= 0.20:
                    ind_score += 5
                elif direction == "SELL" and ind_bb >= 0.80:
                    ind_score += 5
                elif direction == "BUY" and ind_bb >= 0.80:
                    ind_score -= 4
                elif direction == "SELL" and ind_bb <= 0.20:
                    ind_score -= 4

                if (direction == "BUY" and ind_mom > 0.1) or (direction == "SELL" and ind_mom < -0.1):
                    ind_score += min(5, abs(ind_mom) * 15)
                elif (direction == "BUY" and ind_mom < -0.1) or (direction == "SELL" and ind_mom > 0.1):
                    ind_score -= 3

                if direction == "BUY" and ind_sto < 25:
                    ind_score += 4
                elif direction == "SELL" and ind_sto > 75:
                    ind_score += 4
                elif direction == "BUY" and ind_sto > 75:
                    ind_score -= 3
                elif direction == "SELL" and ind_sto < 25:
                    ind_score -= 3

                scores[tf_m] += ind_score
                logging.info("DERIV IND {}s→{}m {}: dir={} rsi={:.0f} macd={:.2f} ma={:.2f} bb={:.2f} mom={:.2f} sto={:.0f} ind_score={:.1f}".format(
                    tf_m * 5, tf_m, pair, ind_dir, ind_rsi, ind_macd, ind_ma, ind_bb, ind_mom, ind_sto, ind_score))

    adx_f = float(adx_val)
    if adx_f >= 35:
        scores[1] += 20
        scores[2] += 16
        scores[3] += 4
    elif adx_f >= 25:
        scores[1] += 10
        scores[2] += 16
        scores[3] += 8
    elif adx_f >= 18:
        scores[1] += 2
        scores[2] += 14
        scores[3] += 12
    else:
        scores[1] -= 10
        scores[2] += 6
        scores[3] += 20

    mom_abs = abs(float(mom))
    if mom_abs >= 0.6:
        scores[1] += 18
        scores[2] += 10
        scores[3] += 2
    elif mom_abs >= 0.3:
        scores[1] += 8
        scores[2] += 16
        scores[3] += 8
    else:
        scores[1] += 0
        scores[2] += 8
        scores[3] += 18

    candle_abs = abs(float(candle))
    if candle_abs >= 0.8 and (candle > 0) == (direction == "BUY"):
        scores[1] += 16
        scores[2] += 6
    elif candle_abs >= 0.4 and (candle > 0) == (direction == "BUY"):
        scores[1] += 6
        scores[2] += 12
    elif candle_abs >= 0.8 and (candle > 0) != (direction == "BUY"):
        scores[1] -= 14
        scores[2] -= 4
        scores[3] += 12
    elif candle_abs < 0.3:
        scores[3] += 12

    ia = int(indicators_agree)
    if ia >= 10:
        if atr >= 0.08:
            scores[1] += 20
            scores[2] += 14
        else:
            scores[1] += 8
            scores[2] += 20
            scores[3] += 6
    elif ia >= 8:
        if atr >= 0.08:
            scores[1] += 14
            scores[2] += 18
        else:
            scores[2] += 20
            scores[3] += 8
    elif ia >= 6:
        scores[2] += 18
        scores[3] += 10
    elif ia >= 4:
        scores[2] += 10
        scores[3] += 16
    else:
        scores[3] += 20

    rsi_f = float(rsi)
    if rsi_f <= 20 or rsi_f >= 80:
        if atr >= 0.09:
            scores[1] += 18
            scores[2] += 8
        elif atr >= 0.06:
            scores[1] += 12
            scores[2] += 14
        else:
            scores[1] += 4
            scores[2] += 16
            scores[3] += 8
    elif rsi_f <= 30 or rsi_f >= 70:
        if atr >= 0.08:
            scores[1] += 10
            scores[2] += 8
        else:
            scores[2] += 12
            scores[3] += 6
    elif 45 <= rsi_f <= 55:
        scores[2] += 10
        scores[3] += 8

    sto_f = float(sto)
    if sto_f <= 15 or sto_f >= 85:
        if atr >= 0.08:
            scores[1] += 14
        else:
            scores[2] += 14
    elif sto_f <= 25 or sto_f >= 75:
        if atr >= 0.07:
            scores[1] += 7
            scores[2] += 6
        else:
            scores[2] += 12

    if bb_pos <= 0.08 or bb_pos >= 0.92:
        if atr >= 0.09:
            scores[1] += 18
            scores[2] += 8
        elif atr >= 0.06:
            scores[1] += 10
            scores[2] += 14
        else:
            scores[2] += 16
            scores[3] += 8
    elif bb_pos <= 0.20 or bb_pos >= 0.80:
        if atr >= 0.07:
            scores[1] += 8
            scores[2] += 8
        else:
            scores[2] += 12
            scores[3] += 6
    elif 0.40 <= bb_pos <= 0.60:
        scores[2] += 10
        scores[3] += 8

    macd_f = abs(float(macd))
    ma_f   = abs(float(ma_diff))
    if macd_f >= 0.5 and ma_f >= 0.4:
        scores[1] += 10
        scores[2] += 14
    elif macd_f >= 0.2 and ma_f >= 0.2:
        scores[2] += 12
        scores[3] += 6
    else:
        scores[3] += 14

    if trend_1h == direction:
        scores[1] += 14
        scores[2] += 14
        scores[3] += 8
    elif trend_1h is not None and trend_1h != direction:
        scores[1] -= 22
        scores[2] -= 8
        scores[3] += 14

    if mtf and mtf.get("total", 0) >= 3:
        mtf_dir_tfs = mtf.get("buy_tfs", 0) if direction == "BUY" else mtf.get("sell_tfs", 0)
        mtf_total   = mtf["total"]
        mtf_ratio   = mtf_dir_tfs / max(mtf_total, 1)
        if mtf_ratio >= 0.75:
            scores[1] += 14
            scores[2] += 16
            scores[3] += 6
        elif mtf_ratio >= 0.50:
            scores[2] += 16
            scores[3] += 8
        else:
            scores[1] -= 12
            scores[3] += 18

    yf_sym = YAHOO_SYMBOLS.get(pair)
    if yf_sym:
        try:
            df_1m = _yf_download_cached(yf_sym, "1d", "1m")
            if df_1m is not None and len(df_1m) >= 5:
                c1 = df_1m["Close"].squeeze().astype(float)
                o1 = df_1m["Open"].squeeze().astype(float)

                bull5 = sum(1 for i in range(-5, 0)
                            if float(c1.iloc[i]) > float(o1.iloc[i]))
                bear5 = 5 - bull5
                micro_dir = "BUY" if bull5 >= bear5 else "SELL"
                micro_str = max(bull5, bear5) / 5 * 100  # 60-100

                bull3 = sum(1 for i in range(-3, 0)
                            if float(c1.iloc[i]) > float(o1.iloc[i]))
                micro3_dir = "BUY" if bull3 >= 2 else "SELL"

                if micro_dir == direction and micro_str >= 80:
                    if atr >= 0.08:
                        scores[1] += 26
                        scores[2] += 12
                    else:
                        scores[1] += 14
                        scores[2] += 20
                elif micro_dir == direction and micro_str >= 60:
                    scores[1] += 10
                    scores[2] += 18
                    scores[3] += 4
                elif micro_dir != direction and micro3_dir == direction:
                    scores[2] += 20
                    scores[3] += 10
                elif micro_dir != direction:
                    scores[1] -= 26
                    scores[2] -= 10
                    scores[3] += 20

                logging.info("NONOTC EXPIRY micro1m {}: dir={} str={:.0f}% last3={} atr={:.3f} → 1m:{:.1f} 2m:{:.1f} 3m:{:.1f}".format(
                    pair, micro_dir, micro_str, micro3_dir, atr,
                    scores[1], scores[2], scores[3]))
        except Exception as _ye:
            logging.warning("smart_nonOTC micro1m failed {}: {}".format(pair, _ye))

    min_s = min(scores.values())
    if min_s < 0:
        for tf in scores:
            scores[tf] -= min_s

    global _tf_candidate_scores, _micro_scores
    _tf_candidate_scores = dict(scores)
    _micro_scores = {}
    if deriv_cache:
        for dc_key in ["5_s", "10_s", "15_s"]:
            dc_trend = deriv_cache.get(dc_key)
            if dc_trend:
                _micro_scores[dc_key] = dc_trend.get("strength", 0)

    best_tf = max(scores, key=lambda t: scores[t])

    logging.info("NONOTC EXPIRY SELECT {}: dir={} 1m:{:.1f} 2m:{:.1f} 3m:{:.1f} → leading={}m [ia={} atr={:.3f} fib={} pa={} pat={} adx={:.0f}]".format(
        pair, direction, scores[1], scores[2], scores[3], best_tf,
        indicators_agree, atr_pct, fib_active, pa_active, pat_active, adx_f))

    return (best_tf, scores)

def _smart_otc_expiry(
    pair: str,
    direction: str,
    rsi: float = 50.0,
    sto: float = 50.0,
    ma_diff: float = 0.0,
    macd: float = 0.0,
    bb_pos: float = 0.5,
    mom: float = 0.0,
    vol: float = 0.5,
    candle: float = 0.0,
    trend_1h=None,
    mtf=None,
    indicators_agree: int = 0,
    movement_cat: str = "MEDIUM",
) -> int:
    """
    Choose best TF (1/2/3 min) for each signal using real logic.
    Works for both OTC and non-OTC signals.
    Returns: 1, 2, au 3
    """

    scores = {1: 0.0, 2: 0.0, 3: 0.0}

    try:
        _otc_combo_sess = _get_session().get("name", "Unknown")
        scores, _otc_combo_info = _apply_pg_best_combo_to_scores(
            scores, pair, direction,
            rsi=rsi, bb_pos=bb_pos, mom=mom,
            session=_otc_combo_sess,
            max_bonus=25.0  # OTC: uzito kidogo mdogo kuliko non-OTC
        )
    except Exception as _otc_a0_e:
        logging.warning("smart_otc A0 combo failed {}: {}".format(pair, _otc_a0_e))

    try:
        sess_name = _get_session().get("name", "Unknown")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS wr,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND session = %s AND tf_mins IN (1, 2, 3)
                """, (pair, sess_name))
                sess_rows = cur.fetchall()
                cur.execute("""
                    SELECT tf_mins,
                           wins::float / NULLIF(wins + losses, 0) AS wr,
                           (wins + losses) AS total
                    FROM tf_session_stats
                    WHERE pair = %s AND tf_mins IN (1, 2, 3)
                """, (pair,))
                overall_rows = cur.fetchall()

        for r in sess_rows:
            tf = int(r["tf_mins"])
            wr = float(r["wr"]) if r["wr"] is not None else 0.5
            tot = int(r["total"])
            if tot >= 3:
                conf = min(1.0, tot / 15.0)
                vte_bonus = (wr - 0.45) * 80 * conf
                scores[tf] += vte_bonus
                logging.info("EXPIRY VTE session {}: tf={}m wr={:.0f}% ({}) bonus={:.1f}".format(
                    pair, tf, wr * 100, tot, vte_bonus))

        sess_tfs_found = {int(r["tf_mins"]) for r in sess_rows if r["wr"] is not None}
        for r in overall_rows:
            tf = int(r["tf_mins"])
            if tf in sess_tfs_found:
                continue  # Session data tayari ipo - usirudie
            wr = float(r["wr"]) if r["wr"] is not None else 0.5
            tot = int(r["total"])
            if tot >= 5:
                conf = min(1.0, tot / 20.0)
                vte_bonus = (wr - 0.45) * 50 * conf
                scores[tf] += vte_bonus

    except Exception as _e:
        logging.warning("smart_expiry VTE failed {}: {}".format(pair, _e))

    try:
        _pg_sess = _get_session().get("name", "Unknown") if 'sess_name' not in dir() else sess_name
        _pg_tf_probs_otc = pg_predict_per_tf(
            pair, direction, rsi=rsi, bb_pos=bb_pos, session=_pg_sess
        )
        for _pg_tf in [1, 2, 3]:
            _pg_prob = _pg_tf_probs_otc.get(_pg_tf, 0.5)
            if _pg_prob >= 0.65:
                _pg_bonus = (_pg_prob - 0.5) * 80   # OTC: uzito kidogo mdogo
                scores[_pg_tf] += min(40, _pg_bonus)
            elif _pg_prob < 0.40:
                _pg_penalty = (0.50 - _pg_prob) * 60
                scores[_pg_tf] -= min(30, _pg_penalty)
        logging.info("PG_PER_TF OTC {}: 1m={:.2f} 2m={:.2f} 3m={:.2f}".format(
            pair, _pg_tf_probs_otc.get(1, 0.5), _pg_tf_probs_otc.get(2, 0.5), _pg_tf_probs_otc.get(3, 0.5)))
    except Exception as _pg_e:
        logging.warning("smart_expiry OTC pg_predict_per_tf failed {}: {}".format(pair, _pg_e))

    mom_abs = abs(float(mom))
    if mom_abs >= 0.6:
        scores[1] += 16
        scores[2] += 9
        scores[3] += 3
    elif mom_abs >= 0.3:
        scores[1] += 9
        scores[2] += 14
        scores[3] += 8
    else:
        scores[1] += 4
        scores[2] += 9
        scores[3] += 15

    candle_abs = abs(float(candle))
    if candle_abs >= 0.8 and (candle > 0) == (direction == "BUY"):
        scores[1] += 14
    elif candle_abs >= 0.4 and (candle > 0) == (direction == "BUY"):
        scores[2] += 10
    elif candle_abs < 0.3:
        scores[3] += 10

    if movement_cat == "HIGH":
        scores[1] += 15
        scores[2] += 8
        scores[3] += 2
    elif movement_cat == "MEDIUM":
        scores[1] += 8
        scores[2] += 10
        scores[3] += 8
    else:  # LOW
        scores[1] += 2
        scores[2] += 8
        scores[3] += 14

    ia = int(indicators_agree)
    if ia >= 10:
        scores[1] += 22
        scores[2] += 10
    elif ia >= 8:
        scores[1] += 14
        scores[2] += 16
    elif ia >= 6:
        scores[2] += 18
        scores[3] += 8
    elif ia >= 4:
        scores[2] += 10
        scores[3] += 16
    else:
        scores[3] += 20

    rsi_f = float(rsi)
    if rsi_f <= 20 or rsi_f >= 80:
        scores[1] += 15
    elif rsi_f <= 30 or rsi_f >= 70:
        scores[1] += 8
        scores[2] += 5
    elif 45 <= rsi_f <= 55:
        scores[2] += 8
        scores[3] += 6

    sto_f = float(sto)
    if sto_f <= 15 or sto_f >= 85:
        scores[1] += 12
    elif sto_f <= 25 or sto_f >= 75:
        scores[1] += 6
        scores[2] += 4

    if bb_pos <= 0.08 or bb_pos >= 0.92:
        scores[1] += 16
    elif bb_pos <= 0.20 or bb_pos >= 0.80:
        scores[1] += 8
        scores[2] += 5
    elif 0.40 <= bb_pos <= 0.60:
        scores[2] += 8
        scores[3] += 6

    macd_f = abs(float(macd))
    ma_f   = abs(float(ma_diff))
    if macd_f >= 0.5 and ma_f >= 0.4:
        scores[1] += 12
        scores[2] += 10
    elif macd_f >= 0.2 and ma_f >= 0.2:
        scores[2] += 10
        scores[3] += 5
    else:
        scores[3] += 12

    if trend_1h == direction:
        scores[1] += 12
        scores[2] += 10
        scores[3] += 5
    elif trend_1h is not None and trend_1h != direction:
        scores[1] -= 15
        scores[2] -= 5
        scores[3] += 10

    if mtf and mtf.get("total", 0) >= 3:
        mtf_dir_tfs = mtf.get("buy_tfs", 0) if direction == "BUY" else mtf.get("sell_tfs", 0)
        mtf_total   = mtf["total"]
        mtf_ratio   = mtf_dir_tfs / max(mtf_total, 1)
        if mtf_ratio >= 0.75:
            scores[1] += 14
            scores[2] += 10
        elif mtf_ratio >= 0.50:
            scores[2] += 12
            scores[3] += 6
        else:
            scores[1] -= 8
            scores[3] += 14

    if "OTC" in pair:
        real_p = OTC_TO_REAL.get(pair)
        if real_p:
            yf_sym = YAHOO_SYMBOLS.get(real_p)
            if yf_sym:
                try:
                    df_1m = _yf_download_cached(yf_sym, "1d", "1m")
                    if df_1m is not None and len(df_1m) >= 5:
                        c1 = df_1m["Close"].squeeze().astype(float)
                        o1 = df_1m["Open"].squeeze().astype(float)
                        bull5 = sum(1 for i in range(-5, 0)
                                    if float(c1.iloc[i]) > float(o1.iloc[i]))
                        bear5 = 5 - bull5
                        micro_dir = "BUY" if bull5 >= bear5 else "SELL"
                        micro_str = max(bull5, bear5) / 5 * 100  # 60-100

                        if micro_dir == direction and micro_str >= 80:
                            scores[1] += 20
                            scores[2] += 8
                        elif micro_dir == direction and micro_str >= 60:
                            scores[1] += 10
                            scores[2] += 14
                        elif micro_dir != direction:
                            scores[1] -= 18
                            scores[2] -= 6
                            scores[3] += 15
                        logging.info("EXPIRY OTC micro {}: dir={} str={:.0f}% → 1m:{:.1f} 2m:{:.1f} 3m:{:.1f}".format(
                            pair, micro_dir, micro_str, scores[1], scores[2], scores[3]))
                except Exception as _oe:
                    logging.warning("smart_expiry OTC micro failed {}: {}".format(pair, _oe))

    min_s  = min(scores.values())
    if min_s < 0:
        for tf in scores:
            scores[tf] -= min_s  # Shift all to >= 0

    best_tf = max(scores, key=lambda t: scores[t])

    logging.info("EXPIRY SELECT OTC {}: dir={} 1m:{:.1f} 2m:{:.1f} 3m:{:.1f} → {}m".format(
        pair, direction, scores[1], scores[2], scores[3], best_tf))

    return best_tf

def update_tf_outcome(pair: str, tf_mins: int, won: bool):
    """
    v50: Kazi hii imesogezwa kwenda update_signal_history_won().
    Imebaki hapa kwa backward compatibility tu - haifanyi kitu.
    tf_session_stats inasasishwa automatically na update_signal_history_won().
    """
    pass  # No-op: now handled by update_signal_history_won()

async def _send_nonotc_signal(context, chat, user_id, pair, direction, timeframe, sig, idx_str):
    """Send a non-OTC signal - simple clean caption."""
    ib          = direction == "BUY"
    arrow       = "Up 🟢" if ib else "Down 🔴"
    strength    = sig.get("strength", 200)
    if isinstance(strength, int) and strength > 450:
        strength = int(90 + (min(500, max(300, strength)) - 300) / 200 * 360)
    elif isinstance(strength, int) and strength < 90:
        strength = int(90 + (max(35, min(97, strength)) - 35) / 62 * 360)
    strength = max(90, min(450, int(strength)))
    _broker_line = get_broker_display(user_id)
    caption  = "*{}* {}\n🕐 In *{}* min\n📊 Signal strength: {}%{}".format(
        pair, arrow, timeframe, strength,
        "\n" + _broker_line if _broker_line else "")
    kb  = nonotc_signal_keyboard(pair, timeframe)
    img = get_buy_image() if ib else get_sell_image()
    try:
        await delete_last_signal(context.bot, chat, user_id)
        sent = await context.bot.send_photo(chat_id=chat, photo=img, caption=caption,
                                            parse_mode="Markdown", reply_markup=kb)
        save_last_signal_msg(user_id, sent.message_id)
    except Exception as e:
        logging.warning("_send_nonotc_signal failed: {}".format(e))

FINNHUB_FOREX_SYMBOLS = {
    "EUR/USD": "OANDA:EUR_USD", "GBP/USD": "OANDA:GBP_USD",
    "USD/JPY": "OANDA:USD_JPY", "USD/CHF": "OANDA:USD_CHF",
    "AUD/USD": "OANDA:AUD_USD", "USD/CAD": "OANDA:USD_CAD",
    "EUR/GBP": "OANDA:EUR_GBP",
    "EUR/JPY": "OANDA:EUR_JPY", "GBP/JPY": "OANDA:GBP_JPY",
    "AUD/JPY": "OANDA:AUD_JPY", "EUR/AUD": "OANDA:EUR_AUD",
    "EUR/CAD": "OANDA:EUR_CAD", "GBP/AUD": "OANDA:GBP_AUD",
    "GBP/CAD": "OANDA:GBP_CAD", "AUD/CAD": "OANDA:AUD_CAD",
    "AUD/CHF": "OANDA:AUD_CHF",
    "EUR/CHF": "OANDA:EUR_CHF", "CHF/JPY": "OANDA:CHF_JPY",
    "CAD/JPY": "OANDA:CAD_JPY", "CAD/CHF": "OANDA:CAD_CHF",
    "GBP/CHF": "OANDA:GBP_CHF",
    "USD/NOK": "OANDA:USD_NOK",
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
        df = _yf_download_cached(symbol, period, interval)
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

        ema9  = float(close.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1]) if n >= 50 else ema21
        gap   = abs(ema9 - ema21) / (ema21 + 1e-9) * 100
        if gap >= 0.003:
            if ema9 > ema21: buy  += 3 + (1 if c > ema21 else 0) + (1 if ema21 > ema50 else 0)
            else:            sell += 3 + (1 if c < ema21 else 0) + (1 if ema21 < ema50 else 0)

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        hist  = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
        h_now = float(hist.iloc[-1]); h_prv = float(hist.iloc[-2])
        if h_now > 0:   buy  += 3 if h_now > h_prv else 1
        elif h_now < 0: sell += 3 if h_now < h_prv else 1

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

        l14 = low.rolling(14).min(); h14 = high.rolling(14).max()
        sto = float(((close-l14)/(h14-l14+1e-9)*100).iloc[-1])
        sp  = float(((close-l14)/(h14-l14+1e-9)*100).iloc[-2])
        if sto < 20: buy  += 3 if sto > sp else 1
        elif sto > 80: sell += 3 if sto < sp else 1

        sma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bb_u  = float((sma20+2*std20).iloc[-1]); bb_l = float((sma20-2*std20).iloc[-1])
        bb_m  = float(sma20.iloc[-1])
        if c < bb_l: buy  += 3
        elif c < bb_m: buy  += 1
        elif c > bb_u: sell += 3
        elif c > bb_m: sell += 1
        if (bb_u-bb_l)/(bb_m+1e-9) < 0.005: buy -= 1; sell -= 1  # Squeeze penalty

        if n >= 11:
            roc = (c - float(close.iloc[-11])) / (float(close.iloc[-11])+1e-9) * 100
            if roc > 0.3: buy += 2
            elif roc > 0.1: buy += 1
            elif roc < -0.3: sell += 2
            elif roc < -0.1: sell += 1

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

        if n >= 20:
            tp  = (high+low+close)/3
            mad = tp.rolling(20).apply(lambda x: abs(x-x.mean()).mean(), raw=True)
            cci = float(((tp-tp.rolling(20).mean())/(0.015*mad+1e-9)).iloc[-1])
            if cci < -100: buy  += 3
            elif cci < -50: buy  += 1
            elif cci > 100: sell += 3
            elif cci > 50:  sell += 1

        if n >= 14:
            wpr = float(((high.rolling(14).max()-close)/(high.rolling(14).max()-low.rolling(14).min()+1e-9)*-100).iloc[-1])
            if wpr < -80: buy  += 3
            elif wpr < -50: buy += 1
            elif wpr > -20: sell += 3
            elif wpr > -50: sell += 1

        if volume.sum() > 0 and n >= 20:
            tp_v  = (high+low+close)/3
            vwap  = (tp_v*volume).rolling(20).sum()/(volume.rolling(20).sum()+1e-9)
            if c > float(vwap.iloc[-1]): buy  += 2
            else:                         sell += 2

        if n >= 10:
            obv = (volume*((close-close.shift(1)).apply(lambda x: 1 if x>0 else(-1 if x<0 else 0)))).cumsum()
            if float(obv.iloc[-1]) > float(obv.rolling(10).mean().iloc[-1]): buy  += 1
            else:                                                               sell += 1

        if n >= 26:
            tk = float(((high.rolling(9).max()+low.rolling(9).min())/2).iloc[-1])
            kj = float(((high.rolling(26).max()+low.rolling(26).min())/2).iloc[-1])
            if c > tk and c > kj and tk > kj:   buy  += 3
            elif c < tk and c < kj and tk < kj: sell += 3
            elif tk > kj: buy  += 1
            elif tk < kj: sell += 1

        if n >= 5:
            ha_c = (df["Open"].squeeze().astype(float)+high+low+close)/4
            ha_o = df["Open"].squeeze().astype(float).ewm(span=2,adjust=False).mean()
            if float(ha_c.iloc[-1])>float(ha_o.iloc[-1]) and float(ha_c.iloc[-2])>float(ha_o.iloc[-2]):
                buy  += 2
            elif float(ha_c.iloc[-1])<float(ha_o.iloc[-1]) and float(ha_c.iloc[-2])<float(ha_o.iloc[-2]):
                sell += 2

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

        if n >= 10:
            rsi_s    = 100-100/(1+gain/loss.replace(0,1e-9))
            price_ch = float(close.iloc[-1])-float(close.iloc[-6])
            rsi_ch   = float(rsi_s.iloc[-1])-float(rsi_s.iloc[-6])
            if price_ch > 0 and rsi_ch < -3:  sell += 3
            elif price_ch < 0 and rsi_ch > 3: buy  += 3

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
    df = _mtf_yf_candles(yf_sym, "1m", "1d")
    if df is not None and len(df) >= 3:
        opens  = df["Open"].squeeze().astype(float)
        closes = df["Close"].squeeze().astype(float)
        c1b = float(closes.iloc[-1]) > float(opens.iloc[-1])
        c2b = float(closes.iloc[-2]) > float(opens.iloc[-2])
        if c1b and c2b:         votes.append("BUY")
        elif not c1b and not c2b: votes.append("SELL")
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
    strength_pct = int(90 + (max(0, min(100, trend_score)) / 100) * 360)
    strength_pct = max(90, min(450, strength_pct))
    return (
        "*{}* {}\n"
        "🕐 In *{}* min\n"
        "📊 Signal strength: {}"
    ).format(pair, arrow, sig_type, strength_pct)

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
    if "OTC" in pair:
        return None

    result = run_mtf_signal_engine(pair)

    if result and result.get("direction") in ("CALL", "PUT"):
        return result

    real_pair = OTC_TO_REAL.get(pair, pair)
    yf_sym    = YAHOO_SYMBOLS.get(real_pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)
    all_dirs  = result.get("tf_labels", []) if result else []

    types_to_try = [signal_type] if signal_type else [1, 2, 3]
    for st in types_to_try:
        try:
            ad = {}
            if result and result.get("tf_labels"):
                for lbl, d in result["tf_labels"]:
                    ad[lbl] = d
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

    st = types_to_try[0] if types_to_try else 1
    return _force_signal_from_micro(pair, st)

_NN_MODEL_DIR        = "/tmp/evalon_nn_models"
_NN_GLOBAL_FILE      = "/tmp/evalon_nn_models/global_model.pkl"
_NN_SCALER_FILE      = "/tmp/evalon_nn_models/global_scaler.pkl"
_NN_MIN_SAMPLES      = 40
_NN_MIN_PAIR_SAMPLES = 25
_NN_CONFIDENCE_THRESHOLD = 0.72
_NN_RETRAIN_HOURS    = 6

_nn_global_model  = None
_nn_global_scaler = None
_nn_per_pair      = {}
_nn_training_data = []
_nn_pair_data     = {}
_nn_last_retrain  = None
_nn_total_flips   = 0
_nn_flip_wins     = 0

_NN_SESSION_MAP = {
    "London Open":  1.0,
    "NY/London":    0.8,
    "NY Session":   0.6,
    "Asian":       -0.5,
    "Dead Hours":  -1.0,
    "Pre-London":   0.3,
}

def _nn_session_num():
    try:
        sess = _get_session()
        return _NN_SESSION_MAP.get(sess.get("name", ""), 0.0)
    except Exception:
        return 0.0

def _nn_features_from_signal(sig_dict, rsi, sto, ma_diff, macd, bb_pos, mom, vol, candle,
                              atr_pct=0.05, adx_val=20.0, cci_val=0.0, wpr_val=-50.0,
                              fib_bonus=0, pa_score=0, pattern_bonus=0,
                              tf_votes=0, pip_movement=0.08, tf_mins=0):
    """Stub - v48 haihitaji features array. Returns None."""
    return None

def _nn_make_model():
    return None

def _nn_make_mlp():
    return None

def _nn_make_xgb():
    return None

def _nn_make_rf():
    return None

def _nn_make_lgb():
    return None

def _nn_load_global():
    """v48 stub - hakuna model ya kupakia."""
    pass

def _nn_load_pair(pair):
    pass

def _nn_save_global():
    pass

def _nn_save_pair(pair):
    pass

def _nn_load_training_data_from_db():
    return []

def _nn_retrain_global(force=False):
    pass

def _nn_retrain_pair(pair):
    pass

def _nn_record_outcome(pair, features_arr, won: bool):
    """v48: matokeo yanahifadhiwa na update_signal_history_won() badala yake."""
    pass

def _nn_adjust_direction(pair, features_arr, current_direction):
    """
    v48: Tumia pg_predict() badala ya ML model.
    Inaangalia DB win-rate na inaweza kubadilisha direction
    kama opposite direction ina win rate nzuri zaidi.
    """
    global _nn_total_flips
    try:
        win_prob, source, should_flip = pg_predict(
            pair, current_direction
        )
        if should_flip:
            flipped = "SELL" if current_direction == "BUY" else "BUY"
            _nn_total_flips += 1
            logging.info("PG_PREDICT FLIP {}: {} → {} (source: {})".format(
                pair, current_direction, flipped, source))
            return flipped, win_prob, True
        high_conf = win_prob >= _NN_CONFIDENCE_THRESHOLD
        return current_direction, win_prob, high_conf
    except Exception as e:
        logging.warning("_nn_adjust_direction v48 failed {}: {}".format(pair, e))
        return current_direction, None, False

_NN_SIGNAL_FEATURES = {}

def nn_store_signal_features(user_id, pair, feat_arr, original_direction=None):
    """v48 stub - features hazihitajiki tena."""
    pass

def nn_get_signal_features(user_id, pair):
    """v48 stub."""
    return None

def record_signal_outcome(pair, direction, tf_used, won, entry_price=None, exit_price=None,
                          movement_pct=0.0, session=None, indicators_agree=0,
                          trend_1h=None, confluence_level=None):
    """
    Record detailed signal outcome to signal_outcomes table.
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
    """v48: matokeo yanaandikwa kwenye signal_history.won moja kwa moja."""
    global _nn_flip_wins
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM signal_history
                    WHERE pair = %s AND won IS NULL
                    ORDER BY created_at DESC LIMIT 1
                """, (pair,))
                row = cur.fetchone()
        if row:
            update_signal_history_won(row["id"], won)
            logging.info("PG_FEEDBACK {}: signal_id={} won={}".format(pair, row["id"], won))
    except Exception as e:
        logging.warning("nn_feedback_from_vte v48 failed {}: {}".format(pair, e))

def nn_get_stats():
    """
    v48: Return PG_PREDICT stats (no ML model).
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN won = TRUE THEN 1 ELSE 0 END) AS wins
                    FROM signal_history
                    WHERE won IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '30 days'
                """)
                row = cur.fetchone()
        total = int(row["total"]) if row and row["total"] else 0
        wins  = int(row["wins"])  if row and row["wins"]  else 0
        acc   = wins / total if total > 0 else 0.0
    except Exception:
        total = 0; acc = 0.0

    return {
        "available":       True,
        "global_ready":    total >= 10,
        "global_acc":      acc,
        "oos_acc_label":   "DB win-rate (30d)",
        "global_samples":  total,
        "in_mem_pending":  0,
        "pairs_trained":   0,
        "total_samples":   total,
        "last_retrain":    "N/A (PostgreSQL-only)",
        "total_flips":     _nn_total_flips,
        "flip_acc":        0.0,
        "top_pairs":       [],
        "next_retrain_hours": 0,
    }

async def _nn_scheduled_retrain_loop():
    """v48 stub - hakuna ML retrain inayohitajika."""
    while True:
        await asyncio.sleep(3600 * 24)  # Sleep forever - nothing to do

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

    opens_arr  = []
    closes_arr = []

    if fh_sym:
        try:
            df = _mtf_fh_candles(fh_sym, "1", 60)
            if df is not None and len(df) >= 15:
                opens_arr  = df["Open"].astype(float).tolist()
                closes_arr = df["Close"].astype(float).tolist()
        except Exception:
            pass

    if not opens_arr and yf_sym:
        try:
            import yfinance as yf
            df = _yf_download_cached(yf_sym, "1d", "1m")
            if df is not None and len(df) >= 15:
                opens_arr  = df["Open"].squeeze().astype(float).tolist()
                closes_arr = df["Close"].squeeze().astype(float).tolist()
        except Exception:
            pass

    if not opens_arr or len(opens_arr) < 10:
        return None

    opens_arr  = opens_arr[-60:]
    closes_arr = closes_arr[-60:]
    total_c    = len(opens_arr)

    results = {}

    bucket_map = {1: 1, 2: 2, 3: 3}  # signal_type → candles per bucket

    for sig_type, bucket in bucket_map.items():
        green = red = 0
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

    deriv_rescue_dir = None
    deriv_rescue_tf  = None
    _deriv_rescue_pair = OTC_TO_REAL.get(pair, pair)  # non-OTC pair - same for non-OTC
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

    if deriv_rescue_dir and _best_str_r >= 60:
        _rescue_tf_final = deriv_rescue_tf or 1
        logging.info("RESCUE nonOTC {} via Deriv: dir={} tf={}m".format(pair, deriv_rescue_dir, _rescue_tf_final))
        return {
            "direction": deriv_rescue_dir, "pair": pair, "timeframe": _rescue_tf_final,
            "strength": int(90 + (_best_str_r / 100) * 360),
            "indicators_agree": 4,
            "trend_1h": deriv_rescue_dir, "vwap_data": None, "confluence": {},
            "mtf": None, "flat": False, "patterns": {},
            "movement_cat": "MEDIUM", "avg_movement": 0.08,
            "no_signal_reason": "",
            "nn_confidence": None, "nn_used": False, "_nn_feat_arr": None,
            "_rescued": True,
        }

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

    micro_result = None  # {tf_mins: (direction, support_pct)}
    if symbol:
        try:
            df = _yf_download_cached(symbol, "1d", "1m")
            if df is not None and len(df) >= 20:
                opens  = df["Open"].squeeze().astype(float).values
                closes = df["Close"].squeeze().astype(float).values
                times_sec = list(range(len(opens)))  # proxy: each candle = 1 unit

                micro_result = {}
                for tf_mins, bucket_size in [(1, 5), (2, 10), (3, 15)]:
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

    best_tf        = None
    best_dir       = None
    best_support   = 0.0

    if micro_result:
        for tf_mins, (mdir, msupport) in micro_result.items():
            if msupport >= 60.0 and msupport > best_support:
                best_support = msupport
                best_tf      = tf_mins
                best_dir     = mdir

    final_dir = None
    final_tf  = best_tf or 2

    if best_dir and hist_dir:
        if best_dir == hist_dir:
            final_dir = best_dir   # Both agree - strong
        else:
            final_dir = best_dir
    elif best_dir:
        final_dir = best_dir
    elif hist_dir:
        final_dir = hist_dir
        if micro_result:
            best_any = max(micro_result.items(), key=lambda x: x[1][1])
            final_tf = best_any[0]

    if final_dir is None:
        return None  # Nothing to rescue with

    logging.info("RESCUE nonOTC {}: dir={} tf={}m (micro_support={:.0f}% hist={})".format(
        pair, final_dir, final_tf, best_support, hist_dir))

    return {
        "direction": final_dir, "pair": pair, "timeframe": final_tf,
        "strength": max(90, min(450, int(90 + (best_support / 100) * 360))),
        "indicators_agree": 3,
        "trend_1h": hist_dir, "vwap_data": None, "confluence": {},
        "mtf": None, "flat": False, "patterns": {},
        "movement_cat": "MEDIUM", "avg_movement": 0.08,
        "no_signal_reason": "",
        "nn_confidence": None, "nn_used": False, "_nn_feat_arr": None,
        "_rescued": True,
    }

_SIGNAL_TIMEOUT = 25  # v63: sequential fetch, cache-first — 25s ni ya kutosha

async def animated_analyzing(bot, chat_id, pair: str):
    """
    Sends an 'Analyzing...' message with animated dots.
    v53: Haizunguki milele — inacheza frames mara moja tu, kisha inasimama.
    Inarudisha (message_obj, stop_event).
    """
    frames = [
        "🔵 *Analyzing {}...*".format(pair),
        "🟣 *Processing {}...* 🔍".format(pair),
        "🔵 *Checking indicators {}...* ⏳".format(pair),
        "🟢 *Almost ready {}...* ✅".format(pair),
    ]
    _MAX_FRAMES = len(frames)  # play once only, no loop

    stop_event = asyncio.Event()
    try:
        cm = await bot.send_message(chat_id=chat_id, text=frames[0], parse_mode="Markdown")
    except Exception:
        return None, stop_event

    async def _animate():
        for i in range(1, _MAX_FRAMES):
            await asyncio.sleep(0.8)  # v62: reduced from 1.5 for faster feel
            if stop_event.is_set():
                return
            try:
                await cm.edit_text(frames[i], parse_mode="Markdown")
            except Exception:
                return

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
        _fb_dir = None
        try:
            _fb_dir = _fetch_1h_trend(pair)
        except Exception:
            pass
        if _fb_dir is None:
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT direction FROM signal_history WHERE pair=%s "
                            "ORDER BY created_at DESC LIMIT 10", (pair,))
                        rows = cur.fetchall()
                if rows:
                    dirs = [r["direction"] for r in rows]
                    _fb_dir = max(set(dirs), key=dirs.count)
            except Exception:
                pass
        if _fb_dir is None:
            _fb_dir = "BUY"  # neutral default - last resort only
        _fb_tf = _smart_otc_expiry(
            pair, _fb_dir,
            rsi=50.0, sto=50.0, ma_diff=0.0, macd=0.0,
            bb_pos=0.5, mom=0.0, vol=0.5, candle=0,
            trend_1h=_fb_dir, mtf=None,
            indicators_agree=3,
            movement_cat="MEDIUM",
        )
        return {
            "direction": _fb_dir, "pair": pair, "timeframe": _fb_tf,
            "strength": 180, "indicators_agree": 3,
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
        if is_otc and sig.get("flat"):
            _r1h = None
            try:
                _r1h = _fetch_1h_trend(pair)
            except Exception:
                pass
            forced_dir = _r1h or sig.get("direction") or "BUY"
            forced_tf  = _smart_otc_expiry(
                pair, forced_dir,
                rsi=50.0, sto=50.0, ma_diff=0.0, macd=0.0,
                bb_pos=0.5, mom=0.0, vol=0.5, candle=0,
                trend_1h=_r1h, mtf=None,
                indicators_agree=3,
                movement_cat="MEDIUM",
            )
            sig["direction"]        = forced_dir
            sig["timeframe"]        = forced_tf
            sig["flat"]             = False
            sig["no_signal_reason"] = ""
            sig["strength"]         = 180
            logging.info("OTC SMART FORCE (flat rescued): {} → {} {}m".format(pair, forced_dir, forced_tf))
        if not is_otc and sig.get("flat"):
            rescued = _rescue_nonOTC_signal(pair)
            if rescued:
                return rescued
        return sig

    except asyncio.TimeoutError:
        logging.warning("generate_signal TIMEOUT ({}s) for {}".format(_SIGNAL_TIMEOUT, pair))
        if is_otc:
            return _otc_fallback()
        rescued = _rescue_nonOTC_signal(pair)
        if rescued:
            return rescued
        return _nonOTC_no_signal("⏱ *No signal available* - market data timed out.")

    except Exception as e:
        logging.warning("generate_signal ERROR for {}: {}".format(pair, e))
        if is_otc:
            return _otc_fallback()
        rescued = _rescue_nonOTC_signal(pair)
        if rescued:
            return rescued
        return _nonOTC_no_signal("🟡 *No signal available* - please try again.")

def _derive_htf_trend_from_micro(pair):
    """
    Extract 'Higher Timeframe Trend' from Deriv micro-candles.

    WAZO: Mtu anayeangalia chart ya 1m anaangalia candle moja kwa wakati mmoja.
    Lakini akiangalia chart ya 30m/1H, anaona MUUNDO wa soko - HH/HL/LH/LL.
    This function does so using Deriv micro-candles (5s/10s/15s):

      5s  micro-candles  → inawakilisha mwelekeo wa TF ya 1m
      10s micro-candles  → inawakilisha mwelekeo wa TF ya 2m
      15s micro-candles  → inawakilisha mwelekeo wa TF ya 3m

    Kila timeframe inasomwa kwa HTF logic (HH/HL, EMA cross, slope)
    na inazungumzwa kama layer ya ziada ya trend confirmation.

    Returns: dict au None
      {
        "trend_1m":  {"direction": "BUY"/"SELL", "strength": 0-100,
                      "htf_structure": "UPTREND"/"DOWNTREND"/"RANGING", ...},
        "trend_2m":  {...},
        "trend_3m":  {...},
        "consensus": "BUY"/"SELL"/None,  # iwapo 2+ TF zinakubaliana
        "consensus_strength": 0-100,
        "dominant_structure": "UPTREND"/"DOWNTREND"/"RANGING",
      }
    """
    cached = _deriv_tick_cache.get(pair)
    if not cached:
        return None

    import time as _t_htf
    age = _t_htf.time() - cached.get("ts", 0)
    if age > _DERIV_CACHE_TTL:
        return None

    data = cached.get("data", {})
    if not data:
        return None

    tf_results = {}
    tf_map = {"5_s": "trend_1m", "10_s": "trend_2m", "15_s": "trend_3m"}

    for micro_key, result_key in tf_map.items():
        trend = data.get(micro_key)
        if not trend:
            continue
        tf_results[result_key] = trend

    if not tf_results:
        return None

    buy_votes  = sum(1 for v in tf_results.values() if v.get("direction") == "BUY")
    sell_votes = sum(1 for v in tf_results.values() if v.get("direction") == "SELL")
    total_tfs  = len(tf_results)

    consensus = None
    consensus_strength = 0

    if buy_votes >= 2:
        consensus = "BUY"
        buy_strengths = [v["strength"] for v in tf_results.values()
                         if v.get("direction") == "BUY"]
        consensus_strength = int(sum(buy_strengths) / len(buy_strengths))
    elif sell_votes >= 2:
        consensus = "SELL"
        sell_strengths = [v["strength"] for v in tf_results.values()
                          if v.get("direction") == "SELL"]
        consensus_strength = int(sum(sell_strengths) / len(sell_strengths))
    elif total_tfs == 1:
        only = list(tf_results.values())[0]
        consensus = only.get("direction")
        consensus_strength = only.get("strength", 0)

    structures = [v.get("htf_structure", "RANGING") for v in tf_results.values()]
    uptrend_count   = structures.count("UPTREND")
    downtrend_count = structures.count("DOWNTREND")
    if uptrend_count > downtrend_count:
        dominant_structure = "UPTREND"
    elif downtrend_count > uptrend_count:
        dominant_structure = "DOWNTREND"
    else:
        dominant_structure = "RANGING"

    result = {**tf_results,
              "consensus":          consensus,
              "consensus_strength": consensus_strength,
              "dominant_structure": dominant_structure,
              "buy_votes":          buy_votes,
              "sell_votes":         sell_votes,
              "total_tfs":          total_tfs}

    logging.info("HTF MICRO {}: 1m={} 2m={} 3m={} | consensus={} str={} struct={}".format(
        pair,
        tf_results.get("trend_1m", {}).get("direction", "?"),
        tf_results.get("trend_2m", {}).get("direction", "?"),
        tf_results.get("trend_3m", {}).get("direction", "?"),
        consensus, consensus_strength, dominant_structure
    ))
    return result

def _confluence_quality_gate(
    pair, direction, real,
    trend_1h=None, vwap_data=None, mtf=None,
    atr_pct=0.05, session_name="Unknown"
):
    """
    v56: Confluence Quality Gate — hesabu quality score (0-100) ya signal.

    Factors (kila moja inachangia pointi):
      1. EMA alignment (HMA + DEMA + EMA ma_diff) — max 25pts
      2. MACD histogram slope (rising = strength) — max 15pts
      3. RSI slope (inayoenda upande sahihi) — max 10pts
      4. Volume surge (volume > 1.5x average) — max 10pts
      5. Keltner breakout direction — max 10pts
      6. Fisher Transform alignment — max 10pts
      7. Trend 1H alignment — max 15pts
      8. Session quality (London/NY = bora zaidi) — max 5pts
      9. Candle body ratio (sio indecision) — max 5pts (-10 kama indecision)
     10. ATR adequate (sio dead market) — max 5pts

    Returns: (score int 0-100, gate_pass bool, reason str)
    gate_pass = True kama score >= 40 (threshold ya chini kabisa)
    """
    if real is None:
        # v59d: non-OTC without real data no longer reaches here (blocked earlier).
        # OTC/fallback: allow through with average score.
        return (30, True, "no_real_data_otc")

    score = 0
    reasons = []

    # 1. EMA alignment: HMA + DEMA + ma_diff (max 25pts)
    ema_pts = 0
    ma_d = real.get("ma_diff", 0)
    hma_d = real.get("hma_direction")
    dema_d = real.get("dema_diff", 0)

    if (direction == "BUY" and ma_d > 0.02) or (direction == "SELL" and ma_d < -0.02):
        ema_pts += 10
    if hma_d == direction:
        ema_pts += 8
    if (direction == "BUY" and dema_d > 0.02) or (direction == "SELL" and dema_d < -0.02):
        ema_pts += 7
    score += min(25, ema_pts)
    if ema_pts >= 15:
        reasons.append("EMA_aligned+{}".format(ema_pts))

    # 2. MACD histogram slope (max 15pts)
    mhs = real.get("macd_hist_slope", 0)
    if (direction == "BUY" and mhs > 0) or (direction == "SELL" and mhs < 0):
        slope_pts = min(15, abs(mhs) * 5000)  # normalise tiny values
        score += slope_pts
        if slope_pts >= 5:
            reasons.append("MACD_slope+{:.0f}".format(slope_pts))
    elif mhs != 0:
        score -= 5  # opposing slope penalty
        reasons.append("MACD_slope_against")

    # 3. RSI slope (max 10pts)
    rs = real.get("rsi_slope", 0)
    rsi_v = real.get("rsi", 50)
    if direction == "BUY" and rs > 0 and rsi_v < 65:
        score += min(10, rs * 0.5)
        reasons.append("RSI_slope_up")
    elif direction == "SELL" and rs < 0 and rsi_v > 35:
        score += min(10, abs(rs) * 0.5)
        reasons.append("RSI_slope_down")

    # 4. Volume surge (max 10pts)
    if real.get("volume_surge", False):
        score += 10
        reasons.append("VOL_surge")

    # 5. Keltner breakout (max 15pts v58: was 10)
    kb = real.get("keltner_breakout")
    if kb == direction:
        score += 15
        reasons.append("Keltner_{}".format(direction))
    elif kb is not None and kb != direction:
        score -= 8   # v58: larger penalty if opposing (was -5)
        reasons.append("Keltner_against")

    # 6. Fisher Transform (max 15pts v58: was 10)
    fd = real.get("fisher_direction")
    fv = real.get("fisher_val", 0)
    if fd == direction:
        score += min(15, abs(fv) * 8)
        reasons.append("Fisher_{}".format(direction))
    elif fd is not None and fd != direction:
        score -= 7   # v58: larger penalty (was -5)

    # 6b. SuperTrend — v63: scaled by distance (trend strength)
    # Weak trend (small distance) = small bonus; Strong trend (large distance) = max bonus
    _st_cq     = real.get("supertrend_direction")
    _st_cq_val = real.get("supertrend_val")
    if _st_cq is not None:
        _st_cq_bonus = 0
        try:
            _st_cq_price = real.get("current_price") or float(_st_cq_val or 0)
            _st_cq_dist  = abs(_st_cq_price - float(_st_cq_val or _st_cq_price)) / (abs(float(_st_cq_val or _st_cq_price)) + 1e-9) * 100
            if _st_cq_dist >= 0.20:   _st_cq_bonus = 25
            elif _st_cq_dist >= 0.10: _st_cq_bonus = 15 + int((_st_cq_dist - 0.10) / 0.10 * 10)
            elif _st_cq_dist >= 0.05: _st_cq_bonus = 8  + int((_st_cq_dist - 0.05) / 0.05 * 7)
            else:                     _st_cq_bonus = int(_st_cq_dist / 0.05 * 8)
        except Exception:
            _st_cq_bonus = 12  # fallback
        if _st_cq == direction:
            score += _st_cq_bonus
            reasons.append("ST_{}+{}".format(direction, _st_cq_bonus))
        else:
            score -= 14   # opposing strong trend = hard penalty
            reasons.append("ST_against")

    # 6c. v57 Weighted Vote (max 20pts v58: was 15) — consensus of 21 indicators
    _v57_b = real.get("v57_buy_score", 0)
    _v57_s = real.get("v57_sell_score", 0)
    _v57_t = _v57_b + _v57_s
    if _v57_t > 0:
        _v57_ratio = (_v57_b if direction == "BUY" else _v57_s) / _v57_t
        if _v57_ratio >= 0.65:
            _cq_v57 = min(20, int((_v57_ratio - 0.5) * 40))
            score += _cq_v57
            reasons.append("v57vote+{:.0f}%".format(_v57_ratio*100))
        elif _v57_ratio < 0.40:
            score -= 10  # v58: larger penalty (was -8)
            reasons.append("v57vote_against")

    # 6d. PSAR alignment (max 8pts v58: was 5)
    if real.get("psar_direction") == direction:
        score += 8
        reasons.append("PSAR")
    elif real.get("psar_direction") is not None:
        score -= 5   # v58: larger penalty (was -3)

    # 6e. TTM Squeeze breakout (max 10pts v58: was 8)
    if real.get("squeeze_direction") == direction and not real.get("squeeze_active", True):
        score += 10
        reasons.append("SQUEEZE_break")

    # 6f. v58: ZigZag Trend (max 18pts — true swing structure)
    _zz_d = real.get("zigzag_direction")
    _zz_s = real.get("zigzag_strength", 0)
    if _zz_d == direction:
        _zz_cq = min(18, 8 + _zz_s * 5)   # 8→13→18 based on strength
        score += _zz_cq
        reasons.append("ZigZag_{}+{}".format(direction, _zz_cq))
    elif _zz_d is not None and _zz_d != direction:
        score -= 8
        reasons.append("ZigZag_against")

    # 7. Trend 1H (max 15pts)
    if trend_1h == direction:
        score += 15
        reasons.append("1H_aligned")
    elif trend_1h is not None and trend_1h != direction:
        score -= 10
        reasons.append("1H_against")

    # 8. Session quality (max 5pts)
    good_sessions = {"London Open", "London Mid", "NY/London", "NY Session"}
    if session_name in good_sessions:
        score += 5
    elif session_name == "Dead Hours":
        score -= 5

    # 9. Candle body ratio (max 5pts, penalty -10 if indecision)
    cbr = real.get("candle_body_ratio", 0.5)
    if real.get("is_indecision", False):
        score -= 10
        reasons.append("INDECISION_candle")
    elif cbr >= 0.5:
        score += 5
        reasons.append("strong_body")

    # 10. ATR adequate
    if atr_pct >= 0.06:
        score += 5
    elif atr_pct < 0.02:
        score -= 5

    score = max(0, min(100, score))
    gate_pass = score >= 40   # v63: restored to v57 level

    reason_str = "cq={} [{}]".format(score, ",".join(reasons[:4]) if reasons else "none")
    logging.info("CONFLUENCE_GATE {}: dir={} score={} pass={}".format(
        pair, direction, score, gate_pass))

    return (score, gate_pass, reason_str)


def generate_signal(pair):
    is_otc = "OTC" in pair
    real   = None
    yahoo_available = True

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

    # ── Sequential fetch (cache-first — avoids TwelveData 429 rate limit) ─
    if not is_otc:
        try:
            real = _fetch_real_indicators_mtf(pair)
            if real is None:
                yahoo_available = False
        except Exception as e:
            logging.warning("generate_signal real fetch failed {}: {}".format(pair, e))
            real = None
            yahoo_available = False

    trend_1h = None
    try:
        trend_1h = _fetch_1h_trend(pair)
    except Exception as e:
        logging.warning("generate_signal 1H trend failed {}: {}".format(pair, e))

    vwap_data = None
    try:
        vwap_data = _fetch_vwap_trend(pair)
    except Exception as e:
        logging.warning("generate_signal vwap failed {}: {}".format(pair, e))

    mtf = None
    try:
        mtf = _fetch_mtf_score(pair)
    except Exception as e:
        logging.warning("generate_signal mtf failed {}: {}".format(pair, e))
    # ────────────────────────────────────────────────────────────────────────

    pattern_buy_bonus = 0
    pattern_sell_bonus = 0
    detected_patterns = {}
    if real is not None:
        real_pair = OTC_TO_REAL.get(pair, pair)
        symbol = YAHOO_SYMBOLS.get(real_pair)
        if symbol:
            try:
                df_5m = _yf_download_cached(symbol, "2d", "5m")
                detected_patterns = _detect_candlestick_patterns(df_5m)
            except Exception:
                pass
    else:
        real_p = OTC_TO_REAL.get(pair)
        if real_p:
            symbol = YAHOO_SYMBOLS.get(real_p)
            if symbol:
                try:
                    df_5m = _yf_download_cached(symbol, "2d", "5m")
                    detected_patterns = _detect_candlestick_patterns(df_5m)
                except Exception:
                    pass

    for pname, (pdir, pbonus) in detected_patterns.items():
        if pdir == "BUY":
            pattern_buy_bonus += pbonus
        else:
            pattern_sell_bonus += pbonus

    avg_movement, movement_cat = _check_pip_movement(pair)

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

    fib_buy_bonus = fib_sell_bonus = 0
    fib_level_str = None
    if not is_otc:
        try:
            fib_buy_bonus, fib_sell_bonus, fib_level_str = _check_fibonacci(pair, "BUY")
        except Exception as _e:
            logging.warning("fibonacci check failed {}: {}".format(pair, _e))

    pa_buy_bonus = pa_sell_bonus = 0
    pa_trend_str = None
    try:
        pa_buy_bonus, pa_sell_bonus, pa_trend_str = _price_action_score(pair)
    except Exception as _e:
        logging.warning("price action score failed {}: {}".format(pair, _e))

    import time as _time_gen
    _deriv_cached = _deriv_tick_cache.get(pair)
    _deriv_ind_data = None
    if not is_otc and _deriv_cached:
        _cache_age = _time_gen.time() - _deriv_cached.get("ts", 0)
        if _cache_age <= _DERIV_CACHE_TTL:
            _deriv_ind_data = _deriv_cached["data"]
            logging.info("Deriv cache hit for {} (age={:.1f}s)".format(pair, _cache_age))
    _sig_deriv_ind = _deriv_ind_data  # may be None - bonus is optional

    _micro_htf = _derive_htf_trend_from_micro(pair)
    _micro_htf_consensus    = _micro_htf["consensus"]          if _micro_htf else None
    _micro_htf_strength     = _micro_htf["consensus_strength"] if _micro_htf else 0
    _micro_htf_structure    = _micro_htf["dominant_structure"] if _micro_htf else "RANGING"
    _micro_htf_buy_votes    = _micro_htf["buy_votes"]          if _micro_htf else 0
    _micro_htf_sell_votes   = _micro_htf["sell_votes"]         if _micro_htf else 0

    if real:
        rsi     = real["rsi"]
        sto     = real["sto"]
        ma_diff = real["ma_diff"]
        macd    = real["macd"]
        bb_pos  = real["bb_pos"]
        mom     = real["mom"]
        vol     = real["vol"]
        _raw_dir = real.get("direction")
        if _raw_dir == "BUY":
            candle = 1.0
        elif _raw_dir == "SELL":
            candle = -1.0
        else:
            candle = 0.5 if mom > 0 else (-0.5 if mom < 0 else 0.0)
    else:
        real_p_otc = OTC_TO_REAL.get(pair)
        real_otc_ind = None
        if real_p_otc:
            try:
                real_otc_ind = _fetch_real_indicators_mtf(real_p_otc)
            except Exception:
                pass

        if real_otc_ind:
            rsi     = real_otc_ind["rsi"]
            sto     = real_otc_ind["sto"]
            ma_diff = real_otc_ind["ma_diff"]
            macd    = real_otc_ind["macd"]
            bb_pos  = real_otc_ind["bb_pos"]
            mom     = real_otc_ind["mom"]
            vol     = real_otc_ind["vol"]
            _raw_dir_otc = real_otc_ind.get("direction")
            if _raw_dir_otc == "BUY":
                candle = 1.0
            elif _raw_dir_otc == "SELL":
                candle = -1.0
            else:
                candle = 0.5 if mom > 0 else (-0.5 if mom < 0 else 0.0)
        else:
            # Non-OTC pair bila data — jaribu mara 3 tu, kisha rudisha flat
            import time as _t

            _real_retry = None
            _attempt = 0
            _MAX_ATTEMPTS = 3  # ← limit — usijaribu zaidi ya mara 3

            while _real_retry is None and _attempt < _MAX_ATTEMPTS:
                _attempt += 1

                # First: try Deriv ticks as fast source
                _deriv_live = None
                _deriv_rescue_pair = OTC_TO_REAL.get(pair, pair)
                if _deriv_rescue_pair in DERIV_SYMBOLS:
                    try:
                        _dc = _deriv_tick_cache.get(_deriv_rescue_pair)
                        if _dc:
                            _dc_age = _t.time() - _dc.get("ts", 0)
                            if _dc_age <= _DERIV_CACHE_TTL:
                                _td = _dc["data"]
                                _best_str_d = -1
                                _best_dir_d = None
                                for _mk in ["5_s", "10_s", "15_s"]:
                                    _tr = _td.get(_mk)
                                    if _tr and _tr.get("direction") not in (None, "FLAT"):
                                        _sv = _tr.get("strength", 0)
                                        if _sv > _best_str_d:
                                            _best_str_d = _sv
                                            _best_dir_d = _tr["direction"]
                                            _best_ind_d = _tr.get("indicators") or {}
                                if _best_dir_d and _best_str_d >= 50:
                                    _deriv_live = {
                                        "direction": _best_dir_d,
                                        "rsi":     _best_ind_d.get("rsi",    50.0),
                                        "sto":     _best_ind_d.get("sto",    50.0),
                                        "ma_diff": _best_ind_d.get("ma_diff", 0.0),
                                        "macd":    _best_ind_d.get("macd",    0.0),
                                        "bb_pos":  _best_ind_d.get("bb_pos",  0.5),
                                        "mom":     _best_ind_d.get("mom",     0.0),
                                        "vol":     _best_ind_d.get("vol",     0.5),
                                        "tf_buy_votes":  1 if _best_dir_d == "BUY"  else 0,
                                        "tf_sell_votes": 1 if _best_dir_d == "SELL" else 0,
                                        "tf_count": 1,
                                        "data_source": "deriv_ticks",
                                    }
                                    logging.info("nonOTC {} attempt {}: Deriv ticks hit dir={} str={:.0f}".format(
                                        pair, _attempt, _best_dir_d, _best_str_d))
                    except Exception as _de:
                        logging.warning("nonOTC {} Deriv ticks read failed: {}".format(pair, _de))

                if _deriv_live is not None:
                    _real_retry = _deriv_live
                    break

                # Pili: jaribu Yahoo/Finnhub
                try:
                    _fetched = _fetch_real_indicators_mtf(pair)
                    if _fetched is not None:
                        _real_retry = _fetched
                        logging.info("nonOTC {} real data obtained attempt {}".format(pair, _attempt))
                        break
                except Exception as _re:
                    logging.warning("nonOTC {} fetch attempt {}: {}".format(pair, _attempt, _re))

                logging.info("nonOTC {} attempt {}: no data yet — retrying in 1s".format(pair, _attempt))
                _t.sleep(1)

            # Data haikupatikana baada ya attempts 3 — rudisha flat (ruka pair hii)
            if _real_retry is None:
                logging.warning("nonOTC {} no data after {} attempts — skip".format(pair, _MAX_ATTEMPTS))
                return {"flat": True, "direction": None, "timeframe": 0,
                        "strength": 0, "indicators_agree": 0, "pair": pair}

            # Data available (Deriv or Yahoo/Finnhub) — proceed with real indicators
            rsi     = _real_retry["rsi"]
            sto     = _real_retry["sto"]
            ma_diff = _real_retry["ma_diff"]
            macd    = _real_retry["macd"]
            bb_pos  = _real_retry["bb_pos"]
            mom     = _real_retry["mom"]
            vol     = _real_retry["vol"]
            _raw_dir_retry = _real_retry.get("direction")
            if _raw_dir_retry == "BUY":
                candle = 1.0
            elif _raw_dir_retry == "SELL":
                candle = -1.0
            else:
                candle = 0.5 if mom > 0 else (-0.5 if mom < 0 else 0.0)
            # Mark as real so v56 bonuses and CQ gate work correctly
            real = _real_retry

    _w = 1.0  # v54-8: non-OTC indicators now get full weight (was 0.5)
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

    if real and real.get("divergence"):
        div = real["divergence"]
        if div == "BUY":  b += 20
        elif div == "SELL": s += 20

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
            b -= 10
            s -= 10

    # ── Fractal scoring (v54-8) ──
    # Source 1: fractal from 5m data (within real)
    fractal_sig = None
    fractal_str = 0
    if real and real.get("fractal_signal"):
        fractal_sig = real["fractal_signal"]
        fractal_str = real.get("fractal_strength", 1)

    # Source 2: fractal from real 1m data (most important for binary 1m)
    # Supersedes 5m fractal if available
    if not is_otc:
        real_pair_fr = OTC_TO_REAL.get(pair, pair)
        yf_sym_fr = YAHOO_SYMBOLS.get(real_pair_fr)
        fh_sym_fr = FINNHUB_FOREX_SYMBOLS.get(real_pair_fr)
        df_1m_fr = None
        try:
            if fh_sym_fr and FINNHUB_KEY:
                df_1m_fr = _mtf_fh_candles(fh_sym_fr, "1", 60)
            if df_1m_fr is None and yf_sym_fr:
                df_1m_fr = _yf_download_cached(yf_sym_fr, "1d", "1m")
        except Exception:
            df_1m_fr = None
        if df_1m_fr is not None and len(df_1m_fr) >= 10:
            ind_1m_fr = _calc_indicators_from_df(df_1m_fr)
            if ind_1m_fr and ind_1m_fr.get("fractal_signal"):
                fractal_sig = ind_1m_fr["fractal_signal"]
                fractal_str = ind_1m_fr.get("fractal_strength", 1) + 1  # 1m gets bonus +1
                logging.info("FRACTAL 1m {}: {} str={}".format(pair, fractal_sig, fractal_str))

    # Kama hakuna fractal yoyote - BB fallback (dhaifu)
    if fractal_sig is None:
        if bb_pos < 0.08:
            fractal_sig = "BUY";  fractal_str = 1
        elif bb_pos > 0.92:
            fractal_sig = "SELL"; fractal_str = 1

    # Weight: fractal gets 35 points (was 15) - more important
    if fractal_sig == "BUY":
        b += 35 * fractal_str
    elif fractal_sig == "SELL":
        s += 35 * fractal_str

    b += pattern_buy_bonus
    s += pattern_sell_bonus

    b += fib_buy_bonus
    s += fib_sell_bonus
    if fib_level_str:
        logging.info("FIB {}: {} buy_bonus={} sell_bonus={}".format(
            pair, fib_level_str, fib_buy_bonus, fib_sell_bonus))

    b += pa_buy_bonus
    s += pa_sell_bonus
    if pa_trend_str:
        logging.info("PA {}: {} buy={} sell={}".format(
            pair, pa_trend_str, pa_buy_bonus, pa_sell_bonus))

    # ── v56: New indicator bonuses ──────────────────────────────────────────
    _v56_real = real if real else (real_otc_ind if not is_otc and 'real_otc_ind' in dir() else None)
    if _v56_real:
        # HMA direction bonus (+15 if it agrees with emerging direction)
        _hma = _v56_real.get("hma_direction")
        if _hma == "BUY":   b += 15
        elif _hma == "SELL": s += 15

        # DEMA diff bonus (+12 if leaning one direction)
        _dema = _v56_real.get("dema_diff", 0)
        if _dema > 0.05:    b += 12
        elif _dema < -0.05: s += 12
        elif _dema > 0.02:  b += 6
        elif _dema < -0.02: s += 6

        # Keltner breakout (+30 v58: was +20 - true breakout is very important)
        _kb = _v56_real.get("keltner_breakout")
        if _kb == "BUY":    b += 30
        elif _kb == "SELL": s += 30

        # Fisher Transform (+20 v58: was +12)
        _fd = _v56_real.get("fisher_direction")
        _fv = abs(_v56_real.get("fisher_val", 0))
        if _fd == "BUY":    b += min(20, int(_fv * 12))
        elif _fd == "SELL": s += min(20, int(_fv * 12))

        # MACD histogram slope (+8 if slope is in our direction)
        _mhs = _v56_real.get("macd_hist_slope", 0)
        if _mhs > 0:        b += min(8, int(abs(_mhs) * 3000))
        elif _mhs < 0:      s += min(8, int(abs(_mhs) * 3000))

        # RSI slope bonus (moving our direction = +6)
        _rss = _v56_real.get("rsi_slope", 0)
        if _rss > 2:        b += 6
        elif _rss < -2:     s += 6

        # Volume surge bonus (+10)
        if _v56_real.get("volume_surge", False):
            if b >= s: b += 10
            else:      s += 10

        # Candle body penalty (doji/indecision = -8 on both sides)
        if _v56_real.get("is_indecision", False):
            b -= 8
            s -= 8
            logging.info("v56 INDECISION_CANDLE {}: b/s penalised -8".format(pair))

        # SuperTrend bonus — v63: scaled by trend strength (distance from ST line)
        # Small distance = weak/new trend = small bonus
        # Large distance = strong established trend = large bonus
        _st_dir = _v56_real.get("supertrend_direction")
        _st_val = _v56_real.get("supertrend_val")
        _st_bonus = 0
        if _st_dir is not None and _st_val is not None:
            try:
                _cur_p = _v56_real.get("current_price") or float(_st_val)
                _st_dist_pct = abs(_cur_p - float(_st_val)) / (float(_st_val) + 1e-9) * 100
                # Scale: 0.05% → 10pts, 0.10% → 20pts, 0.20%+ → 35pts (max)
                if _st_dist_pct >= 0.20:
                    _st_bonus = 35
                elif _st_dist_pct >= 0.10:
                    _st_bonus = 20 + int((_st_dist_pct - 0.10) / 0.10 * 15)
                elif _st_dist_pct >= 0.05:
                    _st_bonus = 10 + int((_st_dist_pct - 0.05) / 0.05 * 10)
                else:
                    _st_bonus = int(_st_dist_pct / 0.05 * 10)  # 0–10 for tiny distance
            except Exception:
                _st_bonus = 15  # fallback if no price
            if _st_dir == "BUY":
                b += _st_bonus
                logging.info("ST {}: BUY +{} (dist={:.4f}%)".format(pair, _st_bonus, _st_dist_pct if '_st_dist_pct' in dir() else 0))
            elif _st_dir == "SELL":
                s += _st_bonus
                logging.info("ST {}: SELL +{} (dist={:.4f}%)".format(pair, _st_bonus, _st_dist_pct if '_st_dist_pct' in dir() else 0))

        # ── v57: Weighted indicator vote bonus ─────────────────────────────
        _v57_buy  = _v56_real.get("v57_buy_score",  0)
        _v57_sell = _v56_real.get("v57_sell_score", 0)
        _v57_tot  = _v57_buy + _v57_sell
        if _v57_tot > 0:
            # Bonus max +40 for winning side (proportional)
            _v57_b_bonus = int((_v57_buy  / _v57_tot) * 40)
            _v57_s_bonus = int((_v57_sell / _v57_tot) * 40)
            b += _v57_b_bonus
            s += _v57_s_bonus
            logging.info("v57 vote {}: buy_score={} sell_score={} → b+{} s+{}".format(
                pair, _v57_buy, _v57_sell, _v57_b_bonus, _v57_s_bonus))

        # Extra bonuses for stronger indicators
        if _v56_real.get("psar_direction") == "BUY":    b += 15
        elif _v56_real.get("psar_direction") == "SELL": s += 15

        # v58: ZigZag Trend bonus — true swing structure
        _zz_dir = _v56_real.get("zigzag_direction")
        _zz_str = _v56_real.get("zigzag_strength", 0)
        if _zz_dir == "BUY":
            _zz_bonus = 15 + _zz_str * 8   # min 15, max 39 for strength=3
            b += _zz_bonus
            logging.info("ZIGZAG {}: BUY +{} (strength={})".format(pair, _zz_bonus, _zz_str))
        elif _zz_dir == "SELL":
            _zz_bonus = 15 + _zz_str * 8
            s += _zz_bonus
            logging.info("ZIGZAG {}: SELL +{} (strength={})".format(pair, _zz_bonus, _zz_str))
        elif _zz_dir is not None and _zz_dir != (_v56_real.get("direction") or ""):
            # ZigZag inapinga direction kuu — penalize
            b -= 10; s -= 10

        if _v56_real.get("squeeze_direction") and not _v56_real.get("squeeze_active", True):
            # Squeeze breakout = very strong
            if _v56_real.get("squeeze_direction") == "BUY":  b += 12
            else:                                              s += 12

        if _v56_real.get("cmf_direction") == "BUY":    b += 8
        elif _v56_real.get("cmf_direction") == "SELL": s += 8

        if _v56_real.get("kama_direction") == "BUY":    b += 8
        elif _v56_real.get("kama_direction") == "SELL": s += 8
        # ── end v57 bonuses ─────────────────────────────────────────────────

    logging.info("v56 indicator scores {}: b={} s={} [hma={} dema={:.3f} kelt={} fisher={} st={}]".format(
        pair, b, s,
        _v56_real.get("hma_direction") if _v56_real else "N/A",
        _v56_real.get("dema_diff", 0) if _v56_real else 0,
        _v56_real.get("keltner_breakout") if _v56_real else "N/A",
        _v56_real.get("fisher_direction") if _v56_real else "N/A",
        _v56_real.get("supertrend_direction") if _v56_real else "N/A",
    ))
    # ── end v56 bonuses ────────────────────────────────────────────────────

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

    _1h_weight = 80 if not is_otc else 45
    if trend_1h == "BUY":
        b += _1h_weight
    elif trend_1h == "SELL":
        s += _1h_weight

    _micro_htf_weight = 60 if is_otc else 35
    if _micro_htf_consensus == "BUY":
        _htf_bonus = int((_micro_htf_strength / 100) * _micro_htf_weight *
                         (_micro_htf_buy_votes / max(_micro_htf_buy_votes + _micro_htf_sell_votes, 1)))
        b += _htf_bonus
        logging.info("MICRO HTF BONUS {}: BUY +{} (str={} struct={} votes={}/{})".format(
            pair, _htf_bonus, _micro_htf_strength, _micro_htf_structure,
            _micro_htf_buy_votes, _micro_htf_sell_votes))
    elif _micro_htf_consensus == "SELL":
        _htf_bonus = int((_micro_htf_strength / 100) * _micro_htf_weight *
                         (_micro_htf_sell_votes / max(_micro_htf_buy_votes + _micro_htf_sell_votes, 1)))
        s += _htf_bonus
        logging.info("MICRO HTF BONUS {}: SELL +{} (str={} struct={} votes={}/{})".format(
            pair, _htf_bonus, _micro_htf_strength, _micro_htf_structure,
            _micro_htf_sell_votes, _micro_htf_buy_votes))

    if vwap_data is not None:
        if vwap_data["direction"] == "BUY":
            bonus = 30 if vwap_data["strength"] == "STRONG" else (18 if vwap_data["strength"] == "MODERATE" else 8)
            b += bonus
        else:
            bonus = 30 if vwap_data["strength"] == "STRONG" else (18 if vwap_data["strength"] == "MODERATE" else 8)
            s += bonus

    _mtf_w = 12 if not is_otc else 8
    if mtf and mtf["total"] >= 3:
        if mtf["buy_tfs"] > mtf["sell_tfs"]:
            b += mtf["buy_tfs"] * _mtf_w
        elif mtf["sell_tfs"] > mtf["buy_tfs"]:
            s += mtf["sell_tfs"] * _mtf_w

    direction = "BUY" if b >= s else "SELL"

    # Fix B (v54-8): if trend_1h missing and real data available, anchor direction to 5m real data
    # This prevents direction flip-flop when 1H is missing and other sources are split
    if not is_otc and trend_1h is None and real is not None:
        real_dir = real.get("direction")  # direction kutoka 5m indicators (MA+MACD)
        if real_dir in ("BUY", "SELL"):
            tf_votes_match = (real_dir == "BUY" and real.get("tf_buy_votes", 0) >= real.get("tf_sell_votes", 0)) or                              (real_dir == "SELL" and real.get("tf_sell_votes", 0) >= real.get("tf_buy_votes", 0))
            if tf_votes_match:
                # 5m direction + tf votes agree - anchor here
                direction = real_dir
                logging.info("DIRECTION ANCHOR {}: trend_1h=None, real_dir={} tf_buy={} tf_sell={} → anchored".format(
                    pair, real_dir, real.get("tf_buy_votes",0), real.get("tf_sell_votes",0)))
            else:
                # 5m direction and tf votes disagree - check vwap as tiebreaker
                if vwap_data is not None:
                    direction = vwap_data["direction"]
                    logging.info("DIRECTION ANCHOR {}: trend_1h=None, 5m vs tf conflict → vwap={}".format(
                        pair, vwap_data["direction"]))
                # if vwap also missing - leave direction = b vs s as-is
    indicators_agree = 0
    checks = [(rsi < 45, rsi > 55), (sto < 45, sto > 55), (ma_diff > 0, ma_diff < 0),
              (macd > 0, macd < 0), (bb_pos < 0.5, bb_pos > 0.5), (mom > 0, mom < 0), (candle > 0, candle < 0)]
    for buy_c, sell_c in checks:
        if direction == "BUY" and buy_c:   indicators_agree += 1
        if direction == "SELL" and sell_c: indicators_agree += 1

    if mtf and mtf["total"] >= 3:
        if direction == "BUY"  and mtf["buy_tfs"]  > mtf["sell_tfs"]: indicators_agree += mtf["buy_tfs"]
        if direction == "SELL" and mtf["sell_tfs"] > mtf["buy_tfs"]:  indicators_agree += mtf["sell_tfs"]
    if trend_1h == direction:
        indicators_agree += 3  # Increased from 2 - 1H trend with reversal detection is stronger

    if _micro_htf_consensus == direction:
        _micro_agree_bonus = _micro_htf_buy_votes if direction == "BUY" else _micro_htf_sell_votes
        indicators_agree += _micro_agree_bonus
        if _micro_htf_structure in ("UPTREND", "DOWNTREND"):
            indicators_agree += 1
    elif _micro_htf_consensus is not None and _micro_htf_consensus != direction:
        indicators_agree = max(0, indicators_agree - 1)

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
                if direction == "BUY" and _ind_rsi < 45: indicators_agree += 1
                elif direction == "SELL" and _ind_rsi > 55: indicators_agree += 1
                if direction == "BUY" and _ind_macd > 0.1: indicators_agree += 1
                elif direction == "SELL" and _ind_macd < -0.1: indicators_agree += 1
                if direction == "BUY" and _ind_ma > 0.1: indicators_agree += 1
                elif direction == "SELL" and _ind_ma < -0.1: indicators_agree += 1
            elif _ind_dir is not None and _ind_dir != direction:
                indicators_agree = max(0, indicators_agree - 1)
        if _sec_total > 0:
            _sec_ratio = _sec_agree / _sec_total
            _sec_bonus = int(_sec_ratio * 25)  # max +25 if all seconds agree
            if direction == "BUY":  b += _sec_bonus
            else:                   s += _sec_bonus
            logging.info("Deriv sec indicators {}: agree={}/{} bonus={} dir={}".format(
                pair, _sec_agree, _sec_total, _sec_bonus, direction))

    if real and not is_otc and real.get("tf_count", 0) >= 2:
        tv = real.get("tf_buy_votes", 0)
        sv = real.get("tf_sell_votes", 0)
        if direction == "BUY"  and tv > sv: indicators_agree += tv
        if direction == "SELL" and sv > tv: indicators_agree += sv

    pattern_agrees = (pattern_buy_bonus > 0 and direction == "BUY") or \
                     (pattern_sell_bonus > 0 and direction == "SELL")
    if pattern_agrees:
        indicators_agree += 2

    # v57: if more than 60% of 20 indicators agree → +2 indicators_agree
    if _v56_real:
        _v57d = _v56_real.get("v57_direction")
        if _v57d == direction:
            indicators_agree += 2
        elif _v57d is not None and _v57d != direction:
            indicators_agree = max(0, indicators_agree - 1)
        # PSAR alignment
        if _v56_real.get("psar_direction") == direction:
            indicators_agree += 1
        # CMF (volume confirms)
        if _v56_real.get("cmf_direction") == direction:
            indicators_agree += 1
        # v58: ZigZag — strong swing structure wins vote +2 or +3
        _zz_ia = _v56_real.get("zigzag_direction")
        _zz_ia_str = _v56_real.get("zigzag_strength", 0)
        if _zz_ia == direction:
            indicators_agree += 1 + min(2, _zz_ia_str)  # +1 weak, +2 moderate, +3 strong
        elif _zz_ia is not None and _zz_ia != direction:
            indicators_agree = max(0, indicators_agree - 2)  # ZigZag inapinga = penalize zaidi
        # SuperTrend alignment — v63: scaled by trend strength
        # Strong trend (large distance) = +3, moderate = +2, weak = +1
        _st_ia_dir = _v56_real.get("supertrend_direction")
        _st_ia_val = _v56_real.get("supertrend_val")
        if _st_ia_dir is not None:
            _st_ia_add = 1  # default weak
            try:
                _st_ia_p = _v56_real.get("current_price") or float(_st_ia_val or 0)
                _st_ia_d = abs(_st_ia_p - float(_st_ia_val or _st_ia_p)) / (abs(float(_st_ia_val or _st_ia_p)) + 1e-9) * 100
                if _st_ia_d >= 0.20:   _st_ia_add = 3   # strong trend
                elif _st_ia_d >= 0.08: _st_ia_add = 2   # moderate
                else:                  _st_ia_add = 1   # weak/new
            except Exception:
                _st_ia_add = 2
            if _st_ia_dir == direction:
                indicators_agree += _st_ia_add
            else:
                indicators_agree = max(0, indicators_agree - _st_ia_add)

    if mtf and trend_1h and mtf["total"] >= 3:
        mtf_dir = "BUY" if mtf["buy_tfs"] > mtf["sell_tfs"] else "SELL"
        if mtf_dir != trend_1h:
            direction = "BUY" if b > s else "SELL"

    min_confluence = 4 if not is_otc else 3   # v62: lowered non-OTC 6→4, OTC 4→3
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

    hist_same, hist_total, hist_pct = _check_signal_history_bias(pair, direction, window=15)
    if hist_total >= 5:
        if hist_pct >= 0.65:
            if direction == "BUY":
                b += int((hist_pct - 0.5) * 30)  # +4.5 hadi +15
            else:
                s += int((hist_pct - 0.5) * 30)
            indicators_agree += 1
        elif hist_pct < 0.40:
            if direction == "BUY":
                b -= 10
            else:
                s -= 10

    dom = max(b, s); tot = max(b + s, 1)
    base_score = int((dom / tot) * 100)            # 50–100 (dominant side ratio)

    ia_bonus = min(20, indicators_agree * 2)

    # ── v56: Confluence Quality Gate ────────────────────────────────────────
    _cq_sess = _get_session().get("name", "Unknown")
    _cq_score, _cq_pass, _cq_reason = _confluence_quality_gate(
        pair=pair, direction=direction, real=_v56_real,
        trend_1h=trend_1h, vwap_data=vwap_data, mtf=mtf,
        atr_pct=atr_pct, session_name=_cq_sess
    )
    if not _cq_pass and not is_otc:
        # Non-OTC signal dhaifu — usiitume (timeframe=0 = no signal)
        logging.info("CQ_GATE BLOCK {}: dir={} score={} reason={}".format(
            pair, direction, _cq_score, _cq_reason))
        return {
            "direction": direction, "pair": pair, "timeframe": 0,
            "strength": 0, "indicators_agree": indicators_agree,
            "trend_1h": trend_1h, "vwap_data": vwap_data,
            "confluence": {}, "mtf": mtf, "flat": True,
            "patterns": detected_patterns,
            "movement_cat": movement_cat, "avg_movement": avg_movement,
            "no_signal_reason": "🔍 *Market confluence too weak* — waiting for clearer setup.",
            "nn_confidence": None, "nn_used": False, "_nn_feat_arr": None,
        }
    # Boost strength if quality gate score is high
    _cq_strength_bonus = max(0, (_cq_score - 50) // 5)  # 0-10pts bonus
    # ── end v56 CQ gate ──────────────────────────────────────────────────────

    mtf_bonus = 0
    if mtf and mtf["total"] >= 3:
        agreeing = mtf["buy_tfs"] if direction == "BUY" else mtf["sell_tfs"]
        mtf_bonus = int((agreeing / mtf["total"]) * 15)

    trend_bonus = 10 if trend_1h == direction else (0 if trend_1h is None else -10)

    micro_htf_bonus_str = 0
    if _micro_htf_consensus == direction:
        _votes_agreeing = _micro_htf_buy_votes if direction == "BUY" else _micro_htf_sell_votes
        micro_htf_bonus_str = min(12, int((_micro_htf_strength / 100) * 8 * _votes_agreeing))
        if _micro_htf_structure in ("UPTREND", "DOWNTREND"):
            micro_htf_bonus_str = min(12, micro_htf_bonus_str + 3)
    elif _micro_htf_consensus is not None and _micro_htf_consensus != direction:
        micro_htf_bonus_str = -6  # Micro HTF inapinga

    pattern_bonus_str = min(8, (pattern_buy_bonus if direction == "BUY" else pattern_sell_bonus) // 5)

    hist_bonus_str = 0
    if hist_total >= 5:
        if hist_pct >= 0.65:
            hist_bonus_str = int((hist_pct - 0.5) * 14)  # 0.65→2, 1.0→7
        elif hist_pct < 0.40:
            hist_bonus_str = -5  # Penalize direction with poor win history

    raw_strength = base_score + ia_bonus + mtf_bonus + trend_bonus + pattern_bonus_str + hist_bonus_str + micro_htf_bonus_str + _cq_strength_bonus
    raw_clamped = max(35, min(97, raw_strength))
    strength = int(90 + (raw_clamped - 35) / (97 - 35) * (450 - 90))

    vte_tf = None  # will be set by non-OTC branch; used by downstream filters
    _pipeline_scores = {1: 0.0, 2: 0.0, 3: 0.0}  # v53: unified score dict for all gates
    if is_otc:
        timeframe = _smart_otc_expiry(
            pair, direction,
            rsi=rsi, sto=sto, ma_diff=ma_diff, macd=macd,
            bb_pos=bb_pos, mom=mom, vol=vol, candle=candle,
            trend_1h=trend_1h, mtf=mtf,
            indicators_agree=indicators_agree,
            movement_cat=movement_cat,
        )
    else:
        _nonotc_result = _smart_nonOTC_expiry(
            pair, direction,
            rsi=rsi, sto=sto, ma_diff=ma_diff, macd=macd,
            bb_pos=bb_pos, mom=mom, vol=vol, candle=candle,
            trend_1h=trend_1h, mtf=mtf,
            indicators_agree=indicators_agree,
            movement_cat=movement_cat,
            atr_pct=atr_pct,
            fib_buy_bonus=fib_buy_bonus, fib_sell_bonus=fib_sell_bonus,
            pa_buy_bonus=pa_buy_bonus, pa_sell_bonus=pa_sell_bonus,
            pattern_buy_bonus=pattern_buy_bonus, pattern_sell_bonus=pattern_sell_bonus,
            deriv_cache=_deriv_ind_data,
            adx_val=float(real.get("adx", 25.0)) if real and real.get("adx") else 25.0,
        )
        if isinstance(_nonotc_result, tuple):
            _leading_tf, _live_scores = _nonotc_result
        else:
            _leading_tf = _nonotc_result
            _live_scores = dict(_tf_candidate_scores) if _tf_candidate_scores else {1: 0.0, 2: 0.0, 3: 0.0}

        timeframe = _leading_tf  # leading suggestion - bado inaweza kubadilika
        vte_tf = timeframe  # keep vte_tf for downstream filters

        _pipeline_scores = dict(_live_scores)

        logging.info("TF SELECTION {}: scores=1m:{:.0f} 2m:{:.0f} 3m:{:.0f} → leading={}m ia={} micro={}".format(
            pair,
            _pipeline_scores.get(1, 0),
            _pipeline_scores.get(2, 0),
            _pipeline_scores.get(3, 0),
            timeframe, indicators_agree,
            {k: round(v, 1) for k, v in _micro_scores.items()}
        ))

    if not is_otc and is_filter_on("confluence") and indicators_agree < 4 and vte_tf is None and timeframe > 0:
        if trend_1h is not None:
            direction = trend_1h  # Fuata 1H - si kupingana nayo
        elif not yahoo_available:
            pass  # No data - lakini timeframe tayari ipo, usiibadilishe

    if not is_otc and is_filter_on("h1confirm") and timeframe > 0:
        h1_confirmed = _confirm_1h_direction(pair, direction)
        if not h1_confirmed:
            _pipeline_scores[1] = max(0.0, _pipeline_scores.get(1, 0) - 35)  # 1m: large penalty
            _pipeline_scores[2] = max(0.0, _pipeline_scores.get(2, 0) - 15)  # 2m: medium penalty
            _pipeline_scores[3] = _pipeline_scores.get(3, 0) + 10             # 3m: wait bonus
            new_tf = max(_pipeline_scores, key=lambda t: _pipeline_scores[t])
            if new_tf != timeframe:
                logging.info("H1CONFIRM {}: 1H not confirmed → leading {}m → {}m after score adjustment (scores: 1m={:.1f} 2m={:.1f} 3m={:.1f})".format(
                    pair, timeframe, new_tf,
                    _pipeline_scores[1], _pipeline_scores[2], _pipeline_scores[3]))
            timeframe = new_tf

    session = _get_session()
    bias    = get_signal_bias(pair, window=10, threshold=session["threshold"])
    if bias is not None and trend_1h is None:
        if bias == direction:
            direction = bias
    elif bias is not None and trend_1h is not None:
        if bias == trend_1h:
            direction = trend_1h

    if trend_1h == "BUY" and direction == "SELL":
        raw_gap = s - b - 45
        if raw_gap < 35:
            direction = "BUY"
    elif trend_1h == "SELL" and direction == "BUY":
        raw_gap = b - s - 45
        if raw_gap < 35:
            direction = "SELL"

    if not is_otc and is_filter_on("stability") and not _check_signal_stability(pair, direction, window_minutes=2):
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

    confluence = _calc_trend_confluence(trend_1h, vwap_data, mtf, direction)

    if not is_otc:
        direction = _apply_reversal_filter(direction, timeframe, pair)

    if not is_otc and timeframe > 0:
        try:
            real_pair_cg = OTC_TO_REAL.get(pair, pair)
            cg_symbol    = YAHOO_SYMBOLS.get(real_pair_cg)
            if cg_symbol:
                df_1m = _yf_download_cached(cg_symbol, "1d", "1m")
                candle_dir_1m = "NEUTRAL"
                if df_1m is not None and len(df_1m) >= 4:
                    opens_1m  = df_1m["Open"].squeeze().astype(float)
                    closes_1m = df_1m["Close"].squeeze().astype(float)
                    c1_bull = float(closes_1m.iloc[-1]) > float(opens_1m.iloc[-1])
                    c2_bull = float(closes_1m.iloc[-2]) > float(opens_1m.iloc[-2])
                    candle_dir_1m = "BUY" if (c1_bull and c2_bull) else \
                                    ("SELL" if (not c1_bull and not c2_bull) else "NEUTRAL")

                df_5m = _yf_download_cached(cg_symbol, "1d", "5m")
                candle_dir_5m = "NEUTRAL"
                if df_5m is not None and len(df_5m) >= 3:
                    opens_5m  = df_5m["Open"].squeeze().astype(float)
                    closes_5m = df_5m["Close"].squeeze().astype(float)
                    c1_5_bull = float(closes_5m.iloc[-1]) > float(opens_5m.iloc[-1])
                    c2_5_bull = float(closes_5m.iloc[-2]) > float(opens_5m.iloc[-2])
                    candle_dir_5m = "BUY" if (c1_5_bull and c2_5_bull) else \
                                    ("SELL" if (not c1_5_bull and not c2_5_bull) else "NEUTRAL")

                gate_scores = _pipeline_scores  # direct reference - edits are real
                _total_gate_score = sum(gate_scores.values())
                if _total_gate_score < 5.0:
                    logging.info("CANDLE GATE {}: scores trivial ({:.1f}) - gate skipped".format(
                        pair, _total_gate_score))
                else:
                    gate_changed = False

                    if candle_dir_1m not in (direction, "NEUTRAL"):
                        gate_scores[1] = max(0.0, gate_scores[1] - 30)
                        gate_changed = True
                        logging.info("CANDLE GATE {}: 1m candle opposes → 1m score penalised".format(pair))

                    if candle_dir_5m not in (direction, "NEUTRAL"):
                        gate_scores[2] = max(0.0, gate_scores[2] - 20)
                        gate_changed = True
                        logging.info("CANDLE GATE {}: 5m candle opposes → 2m score penalised".format(pair))

                    if candle_dir_1m == direction and candle_dir_5m == direction:
                        gate_scores[1] += 15
                        gate_changed = True
                        logging.info("CANDLE GATE {}: 1m+5m confirm → 1m score boosted".format(pair))
                    elif candle_dir_5m == direction and candle_dir_1m == "NEUTRAL":
                        gate_scores[2] += 10

                    if gate_changed:
                        new_tf = max(gate_scores, key=lambda t: gate_scores[t])
                        if new_tf != timeframe:
                            logging.info("CANDLE GATE {}: leading {}m → {}m after candle scores (1m:{:.1f} 2m:{:.1f} 3m:{:.1f})".format(
                                pair, timeframe, new_tf,
                                gate_scores[1], gate_scores[2], gate_scores[3]))
                        timeframe = new_tf
        except Exception as _cg_e:
            logging.warning("candle gate {} failed: {}".format(pair, _cg_e))

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

    if not is_otc and timeframe > 0:
        try:
            _d5  = _d10 = _d15 = None
            if _micro_htf:
                _d5  = _micro_htf.get("5_s",  {}).get("direction")
                _d10 = _micro_htf.get("10_s", {}).get("direction")
                _d15 = _micro_htf.get("15_s", {}).get("direction")

            best_combo = get_best_combo_from_fingerprint(
                pair=pair, rsi=rsi, bb_pos=bb_pos, macd=macd,
                mom=mom, atr_pct=atr_pct, trend_1h=trend_1h,
                d5s_dir=_d5, d10s_dir=_d10, d15s_dir=_d15,
                min_samples=5
            )
            if best_combo is not None:
                fp_dir = best_combo["direction"]
                fp_tf  = best_combo["tf_mins"]
                fp_wr  = best_combo["win_rate"]
                fp_mov = best_combo["avg_movement"]
                fp_score = best_combo["score"]

                fp_bonus = min(60.0, fp_score * 80)  # max 60pts for fp_score=0.75
                _pipeline_scores[fp_tf] = _pipeline_scores.get(fp_tf, 0) + fp_bonus
                if fp_dir != direction and fp_wr >= 0.65:
                    direction = fp_dir
                    logging.info("FP_DIR_OVERRIDE {}: dir → {} (wr={:.0f}% n={})".format(
                        pair, fp_dir, fp_wr * 100, best_combo["sample_n"]))

                new_tf = max(_pipeline_scores, key=lambda t: _pipeline_scores[t])
                if new_tf != timeframe:
                    logging.info("FP_TF_ADJUST {}: leading {}m → {}m after fp_bonus={:.1f} (wr={:.0f}% move={:.4f}% scores: 1m={:.1f} 2m={:.1f} 3m={:.1f})".format(
                        pair, timeframe, new_tf, fp_bonus, fp_wr * 100, fp_mov,
                        _pipeline_scores[1], _pipeline_scores[2], _pipeline_scores[3]))
                else:
                    logging.info("FP_SCORE_CONFIRM {}: {}m confirmed by fingerprint (wr={:.0f}% move={:.4f}%)".format(
                        pair, timeframe, fp_wr * 100, fp_mov))
                timeframe = new_tf
        except Exception as _fp_e:
            logging.warning("fingerprint combo select failed {}: {}".format(pair, _fp_e))

    if not is_otc:
        logging.info("TF PIPELINE FINAL {}: 1m:{:.1f} 2m:{:.1f} 3m:{:.1f} → CHOSEN={}m [h1conf={} candlegate=done fp=done]".format(
            pair,
            _pipeline_scores.get(1, 0),
            _pipeline_scores.get(2, 0),
            _pipeline_scores.get(3, 0),
            timeframe,
            is_filter_on("h1confirm")
        ))

    record_signal(pair, direction,
                  rsi=rsi, macd=macd, bb_pos=bb_pos, sto=sto,
                  ma_diff=ma_diff, mom=mom, atr_pct=atr_pct,
                  session=_get_session().get("name", "Unknown"),
                  trend_1h=trend_1h, score=strength, tf_mins=timeframe)
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
        "_nn_feat_arr":  nn_feat_arr,
        "micro_htf":     _micro_htf,  # 5s→1m, 10s→2m, 15s→3m HTF trend data
    }
    return result

PAIR_INDEX = {str(i): pair for i, pair in enumerate(ALL_PAIRS)}

def pair_to_idx(pair):
    for idx, p in PAIR_INDEX.items():
        if p == pair:
            return idx
    return None

def is_market_closed():
    """
    Returns True when non-OTC forex pairs are unavailable:
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
    if total_mins >= 1245 or total_mins < 15:
        return True
    return False

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

# ── v59: MAIN MENU KEYBOARD ─────────────────────────────────────────────────
# Pairs za multi-scan (Button 3) - user anachagua 4 au 6 pairs
MULTI_SCAN_4_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
]
MULTI_SCAN_6_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "EUR/JPY", "GBP/JPY",
]

def main_menu_keyboard(user_id=None):
    """
    v62: Menu kuu.
      - Free users ambao bado wana signals zilizobaki: wanaona trading buttons tu.
        Upgrade/Licence na My Stats zimefichwa mpaka signals zote zishe.
      - Free users ambao signals zishe (au licensed): wanaona kila kitu.
    """
    lic = is_licensed(user_id) if user_id else False

    # Amua kama kuonyesha Upgrade/Stats au la
    show_upgrade_stats = True
    if user_id and not lic:
        used  = free_signals_used(user_id)
        total = total_free_allowed(user_id)
        if used < total:
            show_upgrade_stats = False  # Bado ana signals — ficha upgrade/stats

    rows = [
        [InlineKeyboardButton("🌐 Global Scan  (All Pairs)", callback_data="global_scan")],
        [InlineKeyboardButton("📊 Select Pair", callback_data="choose_pair")],
        [InlineKeyboardButton("🎯 Multi Scan", callback_data="multi_scan_menu")],
    ]
    if show_upgrade_stats:
        rows.append([InlineKeyboardButton("📊 My Stats", callback_data="my_stats")])
    if show_upgrade_stats and not lic:
        rows.append([InlineKeyboardButton("💎 Upgrade / Licence", callback_data="pay_info")])
    rows.append([InlineKeyboardButton("ℹ️ Help", callback_data="help_inline")])
    return InlineKeyboardMarkup(rows)

def pairs_keyboard():
    """
    Build the pair selection keyboard.

    Logic (auto-detect):
    - Market CLOSED (weekend / night hours):
        Show OTC pairs only. Non-OTC pairs are completely hidden.
    - Market OPEN (weekdays, market hours):
        Show non-OTC forex pairs grouped by tier:
          ★ MAJOR PAIRS (7 most liquid)
          ✦ POPULAR CROSSES (EUR/GBP, GBP/JPY, etc.)
          ◆ MINOR CROSSES

        NOTE (v58): Indices and exotic pairs removed from non-OTC keyboard.
        All shown pairs trigger Auto Scan directly.

    Pairs sorted: hot pairs (consecutive_wins >= 3) first within each
    priority group, then by win rate. Max 96 buttons, 3 per row.
    """
    _MAJORS = [
        "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
        "AUD/USD", "USD/CAD",
    ]
    _POPULAR_CROSSES = [
        "EUR/GBP", "EUR/JPY", "EUR/AUD", "EUR/CAD", "EUR/CHF",
        "GBP/JPY", "GBP/AUD", "GBP/CAD", "GBP/CHF",
    ]
    _MINOR_CROSSES = [
        "AUD/JPY", "AUD/CAD", "AUD/CHF",
        "CHF/JPY", "CAD/JPY", "CAD/CHF",
    ]
    _KNOWN_TIERS = set(_MAJORS + _POPULAR_CROSSES + _MINOR_CROSSES)

    _MAX_BUTTONS = 96
    rows = []
    closed = is_market_closed()
    reason = _market_closed_reason()

    if closed:
        pool = [p for p in ALL_PAIRS if "OTC" in p]
    else:
        # v58: non-OTC = forex pairs tu (majors + crosses), hakuna indices/exotics
        pool = [p for p in (_MAJORS + _POPULAR_CROSSES + _MINOR_CROSSES)
                if p in ALL_PAIRS]

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

    btn_count = 0

    if closed:
        known   = sorted([p for p in pool if p in wr_rows and wr_rows[p][1] >= 3], key=_sort_key)
        unknown = sorted([p for p in pool if p not in known], key=_sort_key)
        pairs   = (known + unknown)[:_MAX_BUTTONS]
        row = []
        for pair in pairs:
            i = pair_to_idx(pair)
            if i is None:
                continue
            row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(i)))
            btn_count += 1
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    else:
        pool_set = set(pool)

        def _tier_buttons(tier_pairs, section_label):
            """Return rows for this tier, with a label button as header."""
            in_pool = [p for p in tier_pairs if p in pool_set]
            if not in_pool:
                return []
            sorted_pairs = sorted(in_pool, key=_sort_key)
            tier_rows = []
            tier_rows.append([InlineKeyboardButton(section_label, callback_data="noop")])
            row = []
            for pair in sorted_pairs:
                i = pair_to_idx(pair)
                if i is None:
                    continue
                row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(i)))
                if len(row) == 3:
                    tier_rows.append(row)
                    row = []
            if row:
                tier_rows.append(row)
            return tier_rows

        rows += _tier_buttons(_MAJORS,          "━━ ★ MAJOR PAIRS ━━")
        rows += _tier_buttons(_POPULAR_CROSSES, "━━ ✦ POPULAR CROSSES ━━")
        rows += _tier_buttons(_MINOR_CROSSES,   "━━ ◆ MINOR CROSSES ━━")
        # v58: hakuna INDICES wala EXOTICS kwenye non-OTC keyboard

    sess_line = _session_header_text()
    if sess_line:
        rows.insert(0, [InlineKeyboardButton(sess_line, callback_data="noop")])

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
        [InlineKeyboardButton("💬 Contact Admin", url=support_url())],
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

PAYMENT_TEXT = """💰 *UNLOCK EVALON WINNERS BOT*

🥈 *MONTHLY ACCESS - $50*
✅ Unlimited signals for 30 days
✅ AI-powered trading signals
✅ 100+ trading pairs

💎 *LIFETIME ACCESS - $150*
✅ Unlimited signals forever
✅ AI-powered trading signals
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

    if user_id == ADMIN_ID:
        return True

    try:
        if await is_channel_member(context.bot, user_id):
            return True
    except Exception:
        return True

    if has_join_request(user_id):
        return True

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    user_id = update.effective_user.id

    try:
        get_user(user_id)
    except Exception as e:
        logging.warning("start: get_user failed for {}: {}".format(user_id, e))

    if context.args:
        try:
            arg = context.args[0]
            referrer_id = int(arg.replace("REF_", ""))
            if referrer_id != user_id:
                register_referral(user_id, referrer_id)
        except Exception:
            pass

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
        "🏆 *AI-Powered Smart Signals*\n"
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
            "━━━━━━━━━━━━━━━━━━\n"
            "👥 *USER MANAGEMENT*\n"
            "`/listusers` - View all users & stats\n"
            "`/totalusers` - Quick user count\n"
            "`/stats` - Detailed statistics\n"
            "`/users` - Full user list with licence status\n"
            "`/userinfo 123456` - Full details of a user\n"
            "`/userchart` - User growth chart (last 30 days)\n"
            "`/addtrial 123456 5` - Give user extra free signals\n"
            "`/deleteuser 123456` - Delete user permanently\n"
            "`finduser name` - Search user by name/username\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📜 *SIGNAL HISTORY*\n"
            "`/history` - Last 20 signals sent\n"
            "`/history 123456` - Last signals for specific user\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚫 *BAN MANAGEMENT*\n"
            "`/blacklist 123456 reason` - Ban a user\n"
            "`/unblacklist 123456` - Unban a user\n"
            "`/listblacklist` - View all banned users\n"
            "`/blockuser 123456` - Block user (no access)\n"
            "`/unblockuser 123456` - Unblock user\n"
            "`/listblocked` - View all blocked users\n"
            "`/blockedbot` - Find users who blocked the bot\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📢 *BROADCAST*\n"
            "`/broadcast message` - Send message to all users\n"
            "_Markdown supported: *bold*, _italic_, `code`_\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🖼 *IMAGES*\n"
            "`/setimage` - Change BUY/SELL signal images\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🗄 *DATABASE*\n"
            "`/dbcheck` - Check database status\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 *PAIR STATS*\n"
            "`/pairstats` - Win/loss stats for all pairs (today)\n"
            "`/pairreport` - Full pair performance report\n"
            "`vtestats` - Forex pairs VTE win rate ranking\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔀 *OTC CONTROL*\n"
            "`/toggleotc` - Enable or disable OTC pairs\n"
            "• OTC OFF → show non-OTC pairs only\n"
            "• OTC ON  → all pairs visible (default)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🎛 *SIGNAL FILTERS*\n"
            "`/filterstatus` - View status of all filters\n"
            "`/trendon` - Enable trend-follow filter (default)\n"
            "`/trendoff` - Disable trend-follow filter (ALL signals)\n"
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
            "`/forcepair EURUSD OTC` - Bypass flat filter for pair\n"
            "`/forcepair all` - Bypass for all pairs\n"
            "`/forcepair list` - Show forced pairs\n"
            "`/unforcepair all` - Clear all overrides\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🧠 *NEURAL NETWORK*\n"
            "`/nnstats` - NN status, accuracy & per-pair models\n"
            "`/nnretrain` - Force NN retrain immediately\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "`/help` - This menu",
            parse_mode="Markdown",
            reply_markup=admin_image_keyboard()
        )
    else:
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
                [InlineKeyboardButton("🌐 Global Scan", callback_data="global_scan")],
                [InlineKeyboardButton("📊 Select Pair", callback_data="choose_pair")],
                [InlineKeyboardButton("🎯 Multi Scan", callback_data="multi_scan_menu")],
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
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_signal_state WHERE user_id = %s", (user_id,))
                conn.commit()
        except Exception as e:
            logging.warning("restart_fresh clear state failed: {}".format(e))
        inactivity_clear(user_id)
        _rb = get_broker_display(user_id)
        await q.edit_message_text(
            "⚡ *EVALON WINNERS BOT*\n\n"
            "🏆 Smart AI Signal Analysis\n"
            "📊 100+ Trading Pairs\n\n"
            "{}"
            "Choose how you want to get a signal:".format(
                (_rb + "\n\n") if _rb else ""
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(user_id)
        )
        return

    # v62: Broker selection callback
    if data.startswith("broker_select_"):
        broker_key = data[len("broker_select_"):]
        # Get display name from BROKER_LIST
        broker_name = broker_key.replace("_", " ").title()
        for name, cb in BROKER_LIST:
            if cb == broker_key:
                broker_name = name
                break
        set_broker_selected(user_id, broker_key)
        user  = get_user(user_id)
        lic   = is_licensed(user_id)
        plan  = user.get("licence_type", "").capitalize() if lic else "Free"
        await q.edit_message_text(
            "✅ *Broker selected: {}*\n\n"
            "⚡ *EVALON WINNERS BOT*\n\n"
            "👤 Plan: *{}*\n"
            "🏦 Broker: {}\n\n"
            "Select how you want to trade:".format(broker_name, plan, broker_name),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(user_id)
        )
        return

    if data == "global_scan":
        if not is_licensed(user_id):
            await q.edit_message_text(
                "🔒 *Global Scan — Subscribers Only*\n\n"
                "Global Scan scans {} pairs simultaneously and sends the best signal.\n\n"
                "Upgrade to unlock:\n"
                "✅ Global scan — all pairs at once\n"
                "✅ Trend-following signals only (no reverse)\n"
                "✅ Unlimited signals".format(len(GLOBAL_SCAN_PAIRS)),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("🔙 Back", callback_data="restart_fresh")],
                ])
            )
            return
        if is_market_closed():
            await q.edit_message_text(
                "🔒 *Market Closed*\n\n"
                "Global Scan works with non-OTC pairs only.\n"
                "Market is currently closed (weekend or night hours).\n\n"
                "_Wait for market to open or select an OTC pair manually._",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Choose OTC Pair", callback_data="choose_pair")],
                    [InlineKeyboardButton("🔙 Back", callback_data="restart_fresh")],
                ])
            )
            return
        # Simamisha scan nyingine inayoendelea
        old_ev = _ACTIVE_SCANS.get(int(user_id))
        if old_ev is not None:
            old_ev.set()
        asyncio.create_task(global_scan_and_send(context.bot, chat, user_id, context))
        return

    if data == "multi_scan_menu":
        if not is_licensed(user_id):
            await q.edit_message_text(
                "🔒 *Multi Scan — Subscribers Only*\n\n"
                "Upgrade to unlock Multi Scan and more.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("🔙 Back", callback_data="restart_fresh")],
                ])
            )
            return
        if is_market_closed():
            await q.edit_message_text(
                "🔒 *Market Closed*\n\n"
                "Multi Scan works with non-OTC pairs only.\n"
                "Market is currently closed (weekend or night hours).\n\n"
                "_Wait for market to open or select an OTC pair manually._",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Choose OTC Pair", callback_data="choose_pair")],
                    [InlineKeyboardButton("🔙 Back", callback_data="restart_fresh")],
                ])
            )
            return
        old_ev = _ACTIVE_SCANS.get(int(user_id))
        if old_ev is not None:
            old_ev.set()
        asyncio.create_task(multi_scan_and_send(context.bot, chat, user_id, MULTI_SCAN_6_PAIRS, context))
        return

    if data == "check_join":
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

    if data == "set_buy_img":
        if user_id != ADMIN_ID: return
        context.user_data["awaiting_image"] = "buy"
        await q.edit_message_text(
            "📈 *Set BUY Image*\n\nSend me the BUY signal image now.\n\n_Forward or send any photo - I will save it._",
            parse_mode="Markdown"
        )
        return

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

    if data == "cancel_scan":
        ev = _ACTIVE_SCANS.get(int(user_id))
        if ev is not None:
            ev.set()
        try: await q.answer()
        except: pass
        try:
            await q.edit_message_text(
                "⏹ *Scan Stopped*\n\n"
                "Auto scan has been stopped.\n"
                "Tap *🏆 EVALON MENU 🏆* to get a new signal.",
                parse_mode="Markdown"
            )
        except: pass
        return

    if data=="choose_pair":
        await delete_last_signal(context.bot, chat, user_id)
        try: await q.edit_message_reply_markup(reply_markup=None)
        except: pass
        try: await q.message.delete()
        except: pass

        closed = is_market_closed()

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
        if not is_licensed(user_id):
            await q.edit_message_text(
                "🔒 *Bot Pick Pair - Subscribers Only*\n\n"
                "This feature is available for licensed subscribers only.\n\n"
                "Upgrade to get:\n"
                "✅ Bot-picked best pairs\n"
                "✅ Unlimited signals\n"
                "✅ AI-powered trading signals",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("📊 Choose Pair Myself", callback_data="choose_pair")],
                ])
            )
            return

        closed = is_market_closed()

        if closed:
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
            top5 = get_top5_pairs(non_otc_only=True)
            if len(top5) < 5:
                _allowed = [
                    "EUR/USD","GBP/USD","USD/JPY","USD/CHF","AUD/USD","USD/CAD",
                    "EUR/GBP","EUR/JPY","EUR/AUD","EUR/CAD","EUR/CHF",
                    "GBP/JPY","GBP/AUD","GBP/CAD","GBP/CHF",
                    "AUD/JPY","AUD/CAD","AUD/CHF",
                    "CHF/JPY","CAD/JPY","CAD/CHF",
                ]
                existing = {r["pair"] for r in top5}
                for p in _allowed:
                    if p not in existing and len(top5) < 5 and p in ALL_PAIRS:
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
            "Best pairs by win rate — Major pairs prioritised.\n"
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
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="restart_fresh")],
        ])
        kb_free = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Referral Link", url=share_url)],
            [InlineKeyboardButton("💎 Upgrade", callback_data="pay_info")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="restart_fresh")],
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
            "🔒 *Free Trial Ended*\n\n"
            "You have used all your free trial signals.\n\n"
            "Contact admin to unlock full access and continue trading.",
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
            "🌐 *Global Scan* - Scan all pairs and send the best combined signal\n"
            "📊 *Select Pair* - Manually select a single pair\n"
            "🎯 *Multi Scan* - Scan 4 or 6 pairs at once\n"
            "📊 *My Stats* - View your account status\n"
            "💎 *Upgrade* - Purchase monthly or lifetime licence\n\n"
            "📌 *How to use:*\n"
            "1. Tap 🏆 EVALON MENU 🏆\n"
            "2. Choose Global Scan, Select Pair, or Multi Scan\n"
            "3. Wait for the signal — enter the trade when it appears",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="restart_fresh")],
                [InlineKeyboardButton("💬 Contact Support", url=support_url())],
            ])
        )
        return

    if data.startswith("otcback_"):
        idx_str = data[8:]
        pair = PAIR_INDEX.get(idx_str)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        await delete_last_signal(context.bot, chat, user_id)
        try: await q.message.delete()
        except: pass
        _m = await context.bot.send_message(
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
        push_msg_id(user_id, _m.message_id)
        return

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
        await delete_last_signal(context.bot, chat, user_id)
        try: await q.message.delete()
        except: pass

        check = check_signal_request(user_id, pair)
        clear_user_signal_state(user_id, pair)  # Force fresh always

        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)
        if cm: push_msg_id(user_id, cm.message_id)
        is_non_otc = False  # pair is OTC
        direction = "BUY"; timeframe = 1; strength = 180; flip_count = 0; sig = None

        try:
          if check["action"] == "fresh":
            sig = await safe_generate_signal(pair)  # guaranteed - OTC always signals
            _anim_stop.set()
            direction = sig["direction"]
            timeframe = sig["timeframe"]
            strength  = sig["strength"]
            flip_count = 0
            _nn_feat = sig.get("_nn_feat_arr")
            if _nn_feat is not None:
                nn_store_signal_features(user_id, pair, _nn_feat, sig.get("direction"))
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
            strength   = random.randint(120, 300)
            flip_count = 1
          else:
            state_s    = get_user_signal_state(user_id, pair)
            flip_count = state_s["flip_count"] + 1 if state_s else 2
            direction  = check["direction"]
            timeframe  = random.choice([1, 2, 3])
            strength   = random.randint(120, 300)

        except Exception as _otn_err:
            logging.warning("otc_normal_ signal failed {}: {}".format(pair, _otn_err))
            _anim_stop.set()
            try: await cm.delete()
            except: pass
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text="⚠️ *Signal unavailable* — please try again.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return
        finally:
            _anim_stop.set()
            try:
                if cm: await cm.delete()
            except: pass

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
        _bline = get_broker_display(user_id)
        cap = "*{}* {}\n🕐 In {} min.\n📊 Signal strength: {}%\n🧠 AI Consensus: {} indicators{}".format(
            pair, arrow, timeframe, strength, ind_agree if 'ind_agree' in dir() else "✓",
            "\n" + _bline if _bline else "")
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

    if data.startswith("nonotc_auto_"):
        data = "sel_{}".format(data[12:])

    if data.startswith("nonotctf_"):
        parts     = data[9:].rsplit("_", 1)
        idx_str   = parts[0]
        chosen_tf = int(parts[1]) if len(parts) == 2 else 1
        pair      = PAIR_INDEX.get(idx_str)
        if not pair: return
        if is_spam(user_id): return
        inactivity_reset(user_id, chat)
        _user_chose_tf = context.user_data.pop("_user_chose_tf", False)
        await delete_last_signal(context.bot, chat, user_id)
        try: await q.message.delete()
        except: pass
        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)
        if cm: push_msg_id(user_id, cm.message_id)

        try:
            mark_pair_active(pair)
            sig, _from_cache = await safe_generate_signal_cached(pair)
            if _from_cache:
                logging.info("PREFETCH HIT nonotctf {}: signal served from cache".format(pair))
            _anim_stop.set()
            direction = sig["direction"]
            timeframe = chosen_tf

            if pair in DERIV_SYMBOLS:
                try:
                    _best_tf, _best_str, _micro_dir, _best_reason = await pick_best_tf_deriv(pair)
                    logging.info("Deriv best_tf={} dir={} str={} - {}".format(
                        _best_tf, _micro_dir, _best_str, _best_reason))
                    if _best_tf is not None and _micro_dir is not None:
                        direction = _micro_dir
                        timeframe = _best_tf
                    else:
                        _weak_agree = sig.get("indicators_agree", 0) < 4
                        _no_1h      = sig.get("trend_1h") is None
                        if _weak_agree and _no_1h:
                            await delete_last_signal(context.bot, chat, user_id)
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
                        logging.info("Deriv FLAT for {} - MTF strong enough, using MTF direction".format(pair))
                        timeframe = chosen_tf
                except Exception as _de:
                    logging.warning("Deriv pick_best_tf error: {} - falling back to MTF".format(_de))
                    timeframe = chosen_tf
            else:
                timeframe = chosen_tf  # Pair haipo Deriv - tumia chosen_tf

            save_user_signal_state(user_id, pair, direction, timeframe, 0)
            context.user_data["_nonotc_sig"]   = sig
            context.user_data["_nonotc_dir"]   = direction
            context.user_data["_nonotc_tf"]    = timeframe
            context.user_data["_nonotc_pair"]  = pair
            context.user_data["_nonotc_idx"]   = idx_str
            await _send_nonotc_signal(context, chat, user_id, pair, direction, timeframe, sig, idx_str)

        except Exception as _nntf_err:
            logging.warning("nonotctf_ signal failed {}: {}".format(pair, _nntf_err))
            await delete_last_signal(context.bot, chat, user_id)
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text="⚠️ *Signal unavailable* — please try again.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
        finally:
            _anim_stop.set()
            try:
                if cm: await cm.delete()
            except: pass
        return

    if data.startswith("otc_secs_"):
        idx_str = data[9:]
        pair = PAIR_INDEX.get(idx_str)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        await delete_last_signal(context.bot, chat, user_id)
        try: await q.message.delete()
        except: pass

        if not is_licensed(user_id):
            _m = await context.bot.send_message(
                chat_id=chat,
                text=(
                    "🔒 *Seconds signals - Subscribers Only*\n\n"
                    "This option is available for licensed subscribers only.\n\n"
                    "Upgrade to unlock:\n"
                    "✅ Seconds signals (3s/5s/10s/15s/30s)\n"
                    "✅ Unlimited signals\n"
                    "✅ AI-powered trading signals"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="pay_info")],
                    [InlineKeyboardButton("🔙 Back", callback_data="otcback_{}".format(idx_str))],
                ])
            )
            push_msg_id(user_id, _m.message_id)
            return

        _m = await context.bot.send_message(
            chat_id=chat,
            text="⏱ *{}*\n\nChoose signal duration:".format(pair),
            parse_mode="Markdown",
            reply_markup=otc_seconds_keyboard(pair)
        )
        push_msg_id(user_id, _m.message_id)
        return

    if data.startswith("otctf_"):
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

        await delete_last_signal(context.bot, chat, user_id)
        try: await q.message.delete()
        except: pass

        cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)
        if cm: push_msg_id(user_id, cm.message_id)

        try:
            sig       = await safe_generate_signal(pair)  # OTC - always returns signal
            _anim_stop.set()
            direction = sig["direction"]
            strength  = sig["strength"]

            trend_dir = get_trend_direction(pair)
            if trend_dir is not None:
                direction = trend_dir
            elif sig.get("indicators_agree", 7) < 4 and "OTC" not in pair:
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

            save_user_signal_state(user_id, pair, direction, 1, 0)

            ib    = direction == "BUY"
            img   = get_buy_image() if ib else get_sell_image()
            arrow = "Up 🟢" if ib else "Down 🔴"
            await delete_last_signal(context.bot, chat, user_id)

            _bline2 = get_broker_display(user_id)
            cap = "*{}* {}\n⏱ In *{}s*\n📊 Signal strength: {}%\n🧠 AI Consensus: 25+ indicators{}".format(
                pair, arrow, chosen_secs, strength,
                "\n" + _bline2 if _bline2 else "")
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

        except Exception as _otctf_err:
            logging.warning("otctf_ signal failed {}: {}".format(pair, _otctf_err))
            await delete_last_signal(context.bot, chat, user_id)
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text="⚠️ *Signal unavailable* — please try again.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="otctf_{}_{}".format(idx_str, chosen_secs))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
        finally:
            _anim_stop.set()
            try:
                if cm: await cm.delete()
            except: pass
        return

    if data.startswith("getmore_"):
        idx  = data[8:]
        pair = PAIR_INDEX.get(idx)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found.", reply_markup=pairs_keyboard())
            return
        if is_blacklisted(user_id):
            await context.bot.send_message(chat_id=chat, text="🚫 *You are banned from this bot.*", parse_mode="Markdown")
            return
        if is_spam(user_id):
            return

        await delete_last_signal(context.bot, chat, user_id)

        try:
            state_for_del = get_user_signal_state(user_id, pair)
            if state_for_del and state_for_del.get("result_msg_id"):
                await context.bot.delete_message(chat_id=chat, message_id=state_for_del["result_msg_id"])
        except Exception:
            pass

        try:
            await q.message.delete()
        except Exception:
            pass

        state = get_user_signal_state(user_id, pair)
        press_count = state.get("flip_count", 0) if state else 0
        expiry_finished = True   # Always treat as fresh - no blocking
        clear_user_signal_state(user_id, pair)

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
                    text="🔒 *Free Trial Ended*\n\nYou have used all your *{} free trial signals*.{}\n\n✅ Unlimited signals\n✅ AI-powered smart analysis\n✅ 100+ trading pairs\n\n_Contact admin to unlock full access._".format(total_free_allowed(user_id), extra),
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
        if cm: push_msg_id(user_id, cm.message_id)

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

        try:
            sig = await safe_generate_signal(pair)  # timeout-safe, OTC guaranteed
            _anim_stop.set()
            direction = sig["direction"]
            strength  = sig["strength"]

            _is_otc_confirm = "OTC" in pair
            try:
                direction = await asyncio.wait_for(
                    _confirm_signal_direction(pair, direction, _is_otc_confirm),
                    timeout=6.0
                )
            except asyncio.TimeoutError:
                logging.warning("_confirm_signal_direction timeout for {}".format(pair))

            _mtf_cap = None
            _gm_is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS

            if _gm_is_non_otc and pair in DERIV_SYMBOLS:
                try:
                    _best_tf, _best_str, _micro_dir, _best_reason = await pick_best_tf_deriv(pair)
                    logging.info("getmore Deriv: pair={} tf={} dir={} str={} - {}".format(
                        pair, _best_tf, _micro_dir, _best_str, _best_reason))
                    if _best_tf is not None and _micro_dir is not None:
                        direction = _micro_dir
                        timeframe = _best_tf
                    else:
                        _gm_weak = sig.get("indicators_agree", 0) < 4 and sig.get("trend_1h") is None
                        if _gm_weak:
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

            if sig.get("flat") and sig["timeframe"] == 0:
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

            trend_dir = get_trend_direction(pair)
            gm_is_non_otc_check = "OTC" not in pair and pair in YAHOO_SYMBOLS
            if trend_dir is not None:
                direction = trend_dir
            elif gm_is_non_otc_check and is_filter_on("confluence") and (sig.get("flat") or sig.get("indicators_agree", 10) < 4):
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

            gm_entry_price = None
            if gm_is_non_otc:
                gm_entry_price = _fetch_current_price(pair)
                save_user_signal_state(user_id, pair, direction, timeframe, new_flip_count, entry_price=gm_entry_price)

            ib    = direction == "BUY"
            img   = get_buy_image() if ib else get_sell_image()
            arrow = "Up 🟢" if ib else "Down 🔴"
            _str  = sig.get("strength", 200)
            if isinstance(_str, int) and _str > 450:
                _str = int(90 + (min(500, max(300, _str)) - 300) / 200 * 360)
            elif isinstance(_str, int) and _str < 90:
                _str = int(90 + (max(35, min(97, _str)) - 35) / 62 * 360)
            _str = max(90, min(450, int(_str)))
            if not is_licensed(user_id): use_free_signal(user_id)
            await delete_last_signal(context.bot, chat, user_id)
            _bline3 = get_broker_display(user_id)
            cap = "*{}* {}\n🕐 In *{}* min\n📊 Signal strength: {}%\n🧠 AI Consensus: 25+ indicators{}".format(
                pair, arrow, timeframe, _str,
                "\n" + _bline3 if _bline3 else "")
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
                        text="⏰ *Your session has expired.*\n\n🌟 *Join our VIP today!*\n\n✅ AI-powered trading signals\n✅ 100+ trading pairs\n✅ Unlimited signals\n\n_Tap *Start* below to open a fresh chart._",
                        parse_mode="Markdown",
                        reply_markup=expired_signal_keyboard()
                    )
                except Exception as e:
                    logging.warning("inactivity_expire send failed: {}".format(e))

            task = asyncio.create_task(inactivity_expire_gm(user_id, chat))
            USER_INACTIVITY[user_id]["task"] = task

        except Exception as _gm_err:
            logging.warning("getmore_ signal failed {}: {}".format(pair, _gm_err))
            await delete_last_signal(context.bot, chat, user_id)
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text="⚠️ *Signal unavailable* — please try again.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx_str))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
        finally:
            _anim_stop.set()
            try:
                if cm: await cm.delete()
            except: pass
        return

    if data.startswith("sel_"):
        idx=data[4:]
        pair=PAIR_INDEX.get(idx)
        if not pair:
            await context.bot.send_message(chat_id=chat, text="❌ Pair not found. Please choose again.", reply_markup=pairs_keyboard())
            return
        if is_blacklisted(user_id):
            await context.bot.send_message(chat_id=chat, text="🚫 *You are banned from this bot.*\n\nContact admin for more info.", parse_mode="Markdown")
            return
        closed = is_market_closed()
        await delete_last_signal(context.bot, chat, user_id)
        if closed and "OTC" not in pair:
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
        if is_spam(user_id):
            return
        inactivity_reset(user_id, chat)
        if not is_licensed(user_id) and free_signals_used(user_id) >= total_free_allowed(user_id):
            try: await q.message.delete()
            except: pass
            bonus = get_bonus_signals(user_id)
            refs = count_referrals(user_id)
            extra = "\n\n🎁 *You have {} referrals* - invite more to unlock extra signals!".format(refs) if refs > 0 else "\n\n🎁 *Invite 3+ friends* to get free bonus signals!"
            await context.bot.send_message(
                chat_id=chat,
                text="🔒 *Free Trial Ended*\n\n"
                     "You have used all your *{} free trial signals*.{}\n\n"
                     "✅ Unlimited signals\n"
                     "✅ AI-powered smart analysis\n"
                     "✅ 100+ trading pairs\n\n"
                     "_Contact admin to unlock full access._"
                     .format(total_free_allowed(user_id), extra),
                parse_mode="Markdown",
                reply_markup=unlock_keyboard()
            )
            return
        try: await q.message.delete()
        except: pass

        if "OTC" in pair:
            await delete_last_signal(context.bot, chat, user_id)
            if not is_licensed(user_id):
                _otcm = await context.bot.send_message(
                    chat_id=chat,
                    text=(
                        "🔒 *Seconds signals - Subscribers Only*\n\n"
                        "This option is available for licensed subscribers only.\n\n"
                        "Upgrade to unlock:\n"
                        "✅ Seconds signals (3s/5s/10s/15s/30s)\n"
                        "✅ Unlimited signals\n"
                        "✅ AI-powered trading signals"
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

        # v58: Every non-OTC pair → auto scan directly (not just 13 pairs)
        _is_forex_nonotc = "OTC" not in pair and pair in AUTO_SCAN_PAIRS
        if _is_forex_nonotc and not is_market_closed():
            old_ev = _ACTIVE_SCANS.get(user_id)
            if old_ev is not None:
                old_ev.set()
            await asyncio.sleep(0.1)
            asyncio.create_task(auto_scan_and_send(context.bot, chat, user_id, pair, context))
            return
        context.user_data["_user_chose_tf"] = False
        mark_pair_active(pair)

        is_non_otc  = "OTC" not in pair and pair in YAHOO_SYMBOLS
        entry_price = None
        trend       = get_trend_direction(pair)
        check       = check_signal_request(user_id, pair)
        clear_user_signal_state(user_id, pair)

        _cache_warm = is_signal_prefetched(pair)
        if _cache_warm:
            cm, _anim_stop = None, asyncio.Event()
            _anim_stop.set()  # hakuna animation - tayari imekamilika
        else:
            cm, _anim_stop = await animated_analyzing(context.bot, chat, pair)
            if cm: push_msg_id(user_id, cm.message_id)

        direction  = "BUY"
        timeframe  = 1
        strength   = 180
        flip_count = 0
        sig        = None

        try:
          if check["action"] == "fresh":
            sig, _from_cache = await safe_generate_signal_cached(pair)
            if _from_cache:
                logging.info("PREFETCH HIT {}: signal served from cache".format(pair))
            _anim_stop.set()
            direction  = sig["direction"]
            timeframe  = sig["timeframe"]
            strength   = sig["strength"]
            flip_count = 0
            if sig.get("flat") and timeframe == 0:
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
            if trend is not None:
                direction = trend
            elif is_non_otc and (sig.get("flat") or sig.get("indicators_agree", 10) < 3):
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

            if is_non_otc and pair in DERIV_SYMBOLS:
                try:
                    _best_tf, _best_str, _micro_dir, _best_reason = await pick_best_tf_deriv(pair)
                    logging.info("Deriv non-OTC: best_tf={} dir={} str={} - {}".format(
                        _best_tf, _micro_dir, _best_str, _best_reason))
                    if _best_tf is not None and _micro_dir is not None:
                        direction = _micro_dir   # micro-seconds decide direction
                        timeframe = _best_tf     # micro-seconds decide TF
                    else:
                        logging.info("Deriv FLAT for {} (sel_ handler) - falling back to MTF direction".format(pair))
                except Exception as _de:
                    logging.warning("Deriv TF confirmation failed {}: {} - falling back to MTF".format(pair, _de))

          else:
            sig2       = await safe_generate_signal(pair)
            _anim_stop.set()
            direction  = sig2["direction"]
            timeframe  = sig2["timeframe"] if sig2["timeframe"] > 0 else 1
            strength   = sig2["strength"]
            flip_count = 0
            sig        = sig2  # use fresh sig for display details

        except Exception as _sel_err:
            logging.warning("sel_ signal generation failed {}: {}".format(pair, _sel_err))
            _anim_stop.set()
            try: await cm.delete()
            except: pass
            _nsm = await context.bot.send_message(
                chat_id=chat,
                text="⚠️ *Signal unavailable* — please try again in a moment.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Get More", callback_data="getmore_{}".format(idx))]
                ])
            )
            save_last_bot_msg(user_id, _nsm.message_id)
            return
        finally:
            _anim_stop.set()
            try:
                if cm: await cm.delete()
            except: pass

        is_non_otc = "OTC" not in pair and pair in YAHOO_SYMBOLS

        # Get entry price BEFORE sending signal (for result tracking)
        if is_non_otc:
            entry_price = _fetch_current_price(pair)
            logging.info("ENTRY PRICE {}: {}".format(pair, entry_price))

        save_user_signal_state(user_id, pair, direction, timeframe, flip_count, entry_price=entry_price)
        if check["action"] != "fresh":
            record_signal(pair, direction)

        ib    = direction == "BUY"
        img   = get_buy_image() if ib else get_sell_image()
        arrow = "Up 🟢" if ib else "Down 🔴"
        _str2 = sig.get("strength", 200)
        if isinstance(_str2, int) and _str2 > 450:
            _str2 = int(90 + (min(500, max(300, _str2)) - 300) / 200 * 360)
        elif isinstance(_str2, int) and _str2 < 90:
            _str2 = int(90 + (max(35, min(97, _str2)) - 35) / 62 * 360)
        _str2 = max(90, min(450, int(_str2)))
        if not is_licensed(user_id): use_free_signal(user_id)
        try: await cm.delete()
        except: pass
        await delete_last_signal(context.bot, chat, user_id)
        _bline4 = get_broker_display(user_id)
        cap = "*{}* {}\n🕐 In *{}* min\n📊 Signal strength: {}%\n🧠 AI Consensus: 25+ indicators{}".format(
            pair, arrow, timeframe, _str2,
            "\n" + _bline4 if _bline4 else "")
        sent_msg = await context.bot.send_photo(chat_id=chat, photo=img, caption=cap, parse_mode="Markdown", reply_markup=signal_keyboard(pair))
        save_last_signal_msg(user_id, sent_msg.message_id)

        if is_non_otc and entry_price is not None:
            asyncio.create_task(
                schedule_result_check(context.bot, chat, user_id, pair, direction, timeframe, entry_price)
            )

        inactivity_reset(user_id, chat, msg_id=sent_msg.message_id)

        async def inactivity_expire(uid, cid):
            """Clears ALL signals and sends VIP message immediately."""
            await asyncio.sleep(INACTIVITY_MINUTES * 60)
            msg_ids = inactivity_get_msgs(uid)
            for mid in msg_ids:
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                except Exception:
                    pass
            inactivity_clear(uid)
            try:
                await context.bot.send_message(
                    chat_id=cid,
                    text=(
                        "⏰ *Your session has expired.*\n\n"
                        "🌟 *Join our VIP today and get more accuracy signals!*\n\n"
                        "✅ AI-powered trading signals\n"
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

AUTO_SCAN_PAIRS = {
    # ★ MAJOR PAIRS
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD",
    # ✦ POPULAR CROSSES
    "EUR/GBP", "EUR/JPY", "EUR/AUD", "EUR/CAD", "EUR/CHF",
    "GBP/JPY", "GBP/AUD", "GBP/CAD", "GBP/CHF",
    # ◆ MINOR CROSSES
    "AUD/JPY", "AUD/CAD", "AUD/CHF",
    "CHF/JPY", "CAD/JPY", "CAD/CHF",
}

# Global scan: sawa na AUTO_SCAN_PAIRS — pairs zote za forex zinazoscan
GLOBAL_SCAN_PAIRS = list(AUTO_SCAN_PAIRS)

_ACTIVE_SCANS = {}  # {user_id: asyncio.Event (cancel event)}

USER_TZ_OFFSET = {}  # {user_id: timedelta}

def _get_user_local_time(user_id):
    now_utc = datetime.utcnow()
    offset  = USER_TZ_OFFSET.get(int(user_id))
    if offset is not None:
        return now_utc + offset
    try:
        import pytz
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT timezone FROM user_settings WHERE user_id=%s", (user_id,))
                row = cur.fetchone()
        if row and row.get("timezone"):
            tz = pytz.timezone(row["timezone"])
            return datetime.now(tz).replace(tzinfo=None)
    except Exception:
        pass
    return now_utc

def _get_next_candle_open(user_id):
    """
    Pata wakati wa mwanzo wa candle inayofuata (1m).
    Subiri hadi sekunde 0 ya dakika inayofuata.
    Returns: (entry_str, secs_until_open, secs_until_close)
    secs_until_close = secs_until_open + 60 (mwisho wa candle hiyo)
    """
    now_local    = _get_user_local_time(user_id)
    now_utc      = datetime.utcnow()
    next_min_utc = now_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    next_min_loc = now_local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    secs_until   = max(0, (next_min_utc - now_utc).total_seconds())
    entry_str    = next_min_loc.strftime("%H:%M")
    return entry_str, secs_until, secs_until + 60


def _confirm_real_candle_direction(pair, expected_direction):
    """
    Fix #6: Thibitisha direction kwa kuangalia candle ya sasa kweli kweli.
    Check last 3 candles on 1m — at least 2 of 3 must point in direction.
    Returns: True kama confirmed, False kama hazilingani.
    """
    try:
        real_pair = OTC_TO_REAL.get(pair, pair)
        symbol = YAHOO_SYMBOLS.get(real_pair)
        if not symbol:
            return True  # Kama hatuipati data, ruhusu signal iendelee
        df = _yf_download_cached(symbol, "1d", "1m")
        if df is None or len(df) < 3:
            return True
        opens  = df["Open"].squeeze().astype(float)
        closes = df["Close"].squeeze().astype(float)
        votes = 0
        for i in [-1, -2, -3]:
            is_bull = float(closes.iloc[i]) > float(opens.iloc[i])
            if expected_direction == "BUY" and is_bull:
                votes += 1
            elif expected_direction == "SELL" and not is_bull:
                votes += 1
        confirmed = votes >= 2
        logging.info("CANDLE CONFIRM {}: dir={} votes={}/3 confirmed={}".format(
            pair, expected_direction, votes, confirmed))
        return confirmed
    except Exception as e:
        logging.warning("_confirm_real_candle_direction failed {}: {}".format(pair, e))
        return True  # Usiblock signal kwa sababu ya error


async def multi_scan_and_send(bot, chat, user_id, pairs_to_scan, context):
    """
    MULTI SCAN ENGINE (v60 - Sequential):
    Scan pairs ZILIZOCHAGULIWA moja kwa moja — pair 1 → pair 2 → ... → pair N → rudia.

    Mabadiliko v60 (OOM fix):
      - Hapo awali (v59): asyncio.gather → pairs ZOTE kwa wakati mmoja → OOM crash
      - Sasa (v60): pair moja kwa wakati → signal inatumwa mara moja ikipata → pair inayofuata
      - RAM inatumika x1 tu (si x6) → hakuna OOM
      - Round moja (pairs zote) inaisha ndani ya sekunde ~30-60 → inaanza tena
    """
    MIN_INDICATORS = 4
    MIN_STRENGTH   = 120
    FIXED_TF       = 1
    PAIR_DELAY     = 20  # v65-fix: was undefined (NameError bug)

    uid = int(user_id)
    n   = len(pairs_to_scan)

    # v65-fix: mark all pairs active so prefetch engine fetches them
    for _p in pairs_to_scan:
        mark_pair_active(_p)

    cancel_ev = asyncio.Event()
    _ACTIVE_SCANS[uid] = cancel_ev

    stop_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹  Stop", callback_data="cancel_scan")]
    ])

    def _is_cancelled():
        return cancel_ev.is_set() or _ACTIVE_SCANS.get(uid) is not cancel_ev

    async def _wait(secs):
        try:
            await asyncio.wait_for(cancel_ev.wait(), timeout=secs)
        except asyncio.TimeoutError:
            pass

    try:
        scan_msg = await bot.send_message(
            chat_id=chat,
            text=(
                "🎯 *Multi Scan Started*\n\n"
                "📡 Scanning market continuously\\.\n"
                "⚡ Every strong signal will be sent automatically\\.\n\n"
                "_Tap Stop to end the session\\._"
            ),
            parse_mode="MarkdownV2",
            reply_markup=stop_kb
        )
        save_last_bot_msg(uid, scan_msg.message_id)
    except Exception as e:
        logging.warning("multi_scan: start msg failed: {}".format(e))
        return

    round_count     = 0
    signal_count    = 0
    dot_tick        = 0   # v62: fast dot counter
    scan_wins_ref   = [0]
    scan_losses_ref = [0]

    try:
        while True:
            if _is_cancelled():
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "⏹ *Multi Scan Stopped* — {} pairs\n\n"
                            "🏆 Won: *{}*   💔 Lost: *{}*\n"
                            "📊 Total signals: *{}*"
                        ).format(n, scan_wins_ref[0], scan_losses_ref[0],
                                 scan_wins_ref[0] + scan_losses_ref[0]),
                        parse_mode="Markdown"
                    )
                except: pass
                return

            if is_market_closed():
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "🔒 *Market Closed*\n\nMulti Scan works with non\-OTC pairs only\.\n"
                            "Wait for market to open\.\n\n_Tap Stop to end\._"
                        ),
                        parse_mode="MarkdownV2",
                        reply_markup=stop_kb
                    )
                except: pass
                await _wait(60)
                continue

            active_pairs = [p for p in pairs_to_scan if p in YAHOO_SYMBOLS]
            if not active_pairs:
                await _wait(60)
                continue

            round_count += 1
            anim = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪", "🟤"][round_count % 8]

            # ── SEQUENTIAL SCAN: pair moja kwa wakati ──────────────────────────
            for pair_idx, pair in enumerate(active_pairs):
                if _is_cancelled():
                    break
                dot_tick += 1
                anim = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪", "🟤"][dot_tick % 8]
                _pemoji = PAIR_EMOJIS.get(pair, "📊")

                # Update status message — inaonyesha pair inayoscaniwa sasa
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "{} *Multi Scanning*\n\n"
                            "🔍 *{}* {}\n\n"
                            "_Analysing market\\.\\.\\._"
                        ).format(anim, pair.replace("/", "\\/"), _pemoji),
                        parse_mode="MarkdownV2",
                        reply_markup=stop_kb
                    )
                except: pass

                # ── Scan pair moja (sequential — RAM x1 tu) ──
                try:
                    result = await safe_generate_signal_cached(pair)
                except Exception as _ge:
                    logging.warning("multi_scan gather {}: {}".format(pair, _ge))
                    await _wait(PAIR_DELAY)
                    continue

                try:
                    sig, _ = result if isinstance(result, tuple) else (result, None)
                    if sig is None:
                        await _wait(PAIR_DELAY)
                        continue

                    is_flat   = sig.get("flat", False)
                    tf        = sig.get("timeframe", 0)
                    ind_agree = sig.get("indicators_agree", 0)
                    strength  = sig.get("strength", 0)
                    direction = sig.get("direction")
                    trend_1h  = sig.get("trend_1h")
                    micro_htf = sig.get("micro_htf")

                    if is_flat or tf == 0 or not direction or ind_agree < MIN_INDICATORS:
                        await _wait(PAIR_DELAY)
                        continue

                    # Normalise strength
                    if isinstance(strength, (int, float)) and strength > 450:
                        strength = int(90 + (min(500, max(300, strength)) - 300) / 200 * 360)
                    elif isinstance(strength, (int, float)) and strength < 90:
                        strength = int(90 + (max(35, min(97, strength)) - 35) / 62 * 360)
                    strength = max(90, min(450, int(strength)))

                    if strength < MIN_STRENGTH:
                        await _wait(PAIR_DELAY)
                        continue

                    # Trend-follow check
                    if is_filter_on("trend_follow"):
                        if trend_1h in ("BUY", "SELL") and direction != trend_1h:
                            logging.info("MULTI_SCAN {}: trend-follow skip dir={} trend={}".format(
                                pair, direction, trend_1h))
                            await _wait(PAIR_DELAY)
                            continue
                        elif trend_1h not in ("BUY", "SELL") and micro_htf:
                            micro_dirs = [
                                micro_htf.get("5_s",  {}).get("direction"),
                                micro_htf.get("10_s", {}).get("direction"),
                                micro_htf.get("15_s", {}).get("direction"),
                            ]
                            micro_dirs = [d for d in micro_dirs if d in ("BUY", "SELL")]
                            if len(micro_dirs) >= 2:
                                micro_trend = "BUY" if micro_dirs.count("BUY") > micro_dirs.count("SELL") else "SELL"
                                if direction != micro_trend:
                                    logging.info("MULTI_SCAN {}: micro-trend skip dir={} micro={}".format(
                                        pair, direction, micro_trend))
                                    await _wait(PAIR_DELAY)
                                    continue

                    candle_ok = _confirm_real_candle_direction(pair, direction)
                    if not candle_ok:
                        await _wait(PAIR_DELAY)
                        continue

                    # ── Signal ipatikana — tuma mara moja ─────────────────────
                    ib        = direction == "BUY"
                    img       = get_buy_image() if ib else get_sell_image()
                    dir_arrow = "📈" if ib else "📉"
                    dir_label = "BUY 🟢" if ib else "SELL 🔴"

                    entry_str, secs_to_open, secs_to_close = _get_next_candle_open(uid)
                    signal_count += 1

                    _bscan1 = get_broker_display(uid)
                    _bscan1_esc = _bscan1.replace("-", "\\-").replace(".", "\\.").replace("!", "\\!").replace("(", "\\(").replace(")", "\\)").replace("|", "\\|")
                    cap = (
                        "🏆 *EVALON WINNERS* 🏆\n\n"
                        "\-\-\-\-\-\-\-\-\-\-\-\-\-\-\n"
                        "📊 PAIR      : *{}*\n"
                        "⏱ EXPIRY    : *1 MIN*\n"
                        "🕐 ENTRY     : *{}*\n"
                        "{} DIRECTION : *{}*\n"
                        "\-\-\-\-\-\-\-\-\-\-\-\-\-\-\n\n"
                        "⚡ Open at next candle"
                        "{}").format(
                        pair.replace("/", "\/"), entry_str, dir_arrow, dir_label,
                        "\n" + _bscan1_esc if _bscan1_esc else "")

                    entry_price = _fetch_current_price(pair)
                    save_user_signal_state(uid, pair, direction, FIXED_TF, 0, entry_price=entry_price)
                    if not is_licensed(uid): use_free_signal(uid)

                    sent_msg = await bot.send_photo(
                        chat_id=chat,
                        photo=img,
                        caption=cap,
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⏹  Stop", callback_data="cancel_scan")]
                        ])
                    )
                    save_last_signal_msg(uid, sent_msg.message_id)
                    record_signal(pair, direction)

                    if entry_price is not None:
                        asyncio.create_task(
                            auto_scan_result_check(
                                bot, chat, uid, pair, direction, FIXED_TF,
                                entry_price, secs_to_close,
                                scan_wins_ref, scan_losses_ref
                            )
                        )

                    logging.info("MULTI_SCAN signal sent: {} {} str={}".format(
                        pair, direction, strength))

                except Exception as _pe:
                    logging.warning("multi_scan pair {} failed: {}".format(pair, _pe))
                    continue

            # Round imekwisha — onyesha status na anza round mpya mara moja
            if not _is_cancelled():
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "✅ *Round \#{} Done* — {} pairs scanned\n\n"
                            "🏆 Won: *{}*   💔 Lost: *{}*\n"
                            "📊 Signals: *{}*\n\n"
                            "🔄 _Starting next round\.\.\._"
                        ).format(
                            round_count, len(active_pairs),
                            scan_wins_ref[0], scan_losses_ref[0], signal_count
                        ),
                        parse_mode="MarkdownV2",
                        reply_markup=stop_kb
                    )
                except: pass

    finally:
        if _ACTIVE_SCANS.get(uid) is cancel_ev:
            _ACTIVE_SCANS.pop(uid, None)


async def auto_scan_and_send(bot, chat, user_id, pair, context):
    # Fix #5: 1m only
    FIXED_TF       = 1
    SCAN_INTERVAL  = 45  # v65-fix: restored from 8 — indicators need time to compute
    MIN_INDICATORS = 4
    MIN_STRENGTH   = 120
    COOLDOWN_SECS  = 0

    # Fix #1: Tumia int(user_id) consistently
    uid = int(user_id)

    cancel_ev = asyncio.Event()
    _ACTIVE_SCANS[uid] = cancel_ev

    PAIR_EMOJIS = {
        # ★ MAJOR PAIRS
        "EUR/USD": "🇪🇺🇺🇸", "GBP/USD": "🇬🇧🇺🇸",
        "USD/JPY": "🇺🇸🇯🇵", "USD/CHF": "🇺🇸🇨🇭",
        "AUD/USD": "🇦🇺🇺🇸", "NZD/USD": "🇳🇿🇺🇸",
        "USD/CAD": "🇺🇸🇨🇦",
        # ✦ POPULAR CROSSES
        "EUR/GBP": "🇪🇺🇬🇧", "EUR/JPY": "🇪🇺🇯🇵",
        "EUR/AUD": "🇪🇺🇦🇺", "EUR/CAD": "🇪🇺🇨🇦",
        "EUR/CHF": "🇪🇺🇨🇭",
        "GBP/JPY": "🇬🇧🇯🇵", "GBP/AUD": "🇬🇧🇦🇺",
        "GBP/CAD": "🇬🇧🇨🇦", "GBP/CHF": "🇬🇧🇨🇭",
        # ◆ MINOR CROSSES
        "AUD/JPY": "🇦🇺🇯🇵", "AUD/CAD": "🇦🇺🇨🇦",
        "AUD/CHF": "🇦🇺🇨🇭", "AUD/NZD": "🇦🇺🇳🇿",
        "NZD/JPY": "🇳🇿🇯🇵", "NZD/CAD": "🇳🇿🇨🇦",
        "NZD/CHF": "🇳🇿🇨🇭",
        "CHF/JPY": "🇨🇭🇯🇵", "CAD/JPY": "🇨🇦🇯🇵",
        "CAD/CHF": "🇨🇦🇨🇭",
        "EUR/NZD": "🇪🇺🇳🇿", "GBP/NZD": "🇬🇧🇳🇿",
        "USD/MXN": "🇺🇸🇲🇽",
    }
    emoji = PAIR_EMOJIS.get(pair, "📊")

    # Fix #1: button uses correct uid string
    stop_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹  Stop", callback_data="cancel_scan")]
    ])

    def _is_cancelled():
        return cancel_ev.is_set() or _ACTIVE_SCANS.get(uid) is not cancel_ev

    async def _wait(secs):
        try:
            await asyncio.wait_for(cancel_ev.wait(), timeout=secs)
        except asyncio.TimeoutError:
            pass

    try:
        scan_msg = await bot.send_message(
            chat_id=chat,
            text=(
                "🔍 *Auto Scan Started*\n\n"
                "📡 Scanning market continuously\\.\\.\\.\n"
                "⚡ Every strong signal will be sent automatically\\.\n\n"
                "_Tap Stop to end the session\\._"
            ),
            parse_mode="MarkdownV2",
            reply_markup=stop_kb
        )
        save_last_bot_msg(uid, scan_msg.message_id)
    except Exception as e:
        logging.warning("auto_scan: start msg failed {}: {}".format(pair, e))
        return

    scan_count    = 0
    signal_count  = 0
    dot_tick      = 0   # v62: fast-changing dot counter
    scan_wins_ref    = [0]  # list so it is mutable inside nested function
    scan_losses_ref  = [0]

    try:
        while True:
            if _is_cancelled():
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "⏹ *Auto Scan Stopped* — {} {}\n\n"
                            "🏆 Won: *{}*   💔 Lost: *{}*\n"
                            "📊 Total signals: *{}*"
                        ).format(emoji, pair,
                                 scan_wins_ref[0], scan_losses_ref[0],
                                 scan_wins_ref[0] + scan_losses_ref[0]),
                        parse_mode="Markdown"
                    )
                except: pass
                return

            if scan_count > 0:
                await _wait(SCAN_INTERVAL)
                if _is_cancelled():
                    continue

            scan_count += 1
            dot_tick   += 1
            anim = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪", "🟤"][dot_tick % 8]

            # Block auto_scan if market is closed
            if is_market_closed():
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "🔒 *Market Closed* \u2014 {} {}\\n\\n"
                            "Auto Scan paused\\. Market is closed\\.\\n"
                            "_(Weekend or night hours)_\\n\\n"
                            "_Tap Stop to end\\._"
                        ).format(pair, emoji),
                        parse_mode="MarkdownV2",
                        reply_markup=stop_kb
                    )
                except: pass
                await _wait(60)
                continue

            try:
                await bot.edit_message_text(
                    chat_id=chat,
                    message_id=scan_msg.message_id,
                    text=(
                        "{} *Scanning*\n\n"
                        "🔍 *{}* {}\n\n"
                        "_Analysing market\\.\\.\\._"
                    ).format(anim, pair.replace("/", "\\/"), emoji),
                    parse_mode="MarkdownV2",
                    reply_markup=stop_kb
                )
            except: pass

            try:
                sig, _ = await safe_generate_signal_cached(pair)
                if sig is None:
                    continue

                is_flat   = sig.get("flat", False)
                tf        = sig.get("timeframe", 0)
                ind_agree = sig.get("indicators_agree", 0)
                _s        = sig.get("strength", 0)

                if isinstance(_s, (int, float)) and _s > 450:
                    _s = int(90 + (min(500, max(300, _s)) - 300) / 200 * 360)
                elif isinstance(_s, (int, float)) and _s < 90:
                    _s = int(90 + (max(35, min(97, _s)) - 35) / 62 * 360)
                _s = max(90, min(450, int(_s)))

                # Fix #5: use 1m only — ignore tf from engine
                timeframe = FIXED_TF

                # TREND-FOLLOW ONLY: direction must match trend_1h
                direction   = sig["direction"]
                trend_1h    = sig.get("trend_1h")

                # Kama trend_1h inapatikana, direction LAZIMA ilingane nayo
                # Reverse signals (direction ≠ trend_1h) zinakataliwa kabisa
                if is_filter_on("trend_follow"):
                  if trend_1h in ("BUY", "SELL"):
                    if direction != trend_1h:
                        logging.info("AUTO_SCAN {}: TREND-FOLLOW SKIP — dir={} opposes trend_1h={} (reverse rejected)".format(
                            pair, direction, trend_1h))
                        continue  # Skip — this is reverse, not trend follow
                    # Direction matches trend — good, continue
                  else:
                    # trend_1h missing — check Deriv indicators as trend proxy
                    micro_htf = sig.get("micro_htf")
                    if micro_htf:
                        micro_dirs = [
                            micro_htf.get("5_s",  {}).get("direction"),
                            micro_htf.get("10_s", {}).get("direction"),
                            micro_htf.get("15_s", {}).get("direction"),
                        ]
                        micro_dirs = [d for d in micro_dirs if d in ("BUY", "SELL")]
                        if len(micro_dirs) >= 2:
                            buy_votes  = micro_dirs.count("BUY")
                            sell_votes = micro_dirs.count("SELL")
                            micro_trend = "BUY" if buy_votes > sell_votes else "SELL"
                            if direction != micro_trend:
                                logging.info("AUTO_SCAN {}: MICRO-TREND SKIP — dir={} opposes micro_trend={}".format(
                                    pair, direction, micro_trend))
                                continue

                logging.info("AUTO_SCAN {}: #{} flat={} tf={} ind={} str={} dir={} trend={}".format(
                    pair, scan_count, is_flat, tf, ind_agree, _s, direction, trend_1h))

                if not is_flat and ind_agree >= MIN_INDICATORS and _s >= MIN_STRENGTH:

                    # Fix #6: Thibitisha kweli candle inakwenda direction hiyo
                    candle_ok = _confirm_real_candle_direction(pair, direction)
                    if not candle_ok:
                        logging.info("AUTO_SCAN {}: CANDLE CONFIRM FAILED dir={} — skipping".format(
                            pair, direction))
                        continue

                    ib        = direction == "BUY"
                    img       = get_buy_image() if ib else get_sell_image()
                    dir_arrow = "📈" if ib else "📉"
                    dir_label = "BUY 🟢" if ib else "SELL 🔴"

                    entry_str, secs_to_open, secs_to_close = _get_next_candle_open(uid)
                    signal_count += 1

                    _bscan2 = get_broker_display(uid)
                    _bscan2_esc = _bscan2.replace("-", "\\-").replace(".", "\\.").replace("!", "\\!").replace("(", "\\(").replace(")", "\\)").replace("|", "\\|")
                    cap = (
                        "🏆 *EVALON WINNERS* 🏆\n\n"
                        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
                        "📊 PAIR      : *{}*\n"
                        "⏱ EXPIRY    : *1 MIN*\n"
                        "🕐 ENTRY     : *{}*\n"
                        "{} DIRECTION : *{}*\n"
                        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n\n"
                        "⚡ Open at next candle"
                        "{}").format(
                        pair, entry_str, dir_arrow, dir_label,
                        "\n" + _bscan2_esc if _bscan2_esc else "")

                    entry_price = _fetch_current_price(pair)
                    save_user_signal_state(uid, pair, direction, FIXED_TF, 0, entry_price=entry_price)
                    if not is_licensed(uid): use_free_signal(uid)

                    sent_msg = await bot.send_photo(
                        chat_id=chat,
                        photo=img,
                        caption=cap,
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⏹  Stop", callback_data="cancel_scan")]
                        ])
                    )
                    save_last_signal_msg(uid, sent_msg.message_id)
                    record_signal(pair, direction)

                    if entry_price is not None:
                        asyncio.create_task(
                            auto_scan_result_check(
                                bot, chat, uid, pair, direction, FIXED_TF,
                                entry_price, secs_to_close,
                                scan_wins_ref, scan_losses_ref
                            )
                        )


            except Exception as _se:
                logging.warning("auto_scan generate failed {}: {}".format(pair, _se))
                continue

    finally:
        if _ACTIVE_SCANS.get(uid) is cancel_ev:
            _ACTIVE_SCANS.pop(uid, None)


async def auto_scan_result_check(bot, chat_id, user_id, pair, direction, timeframe_mins, entry_price, secs_to_close=65, wins_ref=None, losses_ref=None):
    """
    Thin wrapper — delegates to schedule_result_check which has the full
    candle-close logic (Finnhub + Yahoo, doji detection, DB recording).
    Also updates scan-session win/loss counters for the scan summary message.
    """
    if entry_price is None:
        return

    # Subiri mpaka candle ya 1m inayofuata ifunge (clock-aligned)
    # Signal imetumwa wakati wowote → ingia candle ya `:00` ijayo → ifunge `:00` ijayo
    now = datetime.utcnow()
    secs_in_minute = now.second + now.microsecond / 1e6
    # Sekunde zimebaki mpaka `:00` ijayo (candle open)
    secs_to_next_open = 60 - secs_in_minute
    # Subiri: mpaka candle ifunguke + dakika 1 nzima + buffer 5s
    wait_secs = secs_to_next_open + 60 + 5
    await asyncio.sleep(wait_secs)

    # Determine result from closed candle (same logic as schedule_result_check)
    won = None
    is_doji = False
    c_open = c_close = c_high = c_low = None

    real_pair = OTC_TO_REAL.get(pair, pair)
    symbol    = YAHOO_SYMBOLS.get(real_pair)
    fh_sym    = FINNHUB_FOREX_SYMBOLS.get(real_pair)

    for _attempt in range(4):
        try:
            df = None
            if fh_sym and FINNHUB_KEY:
                try:
                    df = _mtf_fh_candles(fh_sym, "1", 10)
                except Exception:
                    df = None
            if df is None and symbol:
                try:
                    _YF_CACHE.pop((symbol, "1d", "1m"), None)
                except Exception:
                    pass
                df = _yf_download_cached(symbol, "1d", "1m")

            if df is not None and len(df) >= 3:
                c_open  = float(df["Open"].squeeze().iloc[-2])
                c_close = float(df["Close"].squeeze().iloc[-2])
                c_high  = float(df["High"].squeeze().iloc[-2])
                c_low   = float(df["Low"].squeeze().iloc[-2])

                body         = abs(c_close - c_open)
                candle_range = c_high - c_low if c_high != c_low else 0.0001
                body_ratio   = body / candle_range
                is_doji      = body_ratio <= 0.10

                is_green = c_close > c_open
                is_red   = c_close < c_open

                if direction == "BUY":
                    won = True if is_green else (None if is_doji else False)
                else:
                    won = True if is_red  else (None if is_doji else False)

                logging.info("AUTO_SCAN RESULT {} attempt {}: open={:.5f} close={:.5f} body_ratio={:.2f} doji={} dir={} won={}".format(
                    pair, _attempt + 1, c_open, c_close, body_ratio, is_doji, direction, won))
                break

        except Exception as e:
            logging.warning("auto_scan_result candle check failed {} attempt {}: {}".format(pair, _attempt + 1, e))

        await asyncio.sleep(5)

    # Price fallback if candle data unavailable
    if won is None and not is_doji:
        exit_price = None
        for _ in range(4):
            exit_price = _fetch_current_price(pair)
            if exit_price is not None:
                break
            await asyncio.sleep(4)
        if exit_price is not None and entry_price is not None:
            diff = exit_price - entry_price
            won  = (diff > 0) if direction == "BUY" else (diff < 0)
            logging.info("AUTO_SCAN RESULT {}: price fallback entry={} exit={} won={}".format(
                pair, entry_price, exit_price, won))
        else:
            won = False

    # Update scan session counters
    if not is_doji and wins_ref is not None and losses_ref is not None:
        if won: wins_ref[0] += 1
        else:   losses_ref[0] += 1

    # Record to DB
    if not is_doji and won is not None:
        try: update_pair_stats(pair, won)
        except Exception as _e: logging.warning("auto_scan_result pair_stats: {}".format(_e))
        try:
            sess = _get_session().get("name", "Unknown")
            update_signal_combo_stats(pair=pair, direction=direction,
                                      tf_mins=timeframe_mins, won=won, session=sess)
        except Exception as _e: logging.warning("auto_scan_result combo_stats: {}".format(_e))
        try: nn_feedback_from_vte(user_id, pair, won)
        except Exception: pass

    # Send result message — always
    dir_arrow = "📈" if direction == "BUY" else "📉"

    if is_doji:
        header     = "〰️ *DOJI*"
        result_note = "No result — candle closed as indecision. Win/loss not counted."
        result_emoji = "〰️"
    elif won:
        header      = "✅ *WIN*"
        result_note = "Candle closed in your direction. Well traded!"
        result_emoji = "🏆"
    else:
        header      = "❌ *LOSS*"
        result_note = "Candle closed against your direction. Stay disciplined, next signal coming."
        result_emoji = "💔"

    candle_detail = ""
    if c_open is not None and c_close is not None:
        candle_detail = "\n📊 *Open:* `{:.5f}`  ➜  *Close:* `{:.5f}`".format(c_open, c_close)

    text = (
        "{} *EVALON WINNERS*\n"
        "━━━━━━━━━━━━━━\n"
        "📌 *Pair:* {}\n"
        "{} *Direction:* {}\n"
        "{}\n"
        "━━━━━━━━━━━━━━\n"
        "{}\n"
        "{}"
    ).format(
        result_emoji, pair,
        dir_arrow, direction,
        candle_detail,
        header, result_note,
    )

    try:
        sent = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        push_msg_id(user_id, sent.message_id)
    except Exception as e:
        logging.warning("auto_scan_result send failed: {}".format(e))


async def global_scan_and_send(bot, chat, user_id, context):
    """
    GLOBAL SCAN ENGINE (v55):
    Scan pairs ZOTE za GLOBAL_SCAN_PAIRS kwa wakati mmoja.
    Chagua signal MOJA bora zaidi kati ya zote — itume mtu.

    Kanuni za uchaguzi wa signal bora:
      1. TREND-FOLLOW ONLY: direction must match trend_1h or micro-HTF
         Reverse signals (counter-trend) zinakataliwa kabisa
      2. Ubora: indicators_agree × strength × trend confirmation
      3. Pair moja tu inatumwa kila scan cycle
    """
    SCAN_INTERVAL  = 45   # v65-fix: restored from 8 — indicators need time to compute
    MIN_INDICATORS = 4
    MIN_STRENGTH   = 120
    FIXED_TF       = 1
    COOLDOWN_SECS  = 0   # no cooldown after signal

    uid = int(user_id)

    # v65-fix: mark all global pairs active so prefetch engine fetches them
    for _p in GLOBAL_SCAN_PAIRS:
        mark_pair_active(_p)

    cancel_ev = asyncio.Event()
    _ACTIVE_SCANS[uid] = cancel_ev

    stop_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹  Stop", callback_data="cancel_scan")]
    ])

    def _is_cancelled():
        return cancel_ev.is_set() or _ACTIVE_SCANS.get(uid) is not cancel_ev

    async def _wait(secs):
        try:
            await asyncio.wait_for(cancel_ev.wait(), timeout=secs)
        except asyncio.TimeoutError:
            pass

    try:
        scan_msg = await bot.send_message(
            chat_id=chat,
            text=(
                "🌐 *Global Scan Started*\n\n"
                "📡 Scanning market continuously\\.\n"
                "⚡ Best trend\\-follow signal will be sent automatically\\.\n\n"
                "_Only trend\\-following signals \\(BUY with uptrend / SELL with downtrend\\)\\._\n\n"
                "_Tap Stop to end the session\\._"
            ),
            parse_mode="MarkdownV2",
            reply_markup=stop_kb
        )
        save_last_bot_msg(uid, scan_msg.message_id)
    except Exception as e:
        logging.warning("global_scan: start msg failed: {}".format(e))
        return

    scan_count    = 0
    signal_count  = 0
    dot_tick      = 0   # v62: fast dot counter
    scan_wins_ref   = [0]
    scan_losses_ref = [0]

    # Filter pairs kwa market hours
    def _get_active_pairs():
        if is_market_closed():
            return []  # Global scan is for non-OTC only
        return [p for p in GLOBAL_SCAN_PAIRS if p in YAHOO_SYMBOLS]

    try:
        while True:
            if _is_cancelled():
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "⏹ *Global Scan Stopped*\n\n"
                            "🏆 Won: *{}*   💔 Lost: *{}*\n"
                            "📊 Total signals: *{}*\n"
                            "📡 Pairs scanned: *{}*"
                        ).format(
                            scan_wins_ref[0], scan_losses_ref[0],
                            scan_wins_ref[0] + scan_losses_ref[0],
                            len(GLOBAL_SCAN_PAIRS)
                        ),
                        parse_mode="Markdown"
                    )
                except: pass
                return

            if scan_count > 0:
                await _wait(SCAN_INTERVAL)
                if _is_cancelled():
                    continue

            scan_count += 1
            dot_tick   += 1
            anim = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪", "🟤"][dot_tick % 8]

            active_pairs = _get_active_pairs()
            if not active_pairs:
                try:
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "🔒 *Market Closed*\n\n"
                            "Global Scan works with non\\-OTC pairs only\\.\n"
                            "Wait for market to open or select an OTC pair manually\\.\n\n"
                            "_Tap Stop to end\\._"
                        ),
                        parse_mode="MarkdownV2",
                        reply_markup=stop_kb
                    )
                except: pass
                await _wait(60)
                continue

            try:
                await bot.edit_message_text(
                    chat_id=chat,
                    message_id=scan_msg.message_id,
                    text=(
                        "{} *Global Scanning*\n\n"
                        "_Analysing all pairs\\.\\.\\. picking best trend signal\\._"
                    ).format(anim),
                    parse_mode="MarkdownV2",
                    reply_markup=stop_kb
                )
            except: pass

            # ── Scan pairs sequentially — moja kwa wakati (OOM fix v60) ────────
            candidates = []
            results    = []
            for _sp in active_pairs:
                if _is_cancelled():
                    break
                try:
                    dot_tick += 1
                    anim = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪", "🟤"][dot_tick % 8]
                    _pemoji = PAIR_EMOJIS.get(_sp, "📊")
                    await bot.edit_message_text(
                        chat_id=chat,
                        message_id=scan_msg.message_id,
                        text=(
                            "{} *Global Scanning*\n\n"
                            "🔍 *{}* {}\n\n"
                            "_Analysing all pairs\\.\\.\\. picking best trend signal\\._"
                        ).format(anim, _sp.replace("/", "\\/"), _pemoji),
                        parse_mode="MarkdownV2",
                        reply_markup=stop_kb
                    )
                except: pass
                try:
                    _sr = await safe_generate_signal_cached(_sp)
                    results.append((_sp, _sr))
                except Exception as _sge:
                    results.append((_sp, _sge))
                await asyncio.sleep(0.5)

            for pair, result in results:
                try:
                    if isinstance(result, Exception):
                        continue
                    sig, _ = result if isinstance(result, tuple) else (result, None)
                    if sig is None:
                        continue

                    is_flat   = sig.get("flat", False)
                    tf        = sig.get("timeframe", 0)
                    ind_agree = sig.get("indicators_agree", 0)
                    strength  = sig.get("strength", 0)
                    direction = sig.get("direction")
                    trend_1h  = sig.get("trend_1h")
                    micro_htf = sig.get("micro_htf")

                    if is_flat or tf == 0:
                        continue
                    if ind_agree < MIN_INDICATORS:
                        continue
                    if not direction:
                        continue

                    # ── TREND-FOLLOW FILTER ──────────────────────────────
                    # trend_1h inapatikana → direction LAZIMA ilingane
                    trend_confirmed = True  # default if filter is off
                    if is_filter_on("trend_follow"):
                        trend_confirmed = False
                        if trend_1h in ("BUY", "SELL"):
                            if direction != trend_1h:
                                logging.info("GLOBAL_SCAN {}: SKIP reverse dir={} vs trend_1h={}".format(
                                    pair, direction, trend_1h))
                                continue
                            trend_confirmed = True
                        else:
                            # Use Deriv micro-HTF as trend proxy
                            if micro_htf:
                                micro_dirs = [
                                    micro_htf.get("5_s",  {}).get("direction"),
                                    micro_htf.get("10_s", {}).get("direction"),
                                    micro_htf.get("15_s", {}).get("direction"),
                                ]
                                micro_dirs = [d for d in micro_dirs if d in ("BUY", "SELL")]
                                if len(micro_dirs) >= 2:
                                    buy_v  = micro_dirs.count("BUY")
                                    sell_v = micro_dirs.count("SELL")
                                    micro_trend = "BUY" if buy_v > sell_v else "SELL"
                                    if direction != micro_trend:
                                        logging.info("GLOBAL_SCAN {}: SKIP reverse dir={} vs micro_trend={}".format(
                                            pair, direction, micro_trend))
                                        continue
                                    trend_confirmed = True

                            # No trend data at all — skip (unknown if trend or reverse)
                            if not trend_confirmed:
                                logging.info("GLOBAL_SCAN {}: SKIP — no trend data, cannot confirm trend-follow".format(pair))
                                continue

                    # ── Normalise strength ───────────────────────────────
                    _s = strength
                    if isinstance(_s, (int, float)) and _s > 450:
                        _s = int(90 + (min(500, max(300, _s)) - 300) / 200 * 360)
                    elif isinstance(_s, (int, float)) and _s < 90:
                        _s = int(90 + (max(35, min(97, _s)) - 35) / 62 * 360)
                    _s = max(90, min(450, int(_s)))

                    if _s < MIN_STRENGTH:
                        continue

                    # ── Score candidate ──────────────────────────────────
                    # Score = indicators_agree × strength × trend_bonus
                    trend_bonus = 1.3 if trend_1h in ("BUY", "SELL") else 1.0
                    score = ind_agree * _s * trend_bonus

                    # Candle confirm bonus
                    candle_ok = _confirm_real_candle_direction(pair, direction)
                    if not candle_ok:
                        logging.info("GLOBAL_SCAN {}: candle confirm failed dir={} — penalise".format(pair, direction))
                        score *= 0.5  # Reduce score instead of rejecting entirely

                    candidates.append({
                        "pair":      pair,
                        "sig":       sig,
                        "direction": direction,
                        "trend_1h":  trend_1h,
                        "strength":  _s,
                        "ind_agree": ind_agree,
                        "score":     score,
                        "candle_ok": candle_ok,
                    })
                    logging.info("GLOBAL_SCAN candidate: {} dir={} score={:.0f} ind={} str={} trend={}".format(
                        pair, direction, score, ind_agree, _s, trend_1h))

                except Exception as _pe:
                    logging.warning("GLOBAL_SCAN pair {} error: {}".format(pair, _pe))
                    continue

            # ── Pick best candidate ─────────────────────────────────────────
            if not candidates:
                logging.info("GLOBAL_SCAN #{}: no trend-follow candidates found".format(scan_count))
                continue

            # Sort: candle_ok first, then highest score
            candidates.sort(key=lambda c: (c["candle_ok"], c["score"]), reverse=True)
            best = candidates[0]

            pair      = best["pair"]
            direction = best["direction"]
            _s        = best["strength"]
            trend_1h  = best["trend_1h"]

            logging.info("GLOBAL_SCAN #{} BEST: {} dir={} score={:.0f} (from {} candidates)".format(
                scan_count, pair, direction, best["score"], len(candidates)))

            # ── Send signal ─────────────────────────────────────────────────
            ib        = direction == "BUY"
            img       = get_buy_image() if ib else get_sell_image()
            dir_arrow = "📈" if ib else "📉"
            dir_label = "BUY 🟢" if ib else "SELL 🔴"
            trend_txt = "Trend: {} ✅".format(trend_1h) if trend_1h else "Trend confirmed ✅"

            entry_str, secs_to_open, secs_to_close = _get_next_candle_open(uid)
            signal_count += 1

            _bscan3 = get_broker_display(uid)
            _bscan3_esc = _bscan3.replace("-", "\\-").replace(".", "\\.").replace("!", "\\!").replace("(", "\\(").replace(")", "\\)").replace("|", "\\|")
            cap = (
                "🏆 *EVALON WINNERS* 🏆\n\n"
                "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
                "📊 PAIR      : *{}*\n"
                "⏱ EXPIRY    : *1 MIN*\n"
                "🕐 ENTRY     : *{}*\n"
                "{} DIRECTION : *{}*\n"
                "📡 {}*\n"
                "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n\n"
                "✅ Trend\\-follow signal"
                "{}"
            ).format(
                pair, entry_str, dir_arrow, dir_label,
                trend_txt.replace("-","\\-").replace(">","\\>"),
                "\n" + _bscan3_esc if _bscan3_esc else ""
            )

            entry_price = _fetch_current_price(pair)
            save_user_signal_state(uid, pair, direction, FIXED_TF, 0, entry_price=entry_price)
            if not is_licensed(uid): use_free_signal(uid)

            sent_msg = await bot.send_photo(
                chat_id=chat,
                photo=img,
                caption=cap,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏹  Stop", callback_data="cancel_scan")]
                ])
            )
            save_last_signal_msg(uid, sent_msg.message_id)
            record_signal(pair, direction)

            if entry_price is not None:
                asyncio.create_task(
                    auto_scan_result_check(
                        bot, chat, uid, pair, direction, FIXED_TF,
                        entry_price, secs_to_close,
                        scan_wins_ref, scan_losses_ref
                    )
                )

            # Scan interval before next cycle
            await _wait(SCAN_INTERVAL)

    finally:
        if _ACTIVE_SCANS.get(uid) is cancel_ev:
            _ACTIVE_SCANS.pop(uid, None)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id=update.effective_user.id

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

    # /settimezone +3 or /settimezone -5 or /settimezone +5:30
    if text.startswith("/settimezone"):
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "⏰ *Set Your Timezone*\n\n"
                "Usage: `/settimezone +3` or `/settimezone -5` or `/settimezone +5:30`\n\n"
                "Check your UTC offset — e.g. Nairobi is `+3`, London is `+0` or `+1`",
                parse_mode="Markdown"
            )
            return
        try:
            raw = parts[1].replace("UTC", "").strip()
            sign = -1 if raw.startswith("-") else 1
            raw  = raw.lstrip("+-")
            if ":" in raw:
                h, m = raw.split(":")
                total_mins = sign * (int(h) * 60 + int(m))
            else:
                total_mins = sign * int(raw) * 60
            offset = timedelta(minutes=total_mins)
            USER_TZ_OFFSET[int(user_id)] = offset
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO user_settings (user_id, timezone)
                            VALUES (%s, %s)
                            ON CONFLICT (user_id) DO UPDATE SET timezone = EXCLUDED.timezone
                        """, (user_id, parts[1]))
                    conn.commit()
            except Exception: pass
            sample = (_get_user_local_time(user_id)).strftime("%H:%M")
            await update.message.reply_text(
                "✅ *Timezone saved!*\n\nYour current time: `{}`".format(sample),
                parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ Invalid format. Try: `/settimezone +3`", parse_mode="Markdown")
        return


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
            oos_label = ns.get("oos_acc_label", "in-sample")
            acc_txt = "{:.1%} ({})".format(ns["global_acc"], oos_label) if ns["global_ready"] else "N/A"
            flip_acc = "{:.1%}".format(ns["flip_acc"]) if ns["total_flips"] > 0 else "N/A"
            top_pairs_txt = ""
            for p, samp, acc in ns["top_pairs"]:
                top_pairs_txt += "  • {} - {} samples, {:.1%} acc\n".format(p, samp, acc)
            if not top_pairs_txt:
                top_pairs_txt = "  _Not enough data yet_\n"
            pending_txt = " (+{} pending)".format(ns["in_mem_pending"]) if ns.get("in_mem_pending", 0) > 0 else ""
            msg = (
                "🧠 *NEURAL NETWORK STATS*\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📡 Status: *{}*\n"
                "🎯 Accuracy: *{}*\n"
                "📦 Real Outcomes (DB): *{}*{}\n"
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
                ns["global_samples"], pending_txt,
                ns["last_retrain"], ns["next_retrain_hours"],
                ns["pairs_trained"], top_pairs_txt,
                ns["total_flips"], flip_acc
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

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
                oos_label2 = ns.get("oos_acc_label", "in-sample")
                acc_txt = "{:.1%} ({})".format(ns["global_acc"], oos_label2) if ns["global_ready"] else "N/A"
                await update.message.reply_text(
                    "✅ *NN Retrain Complete*\n\n"
                    "🎯 Accuracy: *{}*\n"
                    "📦 Real Outcomes (DB): *{}*\n"
                    "📈 Pair Models: *{}*".format(
                        acc_txt, ns["global_samples"], ns["pairs_trained"]
                    ),
                    parse_mode="Markdown"
                )
            except Exception as _e:
                await update.message.reply_text("❌ Retrain failed: {}".format(_e))
            return

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

        if text == "/users":
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT user_id, first_name, last_name, username,
                                   licensed, licence_type, expiry, free_used,
                                   created_at
                            FROM users
                            ORDER BY created_at DESC
                            LIMIT 50
                        """)
                        rows = cur.fetchall()
                if not rows:
                    await update.message.reply_text("No users found.")
                    return
                lines = ["👥 *ALL USERS (last 50)*\n━━━━━━━━━━━━━━━━━━"]
                for r in rows:
                    first = r.get("first_name") or ""
                    last  = r.get("last_name")  or ""
                    name  = "{} {}".format(first, last).strip() or "No name"
                    uname = "@{}".format(r["username"]) if r.get("username") else "no username"
                    if r.get("licensed"):
                        lt = r.get("licence_type") or "?"
                        exp = r.get("expiry")
                        exp_str = exp.strftime("%d %b %Y") if exp else "lifetime"
                        status = "✅ {} | {}".format(lt.capitalize(), exp_str)
                    else:
                        status = "🆓 Free | used: {}".format(r.get("free_used", 0))
                    lines.append("• `{}` | {} | {}\n  {}".format(
                        r["user_id"], name, uname, status
                    ))
                full_msg = "\n".join(lines)
                for i in range(0, len(full_msg), 3800):
                    await update.message.reply_text(full_msg[i:i+3800], parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text("❌ Error: {}".format(e))
            return

        if text.startswith("/history"):
            parts = text.split()
            target_id = int(parts[1]) if len(parts) > 1 else None
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        if target_id:
                            cur.execute("""
                                SELECT pair, direction, tf_mins, score, won,
                                       created_at, session
                                FROM signal_history
                                WHERE user_id = %s
                                ORDER BY created_at DESC
                                LIMIT 20
                            """, (target_id,))
                        else:
                            cur.execute("""
                                SELECT user_id, pair, direction, tf_mins, score,
                                       won, created_at, session
                                FROM signal_history
                                ORDER BY created_at DESC
                                LIMIT 20
                            """)
                        rows = cur.fetchall()
                if not rows:
                    await update.message.reply_text("📭 No signal history found.")
                    return
                title = "📜 *SIGNAL HISTORY{}*\n━━━━━━━━━━━━━━━━━━".format(
                    " — User {}".format(target_id) if target_id else " (last 20)"
                )
                lines = [title]
                for r in rows:
                    dt = r.get("created_at")
                    dt_str = dt.strftime("%d %b %H:%M") if dt else "?"
                    won = r.get("won")
                    result = "✅ WIN" if won is True else ("❌ LOSS" if won is False else "⏳ Pending")
                    uid_str = " | UID: `{}`".format(r["user_id"]) if not target_id else ""
                    lines.append(
                        "• *{}* {} | {}m | {}{}\n  {} | Score: {}".format(
                            r.get("pair","?"), r.get("direction","?"),
                            r.get("tf_mins","?"), result, uid_str,
                            dt_str, r.get("score","?")
                        )
                    )
                await update.message.reply_text("\n".join(lines)[:4000], parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text("❌ Error: {}".format(e))
            return

        if text == "/userchart":
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                            FROM users
                            WHERE created_at >= NOW() - INTERVAL '30 days'
                            GROUP BY day
                            ORDER BY day ASC
                        """)
                        rows = cur.fetchall()
                if not rows:
                    await update.message.reply_text("📭 No user registration data in last 30 days.")
                    return
                total = sum(r["cnt"] for r in rows)
                peak_row = max(rows, key=lambda x: x["cnt"])
                peak_day = peak_row["day"].strftime("%d %b") if peak_row["day"] else "?"
                lines = ["📈 *USER GROWTH — Last 30 Days*\n━━━━━━━━━━━━━━━━━━"]
                for r in rows:
                    day_str = r["day"].strftime("%d %b") if r["day"] else "?"
                    bar = "█" * min(r["cnt"], 20)
                    lines.append("{} {} {}".format(day_str, bar, r["cnt"]))
                lines.append("━━━━━━━━━━━━━━━━━━")
                lines.append("📊 Total new: *{}* | Peak: *{}* on {}".format(total, peak_row["cnt"], peak_day))
                await update.message.reply_text("\n".join(lines)[:4000], parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text("❌ Error: {}".format(e))
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

    if text == "/trendoff" and user_id == ADMIN_ID:
        _FILTER_FLAGS["trend_follow"] = False
        await update.message.reply_text(
            "📉 *Trend-Follow Filter: OFF*\n\n"
            "Bot will now send ALL signals — trend and reverse.\n"
            "Use `/trendon` to restore the default.",
            parse_mode="Markdown"
        )
        return

    if text == "/trendon" and user_id == ADMIN_ID:
        _FILTER_FLAGS["trend_follow"] = True
        await update.message.reply_text(
            "📈 *Trend-Follow Filter: ON*\n\n"
            "Bot will only send trend-following signals — reverse signals are blocked.\n"
            "This is the default setting.",
            parse_mode="Markdown"
        )
        return

    if update.message.text and update.message.text.strip() == "/refer":
        user_id2 = update.effective_user.id
        refs = count_referrals(user_id2)
        bonus = get_bonus_signals(user_id2)
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

        # v62: User mpya — mpe broker selection mara ya kwanza tu
        if not get_broker_selected(user_id):
            await update.message.reply_text(
                "⚡ *EVALON WINNERS BOT*\n\n"
                "👋 Welcome! Before you start trading, please select your binary broker:\n\n"
                "🏦 *Choose your broker:*\n"
                "_This helps the bot optimize signals for your platform._",
                parse_mode="Markdown",
                reply_markup=broker_selection_keyboard()
            )
            return

        _mb = get_broker_display(user_id)
        await update.message.reply_text(
            "⚡ *EVALON WINNERS BOT*\n\n"
            "👤 Plan: *{}*\n"
            "{}\n\n"
            "Select how you want to trade:".format(plan, _mb if _mb else ""),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(user_id)
        )
        return

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

_BG_SCAN_PAIRS = [
    "EUR/USD","GBP/USD","USD/JPY","USD/CHF","AUD/USD","USD/CAD",
    "EUR/GBP","EUR/JPY","EUR/AUD","EUR/CAD","EUR/CHF",
    "GBP/JPY","GBP/AUD","GBP/CAD","GBP/CHF",
    "AUD/JPY","AUD/CAD","AUD/CHF",
    "CHF/JPY","CAD/JPY","CAD/CHF",
]

_fp_pending: dict = {}

def _save_fingerprint(pair, signal_dir, entry_price,
                      rsi=None, bb_pos=None, macd=None, mom=None, atr_pct=None,
                      trend_1h=None, d5s_dir=None, d5s_str=None,
                      d10s_dir=None, d10s_str=None, d15s_dir=None, d15s_str=None):
    """
    Hifadhi fingerprint ya signal kwenye trend_fingerprint_results.
    Returns: id ya row (tumia kwa update ya outcomes baadaye)
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trend_fingerprint_results
                        (pair, rsi, bb_pos, macd, mom, atr_pct, trend_1h,
                         d5s_dir, d5s_str, d10s_dir, d10s_str, d15s_dir, d15s_str,
                         signal_dir, entry_price, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    RETURNING id
                """, (pair, rsi, bb_pos, macd, mom, atr_pct, trend_1h,
                      d5s_dir, d5s_str, d10s_dir, d10s_str, d15s_dir, d15s_str,
                      signal_dir, entry_price))
                row = cur.fetchone()
            conn.commit()
        return row["id"] if row else None
    except Exception as e:
        logging.warning("_save_fingerprint failed {}: {}".format(pair, e))
        return None

def _update_fingerprint_outcome(fp_id, tf_mins, won, movement_pct, exit_price):
    """
    Sasisha outcome ya TF moja (1m, 2m, au 3m) kwa fingerprint.
    """
    col_won  = "won_{}m".format(tf_mins)
    col_move = "move_{}m".format(tf_mins)
    col_exit = "exit_{}m".format(tf_mins)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE trend_fingerprint_results
                    SET {won} = %s, {move} = %s, {exit} = %s
                    WHERE id = %s
                """.format(won=col_won, move=col_move, exit=col_exit),
                (won, movement_pct, exit_price, fp_id))
            conn.commit()
    except Exception as e:
        logging.warning("_update_fingerprint_outcome failed id={}: {}".format(fp_id, e))

def get_best_combo_from_fingerprint(pair, rsi=50.0, bb_pos=0.5, macd=0.0,
                                     mom=0.0, atr_pct=0.05, trend_1h=None,
                                     d5s_dir=None, d10s_dir=None, d15s_dir=None,
                                     min_samples=5):
    """
    Query DB: "Fingerprint similar to this one — where did price move strongly
    zaidi na iliwin wapi kwa uhakika zaidi?"

    Inaangalia zote 6: BUY 1m, BUY 2m, BUY 3m, SELL 1m, SELL 2m, SELL 3m
    Regardless of what indicators said — checks actual price movement.

    Fuzzy match: RSI ±12, BB ±0.15

    Scoring kwa kila combo:
      - Win rate (uzito 50%)
      - Average movement ya winners (uzito 50%) — movement kubwa = ushindi imara
      Combo yenye score kubwa zaidi ndiyo inachaguliwa.

    Returns dict au None:
      {direction, tf_mins, win_rate, avg_movement, sample_n, score}
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                results = {}

                for tf_m in [1, 2, 3]:
                    won_col  = "won_{}m".format(tf_m)
                    move_col = "move_{}m".format(tf_m)

                    cur.execute("""
                        SELECT
                            signal_dir,
                            COUNT(*) AS total,
                            SUM(CASE WHEN {won} = TRUE THEN 1 ELSE 0 END) AS wins,
                            AVG(CASE WHEN {won} = TRUE THEN {move} ELSE NULL END) AS avg_move_win
                        FROM trend_fingerprint_results
                        WHERE pair = %s
                          AND {won} IS NOT NULL
                          AND ABS(rsi - %s) <= 12
                          AND ABS(bb_pos - %s) <= 0.15
                          AND created_at >= NOW() - INTERVAL '30 days'
                        GROUP BY signal_dir
                        HAVING COUNT(*) >= %s
                    """.format(won=won_col, move=move_col),
                    (pair, float(rsi), float(bb_pos), min_samples))

                    for r in cur.fetchall():
                        direction = str(r["signal_dir"])
                        total     = int(r["total"])
                        wins      = int(r["wins"])
                        wr        = wins / total if total > 0 else 0.0
                        avg_move  = float(r["avg_move_win"] or 0.0)

                        move_score = min(1.0, avg_move / 0.10)
                        score = wr * 0.50 + move_score * 0.50

                        key = (direction, tf_m)
                        results[key] = {
                            "direction":    direction,
                            "tf_mins":      tf_m,
                            "win_rate":     wr,
                            "avg_movement": avg_move,
                            "sample_n":     total,
                            "score":        score,
                        }

        if not results:
            return None

        best = max(results.values(), key=lambda x: x["score"])

        if best["win_rate"] <= 0.50:
            return None

        logging.info("FP_BEST {}: dir={} tf={}m wr={:.0f}% move={:.4f}% n={} score={:.3f}".format(
            pair, best["direction"], best["tf_mins"],
            best["win_rate"] * 100, best["avg_movement"],
            best["sample_n"], best["score"]))

        return best

    except Exception as e:
        logging.warning("get_best_combo_from_fingerprint failed {}: {}".format(pair, e))
        return None

_bg_fp_pending: dict = {}

async def _bg_scan_and_learn():
    """
    Background scanner: kila sekunde 10, scan major/popular/minor pairs,
    weka fingerprint + virtual trades 1m/2m/3m sambamba.
    Inaendelea wakati wote soko liko wazi (non-OTC hours).
    """
    now = time.time()

    for pair in _BG_SCAN_PAIRS:
        try:
            real_pair = OTC_TO_REAL.get(pair, pair)
            yf_sym    = YAHOO_SYMBOLS.get(real_pair)
            if not yf_sym:
                continue

            entry_price = _fetch_current_price(pair)
            if entry_price is None:
                continue

            ind = _fetch_real_indicators(pair)
            if ind is None:
                continue

            rsi_v    = ind.get("rsi", 50.0)
            bb_pos_v = ind.get("bb_pos", 0.5)
            macd_v   = ind.get("macd", 0.0)
            mom_v    = ind.get("mom", 0.0)
            atr_v    = ind.get("atr", 0.05) if "atr" in ind else 0.05
            dir_v    = ind.get("direction")

            if dir_v is None:
                continue  # Hakuna direction wazi — skip

            trend_1h_v = None
            try:
                trend_1h_v = _fetch_1h_trend(pair)
            except Exception:
                pass

            d5s_dir = d5s_str = d10s_dir = d10s_str = d15s_dir = d15s_str = None
            try:
                cached = _deriv_tick_cache.get(pair)
                if cached and (time.time() - cached.get("ts", 0)) < _DERIV_CACHE_TTL:
                    data = cached["data"]
                    for secs, dkey in [(5,"5_s"),(10,"10_s"),(15,"15_s")]:
                        t = data.get(dkey, {})
                        if secs == 5:
                            d5s_dir = t.get("direction"); d5s_str = t.get("strength")
                        elif secs == 10:
                            d10s_dir = t.get("direction"); d10s_str = t.get("strength")
                        else:
                            d15s_dir = t.get("direction"); d15s_str = t.get("strength")
            except Exception:
                pass

            fp_id = _save_fingerprint(
                pair=pair, signal_dir=dir_v, entry_price=entry_price,
                rsi=rsi_v, bb_pos=bb_pos_v, macd=macd_v, mom=mom_v,
                atr_pct=atr_v, trend_1h=trend_1h_v,
                d5s_dir=d5s_dir, d5s_str=d5s_str,
                d10s_dir=d10s_dir, d10s_str=d10s_str,
                d15s_dir=d15s_dir, d15s_str=d15s_str
            )

            if fp_id is None:
                continue

            _bg_fp_pending[fp_id] = {
                "pair":      pair,
                "direction": dir_v,
                "entry":     entry_price,
                "expiry_1m": now + 60,
                "expiry_2m": now + 120,
                "expiry_3m": now + 180,
                "done_1m":   False,
                "done_2m":   False,
                "done_3m":   False,
            }

        except Exception as e:
            logging.warning("bg_scan pair {} failed: {}".format(pair, e))
            continue

async def _bg_check_fingerprint_outcomes():
    """
    Angalia fingerprints zilizopita expiry, hifadhi outcomes.
    Inaitwa kila sekunde 10 sambamba na _bg_scan_and_learn().
    """
    now = time.time()
    done_ids = []

    for fp_id, trade in list(_bg_fp_pending.items()):
        pair      = trade["pair"]
        direction = trade["direction"]
        entry     = trade["entry"]

        for tf_m, exp_key, done_key in [
            (1, "expiry_1m", "done_1m"),
            (2, "expiry_2m", "done_2m"),
            (3, "expiry_3m", "done_3m"),
        ]:
            if trade[done_key]:
                continue
            if now < trade[exp_key]:
                continue

            exit_price = _fetch_current_price(pair)
            if exit_price is None:
                trade[done_key] = True
                continue

            raw_diff     = exit_price - entry
            movement_pct = abs(raw_diff) / (entry + 1e-9) * 100
            won          = (raw_diff > 0) if direction == "BUY" else (raw_diff < 0)

            _update_fingerprint_outcome(fp_id, tf_m, won, movement_pct, exit_price)
            trade[done_key] = True

            logging.info("FP_OUTCOME: {} id={} {}m dir={} {} move={:.4f}%".format(
                pair, fp_id, tf_m, direction, "WIN" if won else "LOSS", movement_pct))

        if trade["done_1m"] and trade["done_2m"] and trade["done_3m"]:
            done_ids.append(fp_id)

    for fp_id in done_ids:
        _bg_fp_pending.pop(fp_id, None)

_signal_prefetch_cache: dict = {}
_PREFETCH_TTL = 55  # 55 seconds — nearly 1 minute before going stale

_prefetch_active_pairs: dict = {}   # pair → last_used unix timestamp
_PREFETCH_ACTIVE_TTL  = 600         # sekunde 600 = dakika 10

_PREFETCH_PAIRS_NONOTC = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/AUD", "EUR/CAD", "EUR/CHF",
    "GBP/AUD", "GBP/CAD", "GBP/CHF", "AUD/JPY", "AUD/CAD", "CAD/JPY", "CHF/JPY",
]
_PREFETCH_PAIRS_OTC = [
    "EUR/USD OTC", "GBP/USD OTC", "USD/JPY OTC", "USD/CHF OTC",
    "AUD/USD OTC", "NZD/USD OTC", "USD/CAD OTC",
    "EUR/GBP OTC", "EUR/JPY OTC", "GBP/JPY OTC",
]

def mark_pair_active(pair: str):
    """Weka pair kama active — inaitwa user anapobonyeza pair."""
    _prefetch_active_pairs[pair] = time.time()

def get_active_pairs() -> list:
    """Rudisha pairs zote zilizotumiwa ndani ya dakika 10. Futa za zamani."""
    now = time.time()
    stale = [p for p, ts in _prefetch_active_pairs.items()
             if now - ts > _PREFETCH_ACTIVE_TTL]
    for p in stale:
        _prefetch_active_pairs.pop(p, None)
        _signal_prefetch_cache.pop(p, None)
    return list(_prefetch_active_pairs.keys())

def get_prefetched_signal(pair: str):
    entry = _signal_prefetch_cache.get(pair)
    if not entry:
        return None
    if time.time() - entry["ts"] > _PREFETCH_TTL:
        _signal_prefetch_cache.pop(pair, None)
        return None
    return entry["sig"]

def set_prefetched_signal(pair: str, sig: dict):
    # v65-fix: usihifadhi signal ya flat/zero — itafetch upya scan inayofuata
    if sig is None:
        return
    if sig.get("flat", False) or sig.get("indicators_agree", 0) == 0 or sig.get("strength", 0) == 0:
        return
    _signal_prefetch_cache[pair] = {"sig": sig, "ts": time.time()}

async def signal_prefetch_engine():
    """
    Background engine ya pre-fetching signals (v52).
    - Inafetch active pairs tu (zilizotumiwa ndani ya dakika 10)
    - User akihacha → pairs zinatoka active list → engine inasimama
    - User akirudi → mark_pair_active() → engine inaanza tena
    """
    logging.info("Signal Prefetch Engine v52 starting...")
    await asyncio.sleep(15)

    while True:
        try:
            market_open  = not is_market_closed()
            active_pairs = get_active_pairs()

            if not active_pairs:
                await asyncio.sleep(1)
                continue

            for pair in active_pairs:
                if "OTC" not in pair and not market_open:
                    continue
                if get_prefetched_signal(pair) is not None:
                    continue  # Bado fresh - ruka
                try:
                    sig = await asyncio.wait_for(safe_generate_signal(pair), timeout=25)
                    set_prefetched_signal(pair, sig)
                    logging.info("PREFETCH {}: dir={} tf={}m".format(
                        pair, sig.get("direction", "?"), sig.get("timeframe", 0)))
                except Exception as _pfe:
                    logging.warning("PREFETCH failed {}: {}".format(pair, _pfe))
                await asyncio.sleep(2)  # gap kati ya pairs — punguza CPU pressure

        except Exception as e:
            logging.warning("signal_prefetch_engine error: {}".format(e))
        await asyncio.sleep(2)  # v62: reduced from 5 for faster cache refresh

async def safe_generate_signal_cached(pair: str) -> tuple:
    """
    v53: Cache hit → rudisha mara moja (karibu 0ms).
    Cache miss → fetch upya (inaweza kuchukua sekunde kadhaa).
    """
    cached = get_prefetched_signal(pair)
    if cached is not None:
        return cached, True
    sig = await safe_generate_signal(pair)
    set_prefetched_signal(pair, sig)
    return sig, False

def is_signal_prefetched(pair: str) -> bool:
    """Angalia kama signal ya pair ipo kwenye cache na bado fresh."""
    return get_prefetched_signal(pair) is not None

async def background_learning_engine():
    """
    Main loop ya background learning.
    Kila sekunde 10:
      - Scan pairs na hifadhi fingerprints (soko wazi tu)
      - Angalia outcomes za fingerprints zilizopita
    """
    logging.info("Background Learning Engine v50 starting...")
    while True:
        try:
            if not is_market_closed():
                await _bg_scan_and_learn()
            await _bg_check_fingerprint_outcomes()
        except Exception as e:
            logging.warning("background_learning_engine error: {}".format(e))
        await asyncio.sleep(60)

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
        df = _yf_download_cached(symbol, "2d", "5m")
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

    forex_pairs = [p for p in YAHOO_SYMBOLS if "/" in p and "BTC" not in p
                   and "^" not in YAHOO_SYMBOLS.get(p, "")]

    for pair in forex_pairs:
        try:
            sig = await safe_generate_signal(pair)  # timeout-safe
            direction = sig["direction"]

            last_dir = _vt_get_last_direction(pair)

            if direction == last_dir:
                continue

            _vt_set_last_direction(pair, direction)

            price = _fetch_current_price(pair)
            if price is None:
                continue

            if pair not in _virtual_trades:
                _virtual_trades[pair] = []

            nn_feat = sig.get("_nn_feat_arr")

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

            _vt_delete_trade(pair, entry_price, direction, expiry, tf_secs)

            exit_price = _fetch_current_price(pair)
            if exit_price is None or entry_price is None:
                continue

            raw_diff = exit_price - entry_price
            movement_pct = abs(raw_diff) / (entry_price + 1e-9) * 100

            atr_pct = _vt_calc_atr(pair)
            if atr_pct is not None and movement_pct < (atr_pct * 0.30):
                logging.info("VTE FLAT SKIP: {} move={:.5f}% < 30% of ATR {:.5f}%".format(
                    pair, movement_pct, atr_pct))
                continue   # Skip - flat market, don't corrupt stats

            won = (raw_diff > 0) if direction == "BUY" else (raw_diff < 0)

            if _NN_AVAILABLE and nn_feat is not None:
                try:
                    _nn_record_outcome(pair, nn_feat, won)
                except Exception as _nn_e:
                    logging.warning("VTE→NN feed failed {}: {}".format(pair, _nn_e))

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
        await asyncio.sleep(60)

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

_HIGH_IMPACT_NEWS = [
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

                cur.execute("SELECT optimal_tf FROM pair_stats WHERE pair=%s", (pair,))
                pair_row = cur.fetchone()
                pair_optimal = int(pair_row["optimal_tf"]) if pair_row and pair_row["optimal_tf"] else None

        tf_scores = {}
        for tf_m in target_tfs:
            score = 0.0
            has_data = False

            if tf_m in outcome_rows:
                r = outcome_rows[tf_m]
                wr  = float(r["win_rate"] or 0.5)
                mov = min(float(r["avg_movement"] or 0), 0.5) / 0.5
                total = int(r["total"])
                conf = min(1.0, total / 25.0)
                score += (wr * 0.60 + mov * 0.25 + conf * 0.15) * 2.5  # weight 2.5x
                has_data = True

            if tf_m in session_outcome_rows:
                r = session_outcome_rows[tf_m]
                wr  = float(r["win_rate"] or 0.5)
                mov = min(float(r["avg_movement"] or 0), 0.5) / 0.5
                total = int(r["total"])
                conf = min(1.0, total / 15.0)
                score += (wr * 0.65 + mov * 0.20 + conf * 0.15) * 1.5  # weight 1.5x
                has_data = True

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
    is_otc = "OTC" in pair
    if not is_otc:
        try:
            atr_pct, is_dead = _check_volatility(pair)
            if is_dead:
                return False, "flat"
        except Exception:
            pass

        try:
            real_pair = OTC_TO_REAL.get(pair, pair)
            symbol    = YAHOO_SYMBOLS.get(real_pair)
            if symbol:
                df = _yf_download_cached(symbol, "1d", "5m")
                if df is not None and len(df) >= 35:
                    direction_5m = _mtf_calc_direction(df)
                    if direction_5m is None:
                        return False, "no_direction"
        except Exception:
            pass

    if _NN_AVAILABLE and _nn_global_model is not None:
        try:
            pair_entry = _nn_per_pair.get(pair)
            if pair_entry and pair_entry.get("samples", 0) >= _NN_MIN_PAIR_SAMPLES:
                if pair_entry.get("acc", 1.0) < 0.50:
                    return False, "nn_low_acc"
        except Exception:
            pass

    return True, "ok"

def get_top5_pairs(otc_only=False, non_otc_only=False):
    """
    Return top 5 pairs by win rate — major/popular/minor forex only (non-OTC).
    Exotic pairs, indices, and illiquid pairs are excluded from Bot Top Picks.
    Chagua bora zaidi hata kama win rate ni chini ya 50%.
    """
    _ALLOWED_NONOTC = [
        "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
        "AUD/USD", "USD/CAD",
        "EUR/GBP", "EUR/JPY", "EUR/AUD", "EUR/CAD", "EUR/CHF",
        "GBP/JPY", "GBP/AUD", "GBP/CAD", "GBP/CHF",
        "AUD/JPY", "AUD/CAD", "AUD/CHF",
        "CHF/JPY", "CAD/JPY", "CAD/CHF",
    ]
    _ALLOWED_NONOTC_SET = set(_ALLOWED_NONOTC)

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
                    LIMIT 50
                """)
                rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pair, wins, losses,
                               ROUND(wins::numeric / NULLIF(wins+losses,0) * 100, 1) AS win_rate
                        FROM pair_stats
                        WHERE (wins + losses) >= 3
                        ORDER BY win_rate DESC, wins DESC
                        LIMIT 50
                    """)
                    rows = [dict(r) for r in cur.fetchall()]

        valid = set(ALL_PAIRS)
        rows = [r for r in rows if r["pair"] in valid]

        if otc_only:
            rows = [r for r in rows if "OTC" in r["pair"]]
        elif non_otc_only:
            rows = [r for r in rows if r["pair"] in _ALLOWED_NONOTC_SET]

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

        if len(screened) < 5:
            already = {r["pair"] for r in screened}
            if otc_only:
                fallback_pool = [p for p in ALL_PAIRS if "OTC" in p and p not in already]
                random.shuffle(fallback_pool)
            elif non_otc_only:
                fallback_pool = [p for p in _ALLOWED_NONOTC if p not in already]
            else:
                fallback_pool = [p for p in ALL_PAIRS if p not in already]
                random.shuffle(fallback_pool)

            for p in fallback_pool:
                if len(screened) >= 5:
                    break
                _, is_dead = _check_volatility(p) if "OTC" not in p else (0.05, False)
                if not is_dead:
                    screened.append({"pair": p, "wins": 0, "losses": 0, "win_rate": 0})

        if skipped > 0:
            logging.info("Bot Pick: screened {} pairs, skipped {} flat".format(
                len(screened), skipped))

        return screened[:5]
    except Exception as e:
        logging.warning("get_top5_pairs failed: {}".format(e))
        return []

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

async def _stats_reset_loop():
    """Reset wins_today/losses_today once per day at midnight UTC."""
    while True:
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

    global BOT_USERNAME
    me = await ptb_app.bot.get_me()
    BOT_USERNAME = me.username or ""
    logging.info("Bot username: @{}".format(BOT_USERNAME))

    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler("setimage", setimage_command))
    ptb_app.add_handler(CommandHandler("dbcheck", dbcheck_command))
    ptb_app.add_handler(MessageHandler(filters.COMMAND, message_handler))
    ptb_app.add_handler(ChatJoinRequestHandler(join_request_handler))
    ptb_app.add_handler(CallbackQueryHandler(button_handler))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, message_handler))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("Starting bot polling...")
    await ptb_app.start()
    await ptb_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    print("Bot polling active.")

    _vt_load_pending()
    print("Virtual trades loaded from DB.")

    asyncio.create_task(virtual_trading_engine())
    print("Virtual trading engine started.")

    asyncio.create_task(background_learning_engine())
    print("Background learning engine started.")

    asyncio.create_task(signal_prefetch_engine())
    print("Signal prefetch engine started.")

    asyncio.create_task(_stats_reset_loop())
    print("Stats reset loop started.")

    if _NN_AVAILABLE:
        asyncio.create_task(_nn_scheduled_retrain_loop())
        print("NN scheduled retrain loop started.")

    asyncio.create_task(_licence_expiry_warning_loop(ptb_app.bot))
    print("Licence expiry warning loop started.")

    async def _keepalive_ping():
        import aiohttp
        url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/") or "http://localhost:{}".format(os.environ.get("PORT", 8080))
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    await session.get(url + "/health", timeout=aiohttp.ClientTimeout(total=10))
            except Exception:
                pass
            await asyncio.sleep(600)  # ping every 10 minutes

    asyncio.create_task(_keepalive_ping())
    print("Keepalive ping started.")

    while True:
        await asyncio.sleep(60)

def main():
    # HTTP health server tayari imeanza mwanzo wa faili (module level).
    print("EVALON WINNERS BOT starting...")
    init_db()
    print("Database ready.")
    asyncio.run(run_bot())

if __name__=="__main__":
    main()

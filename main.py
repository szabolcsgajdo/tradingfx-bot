# SMART MONEY AI ENGINE
# TP/SL TRACKING + BREAK EVEN + STATS

import os
import requests
import threading
import time
import datetime
from statistics import mean
from flask import Flask

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv("TWELVEDATA_API_KEY")

ACCOUNT = float(os.getenv("ACCOUNT_BALANCE", 300))
RISK_PERCENT = float(os.getenv("MAX_RISK_PERCENT", 1))

last_update_id = 0
last_signal = "No signal yet."
last_signal_time = 0

active_trade = None

wins = 0
losses = 0

CACHE = {}
CACHE_TIME = {}


def tg(msg, keyboard=False):
    payload = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    if keyboard:
        payload["reply_markup"] = {
            "keyboard": [
                ["📊 STATUS", "📍 LIVE STATUS"],
                ["🎯 REQUEST SIGNAL", "📉 LAST SIGNAL"],
                ["⚠️ RISK", "📋 STATS"],
                ["🔥 SCALP MODE", "🧪 DEBUG API"]
            ],
            "resize_keyboard": True
        }

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json=payload
    )


def get_data(interval, size=120):
    now = time.time()

    if interval in CACHE:
        if now - CACHE_TIME[interval] < 10:
            return CACHE[interval]

    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": "XAU/USD",
            "interval": interval,
            "apikey": API_KEY,
            "outputsize": size
        }
    ).json()

    data = list(reversed(r.get("values", [])))

    CACHE[interval] = data
    CACHE_TIME[interval] = now

    return data


def closes(data):
    return [float(x["close"]) for x in data]


def highs(data):
    return [float(x["high"]) for x in data]


def lows(data):
    return [float(x["low"]) for x in data]


def ema(prices, period):
    if len(prices) < period:
        return prices[-1]

    multiplier = 2 / (period + 1)
    ema_value = mean(prices[:period])

    for p in prices[period:]:
        ema_value = (p - ema_value) * multiplier + ema_value

    return ema_value


def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]

        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = mean(gains) if gains else 0.0001
    avg_loss = mean(losses) if losses else 0.0001

    rs = avg_gain / avg_loss

    return round(100 - (100 / (1 + rs)), 2)


def atr(data, period=14):
    if len(data) < period + 1:
        return 1

    trs = []

    for i in range(1, period + 1):
        high = float(data[-i]["high"])
        low = float(data[-i]["low"])

        trs.append(high - low)

    return round(mean(trs), 2)


def session_name():
    hour = datetime.datetime.utcnow().hour

    if 6 <= hour <= 11:
        return "LONDON"

    if 12 <= hour <= 17:
        return "NEW YORK"

    return "ASIA"


def liquidity_sweep(data):
    hs = highs(data)
    ls = lows(data)
    cs = closes(data)

    recent_high = max(hs[-12:-2])
    recent_low = min(ls[-12:-2])

    last_high = hs[-1]
    last_low = ls[-1]
    last_close = cs[-1]

    sweep_high = False
    sweep_low = False

    if last_high > recent_high and last_close < recent_high:
        sweep_high = True

    if last_low < recent_low and last_close > recent_low:
        sweep_low = True

    return sweep_high, sweep_low


def structure_break(data):
    hs = highs(data)
    ls = lows(data)
    cs = closes(data)

    recent_high = max(hs[-15:-3])
    recent_low = min(ls[-15:-3])

    close = cs[-1]

    bos_bull = False
    bos_bear = False

    if close > recent_high:
        bos_bull = True

    if close < recent_low:
        bos_bear = True

    return bos_bull, bos_bear


def rejection_wick(data):
    candle = data[-1]

    openp = float(candle["open"])
    closep = float(candle["close"])
    highp = float(candle["high"])
    lowp = float(candle["low"])

    body = abs(closep - openp)

    upper_wick = highp - max(openp, closep)
    lower_wick = min(openp, closep) - lowp

    bearish_rejection = upper_wick > body * 2
    bullish_rejection = lower_wick > body * 2

    return bullish_rejection, bearish_rejection


def calculate_market_status():
    m1 = get_data("1min")
    m5 = get_data("5min")
    m15 = get_data("15min")

    if not m1 or not m5 or not m15:
        return None

    p1 = closes(m1)
    p5 = closes(m5)
    p15 = closes(m15)

    price = p1[-1]

    buy_score = 0
    sell_score = 0
    notes = []

    ema20_m5 = ema(p5, 20)
    ema50_m5 = ema(p5, 50)

    ema20_m15 = ema(p15, 20)
    ema50_m15 = ema(p15, 50)

    if ema20_m15 > ema50_m15:
        buy_score += 35
        notes.append("M15 bullish trend")

    elif ema20_m15 < ema50_m15:
        sell_score += 35
        notes.append("M15 bearish trend")

    if ema20_m5 > ema50_m5:
        buy_score += 25

    elif ema20_m5 < ema50_m5:
        sell_score += 25

    rsi5 = rsi(p5)

    if rsi5 > 55:
        buy_score += 15

    if rsi5 < 45:
        sell_score += 15

    if p1[-1] > p1[-3]:
        buy_score += 10

    elif p1[-1] < p1[-3]:
        sell_score += 10

    sweep_high, sweep_low = liquidity_sweep(m5)

    if sweep_high:
        sell_score += 20
        notes.append("Liquidity sweep above highs")

    if sweep_low:
        buy_score += 20
        notes.append("Liquidity sweep below lows")

    bos_bull, bos_bear = structure_break(m5)

    if bos_bull:
        buy_score += 20
        notes.append("Bullish BOS")

    if bos_bear:
        sell_score += 20
        notes.append("Bearish BOS")

    bullish_rejection, bearish_rejection = rejection_wick(m5)

    if bullish_rejection:
        buy_score += 15
        notes.append("Bullish rejection wick")

    if bearish_rejection:
        sell_score += 15
        notes.append("Bearish rejection wick")

    atr5 = atr(m5)

    no_trade = False

    if atr5 < 1.5:
        no_trade = True
        notes.append("Low volatility")

    session = session_name()

    if session in ["LONDON", "NEW YORK"]:
        buy_score += 5
        sell_score += 5

    buy_percent = min(100, round((buy_score / 120) * 100))
    sell_percent = min(100, round((sell_score / 120) * 100))

    if no_trade:
        bias = "NO TRADE"

    elif buy_percent > sell_percent:
        bias = "BUY PRESSURE"

    elif sell_percent > buy_percent:
        bias = "SELL PRESSURE"

    else:
        bias = "NEUTRAL"

    return {
        "price": price,
        "buy_percent": buy_percent,
        "sell_percent": sell_percent,
        "bias": bias,
        "session": session,
        "atr": atr5,
        "rsi": rsi5,
        "notes": notes,
        "no_trade": no_trade
    }


def build_signal():
    global last_signal
    global active_trade

    status = calculate_market_status()

    if not status:
        return "⚠️ Market data error."

    price = status["price"]

    buy = status["buy_percent"]
    sell = status["sell_percent"]

    direction = "WAIT"

    if not status["no_trade"]:
        if buy >= 65 and buy > sell:
            direction = "BUY"

        elif sell >= 65 and sell > buy:
            direction = "SELL"

    atr_value = status["atr"]

    if direction == "BUY":
        sl = round(price - (atr_value * 1.5), 2)
        tp1 = round(price + (atr_value * 1.5), 2)
        tp2 = round(price + (atr_value * 3), 2)
        tp3 = round(price + (atr_value * 4.5), 2)

    elif direction == "SELL":
        sl = round(price + (atr_value * 1.5), 2)
        tp1 = round(price - (atr_value * 1.5), 2)
        tp2 = round(price - (atr_value * 3), 2)
        tp3 = round(price - (atr_value * 4.5), 2)

    else:
        sl = "-"
        tp1 = "-"
        tp2 = "-"
        tp3 = "-"

    if direction in ["BUY", "SELL"]:
        active_trade = {
            "direction": direction,
            "entry": round(price, 2),
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "closed": False,
            "break_even_set": False,
            "trailing_active": False
        }

    note_text = "\n- ".join(status["notes"]) if status["notes"] else "No special warning."

    msg = f"""
🎯 SMART MONEY AI SIGNAL

Price:
{round(price, 2)}

Direction:
{direction}

BUY chance:
{buy}%

SELL chance:
{sell}%

Bias:
{status["bias"]}

SL:
{sl}

TP1:
{tp1}

TP2:
{tp2}

TP3:
{tp3}

Session:
{status["session"]}

ATR:
{status["atr"]}

RSI:
{status["rsi"]}

Notes:
- {note_text}
"""

    last_signal = msg

    return msg


def check_active_trade():
    global active_trade
    global wins
    global losses

    if not active_trade:
        return

    if active_trade.get("closed"):
        return

    data = get_data("1min", size=5)

    if not data:
        return

    price = float(data[-1]["close"])
    direction = active_trade["direction"]

    if direction == "BUY":
        if price <= active_trade["sl"]:
            losses += 1

            tg(f"""
🛑 SL HIT

BUY TRADE CLOSED

Entry:
{active_trade["entry"]}

SL:
{active_trade["sl"]}

Current:
{round(price, 2)}
""")

            active_trade["closed"] = True
            return

        if price >= active_trade["tp1"] and not active_trade["tp1_hit"]:
            active_trade["tp1_hit"] = True

            active_trade["sl"] = active_trade["entry"]
            active_trade["break_even_set"] = True
            active_trade["trailing_active"] = True

            tg(f"""
✅ TP1 HIT

BUY TRADE

TP1:
{active_trade["tp1"]}

Current:
{round(price, 2)}

🟢 BREAK EVEN SET

New SL:
{active_trade["sl"]}
""")

        if price >= active_trade["tp2"] and not active_trade["tp2_hit"]:
            active_trade["tp2_hit"] = True

            tg(f"""
✅ TP2 HIT

BUY TRADE

TP2:
{active_trade["tp2"]}

Current:
{round(price, 2)}
""")

        if price >= active_trade["tp3"] and not active_trade["tp3_hit"]:
            wins += 1

            tg(f"""
🏆 TP3 HIT

BUY TRADE COMPLETED

TP3:
{active_trade["tp3"]}

Current:
{round(price, 2)}
""")

            active_trade["tp3_hit"] = True
            active_trade["closed"] = True

    elif direction == "SELL":
        if price >= active_trade["sl"]:
            losses += 1

            tg(f"""
🛑 SL HIT

SELL TRADE CLOSED

Entry:
{active_trade["entry"]}

SL:
{active_trade["sl"]}

Current:
{round(price, 2)}
""")

            active_trade["closed"] = True
            return

        if price <= active_trade["tp1"] and not active_trade["tp1_hit"]:
            active_trade["tp1_hit"] = True

            active_trade["sl"] = active_trade["entry"]
            active_trade["break_even_set"] = True
            active_trade["trailing_active"] = True

            tg(f"""
✅ TP1 HIT

SELL TRADE

TP1:
{active_trade["tp1"]}

Current:
{round(price, 2)}

🟢 BREAK EVEN SET

New SL:
{active_trade["sl"]}
""")

        if price <= active_trade["tp2"] and not active_trade["tp2_hit"]:
            active_trade["tp2_hit"] = True

            tg(f"""
✅ TP2 HIT

SELL TRADE

TP2:
{active_trade["tp2"]}

Current:
{round(price, 2)}
""")

        if price <= active_trade["tp3"] and not active_trade["tp3_hit"]:
            wins += 1

            tg(f"""
🏆 TP3 HIT

SELL TRADE COMPLETED

TP3:
{active_trade["tp3"]}

Current:
{round(price, 2)}
""")

            active_trade["tp3_hit"] = True
            active_trade["closed"] = True


def live_status():
    tg(build_signal())


def debug_api():
    try:
        results = {}

        for interval in ["1min", "5min", "15min"]:
            r = requests.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol": "XAU/USD",
                    "interval": interval,
                    "apikey": API_KEY,
                    "outputsize": 5
                }
            ).json()

            results[interval] = str(r)[:1000]

        tg(f"""
🧪 DEBUG API RESPONSE

1MIN:
{results["1min"]}

5MIN:
{results["5min"]}

15MIN:
{results["15min"]}
""")

    except Exception as e:
        tg(f"DEBUG ERROR: {e}")


def auto_loop():
    global last_signal_time

    while True:
        try:
            if active_trade and not active_trade.get("closed"):
                check_active_trade()
                time.sleep(15)
                continue

            msg = build_signal()

            if "Direction:\nBUY" in msg or "Direction:\nSELL" in msg:
                now = time.time()

                if now - last_signal_time > 900:
                    tg(msg)
                    last_signal_time = now

            time.sleep(60)

        except Exception as e:
            print("Auto loop error:", e)
            time.sleep(15)


def telegram_polling():
    global last_update_id
    global wins
    global losses

    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={
                    "offset": last_update_id + 1,
                    "timeout": 10
                }
            ).json()

            for update in r.get("result", []):
                last_update_id = update["update_id"]
                text = update.get("message", {}).get("text", "")

                if text == "/start":
                    tg("🤖 SMART MONEY AI ONLINE", keyboard=True)

                elif text == "📊 STATUS":
                    tg("✅ SMART MONEY ENGINE ONLINE")

                elif text == "📍 LIVE STATUS":
                    live_status()

                elif text == "🎯 REQUEST SIGNAL":
                    tg(build_signal())

                elif text == "📉 LAST SIGNAL":
                    tg(last_signal)

                elif text == "⚠️ RISK":
                    tg(f"""
⚠️ RISK

Account:
{ACCOUNT}€

Risk:
{RISK_PERCENT}%

Max risk:
{round(ACCOUNT * (RISK_PERCENT / 100), 2)}€
""")

                elif text == "📋 STATS":
                    total = wins + losses
                    winrate = 0

                    if total > 0:
                        winrate = round((wins / total) * 100, 1)

                    tg(f"""
📋 BOT STATS

Wins:
{wins}

Losses:
{losses}

Total trades:
{total}

Winrate:
{winrate}%
""")

                elif text == "🔥 SCALP MODE":
                    tg("""
🔥 SCALP MODE ACTIVE

15 sec TP tracking enabled.
Break even after TP1 enabled.
""")

                elif text == "🧪 DEBUG API":
                    debug_api()

        except Exception as e:
            print("Polling error:", e)

        time.sleep(2)


@app.route("/")
def home():
    return "SMART MONEY AI ONLINE"


@app.route("/test")
def test():
    tg("✅ SMART MONEY AI ONLINE", keyboard=True)
    return "ok"


if __name__ == "__main__":
    threading.Thread(
        target=auto_loop,
        daemon=True
    ).start()

    threading.Thread(
        target=telegram_polling,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )

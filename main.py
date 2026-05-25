import os
import requests
import datetime
import threading
import time
from flask import Flask

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv("TWELVEDATA_API_KEY")

ACCOUNT = float(os.getenv("ACCOUNT_BALANCE", 300))
RISK_PERCENT = float(os.getenv("MAX_RISK_PERCENT", 1))
MAX_SIGNALS_PER_DAY = 3

signals_today = 0
last_signal_date = None
last_signal = "No signal yet."
last_update_id = 0
active_trade = None
last_crash_alert_time = 0


def tg(msg, keyboard=False):
    payload = {"chat_id": CHAT_ID, "text": msg}

    if keyboard:
        payload["reply_markup"] = {
            "keyboard": [
                ["📊 STATUS", "📍 LIVE STATUS"],
                ["📉 LAST SIGNAL", "⚠️ RISK"],
                ["📋 STATS", "🔥 SCALP MODE"]
            ],
            "resize_keyboard": True
        }

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json=payload
    )


def get_data(interval):
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": "XAUUSD",
            "interval": interval,
            "apikey": API_KEY,
            "outputsize": 80
        }
    ).json()

    return list(reversed(r.get("values", [])))


def close_prices(data):
    return [float(x["close"]) for x in data]


def trend(prices):
    if prices[-1] > prices[-5] > prices[-12]:
        return "bullish"
    if prices[-1] < prices[-5] < prices[-12]:
        return "bearish"
    return "neutral"


def candle_body(candle):
    return abs(float(candle["close"]) - float(candle["open"]))


def candle_direction(candle):
    if float(candle["close"]) > float(candle["open"]):
        return "bullish"
    if float(candle["close"]) < float(candle["open"]):
        return "bearish"
    return "neutral"


def detect_crash():
    global last_crash_alert_time

    now = time.time()

    if now - last_crash_alert_time < 600:
        return

    m1 = get_data("1min")
    m5 = get_data("5min")

    if not m1 or not m5 or len(m1) < 20 or len(m5) < 10:
        return

    last_price = float(m1[-1]["close"])
    last_5_m1 = m1[-5:]

    bearish_count = sum(
        1 for c in last_5_m1 if candle_direction(c) == "bearish"
    )

    bodies = [candle_body(c) for c in m1[-20:]]
    avg_body = sum(bodies[:-1]) / max(len(bodies[:-1]), 1)
    last_body = bodies[-1]

    recent_low_m5 = min(float(c["low"]) for c in m5[-10:-1])
    current_m5_close = float(m5[-1]["close"])

    crash_score = 0
    reasons = []

    if bearish_count >= 4:
        crash_score += 25
        reasons.append("4/5 recent M1 candles bearish")

    if avg_body > 0 and last_body > avg_body * 2:
        crash_score += 25
        reasons.append("large bearish M1 candle body")

    if current_m5_close < recent_low_m5:
        crash_score += 30
        reasons.append("M5 structure break / recent low broken")

    drop_5min = float(m1[-5]["close"]) - last_price

    if drop_5min >= 3:
        crash_score += 25
        reasons.append(f"fast drop: {round(drop_5min, 2)} points in ~5 minutes")

    if crash_score >= 70:
        last_crash_alert_time = now

        tg(f"""
🚨 STRONG SELL MOMENTUM DETECTED

XAUUSD current price:
{round(last_price, 2)}

Crash probability:
{min(crash_score, 95)}%

Reason:
- {chr(10).join(reasons)}

Action:
SELL continuation possible.

Risk:
High volatility — use smaller lot and strict SL.
""")


def calculate_market_status():
    m1 = get_data("1min")
    m5 = get_data("5min")
    m15 = get_data("15min")

    if not m1 or not m5 or not m15:
        return None

    p1 = close_prices(m1)
    p5 = close_prices(m5)
    p15 = close_prices(m15)

    price = p1[-1]
    t1 = trend(p1)
    t5 = trend(p5)
    t15 = trend(p15)

    buy_score = 0
    sell_score = 0

    if t15 == "bullish":
        buy_score += 30
    if t5 == "bullish":
        buy_score += 25
    if t1 == "bullish":
        buy_score += 15

    if t15 == "bearish":
        sell_score += 30
    if t5 == "bearish":
        sell_score += 25
    if t1 == "bearish":
        sell_score += 15

    total_score = buy_score + sell_score

    if total_score == 0:
        buy_percent = 50
        sell_percent = 50
    else:
        buy_percent = round((buy_score / total_score) * 100)
        sell_percent = 100 - buy_percent

    if buy_percent > sell_percent:
        bias = "BUY PRESSURE"
        buy_text = "Better probability, but wait for pullback / confirmation."
        sell_text = "Risky, currently weaker setup."
    elif sell_percent > buy_percent:
        bias = "SELL PRESSURE"
        buy_text = "Risky, currently weaker setup."
        sell_text = "Better probability, but wait for rejection / confirmation."
    else:
        bias = "NEUTRAL"
        buy_text = "Wait. No clear edge."
        sell_text = "Wait. No clear edge."

    return {
        "price": price,
        "t1": t1,
        "t5": t5,
        "t15": t15,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "buy_percent": buy_percent,
        "sell_percent": sell_percent,
        "bias": bias,
        "buy_text": buy_text,
        "sell_text": sell_text
    }


def analyze(send_wait=True):
    global signals_today, last_signal_date, last_signal, active_trade

    today = datetime.date.today()

    if last_signal_date != today:
        signals_today = 0
        last_signal_date = today

    status = calculate_market_status()

    if not status:
        if send_wait:
            tg("⚠️ Data error. No market data received.")
        return

    price = status["price"]
    buy_percent = status["buy_percent"]
    sell_percent = status["sell_percent"]
    t1 = status["t1"]
    t5 = status["t5"]
    t15 = status["t15"]

    direction = "WAIT"
    confidence = max(buy_percent, sell_percent)

    if buy_percent >= 60:
        direction = "BUY"
    elif sell_percent >= 60:
        direction = "SELL"

    risk_amount = ACCOUNT * (RISK_PERCENT / 100)

    if direction == "WAIT":
        msg = f"""
⏸ XAUUSD WAIT

Price: {round(price, 2)}

BUY chance: {buy_percent}%
SELL chance: {sell_percent}%

M1: {t1}
M5: {t5}
M15: {t15}

Reason: No high probability setup.
"""
        last_signal = msg
        if send_wait:
            tg(msg)
        return

    if active_trade and not active_trade.get("closed"):
        return

    if signals_today >= MAX_SIGNALS_PER_DAY:
        return

    if direction == "BUY":
        sl = round(price - 3.5, 2)
        tp1 = round(price + 3, 2)
        tp2 = round(price + 6, 2)
        tp3 = round(price + 9, 2)
    else:
        sl = round(price + 3.5, 2)
        tp1 = round(price - 3, 2)
        tp2 = round(price - 6, 2)
        tp3 = round(price - 9, 2)

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
        "closed": False
    }

    msg = f"""
📊 XAUUSD {direction} SIGNAL

Entry: {round(price, 2)}
SL: {sl}

TP1: {tp1}
TP2: {tp2}
TP3: {tp3}

Confidence: {confidence}%
BUY chance: {buy_percent}%
SELL chance: {sell_percent}%

Lot: 0.01
Risk: {round(risk_amount, 2)}€

M1: {t1}
M5: {t5}
M15: {t15}

Signals today: {signals_today}/{MAX_SIGNALS_PER_DAY}
"""

    last_signal = msg
    tg(msg)
    signals_today += 1


def check_trade_status():
    global active_trade

    if not active_trade or active_trade.get("closed"):
        return

    data = get_data("1min")

    if not data:
        return

    price = float(data[-1]["close"])
    direction = active_trade["direction"]

    if direction == "BUY":
        if price <= active_trade["sl"]:
            tg(f"""
🛑 SL HIT

XAUUSD BUY stopped out.

Entry: {active_trade["entry"]}
SL: {active_trade["sl"]}
Current price: {round(price, 2)}
""")
            active_trade["closed"] = True
            return

        if price >= active_trade["tp1"] and not active_trade["tp1_hit"]:
            tg(f"""
✅ TP1 HIT

XAUUSD BUY

TP1: {active_trade["tp1"]}
Current price: {round(price, 2)}
""")
            active_trade["tp1_hit"] = True

        if price >= active_trade["tp2"] and not active_trade["tp2_hit"]:
            tg(f"""
✅ TP2 HIT

XAUUSD BUY

TP2: {active_trade["tp2"]}
Current price: {round(price, 2)}
""")
            active_trade["tp2_hit"] = True

        if price >= active_trade["tp3"] and not active_trade["tp3_hit"]:
            tg(f"""
🏆 TP3 HIT — TRADE COMPLETED

XAUUSD BUY successful.

Entry: {active_trade["entry"]}
TP3: {active_trade["tp3"]}
Current price: {round(price, 2)}
""")
            active_trade["tp3_hit"] = True
            active_trade["closed"] = True

    if direction == "SELL":
        if price >= active_trade["sl"]:
            tg(f"""
🛑 SL HIT

XAUUSD SELL stopped out.

Entry: {active_trade["entry"]}
SL: {active_trade["sl"]}
Current price: {round(price, 2)}
""")
            active_trade["closed"] = True
            return

        if price <= active_trade["tp1"] and not active_trade["tp1_hit"]:
            tg(f"""
✅ TP1 HIT

XAUUSD SELL

TP1: {active_trade["tp1"]}
Current price: {round(price, 2)}
""")
            active_trade["tp1_hit"] = True

        if price <= active_trade["tp2"] and not active_trade["tp2_hit"]:
            tg(f"""
✅ TP2 HIT

XAUUSD SELL

TP2: {active_trade["tp2"]}
Current price: {round(price, 2)}
""")
            active_trade["tp2_hit"] = True

        if price <= active_trade["tp3"] and not active_trade["tp3_hit"]:
            tg(f"""
🏆 TP3 HIT — TRADE COMPLETED

XAUUSD SELL successful.

Entry: {active_trade["entry"]}
TP3: {active_trade["tp3"]}
Current price: {round(price, 2)}
""")
            active_trade["tp3_hit"] = True
            active_trade["closed"] = True


def live_status():
    status = calculate_market_status()

    if not status:
        tg("⚠️ Data error. No market data received.")
        return

    trade_text = "No active trade."

    if active_trade and not active_trade.get("closed"):
        trade_text = f"""
Active trade:
{active_trade["direction"]}

Entry: {active_trade["entry"]}
SL: {active_trade["sl"]}
TP1: {active_trade["tp1"]}
TP2: {active_trade["tp2"]}
TP3: {active_trade["tp3"]}
"""

    tg(f"""
📍 LIVE MARKET STATUS

XAUUSD current price:
{round(status["price"], 2)}

BUY chance:
{status["buy_percent"]}%

SELL chance:
{status["sell_percent"]}%

Bias:
{status["bias"]}

If BUY:
{status["buy_text"]}

If SELL:
{status["sell_text"]}

M1:
{status["t1"]}

M5:
{status["t5"]}

M15:
{status["t15"]}

Buy score:
{status["buy_score"]}

Sell score:
{status["sell_score"]}

{trade_text}
""")


def market_loop():
    while True:
        detect_crash()
        analyze(send_wait=False)
        check_trade_status()
        time.sleep(60)


def telegram_polling():
    global last_update_id

    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 10}
            ).json()

            for update in r.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                text = message.get("text", "")

                if text == "/start":
                    tg("🤖 TRADING FX AI BOT ONLINE\n\nVálassz funkciót:", keyboard=True)

                elif text == "📊 STATUS":
                    tg(f"""
📊 BOT STATUS

Bot: ONLINE ✅
Signals today: {signals_today}/{MAX_SIGNALS_PER_DAY}

Account: {ACCOUNT}€
Risk: {RISK_PERCENT}%
""")

                elif text == "📍 LIVE STATUS":
                    live_status()

                elif text == "📉 LAST SIGNAL":
                    tg(last_signal)

                elif text == "⚠️ RISK":
                    risk_amount = ACCOUNT * (RISK_PERCENT / 100)
                    tg(f"""
⚠️ RISK MANAGEMENT

Account: {ACCOUNT}€
Risk per trade: {RISK_PERCENT}%

Max risk:
{round(risk_amount, 2)}€
""")

                elif text == "📋 STATS":
                    tg(f"""
📋 DAILY STATS

Signals today: {signals_today}
Max daily: {MAX_SIGNALS_PER_DAY}
""")

                elif text == "🔥 SCALP MODE":
                    tg("""
🔥 SCALP MODE

M1 + M5 fast signal mode active.
""")

        except Exception as e:
            print("Polling error:", e)

        time.sleep(2)


@app.route("/")
def home():
    return "TRADING FX BOT ONLINE"


@app.route("/test")
def test():
    tg("✅ TRADING FX BOT ONLINE", keyboard=True)
    return "Test sent."


@app.route("/manual")
def manual():
    analyze(send_wait=True)
    return "Manual analysis started."


if __name__ == "__main__":
    threading.Thread(target=market_loop, daemon=True).start()
    threading.Thread(target=telegram_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

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

signals_today = 0
last_update_id = 0
last_signal = "No signal yet."
last_crash_alert_time = 0


# =========================================
# TELEGRAM MESSAGE
# =========================================

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


# =========================================
# MARKET DATA
# =========================================

def get_data(interval):

    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": "XAU/USD",
            "interval": interval,
            "apikey": API_KEY,
            "outputsize": 80
        }
    ).json()

    return list(reversed(r.get("values", [])))


def close_prices(data):

    return [float(x["close"]) for x in data]


# =========================================
# TREND
# =========================================

def trend(prices):

    if len(prices) < 15:
        return "neutral"

    if prices[-1] > prices[-5] > prices[-12]:
        return "bullish"

    if prices[-1] < prices[-5] < prices[-12]:
        return "bearish"

    return "neutral"


# =========================================
# DEBUG API
# =========================================

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

        tg(f"⚠️ DEBUG ERROR: {e}")


# =========================================
# MARKET STATUS
# =========================================

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

    # M15
    if t15 == "bullish":
        buy_score += 30

    elif t15 == "bearish":
        sell_score += 30

    # M5
    if t5 == "bullish":
        buy_score += 25

    elif t5 == "bearish":
        sell_score += 25

    # M1
    if t1 == "bullish":
        buy_score += 15

    elif t1 == "bearish":
        sell_score += 15

    # REALISTIC PERCENTAGES
    buy_percent = round((buy_score / 70) * 100)
    sell_percent = round((sell_score / 70) * 100)

    buy_percent = min(buy_percent, 100)
    sell_percent = min(sell_percent, 100)

    # BIAS
    if buy_percent > sell_percent:

        bias = "BUY PRESSURE"

    elif sell_percent > buy_percent:

        bias = "SELL PRESSURE"

    else:

        bias = "NEUTRAL"

    return {
        "price": price,
        "t1": t1,
        "t5": t5,
        "t15": t15,
        "buy_percent": buy_percent,
        "sell_percent": sell_percent,
        "bias": bias,
        "buy_score": buy_score,
        "sell_score": sell_score
    }


# =========================================
# LIVE STATUS
# =========================================

def live_status():

    status = calculate_market_status()

    if not status:

        tg("⚠️ Data error. No market data received.")

        return

    tg(f"""
📍 LIVE MARKET STATUS

XAUUSD:
{round(status["price"], 2)}

BUY chance:
{status["buy_percent"]}%

SELL chance:
{status["sell_percent"]}%

Bias:
{status["bias"]}

M1:
{status["t1"]}

M5:
{status["t5"]}

M15:
{status["t15"]}

BUY SCORE:
{status["buy_score"]}

SELL SCORE:
{status["sell_score"]}
""")


# =========================================
# REQUEST SIGNAL
# =========================================

def force_signal_request():

    global last_signal

    status = calculate_market_status()

    if not status:

        tg("⚠️ Data error. No market data received.")

        return

    price = status["price"]

    buy_percent = status["buy_percent"]
    sell_percent = status["sell_percent"]

    # DIRECTION
    if buy_percent >= 60:

        direction = "BUY"

        sl = round(price - 3.5, 2)

        tp1 = round(price + 3, 2)
        tp2 = round(price + 6, 2)
        tp3 = round(price + 9, 2)

    elif sell_percent >= 60:

        direction = "SELL"

        sl = round(price + 3.5, 2)

        tp1 = round(price - 3, 2)
        tp2 = round(price - 6, 2)
        tp3 = round(price - 9, 2)

    else:

        direction = "WAIT"

        sl = "-"
        tp1 = "-"
        tp2 = "-"
        tp3 = "-"

    confidence = max(buy_percent, sell_percent)

    msg = f"""
🎯 REQUESTED SIGNAL

Current price:
{round(price, 2)}

Direction:
{direction}

BUY chance:
{buy_percent}%

SELL chance:
{sell_percent}%

SL:
{sl}

TP1:
{tp1}

TP2:
{tp2}

TP3:
{tp3}

Confidence:
{confidence}%

M1:
{status["t1"]}

M5:
{status["t5"]}

M15:
{status["t15"]}
"""

    last_signal = msg

    tg(msg)


# =========================================
# CRASH DETECTOR
# =========================================

def crash_detector():

    global last_crash_alert_time

    now = time.time()

    if now - last_crash_alert_time < 600:
        return

    m1 = get_data("1min")

    if not m1:
        return

    p1 = close_prices(m1)

    current_price = p1[-1]

    last5 = p1[-5:]

    bearish = 0

    for i in range(1, len(last5)):

        if last5[i] < last5[i - 1]:
            bearish += 1

    move_size = max(last5) - min(last5)

    score = 0

    if bearish >= 4:
        score += 40

    if move_size >= 8:
        score += 40

    if move_size >= 12:
        score += 20

    if score >= 70:

        tg(f"""
🚨 STRONG SELL MOMENTUM DETECTED

Price:
{round(current_price, 2)}

Crash probability:
{score}%

High volatility detected.
SELL continuation possible.
""")

        last_crash_alert_time = now


# =========================================
# AUTO SIGNAL LOOP
# =========================================

def auto_signal_loop():

    global last_signal

    while True:

        try:

            status = calculate_market_status()

            if status:

                buy = status["buy_percent"]
                sell = status["sell_percent"]

                if buy >= 70:

                    msg = f"""
📈 AUTO BUY SIGNAL

Price:
{round(status["price"], 2)}

BUY chance:
{buy}%

M1:
{status["t1"]}

M5:
{status["t5"]}

M15:
{status["t15"]}
"""

                    last_signal = msg

                    tg(msg)

                    time.sleep(900)

                elif sell >= 70:

                    msg = f"""
📉 AUTO SELL SIGNAL

Price:
{round(status["price"], 2)}

SELL chance:
{sell}%

M1:
{status["t1"]}

M5:
{status["t5"]}

M15:
{status["t15"]}
"""

                    last_signal = msg

                    tg(msg)

                    time.sleep(900)

            crash_detector()

        except Exception as e:

            print("Auto signal error:", e)

        time.sleep(60)


# =========================================
# TELEGRAM POLLING
# =========================================

def telegram_polling():

    global last_update_id

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

                message = update.get("message", {})

                text = message.get("text", "")

                if text == "/start":

                    tg(
                        "🤖 TRADING FX BOT ONLINE",
                        keyboard=True
                    )

                elif text == "📊 STATUS":

                    tg(f"""
📊 BOT STATUS

ONLINE ✅

Account:
{ACCOUNT}€

Risk:
{RISK_PERCENT}%
""")

                elif text == "📍 LIVE STATUS":

                    live_status()

                elif text == "🎯 REQUEST SIGNAL":

                    force_signal_request()

                elif text == "📉 LAST SIGNAL":

                    tg(last_signal)

                elif text == "⚠️ RISK":

                    tg(f"""
⚠️ RISK

Account:
{ACCOUNT}€

Risk:
{RISK_PERCENT}%
""")

                elif text == "📋 STATS":

                    tg(f"""
📋 STATS

Signals today:
{signals_today}
""")

                elif text == "🔥 SCALP MODE":

                    tg("""
🔥 SCALP MODE ACTIVE

Fast M1 + M5 signals enabled.
""")

                elif text == "🧪 DEBUG API":

                    debug_api()

        except Exception as e:

            print("Polling error:", e)

        time.sleep(2)


# =========================================
# FLASK
# =========================================

@app.route("/")
def home():

    return "TRADING FX BOT ONLINE"


@app.route("/test")
def test():

    tg(
        "✅ BOT ONLINE",
        keyboard=True
    )

    return "Test sent."


# =========================================
# START
# =========================================

if __name__ == "__main__":

    threading.Thread(
        target=auto_signal_loop,
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

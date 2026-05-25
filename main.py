import os
import requests
import datetime
import threading
import time
from flask import Flask
from statistics import mean

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv("TWELVEDATA_API_KEY")

ACCOUNT = float(os.getenv("ACCOUNT_BALANCE", 300))
RISK_PERCENT = float(os.getenv("MAX_RISK_PERCENT", 1))

last_update_id = 0
last_signal = "No signal yet."
last_crash_alert_time = 0


# =========================================
# TELEGRAM
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
            "outputsize": 120
        }
    ).json()

    return list(reversed(r.get("values", [])))


def close_prices(data):

    return [float(x["close"]) for x in data]


# =========================================
# EMA
# =========================================

def ema(prices, period):

    if len(prices) < period:
        return None

    multiplier = 2 / (period + 1)

    ema_value = mean(prices[:period])

    for price in prices[period:]:

        ema_value = (price - ema_value) * multiplier + ema_value

    return ema_value


# =========================================
# RSI
# =========================================

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


# =========================================
# ATR
# =========================================

def atr(data, period=14):

    if len(data) < period + 1:
        return 0

    trs = []

    for i in range(1, period + 1):

        high = float(data[-i]["high"])
        low = float(data[-i]["low"])

        trs.append(high - low)

    return round(mean(trs), 2)


# =========================================
# SESSION FILTER
# =========================================

def session_name():

    hour = datetime.datetime.utcnow().hour

    if 6 <= hour <= 11:
        return "LONDON"

    if 12 <= hour <= 17:
        return "NEW YORK"

    return "ASIA"


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

    # EMA
    ema20_m5 = ema(p5, 20)
    ema50_m5 = ema(p5, 50)

    ema20_m15 = ema(p15, 20)
    ema50_m15 = ema(p15, 50)

    # RSI
    rsi_m5 = rsi(p5)
    rsi_m15 = rsi(p15)

    # ATR
    atr_m5 = atr(m5)

    # SESSION
    session = session_name()

    buy_score = 0
    sell_score = 0

    # =========================
    # MAIN TREND M15
    # =========================

    if ema20_m15 and ema50_m15:

        if ema20_m15 > ema50_m15:
            buy_score += 35

        elif ema20_m15 < ema50_m15:
            sell_score += 35

    # =========================
    # M5 CONFIRMATION
    # =========================

    if ema20_m5 and ema50_m5:

        if ema20_m5 > ema50_m5:
            buy_score += 25

        elif ema20_m5 < ema50_m5:
            sell_score += 25

    # =========================
    # RSI FILTER
    # =========================

    if rsi_m5 > 55:
        buy_score += 15

    if rsi_m5 < 45:
        sell_score += 15

    if rsi_m15 > 55:
        buy_score += 10

    if rsi_m15 < 45:
        sell_score += 10

    # =========================
    # ENTRY TIMING M1
    # =========================

    if p1[-1] > p1[-3]:
        buy_score += 10

    elif p1[-1] < p1[-3]:
        sell_score += 10

    # =========================
    # NO TRADE ZONE
    # =========================

    no_trade = False

    if atr_m5 < 1.5:
        no_trade = True

    # =========================
    # SESSION BOOST
    # =========================

    if session in ["LONDON", "NEW YORK"]:

        buy_score += 5
        sell_score += 5

    # =========================
    # PERCENTAGES
    # =========================

    buy_percent = round((buy_score / 100) * 100)
    sell_percent = round((sell_score / 100) * 100)

    buy_percent = min(buy_percent, 100)
    sell_percent = min(sell_percent, 100)

    # =========================
    # BIAS
    # =========================

    if no_trade:

        bias = "NO TRADE ZONE"

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
        "rsi_m5": rsi_m5,
        "rsi_m15": rsi_m15,
        "atr_m5": atr_m5,
        "ema20_m5": ema20_m5,
        "ema50_m5": ema50_m5,
        "ema20_m15": ema20_m15,
        "ema50_m15": ema50_m15,
        "no_trade": no_trade
    }


# =========================================
# REQUEST SIGNAL
# =========================================

def force_signal_request():

    global last_signal

    status = calculate_market_status()

    if not status:

        tg("⚠️ Market data error.")

        return

    price = status["price"]

    buy = status["buy_percent"]
    sell = status["sell_percent"]

    if status["no_trade"]:

        direction = "WAIT"

    elif buy >= 65:

        direction = "BUY"

    elif sell >= 65:

        direction = "SELL"

    else:

        direction = "WAIT"

    if direction == "BUY":

        sl = round(price - 4, 2)

        tp1 = round(price + 4, 2)
        tp2 = round(price + 8, 2)
        tp3 = round(price + 12, 2)

    elif direction == "SELL":

        sl = round(price + 4, 2)

        tp1 = round(price - 4, 2)
        tp2 = round(price - 8, 2)
        tp3 = round(price - 12, 2)

    else:

        sl = "-"
        tp1 = "-"
        tp2 = "-"
        tp3 = "-"

    msg = f"""
🎯 AI SIGNAL

Price:
{round(price, 2)}

Direction:
{direction}

BUY chance:
{buy}%

SELL chance:
{sell}%

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

RSI M5:
{status["rsi_m5"]}

RSI M15:
{status["rsi_m15"]}

ATR:
{status["atr_m5"]}

Bias:
{status["bias"]}
"""

    last_signal = msg

    tg(msg)


# =========================================
# LIVE STATUS
# =========================================

def live_status():

    status = calculate_market_status()

    if not status:

        tg("⚠️ Market data error.")

        return

    tg(f"""
📍 LIVE MARKET STATUS

Price:
{round(status["price"], 2)}

BUY:
{status["buy_percent"]}%

SELL:
{status["sell_percent"]}%

Bias:
{status["bias"]}

Session:
{status["session"]}

RSI M5:
{status["rsi_m5"]}

RSI M15:
{status["rsi_m15"]}

ATR:
{status["atr_m5"]}

EMA20 M5:
{round(status["ema20_m5"], 2)}

EMA50 M5:
{round(status["ema50_m5"], 2)}

EMA20 M15:
{round(status["ema20_m15"], 2)}

EMA50 M15:
{round(status["ema50_m15"], 2)}
""")


# =========================================
# AUTO SIGNAL LOOP
# =========================================

def auto_signal_loop():

    while True:

        try:

            status = calculate_market_status()

            if status and not status["no_trade"]:

                if status["buy_percent"] >= 75:

                    tg(f"""
📈 AUTO BUY SIGNAL

BUY chance:
{status["buy_percent"]}%

Price:
{round(status["price"], 2)}
""")

                    time.sleep(900)

                elif status["sell_percent"] >= 75:

                    tg(f"""
📉 AUTO SELL SIGNAL

SELL chance:
{status["sell_percent"]}%

Price:
{round(status["price"], 2)}
""")

                    time.sleep(900)

        except Exception as e:

            print("Loop error:", e)

        time.sleep(60)


# =========================================
# DEBUG API
# =========================================

def debug_api():

    try:

        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": "XAU/USD",
                "interval": "5min",
                "apikey": API_KEY,
                "outputsize": 5
            }
        ).json()

        tg(str(r)[:3500])

    except Exception as e:

        tg(f"DEBUG ERROR: {e}")


# =========================================
# TELEGRAM
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
                        "🤖 AI TRADING BOT ONLINE",
                        keyboard=True
                    )

                elif text == "📊 STATUS":

                    tg("✅ BOT ONLINE")

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

                    tg("""
📋 STATS

AI ENGINE ACTIVE
EMA + RSI + ATR ENABLED
""")

                elif text == "🔥 SCALP MODE":

                    tg("""
🔥 SCALP MODE

M1 timing enabled.
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

    return "AI BOT ONLINE"


@app.route("/test")
def test():

    tg(
        "✅ AI BOT ONLINE",
        keyboard=True
    )

    return "ok"


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

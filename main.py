import os
import requests
import datetime
import threading
import time
from flask import Flask, request

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


def tg(msg, keyboard=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    if keyboard:
        payload["reply_markup"] = {
            "keyboard": [
                ["📊 STATUS", "📈 ANALYZE"],
                ["📉 LAST SIGNAL", "⚠️ RISK"],
                ["📋 STATS", "🔥 SCALP MODE"]
            ],
            "resize_keyboard": True
        }

    requests.post(url, json=payload)


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


def trend(prices):
    if prices[-1] > prices[-5] > prices[-12]:
        return "bullish"

    if prices[-1] < prices[-5] < prices[-12]:
        return "bearish"

    return "neutral"


def analyze(send_wait=True):
    global signals_today, last_signal_date, last_signal

    today = datetime.date.today()

    if last_signal_date != today:
        signals_today = 0
        last_signal_date = today

    try:
        m1 = get_data("1min")
        m5 = get_data("5min")
        m15 = get_data("15min")

        if not m1 or not m5 or not m15:
            if send_wait:
                tg("⚠️ Data error. No market data received.")
            return

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

        direction = "WAIT"
        confidence = max(buy_score, sell_score)

        if buy_score >= 70 and buy_score > sell_score:
            direction = "BUY"

        elif sell_score >= 70 and sell_score > buy_score:
            direction = "SELL"

        risk_amount = ACCOUNT * (RISK_PERCENT / 100)

        if direction == "BUY":
            sl = round(price - 3.5, 2)
            tp1 = round(price + 3, 2)
            tp2 = round(price + 6, 2)
            tp3 = round(price + 9, 2)

        elif direction == "SELL":
            sl = round(price + 3.5, 2)
            tp1 = round(price - 3, 2)
            tp2 = round(price - 6, 2)
            tp3 = round(price - 9, 2)

        else:
            msg = f"""
⏸ XAUUSD WAIT

Price: {round(price, 2)}

Buy score: {buy_score}%
Sell score: {sell_score}%

M1: {t1}
M5: {t5}
M15: {t15}

Reason: No high probability setup.
"""
            last_signal = msg

            if send_wait:
                tg(msg)

            return

        msg = f"""
📊 XAUUSD {direction} SIGNAL

Entry: {round(price, 2)}
SL: {sl}

TP1: {tp1}
TP2: {tp2}
TP3: {tp3}

Confidence: {confidence}%
Lot: 0.01
Risk: {round(risk_amount, 2)}€

M1: {t1}
M5: {t5}
M15: {t15}

Signals today: {signals_today}/{MAX_SIGNALS_PER_DAY}
"""

        last_signal = msg

        if signals_today < MAX_SIGNALS_PER_DAY:
            tg(msg)
            signals_today += 1

    except Exception as e:
        tg(f"⚠️ Error: {e}")


def market_loop():
    while True:
        analyze(send_wait=False)
        time.sleep(60)


def telegram_polling():
    global last_update_id

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            r = requests.get(url, params={
                "offset": last_update_id + 1,
                "timeout": 10
            }).json()

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

                elif text == "📈 ANALYZE":
                    analyze(send_wait=True)

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

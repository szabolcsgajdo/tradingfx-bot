import os, requests, datetime, math
from flask import Flask, request, jsonify
import threading, time

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv("TWELVEDATA_API_KEY")

ACCOUNT = float(os.getenv("ACCOUNT_BALANCE", 300))
RISK_PERCENT = float(os.getenv("MAX_RISK_PERCENT", 1))
MAX_SIGNALS_PER_DAY = 3

signals_today = 0
last_signal_date = None
last_signal_time = None

def tg(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg})

def get_data(interval):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "XAU/USD",
        "interval": interval,
        "apikey": API_KEY,
        "outputsize": 80
    }
    r = requests.get(url, params=params).json()
    vals = r.get("values", [])
    return list(reversed(vals))

def close_prices(data):
    return [float(x["close"]) for x in data]

def trend(prices):
    if prices[-1] > prices[-5] > prices[-12]:
        return "bullish"
    if prices[-1] < prices[-5] < prices[-12]:
        return "bearish"
    return "neutral"

def analyze():
    global signals_today, last_signal_date, last_signal_time

    today = datetime.date.today()
    if last_signal_date != today:
        signals_today = 0
        last_signal_date = today

    if signals_today >= MAX_SIGNALS_PER_DAY:
        return

    m1 = get_data("1min")
    m5 = get_data("5min")
    m15 = get_data("15min")

    if not m1 or not m5 or not m15:
        return

    p1 = close_prices(m1)
    p5 = close_prices(m5)
    p15 = close_prices(m15)

    price = p1[-1]
    t1, t5, t15 = trend(p1), trend(p5), trend(p15)

    recent_high = max(p1[-20:])
    recent_low = min(p1[-20:])
    range_size = recent_high - recent_low

    buy_score = 0
    sell_score = 0

    if t15 == "bullish": buy_score += 25
    if t5 == "bullish": buy_score += 25
    if t1 == "bullish": buy_score += 15

    if t15 == "bearish": sell_score += 25
    if t5 == "bearish": sell_score += 25
    if t1 == "bearish": sell_score += 15

    if price > recent_high - 0.8 and t5 == "bullish":
        buy_score += 15

    if price < recent_low + 0.8 and t5 == "bearish":
        sell_score += 15

    if range_size > 3:
        buy_score += 5
        sell_score += 5

    direction = "WAIT"
    confidence = max(buy_score, sell_score)

    if buy_score >= 70 and buy_score > sell_score:
        direction = "BUY"

    if sell_score >= 70 and sell_score > buy_score:
        direction = "SELL"

    if direction == "WAIT":
        return

    now = time.time()
    if last_signal_time and now - last_signal_time < 1800:
        return

    risk_amount = ACCOUNT * (RISK_PERCENT / 100)
    lot = 0.01

    if direction == "BUY":
        sl = round(price - 3.5, 2)
        tp1 = round(price + 3.0, 2)
        tp2 = round(price + 6.0, 2)
        tp3 = round(price + 9.0, 2)
    else:
        sl = round(price + 3.5, 2)
        tp1 = round(price - 3.0, 2)
        tp2 = round(price - 6.0, 2)
        tp3 = round(price - 9.0, 2)

    msg = f"""
📊 XAUUSD {direction} SIGNAL

Entry: {round(price, 2)}
SL: {sl}

TP1: {tp1}
TP2: {tp2}
TP3: {tp3}

Confidence: {confidence}%
Lot: {lot}
Risk: {risk_amount:.2f}€

M1 trend: {t1}
M5 trend: {t5}
M15 trend: {t15}

Max daily signals: {MAX_SIGNALS_PER_DAY}
"""

    tg(msg)
    signals_today += 1
    last_signal_time = now

def loop():
    while True:
        try:
            analyze()
        except Exception as e:
            print("ERROR:", e)
        time.sleep(60)

@app.route("/")
def home():
    return "Trading FX AI Bot running."

@app.route("/test")
def test():
    tg("✅ TRADING FX BOT ONLINE\n\nLive AI Signal Engine aktiv.")
    return "Test sent."

@app.route("/manual")
def manual():
    analyze()
    return "Manual analysis started."

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

import os, requests, datetime, threading, time
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
last_signal_time = None

def tg(msg):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg}
    )

def get_data(interval):
    r = requests.get("https://api.twelvedata.com/time_series", params={
        "symbol": "XAU/USD",
        "interval": interval,
        "apikey": API_KEY,
        "outputsize": 120
    }).json()
    return list(reversed(r.get("values", [])))

def closes(data):
    return [float(x["close"]) for x in data]

def ema(prices, period):
    k = 2 / (period + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return e

def rsi(prices, period=14):
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def trend(prices):
    e20 = ema(prices[-60:], 20)
    e50 = ema(prices[-80:], 50)
    price = prices[-1]
    if price > e20 > e50:
        return "bullish"
    if price < e20 < e50:
        return "bearish"
    return "neutral"

def in_session():
    hour = datetime.datetime.utcnow().hour
    return 7 <= hour <= 20

def analyze(force=False):
    global signals_today, last_signal_date, last_signal_time

    today = datetime.date.today()
    if last_signal_date != today:
        signals_today = 0
        last_signal_date = today

    if signals_today >= MAX_SIGNALS_PER_DAY:
        if force:
            tg("⛔ Max daily signals reached.")
        return

    if not in_session():
        if force:
            tg("⏸ WAIT\nMarket outside preferred trading session.")
        return

    m1, m5, m15 = get_data("1min"), get_data("5min"), get_data("15min")
    if not m1 or not m5 or not m15:
        if force:
            tg("⚠️ Data error. No market data received.")
        return

    p1, p5, p15 = closes(m1), closes(m5), closes(m15)
    price = p1[-1]

    t1, t5, t15 = trend(p1), trend(p5), trend(p15)
    rsi1, rsi5 = rsi(p1), rsi(p5)

    recent_high = max(p1[-30:])
    recent_low = min(p1[-30:])
    range_size = recent_high - recent_low

    buy_score = 0
    sell_score = 0

    if t15 == "bullish": buy_score += 25
    if t5 == "bullish": buy_score += 25
    if t1 == "bullish": buy_score += 15

    if t15 == "bearish": sell_score += 25
    if t5 == "bearish": sell_score += 25
    if t1 == "bearish": sell_score += 15

    if rsi1 < 35 and t5 != "bearish": buy_score += 15
    if rsi1 > 65 and t5 != "bullish": sell_score += 15

    if price > recent_high - 0.7 and rsi1 > 65:
        sell_score += 10

    if price < recent_low + 0.7 and rsi1 < 35:
        buy_score += 10

    if range_size >= 3:
        buy_score += 5
        sell_score += 5

    direction = "WAIT"
    confidence = max(buy_score, sell_score)

    if buy_score >= 70 and buy_score > sell_score:
        direction = "BUY"
    elif sell_score >= 70 and sell_score > buy_score:
        direction = "SELL"

    if direction == "WAIT":
        if force:
            tg(f"""⏸ XAUUSD WAIT

Price: {round(price, 2)}
Buy score: {buy_score}%
Sell score: {sell_score}%

M1: {t1}
M5: {t5}
M15: {t15}

RSI M1: {round(rsi1, 1)}
RSI M5: {round(rsi5, 1)}

Reason: No high probability setup.
""")
        return

    now = time.time()
    if last_signal_time and now - last_signal_time < 1800:
        if force:
            tg("⏸ WAIT\nSignal cooldown active.")
        return

    risk_amount = ACCOUNT * (RISK_PERCENT / 100)
    lot = 0.01

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

    tg(f"""📊 XAUUSD {direction} SIGNAL

Entry: {round(price, 2)}
SL: {sl}

TP1: {tp1}
TP2: {tp2}
TP3: {tp3}

Confidence: {confidence}%
Lot: {lot}
Risk: {risk_amount:.2f}€

M1: {t1}
M5: {t5}
M15: {t15}

RSI M1: {round(rsi1, 1)}
RSI M5: {round(rsi5, 1)}

Max daily signals: {MAX_SIGNALS_PER_DAY}
""")

    signals_today += 1
    last_signal_time = now

def loop():
    while True:
        try:
            analyze(False)
        except Exception as e:
            print("ERROR:", e)
        time.sleep(60)

@app.route("/")
def home():
    return "Trading FX AI Bot running."

@app.route("/test")
def test():
    tg("✅ TRADING FX BOT ONLINE\n\nAdvanced AI Signal Engine aktiv.")
    return "Test sent."

@app.route("/manual")
def manual():
    analyze(True)
    return "Manual analysis started."

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

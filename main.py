import os
import requests
import datetime
import threading
import time

from flask import Flask
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

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


# =========================
# TELEGRAM SEND
# =========================

def tg(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": msg
    })


# =========================
# MARKET DATA
# =========================

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


# =========================
# ANALYZE
# =========================

def analyze():

    global signals_today
    global last_signal_date
    global last_signal

    today = datetime.date.today()

    if last_signal_date != today:
        signals_today = 0
        last_signal_date = today

    if signals_today >= MAX_SIGNALS_PER_DAY:
        return

    try:

        m1 = get_data("1min")
        m5 = get_data("5min")
        m15 = get_data("15min")

        if not m1 or not m5 or not m15:
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

        if buy_score >= 70:
            direction = "BUY"

        if sell_score >= 70:
            direction = "SELL"

        msg = f"""
📊 XAUUSD {direction}

Price: {round(price, 2)}

Buy score: {buy_score}%
Sell score: {sell_score}%

M1: {t1}
M5: {t5}
M15: {t15}

Confidence: {confidence}%
"""

        last_signal = msg

        if direction != "WAIT":
            tg(msg)
            signals_today += 1

    except Exception as e:
        print("ERROR:", e)


# =========================
# AUTO LOOP
# =========================

def loop():

    while True:

        try:
            analyze()

        except Exception as e:
            print(e)

        time.sleep(60)


# =========================
# TELEGRAM BUTTON MENU
# =========================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        ["📊 STATUS", "📈 ANALYZE"],
        ["📉 LAST SIGNAL", "⚠️ RISK"],
        ["📋 STATS", "🔥 SCALP MODE"]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🤖 TRADING FX AI BOT ONLINE\n\nVálassz funkciót:",
        reply_markup=reply_markup
    )


# =========================
# BUTTON ACTIONS
# =========================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    if text == "📊 STATUS":

        await update.message.reply_text(
            f"""
📊 BOT STATUS

Signals today: {signals_today}/{MAX_SIGNALS_PER_DAY}

Account: {ACCOUNT}€
Risk: {RISK_PERCENT}%

Bot status: ONLINE
"""
        )

    elif text == "📈 ANALYZE":

        analyze()

        await update.message.reply_text(
            "📈 Live analysis started..."
        )

    elif text == "📉 LAST SIGNAL":

        await update.message.reply_text(last_signal)

    elif text == "⚠️ RISK":

        risk_amount = ACCOUNT * (RISK_PERCENT / 100)

        await update.message.reply_text(
            f"""
⚠️ RISK MANAGEMENT

Account: {ACCOUNT}€
Risk per trade: {RISK_PERCENT}%

Max risk:
{risk_amount:.2f}€
"""
        )

    elif text == "📋 STATS":

        await update.message.reply_text(
            f"""
📋 DAILY STATS

Signals today:
{signals_today}

Max daily:
{MAX_SIGNALS_PER_DAY}
"""
        )

    elif text == "🔥 SCALP MODE":

        await update.message.reply_text(
            """
🔥 SCALP MODE

Fast signals enabled.
M1 + M5 aggressive entries active.
"""
        )


# =========================
# TELEGRAM START
# =========================

def start_telegram():

    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", cmd_start))

    app_bot.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            buttons
        )
    )

    app_bot.run_polling()


# =========================
# FLASK ROUTES
# =========================

@app.route("/")
def home():
    return "TRADING FX BOT ONLINE"


@app.route("/test")
def test():

    tg("✅ TRADING FX BOT ONLINE")

    return "Test sent."


# =========================
# START
# =========================

if __name__ == "__main__":

    threading.Thread(
        target=loop,
        daemon=True
    ).start()

    threading.Thread(
        target=start_telegram,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )

import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ACCOUNT_SIZE = 300
MAX_SIGNALS_PER_DAY = 3

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    return requests.post(url, json=payload)

def calculate_signal(data):
    symbol = data.get("symbol", "XAUUSD")
    price = float(data.get("price", 0))
    direction = data.get("direction", "WAIT").upper()
    confidence = int(data.get("confidence", 70))

    risk_eur = ACCOUNT_SIZE * 0.015
    lot = 0.01

    if direction == "BUY":
        sl = round(price - 4, 2)
        tp1 = round(price + 3, 2)
        tp2 = round(price + 6, 2)
        tp3 = round(price + 9, 2)
    elif direction == "SELL":
        sl = round(price + 4, 2)
        tp1 = round(price - 3, 2)
        tp2 = round(price - 6, 2)
        tp3 = round(price - 9, 2)
    else:
        return "WAIT"

    return f"""
📊 <b>{symbol} {direction} SIGNAL</b>

Confidence: <b>{confidence}%</b>
Entry: <b>{price}</b>

SL: <b>{sl}</b>
TP1: <b>{tp1}</b>
TP2: <b>{tp2}</b>
TP3: <b>{tp3}</b>

Lot: <b>{lot}</b>
Risk: <b>{risk_eur:.2f}€</b>

Mode: AI Scalp System v1
"""

@app.route("/")
def home():
    return "Trading FX AI Bot is running."

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    signal = calculate_signal(data)

    if signal != "WAIT":
        send_telegram(signal)

    return jsonify({"status": "ok", "signal": signal})

@app.route("/test")
def test():
    msg = """
✅ <b>TRADING FX BOT ONLINE</b>

XAUUSD AI Signal System aktiv.
Risk account: 300€
Max daily signals: 3
"""
    send_telegram(msg)
    return "Test sent."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

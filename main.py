from flask import Flask
import requests
import os
import base64
from openai import OpenAI
from playwright.sync_api import sync_playwright

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHART_URL = os.getenv("CHART_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

def send_telegram(msg):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": msg
        }
    )

def capture_chart():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        page = browser.new_page(viewport={"width": 1600, "height": 900})

        page.goto(CHART_URL)

        page.wait_for_timeout(10000)

        page.screenshot(path="chart.png")

        browser.close()

def analyze_chart():

    with open("chart.png", "rb") as image_file:
        image_base64 = base64.b64encode(image_file.read()).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": """
You are a professional Smart Money Concept and ICT trader.

Analyze the chart image.

Look for:
- trend
- liquidity sweep
- BOS
- CHOCH
- order block
- fair value gap
- rejection candles
- candlestick patterns
- compression
- accumulation/distribution
- momentum
- breakout or fake breakout

Decide:
BUY / SELL / WAIT

Only give strong signals.

Return response exactly in this format:

SIGNAL: BUY or SELL or WAIT
CONFIDENCE: %
ENTRY:
SL:
TP1:
TP2:
TP3:
REASON:
"""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Analyze this XAUUSD chart."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        max_tokens=500
    )

    return response.choices[0].message.content

@app.route("/")
def home():
    return "AI CHART ANALYZER ONLINE"

@app.route("/scan")
def scan():

    try:

        capture_chart()

        result = analyze_chart()

        send_telegram(result)

        return result

    except Exception as e:

        send_telegram(f"ERROR:\n{str(e)}")

        return str(e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

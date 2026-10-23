
import json
import os
import time
import urllib.parse
import urllib.request
from itertools import permutations

BINANCE = "https://api.binance.com"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
START_AMOUNT = float(os.environ.get("START_AMOUNT", "100"))
FEE = float(os.environ.get("FEE", "0.001"))
MIN_PROFIT = float(os.environ.get("MIN_PROFIT", "0.5"))
SCAN_SECONDS = 15
ALERT_COOLDOWN = 300

last_alert = {}


def get_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "TriangleScanner/1.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Не задані TELEGRAM_TOKEN або TELEGRAM_CHAT_ID")
        return

    url = (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    )
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()


def build_markets():
    info = get_json(BINANCE + "/api/v3/exchangeInfo")
    tickers = get_json(BINANCE + "/api/v3/ticker/bookTicker")
    ticker_map = {t["symbol"]: t for t in tickers}
    markets = {}

    for item in info["symbols"]:
        symbol = item["symbol"]
        if item["status"] != "TRADING":
            continue
        if not item.get("isSpotTradingAllowed", True):
            continue
        ticker = ticker_map.get(symbol)
        if not ticker:
            continue

        try:
            bid = float(ticker["bidPrice"])
            ask = float(ticker["askPrice"])
        except (ValueError, KeyError):
            continue

        if bid <= 0 or ask <= 0:
            continue

        base = item["baseAsset"]
        quote = item["quoteAsset"]

        markets[(base, quote)] = (bid, ask, symbol)

    return markets


def convert(amount, source, target, markets):
    market = markets.get((source, target))
    if market:
        bid, ask, _ = market
        return amount * bid * (1 - FEE)

    market = markets.get((target, source))
    if market:
        bid, ask, _ = market
        return amount / ask * (1 - FEE)

    return None


def scan(markets):
    graph = {}
    for base, quote in markets:
        graph.setdefault(base, set()).add(quote)
        graph.setdefault(quote, set()).add(base)

    routes = set()
    for a in graph.get("USDT", set()):
        for b in graph.get(a, set()):
            if b == "USDT" or b == a:
                continue
            if "USDT" in graph.get(b, set()):
                routes.add(("USDT", a, b, "USDT"))

    opportunities = []
    now = time.time()

    for route in routes:
        amount = START_AMOUNT
        valid = True

        for source, target in zip(route, route[1:]):
            result = convert(amount, source, target, markets)
            if result is None:
                valid = False
                break
            amount = result

        if not valid:
            continue

        profit = amount - START_AMOUNT
        percent = profit / START_AMOUNT * 100
        if percent < MIN_PROFIT:
            continue

        key = " -> ".join(route)
        if now - last_alert.get(key, 0) < ALERT_COOLDOWN:
            continue

        last_alert[key] = now
        opportunities.append((percent, profit, key, amount))

    return sorted(opportunities, reverse=True)


def main():
    print("Сканер трикутного арбітражу Binance запущено.")
    print(f"Сума: {START_AMOUNT} USDT | Комісія: {FEE * 100:.3f}% за угоду")
    print(f"Поріг сповіщення: {MIN_PROFIT:.2f}%")

    while True:
        try:
            markets = build_markets()
            opportunities = scan(markets)

            if opportunities:
                for percent, profit, route, final_amount in opportunities[:10]:
                    message = (
                        "🔎 Можливість трикутного арбітражу Binance\n"
                        f"Маршрут: {route}\n"
                        f"Старт: {START_AMOUNT:.4f} USDT\n"
                        f"Розрахунковий результат: {final_amount:.4f} USDT\n"
                        f"Розрахунковий прибуток: {profit:.4f} USDT "
                        f"({percent:.3f}%)\n"
                        "⚠️ Це оцінка за найкращими bid/ask, не гарантія прибутку."
                    )
                    print(message)
                    send_telegram(message)
            else:
                print(time.strftime("%H:%M:%S"), "- вигідних сигналів немає")

        except Exception as error:
            print("Помилка сканування:", error)

        time.sleep(SCAN_SECONDS)


from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import os

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Binance scanner is running")

    def log_message(self, format, *args):
        pass

def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

if __name__ == "__main__":
    Thread(target=start_web_server, daemon=True).start()
    main()

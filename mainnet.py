#!/usr/bin/env python3
"""
mainnet.py - Binance Futures MAINNET
Listens to 1m candles and places STOP-MARKET orders after trigger.
Cloud-ready: reads API keys from .env via python-dotenv.
"""

import os
import json
import time
import hmac
import hashlib
import requests
import websocket
import sys
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv

# ------------------- LOAD ENV -------------------
load_dotenv()  # pip install python-dotenv
API_KEY = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")

REST_BASE_URL = "https://fapi.binance.com"
WS_BASE_URL   = "wss://fstream.binance.com/ws"
symbol = "ETHUSDT"

# ------------------- Read args -------------------
if len(sys.argv) >= 4:
    entry_price = float(sys.argv[1])
    x_percent   = float(sys.argv[2])
    side        = sys.argv[3].upper()
else:
    print("Usage: python mainnet.py <entry_price> <x_percent> <side>")
    sys.exit(1)

# ------------------- Compute trigger/stop -------------------
if side == "LONG":
    trigger_price = entry_price + (0.55 * x_percent / 100) * entry_price
    stop_limit    = entry_price + (0.25 * x_percent / 100) * entry_price
else:  # SHORT
    trigger_price = entry_price - (0.55 * x_percent / 100) * entry_price
    stop_limit    = entry_price - (0.25 * x_percent / 100) * entry_price

print("==================================================")
print(f"[CONFIG] Side:          {side}")
print(f"[CONFIG] Entry Price:   {entry_price}")
print(f"[CONFIG] x%:            {x_percent:.4f}")
print(f"[CONFIG] Trigger Price: {trigger_price}")
print(f"[CONFIG] Stop Limit:    {stop_limit}")
print("==================================================")

# ------------------- Helpers -------------------
session = requests.Session()

def get_server_time():
    """Fetch Binance server time (retry if fails)."""
    url = f"{REST_BASE_URL}/fapi/v1/time"
    for attempt in range(5):
        try:
            r = session.get(url, timeout=10)
            r.raise_for_status()
            return int(r.json()["serverTime"])
        except Exception as e:
            print(f"[WARN] get_server_time attempt {attempt+1} failed:", e)
            time.sleep(1)
    raise SystemExit("[FATAL] Could not fetch Binance server time")

def sign(params):
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig

def get_symbol_info(symbol):
    url = f"{REST_BASE_URL}/fapi/v1/exchangeInfo"
    r = session.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    for s in data["symbols"]:
        if s["symbol"] == symbol:
            return s
    return None

symbol_info = get_symbol_info(symbol)
if not symbol_info:
    raise SystemExit("[ERROR] Could not fetch symbol info")

tick_size = Decimal(next(f["tickSize"] for f in symbol_info["filters"] if f["filterType"]=="PRICE_FILTER"))
step_size = Decimal(next(f["stepSize"] for f in symbol_info["filters"] if f["filterType"]=="LOT_SIZE"))

def round_price(price):
    return Decimal(price).quantize(tick_size, rounding=ROUND_DOWN)

def round_qty(qty):
    return Decimal(qty).quantize(step_size, rounding=ROUND_DOWN)

# ------------------- Position -------------------
position_qty = 0
stop_requested = False

def get_position(symbol):
    global position_qty
    try:
        ts = get_server_time()
        params = {"timestamp": ts, "recvWindow": 5000}
        query = sign(params)
        url = f"{REST_BASE_URL}/fapi/v2/positionRisk?{query}"
        headers = {"X-MBX-APIKEY": API_KEY}
        r = session.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            for pos in data:
                if pos["symbol"] == symbol and float(pos["positionAmt"]) != 0:
                    amt = float(pos["positionAmt"])
                    print(f"[INFO] Position: {amt} {symbol}")
                    return amt
        return 0
    except Exception as e:
        print("[WARN] get_position error:", e)
        return position_qty

# ------------------- Orders -------------------
def place_stop_market_order(symbol, side, qty, stop_price):
    global stop_requested
    try:
        ts = get_server_time()
        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "quantity": str(round_qty(qty)),
            "stopPrice": str(round_price(stop_price)),
            "reduceOnly": "true",
            "timestamp": ts,
            "recvWindow": 5000,
        }
        query = sign(params)
        url = f"{REST_BASE_URL}/fapi/v1/order?{query}"
        headers = {"X-MBX-APIKEY": API_KEY}
        r = session.post(url, headers=headers, timeout=10)
        if r.status_code in (200,201):
            print("[ORDER] Stop-market order placed:", r.json())
            stop_requested = True
        else:
            print("[ERROR] placing stop-market order:", r.status_code, r.text)
    except Exception as e:
        print("Exception while placing stop-market order:", e)

# ------------------- WebSocket -------------------
def on_message(ws, message):
    global position_qty
    try:
        data = json.loads(message)
        kline = data.get("k", {})
        if not kline or not kline.get("x"):
            return  # only closed candles
        close_price = float(kline["c"])
        close_time = int(kline["T"])
        print(f"[CANDLE] {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(close_time/1000))} | Close: {close_price}")

        position_qty_now = get_position(symbol)
        if position_qty_now == 0:
            print("[INFO] Position closed. Exiting.")
            ws.close()
            return
        position_qty = position_qty_now

        if position_qty > 0 and close_price > trigger_price:
            print("[TRIGGER] LONG trigger met.")
            place_stop_market_order(symbol, "SELL", position_qty, trigger_price)
            ws.close()
        elif position_qty < 0 and close_price < trigger_price:
            print("[TRIGGER] SHORT trigger met.")
            place_stop_market_order(symbol, "BUY", abs(position_qty), trigger_price)
            ws.close()
    except Exception as e:
        print("Error in on_message:", e)

def on_error(ws, error): print("WebSocket error:", error)
def on_close(ws, code, msg): print("WebSocket closed", code, msg)
def on_open(ws): print("[INFO] WebSocket connected. Listening for 1m candles...")

def run_bot():
    global position_qty
    print("[INFO] Starting bot...")
    position_qty = get_position(symbol)
    if position_qty == 0:
        print("[EXIT] No open position.")
        return
    stream_name = f"{symbol.lower()}@kline_1m"
    ws_url = f"{WS_BASE_URL}/{stream_name}"
    while True:
        if stop_requested: break
        try:
            ws = websocket.WebSocketApp(ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close)
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print("[ERROR] WebSocket crashed:", e)
        if stop_requested: break
        print("[INFO] Reconnecting in 5s...")
        time.sleep(5)

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("[WARN] No BINANCE_API_KEY/BINANCE_API_SECRET set.")
        sys.exit(1)
    run_bot()

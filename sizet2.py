import requests
import statistics
import time
import hmac
import hashlib
import os
from decimal import Decimal
import subprocess
from dotenv import load_dotenv

# ------------------- LOAD ENV -------------------
load_dotenv()  # pip install python-dotenv
API_KEY = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")

# ------------------- CONFIG -------------------
SYMBOL = "ETHUSDT"
TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h"]
CHECK_INTERVAL = 10  # seconds

BASE_URL = "https://fapi.binance.com"
MAINNET_SCRIPT = "mainnet.py"  # relative path in repo

# ------------------- SESSION -------------------
session = requests.Session()  # no proxy

# ------------------- UTILS -------------------
def round_step(value, step):
    step_dec = Decimal(str(step))
    value_dec = Decimal(str(value))
    return float((value_dec // step_dec) * step_dec)

def get_server_time():
    r = session.get(f"{BASE_URL}/fapi/v1/time", timeout=10)
    r.raise_for_status()
    return int(r.json()["serverTime"])

def get_symbol_info(symbol):
    try:
        url = f"{BASE_URL}/fapi/v1/exchangeInfo"
        r = session.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                return s
    except Exception as e:
        print("[WARN] get_symbol_info failed:", e)
    return None

symbol_info = get_symbol_info(SYMBOL)
if not symbol_info:
    raise SystemExit("Failed to fetch symbol info; check BASE_URL.")

tick_size = float(symbol_info['filters'][0]['tickSize'])
step_size = float(symbol_info['filters'][2]['stepSize'])

# ------------------- BOLLINGER BANDS -------------------
def get_closes(symbol, interval, limit=210):
    try:
        url = f"{BASE_URL}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = session.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [float(candle[4]) for candle in data]
    except Exception as e:
        print(f"[WARN] get_closes({interval}) error:", e)
        return []

def bollinger_bands(closes, period=200, std_dev=2):
    if len(closes) < period:
        return None, None, None
    recent = closes[-period:]
    middle = statistics.mean(recent)
    stdev = statistics.stdev(recent)
    upper = middle + std_dev * stdev
    lower = middle - std_dev * stdev
    return middle, upper, lower

# ------------------- POSITION & ORDERS -------------------
def get_current_position(symbol):
    try:
        ts = get_server_time()
        params = f"timestamp={ts}&recvWindow=5000"
        signature = hmac.new(API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE_URL}/fapi/v2/positionRisk?{params}&signature={signature}"
        headers = {"X-MBX-APIKEY": API_KEY}
        r = session.get(url, headers=headers, timeout=10)
        positions = r.json()
        if not isinstance(positions, list):
            return "ERROR"
        for pos in positions:
            if pos.get("symbol") == symbol and float(pos.get("positionAmt", 0)) != 0:
                side = "LONG" if float(pos["positionAmt"]) > 0 else "SHORT"
                entry_price = float(pos["entryPrice"])
                quantity = abs(float(pos["positionAmt"]))
                return {"side": side, "entry_price": entry_price, "quantity": quantity}
        return None
    except Exception as e:
        print("[WARN] get_current_position error:", e)
        return "ERROR"

def cancel_all_open_orders(symbol):
    try:
        ts = get_server_time()
        params = f"symbol={symbol}&timestamp={ts}&recvWindow=5000"
        signature = hmac.new(API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE_URL}/fapi/v1/allOpenOrders?{params}&signature={signature}"
        headers = {"X-MBX-APIKEY": API_KEY}
        r = session.delete(url, headers=headers, timeout=10)
        print(f"[INFO] Cancelled all open orders for {symbol}: {r.json()}")
    except Exception as e:
        print("[WARN] cancel_all_open_orders error:", e)

def compute_orders(position, middle, upper, lower):
    diff_upper = abs(upper - middle) / middle * 100
    diff_lower = abs(middle - lower) / middle * 100
    x = max(diff_upper, diff_lower)
    entry = position["entry_price"]
    qty = round_step(position["quantity"], step_size)

    if position["side"].upper() == "LONG":
        sl_limit = round_step(entry - (x/3)/100 * entry, tick_size)
        tp_trigger = round_step(entry + (x - 0.01)/100 * entry, tick_size)
        tp_limit = round_step(entry + x/100 * entry, tick_size)
    else:
        sl_limit = round_step(entry + (x/3)/100 * entry, tick_size)
        tp_trigger = round_step(entry - (x - 0.01)/100 * entry, tick_size)
        tp_limit = round_step(entry - x/100 * entry, tick_size)

    return {
        "stop_loss": {"limit": sl_limit, "quantity": qty},
        "take_profit": {"trigger": tp_trigger, "limit": tp_limit, "quantity": qty},
        "x_percent": x
    }

def place_limit_order(symbol, side, quantity, price):
    try:
        ts = get_server_time()
        params = f"symbol={symbol}&side={side}&type=LIMIT&timeInForce=GTC&quantity={quantity}&price={price}&reduceOnly=true&timestamp={ts}&recvWindow=5000"
        signature = hmac.new(API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE_URL}/fapi/v1/order?{params}&signature={signature}"
        headers = {"X-MBX-APIKEY": API_KEY}
        r = session.post(url, headers=headers, timeout=10)
        print(f"[INFO] Placing LIMIT {side} at {price} qty {quantity}")
        print(r.json())
    except Exception as e:
        print("[WARN] place_limit_order error:", e)

def place_stop_limit_order(symbol, side, quantity, limit_price):
    try:
        ts = get_server_time()
        params = f"symbol={symbol}&side={side}&type=STOP&timeInForce=GTC&quantity={quantity}&price={limit_price}&stopPrice={limit_price}&reduceOnly=true&timestamp={ts}&recvWindow=5000"
        signature = hmac.new(API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()
        url = f"{BASE_URL}/fapi/v1/order?{params}&signature={signature}"
        headers = {"X-MBX-APIKEY": API_KEY}
        r = session.post(url, headers=headers, timeout=10)
        print(f"[INFO] Placing STOP-LIMIT {side} limit {limit_price} qty {quantity}")
        print(r.json())
    except Exception as e:
        print("[WARN] place_stop_limit_order error:", e)

# ------------------- MAIN LOOP -------------------
def main():
    orders_placed = False

    while True:
        for tf in TIMEFRAMES:
            closes = get_closes(SYMBOL, tf)
            middle, upper, lower = bollinger_bands(closes)
            if middle is None:
                continue
            diff_upper = abs(upper - middle) / middle * 100
            diff_lower = abs(middle - lower) / middle * 100
            if diff_upper >= 2 or diff_lower >= 2:
                print(f"[{time.strftime('%X')}] {tf} | Middle: {middle:.2f}, Upper: {upper:.2f}, Lower: {lower:.2f}")

        position = get_current_position(SYMBOL)

        if position == "ERROR":
            time.sleep(CHECK_INTERVAL)
            continue

        if position and not orders_placed:
            cancel_all_open_orders(SYMBOL)
            chosen_orders = None
            for tf in TIMEFRAMES:
                closes = get_closes(SYMBOL, tf)
                middle, upper, lower = bollinger_bands(closes)
                if not middle:
                    continue
                orders = compute_orders(position, middle, upper, lower)
                if orders and orders["x_percent"] >= 2:
                    chosen_orders = orders
                    break
            if not chosen_orders:
                time.sleep(CHECK_INTERVAL)
                continue

            side_sl = "SELL" if position["side"] == "LONG" else "BUY"
            side_tp = side_sl

            place_stop_limit_order(SYMBOL, side_sl, chosen_orders["stop_loss"]["quantity"], chosen_orders["stop_loss"]["limit"])
            place_limit_order(SYMBOL, side_tp, chosen_orders["take_profit"]["quantity"], chosen_orders["take_profit"]["limit"])

            orders_placed = True

            # Launch mainnet.py in parallel
            subprocess.Popen(
                ["python", MAINNET_SCRIPT, str(position["entry_price"]), str(chosen_orders["x_percent"]), position["side"]],
                shell=False
            )
            print("[INFO] mainnet.py launched.")
            print("==========================================\n")

        elif position is None and orders_placed:
            print("[INFO] Position closed, cancelling remaining orders...")
            cancel_all_open_orders(SYMBOL)
            orders_placed = False

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("[WARN] No BINANCE_API_KEY/BINANCE_API_SECRET set in .env")
    else:
        main()

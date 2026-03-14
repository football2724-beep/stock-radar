#!/usr/bin/env python3
"""
AI 股票觀察站 - 後端伺服器
執行方式：python3 server.py
"""

import os
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", 8888))

class StockHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # 簡化 log 輸出
        print(f"  → {args[0]} {args[1]}")

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-api-key, anthropic-version")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        # 股票數據：/stock/AAPL
        if self.path.startswith("/stock/"):
            ticker = self.path.split("/stock/")[1].upper().strip()
            self.fetch_stock(ticker)

        # 股票歷史：/history/AAPL?range=1mo
        elif self.path.startswith("/history/"):
            parts = self.path.split("/history/")[1]
            if "?" in parts:
                ticker, params = parts.split("?", 1)
                range_val = "1mo"
                for p in params.split("&"):
                    if p.startswith("range="):
                        range_val = p.split("=")[1]
            else:
                ticker = parts
                range_val = "1mo"
            self.fetch_history(ticker.upper(), range_val)

        # 首頁說明
        elif self.path == "/" or self.path == "" or self.path == "/index.html":
            try:
                with open("index.html", "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_json({"status": "ok", "message": "AI 股票觀察站後端運行中 🚀"})

        else:
            self.send_json({"error": "找不到此路由"}, 404)

    def do_POST(self):
        # AI 分析代理：/ai
        if self.path == "/ai":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            api_key = self.headers.get("x-api-key", "")
            self.proxy_ai(body, api_key)
        else:
            self.send_json({"error": "找不到此路由"}, 404)

    # ── 抓股票即時數據 ──────────────────────────────────────────
    def fetch_stock(self, ticker):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())

            result = data["chart"]["result"][0]
            meta = result["meta"]

            # Get volume from indicators (more reliable than meta)
            quote_ind = result.get("indicators", {}).get("quote", [{}])[0]
            volumes = quote_ind.get("volume", [])
            volume = next((v for v in reversed(volumes) if v), 0) or meta.get("regularMarketVolume", 0)

            price     = meta.get("regularMarketPrice", 0)
            prev      = meta.get("previousClose") or meta.get("chartPreviousClose", price)
            change    = round(price - prev, 2)
            changePct = round((change / prev) * 100, 2) if prev else 0
            market_cap = meta.get("marketCap", 0)

            # If missing market cap, try v7 API
            if not market_cap:
                try:
                    url2 = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
                    req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req2, timeout=5) as resp2:
                        data2 = json.loads(resp2.read())
                    q = data2.get("quoteResponse", {}).get("result", [{}])[0]
                    market_cap = q.get("marketCap", 0)
                    if not volume:
                        volume = q.get("regularMarketVolume", 0)
                except:
                    pass

            self.send_json({
                "symbol":    meta.get("symbol", ticker),
                "name":      meta.get("longName") or meta.get("shortName", ticker),
                "price":     round(price, 2),
                "change":    change,
                "changePct": changePct,
                "high":      round(meta.get("regularMarketDayHigh", price), 2),
                "low":       round(meta.get("regularMarketDayLow", price), 2),
                "volume":    volume,
                "hi52":      round(meta.get("fiftyTwoWeekHigh", price), 2),
                "lo52":      round(meta.get("fiftyTwoWeekLow", price), 2),
                "marketCap": market_cap,
                "currency":  meta.get("currency", "USD"),
            })

        except Exception as e:
            self.send_json({"error": f"找不到股票 {ticker}，請確認代號正確。({e})"}, 404)

    # ── 抓歷史價格 ──────────────────────────────────────────────
    def fetch_history(self, ticker, range_val):
        interval_map = {"1mo": "1d", "3mo": "1d", "6mo": "1wk", "1y": "1wk"}
        interval = interval_map.get(range_val, "1d")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_val}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())

            result    = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            closes    = result["indicators"]["quote"][0].get("close", [])

            labels = []
            for t in timestamps:
                import datetime
                d = datetime.datetime.fromtimestamp(t)
                labels.append(f"{d.month}/{d.day}")

            prices = [round(p, 2) if p else None for p in closes]
            self.send_json({"labels": labels, "prices": prices})

        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    # ── 代理 Anthropic AI 請求 ──────────────────────────────────
    def proxy_ai(self, body, api_key):
        if not api_key:
            self.send_json({"error": "未提供 API Key"}, 400)
            return
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = resp.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors()
            self.end_headers()
            self.wfile.write(result)
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            self.send_json({"error": f"AI API 錯誤：{e.code} {err}"}, e.code)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    # ── 工具函式 ────────────────────────────────────────────────
    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), StockHandler)
    print("=" * 45)
    print("  🚀 AI 股票觀察站後端已啟動！")
    print(f"  📡 伺服器位址：http://localhost:{PORT}")
    print("  💡 請同時打開 index.html 使用儀表板")
    print("  ⏹  按 Ctrl+C 可停止伺服器")
    print("=" * 45)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止伺服器。再見！")

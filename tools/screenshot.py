#!/usr/bin/env python3
"""Seite in Chromium (headless) laden, optional JavaScript-Schritte ausführen, Screenshot speichern.

    .venv/bin/python tools/screenshot.py <url> <bild.png> <breite,höhe> ['[[wartezeit_s, "js"], …]']
"""
import base64, json, subprocess, sys, time, urllib.request
import simple_websocket

url, out_png, size = sys.argv[1], sys.argv[2], sys.argv[3]
steps = json.loads(sys.argv[4]) if len(sys.argv) > 4 else [[4, "1"]]
proc = subprocess.Popen(["chromium", "--headless=new", "--no-sandbox", "--remote-debugging-port=9334",
                         f"--window-size={size}", "--hide-scrollbars", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    page = None
    for _ in range(50):
        try:
            page = next(t for t in json.load(urllib.request.urlopen("http://127.0.0.1:9334/json", timeout=1)) if t.get("type") == "page")
            break
        except Exception:
            time.sleep(0.2)
    ws = simple_websocket.Client(page["webSocketDebuggerUrl"]); n = 0

    def call(method, params=None):
        global n
        n += 1; ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
        while True:
            r = json.loads(ws.receive())
            if r.get("id") == n:
                return r

    for wait_s, js in steps:
        time.sleep(wait_s)
        r = call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
        print("JS:", json.dumps(r.get("result", {}).get("result", {}).get("value"), ensure_ascii=False)[:300])
    open(out_png, "wb").write(base64.b64decode(call("Page.captureScreenshot", {"format": "png"})["result"]["data"]))
    print("Screenshot:", out_png); ws.close()
finally:
    proc.terminate()

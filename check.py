"""
SKYLRK 新品 + 補貨通知
每次執行：抓一次商品清單 → 跟上次存的比對 → 有新品或補貨就推播到手機 (ntfy)
"""

import base64
import json
import os
import re
import requests

SHOP = "https://skylrk.com"
SEEN_FILE = "seen.json"               # 存「已經看過的商品」和「上次有沒有貨」
NTFY_TOPIC = os.environ["NTFY_TOPIC"]  # 從 GitHub Secrets 讀進來，不寫在程式裡

HEADERS = {"User-Agent": "Mozilla/5.0 (new-item-checker)"}


def get_products():
    """回傳 {商品代號: {"title": 名稱, "available": 有沒有貨}}。
    先試 Shopify 的 products.json，失敗再退回讀網頁（網頁看不出庫存，一律當有貨）。"""
    try:
        r = requests.get(f"{SHOP}/products.json?limit=250", headers=HEADERS, timeout=30)
        r.raise_for_status()
        products = r.json()["products"]
        if products:
            return {
                p["handle"]: {
                    "title": p["title"],
                    "available": any(v.get("available") for v in p.get("variants", [])),
                }
                for p in products
            }
    except Exception as e:
        print("products.json 失敗，改讀網頁:", e)

    r = requests.get(SHOP, headers=HEADERS, timeout=30)
    r.raise_for_status()
    handles = re.findall(r'href="/products/([a-z0-9\-]+)', r.text)
    return {h: {"title": h.replace("-", " ").upper(), "available": True}
            for h in dict.fromkeys(handles)}


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):           # 舊版格式只有名單，沒有庫存，先當作有貨
        return {h: True for h in data}
    return data


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(seen.items())), f, indent=2, ensure_ascii=False)


def notify(title, body):
    # HTTP 標頭只能放英文，中文標題要先用 RFC 2047 格式編碼，ntfy 會自動解回中文
    encoded_title = "=?UTF-8?B?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?="
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": encoded_title, "Priority": "high", "Tags": "shopping_bags"},
        timeout=30,
    )


def main():
    current = get_products()
    print(f"目前共 {len(current)} 個商品")

    seen = load_seen()
    if seen is None:
        # 第一次執行：把現有商品全部記下來，不算新品
        save_seen({h: p["available"] for h, p in current.items()})
        notify("SKYLRK 監控已啟動", f"已記錄 {len(current)} 個現有商品，之後有新品或補貨會通知你。")
        print("第一次執行，已建立 seen.json")
        return

    new = [h for h in current if h not in seen]
    restocked = [h for h, p in current.items()
                 if h in seen and seen[h] is False and p["available"]]

    if new:
        lines = [f"{current[h]['title']}\n{SHOP}/products/{h}" for h in new]
        notify(f"SKYLRK 新品 x{len(new)}", "\n\n".join(lines))
        print("新品:", [current[h]["title"] for h in new])

    if restocked:
        lines = [f"{current[h]['title']}\n{SHOP}/products/{h}" for h in restocked]
        notify(f"SKYLRK 補貨 x{len(restocked)}", "\n\n".join(lines))
        print("補貨:", [current[h]["title"] for h in restocked])

    if not new and not restocked:
        print("沒有新品也沒有補貨")

    # 更新紀錄：新商品加進去，舊商品更新庫存狀態
    for h, p in current.items():
        seen[h] = p["available"]
    save_seen(seen)


if __name__ == "__main__":
    main()

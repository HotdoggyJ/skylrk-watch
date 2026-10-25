"""
SKYLRK 新品 + 補貨通知（尺寸等級）
每次執行：抓一次商品清單 → 跟上次存的比對 → 有新品、或任一尺寸從沒貨變有貨，就推播到手機 (ntfy)
"""

import base64
import json
import os
import re
import requests

SHOP = "https://skylrk.com"
SEEN_FILE = "seen.json"               # 存每個商品、每個尺寸上次有沒有貨
NTFY_TOPIC = os.environ["NTFY_TOPIC"]  # 從 GitHub Secrets 讀進來，不寫在程式裡

HEADERS = {"User-Agent": "Mozilla/5.0 (new-item-checker)"}


def get_products():
    """回傳 {商品代號: {"title": 名稱, "variants": {尺寸名稱: 有沒有貨}}}。
    先試 Shopify 的 products.json，失敗再退回讀網頁（網頁看不出庫存，一律當有貨）。"""
    try:
        r = requests.get(f"{SHOP}/products.json?limit=250", headers=HEADERS, timeout=30)
        r.raise_for_status()
        products = r.json()["products"]
        if products:
            return {
                p["handle"]: {
                    "title": p["title"],
                    "variants": {v["title"]: bool(v.get("available")) for v in p.get("variants", [])},
                }
                for p in products
            }
    except Exception as e:
        print("products.json 失敗，改讀網頁:", e)

    r = requests.get(SHOP, headers=HEADERS, timeout=30)
    r.raise_for_status()
    handles = re.findall(r'href="/products/([a-z0-9\-]+)', r.text)
    return {h: {"title": h.replace("-", " ").upper(), "variants": {"Default": True}}
            for h in dict.fromkeys(handles)}


def load_seen():
    """讀舊紀錄。舊版格式（名單、或商品等級的有貨/沒貨）會自動轉成新格式。"""
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {h: {} for h in data}
    return {h: (v if isinstance(v, dict) else {}) for h, v in data.items()}


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
        save_seen({h: p["variants"] for h, p in current.items()})
        notify("SKYLRK 監控已啟動", f"已記錄 {len(current)} 個現有商品，之後有新品或補貨會通知你。")
        print("第一次執行，已建立 seen.json")
        return

    # 新品：以前沒看過的商品
    new = [h for h in current if h not in seen]

    # 補貨：以前看過、而且某個尺寸上次是沒貨、這次變有貨
    restocked = []   # (商品代號, [尺寸, 尺寸...])
    for h, p in current.items():
        if h not in seen:
            continue
        old = seen[h]
        sizes = [s for s, ok in p["variants"].items() if ok and old.get(s) is False]
        if sizes:
            restocked.append((h, sizes))

    if new:
        lines = [f"{current[h]['title']}\n{SHOP}/products/{h}" for h in new]
        notify(f"SKYLRK 新品 x{len(new)}", "\n\n".join(lines))
        print("新品:", [current[h]["title"] for h in new])

    if restocked:
        lines = [f"{current[h]['title']}（{', '.join(sizes)}）\n{SHOP}/products/{h}"
                 for h, sizes in restocked]
        notify(f"SKYLRK 補貨 x{len(restocked)}", "\n\n".join(lines))
        print("補貨:", [(current[h]["title"], sizes) for h, sizes in restocked])

    if not new and not restocked:
        print("沒有新品也沒有補貨")

    # 更新紀錄：新商品加進去，舊商品更新每個尺寸的庫存狀態
    for h, p in current.items():
        seen[h] = p["variants"]
    save_seen(seen)


if __name__ == "__main__":
    main()

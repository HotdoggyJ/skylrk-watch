"""
SKYLRK 新品通知
每次執行：抓一次商品清單 → 跟上次存的比對 → 有新品就推播到手機 (ntfy)
"""

import json
import os
import re
import requests

SHOP = "https://skylrk.com"
SEEN_FILE = "seen.json"               # 存「已經看過的商品」的檔案
NTFY_TOPIC = os.environ["NTFY_TOPIC"]  # 從 GitHub Secrets 讀進來，不寫在程式裡

HEADERS = {"User-Agent": "Mozilla/5.0 (new-item-checker)"}


def get_products():
    """回傳 {商品代號: 商品名稱}。先試 Shopify 的 products.json，失敗再退回讀網頁。"""
    try:
        r = requests.get(f"{SHOP}/products.json?limit=250", headers=HEADERS, timeout=30)
        r.raise_for_status()
        products = r.json()["products"]
        if products:
            return {p["handle"]: p["title"] for p in products}
    except Exception as e:
        print("products.json 失敗，改讀網頁:", e)

    r = requests.get(SHOP, headers=HEADERS, timeout=30)
    r.raise_for_status()
    handles = re.findall(r'href="/products/([a-z0-9\-]+)', r.text)
    return {h: h.replace("-", " ").upper() for h in dict.fromkeys(handles)}


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE, encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(handles):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(handles), f, indent=2, ensure_ascii=False)


def notify(title, body):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "shopping_bags"},
        timeout=30,
    )


def main():
    current = get_products()
    print(f"目前共 {len(current)} 個商品")

    seen = load_seen()
    if seen is None:
        # 第一次執行：把現有商品全部記下來，不算新品
        save_seen(current.keys())
        notify("SKYLRK 監控已啟動", f"已記錄 {len(current)} 個現有商品，之後有新品會通知你。")
        print("第一次執行，已建立 seen.json")
        return

    new = [h for h in current if h not in seen]
    if not new:
        print("沒有新品")
        return

    lines = [f"{current[h]}\n{SHOP}/products/{h}" for h in new]
    notify(f"SKYLRK 新品 x{len(new)}", "\n\n".join(lines))
    print("新品:", [current[h] for h in new])

    save_seen(seen | set(current.keys()))


if __name__ == "__main__":
    main()

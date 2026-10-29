"""
SKYLRK 新品 / 新色 / 補貨 / 上首頁 通知
每次執行：抓商品清單 + 首頁 → 跟上次存的比對 → 有變化就推播到手機 (ntfy)
"""

import base64
import json
import os
import re
import requests

SHOP = "https://skylrk.com"
SEEN_FILE = "seen.json"               # 存每個商品的尺寸/顏色庫存、有沒有在首頁
NTFY_TOPIC = os.environ["NTFY_TOPIC"]  # 從 GitHub Secrets 讀進來，不寫在程式裡

HEADERS = {"User-Agent": "Mozilla/5.0 (new-item-checker)"}


def get_products():
    """回傳 {商品代號: {"title": 名稱, "variants": {選項名稱: 有沒有貨}}}
    選項名稱像 "Blue / M"，顏色和尺寸都在裡面。"""
    r = requests.get(f"{SHOP}/products.json?limit=250", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return {
        p["handle"]: {
            "title": p["title"],
            "variants": {v["title"]: bool(v.get("available")) for v in p.get("variants", [])},
        }
        for p in r.json()["products"]
    }


def get_homepage_handles():
    """回傳首頁上有出現的商品代號（集合）。抓不到就回傳 None，當作這輪不判斷首頁。"""
    try:
        r = requests.get(SHOP, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return set(re.findall(r'href="/products/([a-z0-9\-]+)', r.text))
    except Exception as e:
        print("首頁抓取失敗，這輪跳過首頁判斷:", e)
        return None


def load_seen():
    """讀舊紀錄。舊版格式會自動轉成新格式：{代號: {"variants": {...}, "home": bool}}"""
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE, encoding="utf-8") as f:
        data = json.load(f)
    seen = {}
    if isinstance(data, list):
        for h in data:
            seen[h] = {"variants": {}, "home": None}
    else:
        for h, v in data.items():
            if isinstance(v, dict) and "variants" in v:
                seen[h] = {"variants": v["variants"], "home": v.get("home")}
            elif isinstance(v, dict):
                seen[h] = {"variants": v, "home": None}
            else:
                seen[h] = {"variants": {}, "home": None}
    return seen


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(seen.items())), f, indent=2, ensure_ascii=False)


def notify(title, body):
    # HTTP 標頭只能放英文，中文標題要先用 RFC 2047 格式編碼，ntfy 會自動解回中文
    encoded_title = "=?UTF-8?B?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?="
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": encoded_title, "Priority": "urgent", "Tags": "shopping_bags"},
        timeout=30,
    )


def link(h):
    return f"{SHOP}/products/{h}"


def main():
    current = get_products()
    home = get_homepage_handles()
    print(f"目前共 {len(current)} 個商品，首頁 {len(home) if home is not None else '?'} 個")

    seen = load_seen()
    if seen is None:
        save_seen({h: {"variants": p["variants"], "home": (h in home) if home is not None else None}
                   for h, p in current.items()})
        notify("SKYLRK 監控已啟動", f"已記錄 {len(current)} 個現有商品，之後有新品、新色、補貨、上首頁都會通知你。")
        print("第一次執行，已建立 seen.json")
        return

    new, new_variants, restocked, to_home = [], [], [], []

    for h, p in current.items():
        if h not in seen:
            new.append(h)                                   # 全新商品
            continue
        old = seen[h]["variants"]
        added = [s for s in p["variants"] if s not in old]  # 新顏色 / 新尺寸
        if added:
            new_variants.append((h, added))
        back = [s for s, ok in p["variants"].items() if ok and old.get(s) is False]
        if back:
            restocked.append((h, back))                     # 補貨
        if home is not None and h in home and seen[h]["home"] is False:
            to_home.append(h)                               # 本來不在首頁，現在上首頁了

    if new:
        notify(f"SKYLRK 新品 x{len(new)}",
               "\n\n".join(f"{current[h]['title']}\n{link(h)}" for h in new))
    if new_variants:
        notify(f"SKYLRK 新色/新尺寸 x{len(new_variants)}",
               "\n\n".join(f"{current[h]['title']}（{', '.join(s)}）\n{link(h)}" for h, s in new_variants))
    if restocked:
        notify(f"SKYLRK 補貨 x{len(restocked)}",
               "\n\n".join(f"{current[h]['title']}（{', '.join(s)}）\n{link(h)}" for h, s in restocked))
    if to_home:
        notify(f"SKYLRK 上首頁 x{len(to_home)}",
               "\n\n".join(f"{current[h]['title']}\n{link(h)}" for h in to_home))

    print("新品:", new, "| 新色:", new_variants, "| 補貨:", restocked, "| 上首頁:", to_home)

    # 更新紀錄
    for h, p in current.items():
        prev_home = seen.get(h, {}).get("home")
        seen[h] = {
            "variants": p["variants"],
            "home": (h in home) if home is not None else prev_home,
        }
    save_seen(seen)


if __name__ == "__main__":
    main()

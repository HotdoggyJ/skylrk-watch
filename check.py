"""
SKYLRK 新品 / 換色 / 新色 / 補貨 / 上首頁 通知
每次執行：抓商品清單 + 首頁 → 跟上次存的比對 → 有變化就推播到手機 (ntfy)
"""

import base64
import json
import os
import re
import requests

SHOP = "https://skylrk.com"
SEEN_FILE = "seen.json"
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
HEADERS = {"User-Agent": "Mozilla/5.0 (new-item-checker)"}


def get_products():
    """回傳 {代號: {"title": 名稱, "variants": {選項ID: {"title": 選項名稱, "available": 有沒有貨}}}}
    選項 ID 是 Shopify 給每個尺寸/顏色的內部編號，店家換色就算尺寸名稱一樣，ID 也會換。"""
    r = requests.get(f"{SHOP}/products.json?limit=250", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return {
        p["handle"]: {
            "title": p["title"],
            "variants": {
                str(v["id"]): {"title": v["title"], "available": bool(v.get("available"))}
                for v in p.get("variants", [])
            },
        }
        for p in r.json()["products"]
    }


def get_homepage_handles():
    """首頁上出現的商品代號。連結可能是 /products/xxx 或 https://skylrk.com/products/xxx，兩種都認。"""
    try:
        r = requests.get(SHOP, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return set(re.findall(r'/products/([a-z0-9\-]+)', r.text))
    except Exception as e:
        print("首頁抓取失敗，這輪跳過首頁判斷:", e)
        return None


def load_seen():
    """讀舊紀錄。任何舊格式都轉成新格式；舊格式沒有的欄位先留空，這一輪只記錄不比對。"""
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE, encoding="utf-8") as f:
        data = json.load(f)
    seen = {}
    if isinstance(data, list):
        data = {h: {} for h in data}
    for h, v in data.items():
        if isinstance(v, dict) and "variants" in v and all(isinstance(x, dict) for x in v["variants"].values()):
            seen[h] = {"title": v.get("title"), "variants": v["variants"], "home": v.get("home")}
        else:
            seen[h] = {"title": None, "variants": {}, "home": None}
    return seen


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(seen.items())), f, indent=2, ensure_ascii=False)


def notify(title, body):
    encoded_title = "=?UTF-8?B?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?="
    r = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": encoded_title, "Priority": "urgent", "Tags": "shopping_bags"},
        timeout=30,
    )
    print(f"ntfy 回應 {r.status_code}: {r.text[:200]}")
    r.raise_for_status()   # 發不出去就讓這一輪變紅，不要默默吞掉


def link(h):
    return f"{SHOP}/products/{h}"


def main():
    current = get_products()
    home = get_homepage_handles()
    print(f"目前共 {len(current)} 個商品，首頁 {len(home) if home is not None else '?'} 個")

    seen = load_seen()
    if seen is None:
        save_seen({h: {"title": p["title"], "variants": p["variants"],
                       "home": (h in home) if home is not None else None}
                   for h, p in current.items()})
        notify("SKYLRK 監控已啟動", f"已記錄 {len(current)} 個現有商品。")
        return

    new, changed, new_variants, restocked, to_home = [], [], [], [], []

    for h, p in current.items():
        if h not in seen:
            new.append(h)
            continue
        old = seen[h]
        old_vars = old["variants"]

        # 名稱換了 = 店家把這個商品換成另一個顏色/款式
        if old["title"] and old["title"] != p["title"]:
            changed.append((h, old["title"]))

        # 多出新的選項 ID = 新色 / 新尺寸（就算名稱跟舊的一樣也算）
        if old_vars:
            added = [v["title"] for vid, v in p["variants"].items() if vid not in old_vars]
            if added and not any(c[0] == h for c in changed):
                new_variants.append((h, added))

            # 同一個選項 ID 從沒貨變有貨 = 補貨
            back = [v["title"] for vid, v in p["variants"].items()
                    if vid in old_vars and old_vars[vid]["available"] is False and v["available"]]
            if back:
                restocked.append((h, back))

        if home is not None and h in home and old["home"] is False:
            to_home.append(h)

    if new:
        notify(f"SKYLRK 新品 x{len(new)}",
               "\n\n".join(f"{current[h]['title']}\n{link(h)}" for h in new))
    if changed:
        notify(f"SKYLRK 換新款 x{len(changed)}",
               "\n\n".join(f"{current[h]['title']}（原本是 {old_t}）\n{link(h)}" for h, old_t in changed))
    if new_variants:
        notify(f"SKYLRK 新色/新尺寸 x{len(new_variants)}",
               "\n\n".join(f"{current[h]['title']}（{', '.join(s)}）\n{link(h)}" for h, s in new_variants))
    if restocked:
        notify(f"SKYLRK 補貨 x{len(restocked)}",
               "\n\n".join(f"{current[h]['title']}（{', '.join(s)}）\n{link(h)}" for h, s in restocked))
    if to_home:
        notify(f"SKYLRK 上首頁 x{len(to_home)}",
               "\n\n".join(f"{current[h]['title']}\n{link(h)}" for h in to_home))

    print("新品:", new, "| 換新款:", changed, "| 新色:", new_variants, "| 補貨:", restocked, "| 上首頁:", to_home)

    for h, p in current.items():
        prev_home = seen.get(h, {}).get("home")
        seen[h] = {"title": p["title"], "variants": p["variants"],
                   "home": (h in home) if home is not None else prev_home}
    save_seen(seen)


if __name__ == "__main__":
    main()

"""M1号 STORES ショップの新商品・再入荷を検知してメールで通知する。

状態は state.json に保存し、前回との差分だけを通知する。
"""
import json
import os
import re
import smtplib
import sys
import time
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SHOP_URL = os.environ.get("SHOP_URL", "https://m1go.stores.jp/")
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
MAX_PAGES = 20
ITEM_RE = re.compile(r"/items/([0-9a-zA-Z]+)")
PRICE_RE = re.compile(r"[¥￥]\s?([\d,]+)")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def parse_items(html: str, base_url: str) -> dict:
    """ページ内の /items/<id> リンクを商品として抽出する。

    画像リンクと商品名リンクなど、同じ商品に複数のリンクがある場合は
    テキストをまとめてから判定する。
    """
    soup = BeautifulSoup(html, "html.parser")
    texts: dict[str, list[str]] = {}
    urls: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        m = ITEM_RE.search(a["href"])
        if not m:
            continue
        item_id = m.group(1)
        urls.setdefault(item_id, urljoin(base_url, a["href"]))
        t = a.get_text(" ", strip=True)
        if t:
            texts.setdefault(item_id, []).append(t)

    items = {}
    for item_id, url in urls.items():
        joined = " ".join(texts.get(item_id, []))
        sold_out = bool(re.search(r"SOLD\s*OUT|売り切れ|在庫なし", joined, re.I))
        price_m = PRICE_RE.search(joined)
        name = joined
        name = re.sub(r"SOLD\s*OUT|売り切れ|在庫なし", "", name, flags=re.I)
        name = PRICE_RE.sub("", name)
        name = re.sub(r"\boriginal\b", "", name)
        name = re.sub(r"\s+", " ", name).strip() or f"(商品 {item_id})"
        items[item_id] = {
            "name": name,
            "price": f"¥{price_m.group(1)}" if price_m else None,
            "sold_out": sold_out,
            "url": url,
        }
    return items


def fetch_all_items() -> dict:
    session = requests.Session()
    session.headers.update(HEADERS)
    all_items: dict = {}
    for page in range(1, MAX_PAGES + 1):
        url = SHOP_URL if page == 1 else urljoin(SHOP_URL, f"?page={page}")
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        items = parse_items(resp.text, SHOP_URL)
        new_ids = set(items) - set(all_items)
        if not new_ids:
            break  # 最終ページを過ぎた
        all_items.update(items)
        time.sleep(1)  # サーバーへの負荷を抑える
    return all_items


def diff(old: dict, new: dict) -> tuple[list, list]:
    added, restocked = [], []
    for item_id, item in new.items():
        prev = old.get(item_id)
        if prev is None:
            added.append(item)
        elif prev.get("sold_out") and not item["sold_out"]:
            restocked.append(item)
    return added, restocked


def fmt(item: dict) -> str:
    status = "SOLD OUT" if item["sold_out"] else (item["price"] or "価格不明")
    return f"・{item['name']}（{status}）\n  {item['url']}"


MAIL_READY_FILE = Path(os.environ.get("MAIL_READY_FILE", "mail_ready"))


def mail_configured() -> bool:
    return all(os.environ.get(k, "").strip() for k in ("SMTP_USER", "SMTP_PASS", "MAIL_TO"))


def summary(text: str) -> None:
    """Actions の実行結果画面（Summary）とログに表示する。"""
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")


def notify(subject: str, body: str) -> None:
    """メール設定があれば送信、なければ結果画面に表示するだけ。"""
    summary(f"### {subject}\n```\n{body}\n```")
    if mail_configured():
        send_mail(subject, body)
    else:
        print("（メール未設定のため送信をスキップしました）")


def send_mail(subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"].strip()
    password = os.environ["SMTP_PASS"].replace(" ", "").strip()
    to = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = os.environ.get("MAIL_FROM", user)
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)


def main() -> int:
    items = fetch_all_items()
    if not items:
        # 取得失敗やページ構造の変更。誤って「全部新商品」と通知しないよう止める
        print("ERROR: 商品が1件も取得できませんでした。ページ構造が変わった可能性があります。")
        return 1

    first_run = not STATE_FILE.exists()
    old = {} if first_run else json.loads(STATE_FILE.read_text(encoding="utf-8"))
    in_stock = sum(1 for i in items.values() if not i["sold_out"])
    summary(
        f"**取得した商品数: {len(items)}件（在庫あり {in_stock}件）**"
        + ("" if mail_configured() else "　※メール未設定")
    )

    # メール設定が入った最初の回に、確認メールを1通送る
    if mail_configured() and not MAIL_READY_FILE.exists():
        send_mail(
            "【M1号監視】メール通知を開始しました",
            f"{SHOP_URL} の監視結果をこのアドレスにお知らせします。\n"
            f"現在の商品数: {len(items)}件（在庫あり {in_stock}件）\n\n"
            "今後、新商品の追加や再入荷があればメールが届きます。",
        )
        MAIL_READY_FILE.write_text("ok\n", encoding="utf-8")
        summary("確認メールを送信しました")

    if first_run:
        summary(f"初回実行: {len(items)}件を記録しました（次回以降、差分を通知します）")
    else:
        added, restocked = diff(old, items)
        if added or restocked:
            parts = []
            if added:
                parts.append("■ 新商品\n" + "\n".join(fmt(i) for i in added))
            if restocked:
                parts.append("■ 再入荷\n" + "\n".join(fmt(i) for i in restocked))
            labels = (["新商品"] if added else []) + (["再入荷"] if restocked else [])
            notify(
                f"【M1号】{'・'.join(labels)}があります",
                "\n\n".join(parts) + f"\n\nショップ: {SHOP_URL}",
            )
        else:
            summary("変化なし")

    # 一覧から消えた商品も、再掲載に備えて記録を残しておく
    merged = {**old, **items}
    new_text = json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True)
    if first_run or new_text != json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True):
        STATE_FILE.write_text(new_text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

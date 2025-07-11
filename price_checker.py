import os
import time
import requests
from playwright.sync_api import sync_playwright

TELEGRAM_BOT_TOKEN = "7980048285:AAGs8i5wU3PP0rU5eux7KBsACQaYtTxI_aQ"
TELEGRAM_CHAT_ID = "8149536064"

PRODUCTS = [
    {
        "name": "ANC Headphones",
        "url": "https://www.lazada.co.th/products/pdp-i5351654991-s22744542965.html?c=&channelLpJumpArgs=..."
    },
    {
        "name": "Non ANC Headphones",
        "url": "https://www.lazada.co.th/products/pdp-i5238348189-s22238406877.html?c=&channelLpJumpArgs=..."
    },
    {
        "name": "Phillips Blade Replacement",
        "url": "https://www.lazada.co.th/products/pdp-i4553922937-s18538674511.html?c=&channelLpJumpArgs=..."
    },
]


CHECK_INTERVAL = 300  # 5 minutes

def send_telegram_message(text):
    print(f"[info] Sending Telegram message...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        resp = requests.post(url, data=data, timeout=10)
        resp.raise_for_status()
        print(f"[info] Telegram message sent successfully.")
    except Exception as e:
        print(f"[error] Failed to send Telegram message: {e}")

def get_last_price(product_name):
    filename = f"{product_name.replace(' ', '_').lower()}_last_price.txt"
    if os.path.isfile(filename):
        try:
            with open(filename, "r") as f:
                price_str = f.read().strip()
                return float(price_str)
        except Exception as e:
            print(f"[warn] Could not read last price file for {product_name}: {e}")
    return None

def save_last_price(product_name, price):
    filename = f"{product_name.replace(' ', '_').lower()}_last_price.txt"
    try:
        with open(filename, "w") as f:
            f.write(str(price))
    except Exception as e:
        print(f"[warn] Could not save last price file for {product_name}: {e}")

def fetch_price(page, url, product_name):
    short_url = url[:60] + "..." if len(url) > 60 else url
    print(f"[info] Navigating to {product_name} page: {short_url}")
    page.goto(url, timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except:
        print("[warn] Page may not be fully loaded yet.")

    selectors = [
        "span.pdp-price.pdp-price_type_normal.pdp-price_color_orange.pdp-price_size_xl",
        "span.pdp-price",
        "span._30jeq3",
        "div.product-price > span",
        "span.price-current",
        "span[data-price]",
        "span.price__current",
        "div.pdp-price_color_orange",
        "span.price-tag",
        "div.pdp-product-price",
        "span.pdp-price_type_highlight"
    ]
    for selector in selectors:
        elements = page.query_selector_all(selector)
        for el in elements:
            price_text = el.inner_text().strip().replace(",", "")
            price_text = price_text.replace("฿", "").replace("THB", "").strip()
            if price_text.replace('.', '', 1).isdigit():
                print(f"[info] Found price using selector '{selector}': {price_text}")
                return float(price_text)

    # Fallback scan ALL spans for anything that looks like a price
    all_spans = page.query_selector_all("span")
    for el in all_spans:
        text = el.inner_text().strip()
        if "฿" in text or text.replace('.', '', 1).isdigit():
            clean = text.replace("฿", "").replace(",", "").strip()
            if clean.replace('.', '', 1).isdigit():
                print(f"[info] Fallback found possible price in <span>: {clean}")
                return float(clean)

    print("[warn] Could not find price element with any strategy.")
    return None

def main():
    print("[info] Starting Lazada price tracker...")
    send_telegram_message("🚀 Lazada Price Tracker started! Monitoring products now.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        while True:
            for product in PRODUCTS:
                name = product["name"]
                url = product["url"]

                print(f"\n[info] Checking product: {name}")

                try:
                    price = fetch_price(page, url, name)
                    if price is None:
                        print(f"[warn] Could not find price for {name}")
                        continue
                    print(f"[info] Current price of '{name}': {price}")

                    last_price = get_last_price(name)
                    if last_price is None:
                        print(f"[info] No last price found for '{name}', saving current price.")
                        save_last_price(name, price)
                    elif price < last_price:
                        print(f"[alert] Price drop detected for '{name}'! Was {last_price}, now {price}")
                        msg = (
                            f"🚨 *Price drop for {name}!*\n"
                            f"Was: {last_price}\n"
                            f"Now: {price}\n"
                            f"[View product]({url})"
                        )
                        send_telegram_message(msg)
                        save_last_price(name, price)
                    else:
                        print(f"[info] No price drop for '{name}'. Last: {last_price}, Current: {price}")

                except Exception as e:
                    print(f"[error] Exception while checking '{name}': {e}")

            print(f"\n[info] Waiting {CHECK_INTERVAL} seconds before next check...\n")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()

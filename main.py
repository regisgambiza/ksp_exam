from playwright.sync_api import sync_playwright
import requests
import time

def ask_ollama(question, choices):
    prompt = f"""
You are a smart MCQ solver. Read the question and options carefully.
Question: {question}
Options:
{chr(10).join(f"{i+1}. {c}" for i, c in enumerate(choices))}
Respond ONLY with the choice number (like '1', '2', '3' or '4'). Do not explain or add any text.
"""

    payload = {
        "model": "deepseek-r1:8b",
        "prompt": prompt,
        "stream": False
    }

    try:
        r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=30)
        answer_text = r.json()["response"].strip()
        print(f"📝 Ollama raw response: {answer_text}")

        # Parse first valid number
        for token in answer_text.split():
            clean = ''.join(filter(str.isdigit, token))
            if clean.isdigit():
                number = int(clean)
                if 1 <= number <= len(choices):
                    return number
    except Exception as e:
        print(f"⚠️ Error communicating with Ollama: {e}")

    return None


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://ksp-7module.one.th")
        page.wait_for_load_state("networkidle")

        print("\nPage loaded. Please log in and navigate to the exam page.")
        input("✅ Press ENTER to start automation...")

        question_count = 0

        while True:
            time.sleep(1)  # short delay to let page settle

            # Get question
            question_selector = "div.container.app div.question p"
            try:
                question_text = page.locator(question_selector).nth(0).inner_text()
            except:
                print("❌ Could not find question on page.")
                break

            # Get choices
            choice_selector = "div.choice p"
            choices = page.locator(choice_selector).all_inner_texts()

            print(f"\n📌 Question: {question_text}")
            print("📋 Choices:")
            for idx, choice in enumerate(choices, start=1):
                print(f"{idx}. {choice}")

            # Send to ollama
            answer_number = ask_ollama(question_text, choices)
            print(f"✅ Ollama picked option: {answer_number}")

            if answer_number and 1 <= answer_number <= len(choices):
                # Click the button matching the choice
                try:
                    # The structure of your site: multiple divs.col-12 each with a button inside
                    # We pick the (answer_number-1)th because nth-child is not always reliable with multiple nested divs
                    buttons = page.locator("div.col-12 button")
                    buttons.nth(answer_number - 1).click()
                    print(f"🖱️ Clicked choice {answer_number}")
                except Exception as e:
                    print(f"❌ Failed to click choice {answer_number}: {e}")
                    break
            else:
                print("⚠️ Could not parse a valid answer from Ollama.")
                break

            time.sleep(1)  # look human

            # Click Next
            try:
                next_button_span = page.locator('span.v-btn__content', has_text="Next >")
                if next_button_span.is_visible():
                    next_button = next_button_span.locator("xpath=..")  # go to parent <button>
                    next_button.click()
                    question_count += 1
                    print(f"➡️ Clicked Next. Moving to question #{question_count+1}")
                    time.sleep(2)  # wait for next question to load
                else:
                    print("🚦 No more Next button found. Finished.")
                    break
            except:
                print("🚦 Next button not found. Finished.")
                break

        print(f"\n🎉 Completed {question_count+1} questions.")
        input("\nPress ENTER to close browser...")
        browser.close()


if __name__ == "__main__":
    run()

from playwright.sync_api import sync_playwright
import requests
import time
import os

def ask_ollama(question, choices, context):
    prompt = f"""
You are a smart MCQ solver. Here is the previous context of questions and answers:

{context}

Now answer the following question. Respond ONLY with the choice number (like '1', '2', '3' or '4'). Do not explain.

Question: {question}
Options:
{chr(10).join(f"{i+1}. {c}" for i, c in enumerate(choices))}
"""

    payload = {
        "model": "deepseek-r1:14b",
        "prompt": prompt,
        "stream": False
    }

    while True:  # keep trying until we succeed
        try:
            r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=500)
            r.raise_for_status()
            answer_text = r.json()["response"].strip()
            print(f"📝 Ollama raw response: {answer_text}")

            for token in answer_text.split():
                clean = ''.join(filter(str.isdigit, token))
                if clean.isdigit():
                    number = int(clean)
                    if 1 <= number <= len(choices):
                        return number, answer_text
            print("⚠️ Ollama did not return a valid option, retrying in 5 sec...")
            time.sleep(5)
        except requests.exceptions.RequestException as e:
            print(f"⚠️ HTTP error: {e}. Retrying in 5 sec...")
            time.sleep(5)
        except Exception as e:
            print(f"⚠️ General error communicating with Ollama: {e}. Retrying in 5 sec...")
            time.sleep(5)

def append_to_log(question, choices, picked_option, raw_ollama):
    with open("exam_log.txt", "a", encoding="utf-8") as f:
        if picked_option:
            f.write(f"{picked_option}\n")
        f.write("----------------------------------------\n")
        f.write(f"Question: {question}\n")
        for idx, choice in enumerate(choices, start=1):
            f.write(f"{idx}. {choice}\n")
        f.write(f"Ollama picked: {picked_option}, nothing else\n")
        f.write("----------------------------------------\n")

def get_context():
    if os.path.exists("exam_log.txt"):
        with open("exam_log.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            return ''.join(lines[-60:])
    return ""

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
            time.sleep(1)

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

            # Get previous context from log
            context = get_context()

            # Ask Ollama until it returns a valid number
            answer_number, raw_ollama = ask_ollama(question_text, choices, context)
            print(f"✅ Ollama picked option: {answer_number}")

            # Log to txt file in the minimal style
            append_to_log(question_text, choices, answer_number, raw_ollama)

            # Click the selected option
            if answer_number and 1 <= answer_number <= len(choices):
                try:
                    buttons = page.locator("div.col-12 button")
                    buttons.nth(answer_number - 1).click()
                    print(f"🖱️ Clicked choice {answer_number}")
                except Exception as e:
                    print(f"❌ Failed to click choice {answer_number}: {e}")
                    break
            else:
                print("⚠️ Could not parse a valid answer from Ollama.")
                break

            time.sleep(1)

            # Click Next
            try:
                next_button_span = page.locator('span.v-btn__content', has_text="Next >")
                if next_button_span.is_visible():
                    next_button = next_button_span.locator("xpath=..")
                    next_button.click()
                    question_count += 1
                    print(f"➡️ Clicked Next. Moving to question #{question_count+1}")
                    time.sleep(2)
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

import os
import re
import json
import csv
import time
import hashlib
import requests
from collections import Counter
from playwright.sync_api import sync_playwright
from scanner import extract_text_from_pics_and_get_score
import random


print("[debug] Imported all modules")

MEMORY_FILE = "question_memory.json"
CSV_FILE = "questions_log.csv"
STATE_FILE = "run_state.json"
TOTAL_QUESTIONS = 30
TELEGRAM_BOT_TOKEN = "<YOUR_TOKEN>"
TELEGRAM_CHAT_ID = "<YOUR_CHAT_ID>"

print("[debug] Config constants set")

def question_hash(text):
    print(f"[debug] Hashing question text: {text[:30]}...")
    return hashlib.md5(text.encode()).hexdigest()

def load_memory():
    print("[debug] Loading memory file")
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"[debug] Loaded memory: {len(data)} questions")
                return data
        except Exception as e:
            print(f"[debug] Failed to load memory: {e}")
    print("[debug] Starting with empty memory")
    return {}

def save_memory(memory):
    print(f"[debug] Saving memory with {len(memory)} questions")
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)

def append_to_csv(run_number, q_hash, question_text, options, picked_answer, score=None):
    print(f"[debug] Appending to CSV for question {q_hash}")
    rows = {}
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                rows[row[1]] = row
    rows[q_hash] = [
        str(run_number), q_hash, question_text, "|".join(options),
        str(picked_answer), str(score if score else "")
    ]
    while len(rows) > TOTAL_QUESTIONS:
        key = next(iter(rows))
        print(f"[debug] Removing oldest from CSV: {key}")
        del rows[key]
    with open(CSV_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["run", "question_hash", "question_text", "options", "picked_answer", "score"])
        for row in rows.values():
            writer.writerow(row)
    print("[debug] CSV updated")

def send_telegram_message(text):
    print(f"[debug] Sending Telegram message: {text[:50]}...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.post(url, data=data, timeout=10)
        print("[debug] Telegram message sent")
    except Exception as e:
        print(f"[debug] Failed to send Telegram message: {e}")

def load_state():
    print("[debug] Loading run state")
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                print(f"[debug] Loaded state: {state}")
                return state.get("run_number", 0), state.get("current_question_index", 0)
        except Exception as e:
            print(f"[debug] Failed to load state: {e}")
    print("[debug] Using fresh state")
    return 0, 0

def save_state(run_number, current_question_index):
    print(f"[debug] Saving state: run_number={run_number}, current_question_index={current_question_index}")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"run_number": run_number, "current_question_index": current_question_index}, f, indent=2)

def extract_from_page(page):
    print("[debug] Extracting question and choices from page")
    q_p = page.locator("div.container.app div.question p")
    q_p.first.wait_for(state="visible", timeout=5000)
    question_text = "\n".join(q_p.all_inner_texts())
    choices = page.locator("div.choice p").all_inner_texts()
    print(f"[debug] Found question with {len(choices)} choices")
    return question_text, choices

def click_answer(page, answer):
    print(f"[debug] Clicking answer option {answer}")
    locator = page.locator("div.col-12 button").nth(answer-1)
    locator.wait_for(state="visible", timeout=5000)
    locator.click()

def click_next_or_break(page):
    print("[debug] Trying to click Next > button")
    try:
        btn = page.locator('span.v-btn__content', has_text="Next >").first
        btn.wait_for(state="visible", timeout=5000)
        btn.click()
        print("[debug] Clicked Next >")
        return True
    except:
        print("[debug] No Next button found")
        return False

def complete_exam_and_get_score(page):
    print("[debug] Completing exam and capturing screenshots")
    pics_dir = "pics"
    os.makedirs(pics_dir, exist_ok=True)
    try:
        finish_btn = page.locator("xpath=//div[@id='app']/div/main/div/div/div[2]/div/div/div[2]/div[3]/div/nav/div/div/div/div[2]/div[2]/div/button/span")
        finish_btn.wait_for(state="visible", timeout=20000)
        finish_btn.click()
    except Exception as e:
        print(f"[debug] Error clicking finish button: {e}")

    page.wait_for_timeout(1000)

    try:
        confirm_btn = page.locator("xpath=//div[@id='app']/div[3]/div/div/div[3]/button[2]/span")
        confirm_btn.wait_for(state="visible", timeout=20000)
        confirm_btn.click()
    except Exception as e:
        print(f"[debug] Error clicking confirm button: {e}")

    start_time = time.time()
    count = 0
    while time.time() - start_time < 10:
        snap_path = os.path.join(pics_dir, f"popup_{count}.png")
        page.screenshot(path=snap_path)
        print(f"[debug] Saved screenshot {snap_path}")
        count += 1
        time.sleep(0.2)
    print("[debug] Calling OCR+AI to get score")
    return extract_text_from_pics_and_get_score()

def restart_exam(page):
    print("[debug] Restarting exam sequence (slow safe mode)")

    page.goto("https://ksp-7module.one.th/course/97083ed2-2b6c-47b1-8864-71dbe15a7514/learn")
    page.wait_for_timeout(2000)

    try:
        print("[debug] Waiting for first restart button")
        btn1 = page.locator("xpath=//div[@id='app']/div[2]/div/div[3]/div")
        btn1.wait_for(state="attached", timeout=60000)
        btn1.wait_for(state="visible", timeout=60000)
        btn1.click()
        page.wait_for_timeout(1000)

        print("[debug] Waiting for confirmation button")
        btn2 = page.locator("xpath=//div[@id='app']/div[2]/div/div[4]/div[2]/div[13]/button")
        btn2.wait_for(state="attached", timeout=60000)
        btn2.wait_for(state="visible", timeout=60000)
        btn2.click()
        page.wait_for_timeout(1000)

        print("[debug] Waiting for exam selection paragraph")
        para = page.locator("xpath=(.//*[normalize-space(text()) and normalize-space(.)='Final Exam Module 4 batch 2'])[1]/following::p[1]")
        para.wait_for(state="attached", timeout=60000)
        para.wait_for(state="visible", timeout=60000)
        para.click()
        page.wait_for_timeout(1000)

        print("[debug] Waiting for start exam button")
        btn3 = page.locator("xpath=//div[@id='app']/div[2]/div/div/div/div/div[3]/div/div[2]/div[2]/div/div/div[2]/button/span/h4")
        btn3.wait_for(state="attached", timeout=60000)
        btn3.wait_for(state="visible", timeout=60000)
        btn3.click()
        page.wait_for_timeout(3000)

    except Exception as e:
        print(f"[debug] Failed in restart sequence: {e}")
        # fallback: just reload to try again
        page.reload()
        page.wait_for_timeout(5000)

    print("[debug] Navigating to exam site")
    page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=60000)
    page.wait_for_timeout(3000)
    print("[debug] Restart sequence complete")

def perform_login(page):
    print("[debug] Performing login navigation")
    page.goto("https://ksp-7module.one.th/")
    time.sleep(1)

    print("[debug] Waiting for first button to be visible")
    btn = page.locator("xpath=//div[@id='app']/nav/div[3]/div/div/div[3]/button/span/h6")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking first button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for second button to be visible")
    btn = page.locator("xpath=//header[@id='menu1']/div/div/div/div[2]/a[3]/span/h6")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking second button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for input field 'id=input-201' to be attached")
    inp = page.locator("id=input-201")
    inp.wait_for(state="attached", timeout=60000)
    print("[debug] Filling input field 'id=input-201'")
    inp.fill("0047841106017")
    time.sleep(1)

    print("[debug] Waiting for password field 'id=password' to be attached")
    pwd = page.locator("id=password")
    pwd.wait_for(state="attached", timeout=60000)
    print("[debug] Filling password field 'id=password'")
    pwd.fill("Ednicewonder1984")
    time.sleep(1)

    print("[debug] Waiting for login button to be visible")
    btn = page.locator("xpath=//div[@id='loginPage']/div/div/form/div[2]/div/div/div[2]/div/button")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking login button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for submit button to be visible")
    btn = page.locator("xpath=//div[@id='loginPage']/div/div/form/button/span")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking submit button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for post-login menu button to be visible")
    btn = page.locator("xpath=//div[@id='app']/nav/div[3]/div/div/div[3]/button/span/h6")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking post-login menu button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for course menu button to be visible")
    btn = page.locator("xpath=//header[@id='menu1']/div/div/div/div[2]/a[2]/span/h6")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking course menu button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for Module 4 content area to be visible")
    area = page.locator("div.v-responsive__content", has_text="Module 4")
    area.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking Module 4 content area")
    area.click()
    time.sleep(1)

    print("[debug] Waiting for Module 4 button to be visible")
    btn = page.locator("xpath=//div[@id='courseDetail']/div/div/div[2]/div[2]/div/div[4]/div[3]/div/div/div/button/span/h6")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking Module 4 button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for next navigation button to be visible")
    btn = page.locator("xpath=//div[@id='app']/div[2]/div/div[3]/div")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking next navigation button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for confirmation button to be visible")
    btn = page.locator("xpath=//div[@id='app']/div[2]/div/div[4]/div[2]/div[13]/button")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking confirmation button")
    btn.click()
    time.sleep(1)

    print("[debug] Waiting for exam selection paragraph to be visible")
    para = page.locator("xpath=(.//*[normalize-space(text()) and normalize-space(.)='Final Exam Module 4 batch 2'])[1]/following::p[1]")
    para.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking exam selection paragraph")
    para.click()
    time.sleep(1)

    print("[debug] Waiting for exam start button to be visible")
    btn = page.locator("xpath=//div[@id='app']/div[2]/div/div/div/div/div[3]/div/div[2]/div[2]/div/div/div[2]/button/span/h4")
    btn.wait_for(state="visible", timeout=60000)
    print("[debug] Clicking exam start button")
    btn.click()
    time.sleep(5)

    print("[debug] Navigating to exam page")
    page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=600000)
    time.sleep(2)
    print("[debug] Login sequence completed.")


def run_greedy_search():
    print("[debug] Starting greedy search algorithm")
    memory = load_memory()
    run_number, current_question_index = load_state()
    num_options = 4

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        page = browser.new_page()
        perform_login(page)

        # Extract all questions once before main loop
        question_hashes, question_texts, question_choices_list = [], [], []
        print("[debug] Extracting all questions and choices")
        while len(question_hashes) < TOTAL_QUESTIONS:
            question_text, choices = extract_from_page(page)
            q_hash = question_hash(question_text)
            if q_hash not in memory:
                memory[q_hash] = {"tries": [], "current_option": 1, "best_option": 1, "best_score": 0}
            question_hashes.append(q_hash)
            question_texts.append(question_text)
            question_choices_list.append(choices)
            if not click_next_or_break(page):
                break

        total_questions = len(question_hashes)
        # Initialize answers based on best known option from memory
        answers = {}
        for qh in question_hashes:
            best_option = memory[qh]["best_option"]
            answers[qh] = best_option
            print(f"[debug] Initialized Q{qh[:8]} with option {best_option}")
        attempts = 0

        while True:
            # Run exam with current answers
            restart_exam(page)
            page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=60000)
            page.wait_for_timeout(2000)

            for i, qh in enumerate(question_hashes):
                click_answer(page, answers[qh])
                append_to_csv(run_number, qh, question_texts[i], question_choices_list[i], answers[qh])
                if i < total_questions - 1:
                    if not click_next_or_break(page):
                        print("[debug] No Next button when expected during main answering")
                        break
                time.sleep(0.5)

            score = complete_exam_and_get_score(page)
            attempts += 1
            print(f"[GreedySearch] Main run attempt {attempts} got score = {score}/{total_questions}")
            send_telegram_message(f"Attempt {attempts}: Score = {score}/{total_questions}")

            # Update CSV with score for all questions in this run
            for i, qh in enumerate(question_hashes):
                append_to_csv(run_number, qh, question_texts[i], question_choices_list[i], answers[qh], score)

            if score == total_questions:
                print("\n=== RESULTS SUMMARY ===")
                print(f"Total Questions: {total_questions}")
                print(f"Total Attempts: {attempts}")
                print("Answers:")
                for idx, qh in enumerate(question_hashes):
                    print(f"  Question {idx+1}: Option {answers[qh]}")
                save_memory(memory)
                browser.close()
                return

            # Greedy improvement phase
            improved = False
            question_order = question_hashes.copy()
            random.shuffle(question_order)

            for q_hash in question_order:
                best_option = answers[q_hash]
                best_score = score  # Start with the main run's score

                for opt in range(1, num_options + 1):
                    if opt == answers[q_hash]:
                        continue  # Skip the current option
                    trial_answers = answers.copy()
                    trial_answers[q_hash] = opt

                    restart_exam(page)
                    page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=60000)
                    page.wait_for_timeout(2000)

                    for i, qh in enumerate(question_hashes):
                        click_answer(page, trial_answers[qh])
                        if i < total_questions - 1:
                            if not click_next_or_break(page):
                                print("[debug] No Next button when expected during trial answering")
                                break
                        time.sleep(0.5)

                    trial_score = complete_exam_and_get_score(page)
                    attempts += 1
                    print(f"[GreedySearch] Trial {attempts}: Set Q{question_hashes.index(q_hash)+1} to {opt}, Score = {trial_score}/{total_questions}")
                    send_telegram_message(f"Trial {attempts}: Q{question_hashes.index(q_hash)+1} = {opt}, Score = {trial_score}/{total_questions}")

                    # Update memory with trial result
                    memory[q_hash]["tries"].append({"option": opt, "score": trial_score})
                    if trial_score > memory[q_hash]["best_score"]:
                        memory[q_hash]["best_score"] = trial_score
                        memory[q_hash]["best_option"] = opt

                    if trial_score > best_score:
                        best_score = trial_score
                        best_option = opt
                        improved = True

                    if trial_score == total_questions:
                        print("\n=== RESULTS SUMMARY ===")
                        print(f"Total Questions: {total_questions}")
                        print(f"Total Attempts: {attempts}")
                        print("Answers:")
                        for idx, qh in enumerate(question_hashes):
                            print(f"  Question {idx+1}: Option {trial_answers[qh]}")
                        save_memory(memory)
                        browser.close()
                        return

                if best_option != answers[q_hash]:
                    print(f"[GreedySearch] Improved Q{question_hashes.index(q_hash)+1} to Option {best_option}")
                    answers[q_hash] = best_option
                    memory[q_hash]["current_option"] = best_option
                    improved = True

            save_memory(memory)
            run_number += 1
            save_state(run_number, 0)

            if not improved:
                print("[GreedySearch] No further improvements found. Trying random perturbation.")
                # Randomly change one answer to escape potential local optimum
                q_hash = random.choice(question_hashes)
                current_opt = answers[q_hash]
                new_opt = random.choice([i for i in range(1, num_options + 1) if i != current_opt])
                answers[q_hash] = new_opt
                memory[q_hash]["current_option"] = new_opt
                print(f"[GreedySearch] Randomly set Q{question_hashes.index(q_hash)+1} to Option {new_opt}")


if __name__ == "__main__":
    print("[debug] Entry point reached")
    run_greedy_search()

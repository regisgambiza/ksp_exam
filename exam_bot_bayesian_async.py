import os
import re
import json
import csv
import time
import hashlib
import requests
import random
import math
from collections import Counter
from playwright.sync_api import sync_playwright, TimeoutError

# Config
MODEL_WEIGHTS = {
    "llama3.1:8b": 5
}
TOP_MODELS = ["llama3.1:8b"]
OLLAMA_URL = "http://localhost:11434/api/generate"
TIMEOUT = 90
MEMORY_FILE = "question_memory.json"
CSV_FILE = "questions_log.csv"
TOTAL_QUESTIONS = 30
RETRY_WAIT_SECONDS = 20
TELEGRAM_BOT_TOKEN = "7980048285:AAGs8i5wU3PP0rU5eux7KBsACQaYtTxI_aQ"
TELEGRAM_CHAT_ID = "8149536064"
STATE_FILE = "run_state.json"  # <-- added state file

# --- Utils
def question_hash(text):
    return hashlib.md5(text.encode()).hexdigest()

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                print("[debug] Memory file is empty, starting fresh")
                return {}
            try:
                print("[debug] Loaded memory file")
                return json.loads(content)
            except Exception as e:
                print(f"[debug] Memory file corrupted or invalid JSON: {e}, starting fresh")
                return {}
    print("[debug] No memory file found, starting fresh")
    return {}

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
    print("[debug] Saved memory to disk")

def append_to_csv(run_number, q_hash, question_text, options, picked_answer, score=None):
    rows = {}
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            for row in reader:
                if len(row) >= 2:
                    rows[row[1]] = row
    rows[q_hash] = [
        str(run_number),
        q_hash,
        question_text,
        "|".join(options),
        str(picked_answer),
        str(score if score is not None else "")
    ]
    while len(rows) > TOTAL_QUESTIONS:
        oldest_key = next(iter(rows))
        del rows[oldest_key]
    with open(CSV_FILE, "w", newline='', encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["run", "question_hash", "question_text", "options", "picked_answer", "score"])
        for row in rows.values():
            writer.writerow(row)
    print(f"[debug] Updated CSV, total questions logged: {len(rows)}")

def trim_memory(memory):
    if len(memory) > TOTAL_QUESTIONS:
        excess = len(memory) - TOTAL_QUESTIONS
        for _ in range(excess):
            oldest_key = next(iter(memory))
            del memory[oldest_key]
        print(f"[debug] Trimmed memory to latest {TOTAL_QUESTIONS} questions.")
        save_memory(memory)
        trim_memory(memory)

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

# --- Model interaction
def ask_model(model, prompt):
    print(f"[debug] Sending prompt to {model}")
    payload = {"model": model, "prompt": prompt, "stream": False}
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        text = r.json()["response"]
        print(f"[debug] Response from {model}: {text[:80]}...")
        return text
    except Exception as e:
        print(f"[debug] Error with {model}: {e}")
        return ""

def extract_number_and_confidence(text, num_choices=4):
    number, confidence = None, 0.5
    rank_match = re.search(r'rank[:=]\s*\[([^\]]+)]', text.lower())
    if rank_match:
        try:
            ranks = [int(x) for x in re.findall(r'\d+', rank_match.group(1)) if 1 <= int(x) <= num_choices]
            print(f"[debug] Parsed ranks: {ranks}")
        except:
            print("[debug] Failed to parse ranks")
    answer_match = re.search(r'answer[:=\s]*([1-4])', text.lower())
    if answer_match:
        number = int(answer_match.group(1))
    conf_match = re.search(r'confidence[:=\s]*([0-9]*\.?[0-9]+)', text.lower())
    if conf_match:
        try:
            c = float(conf_match.group(1))
            confidence = min(max(c / 100.0 if c > 1 else c, 0), 1)
        except:
            print(f"[debug] Invalid confidence string: {conf_match.group(1)}")
    print(f"[debug] Extracted: answer={number} confidence={confidence}")
    return number or 1, confidence

# --- Playwright helpers
def extract_from_page(page):
    q_p = page.locator("div.container.app div.question p")
    q_p.first.wait_for(state="visible", timeout=5000)
    question_text = "\n".join(q_p.all_inner_texts())
    choices = page.locator("div.choice p").all_inner_texts()
    print(f"[debug] Extracted question with {len(choices)} choices")
    return question_text, choices

def click_answer(page, answer):
    print(f"[debug] Clicking answer {answer}")
    page.locator("div.col-12 button").nth(answer-1).click()

def click_next_or_break(page):
    print("[debug] Trying to find Next button...")
    try:
        next_btn = page.locator('span.v-btn__content', has_text="Next >").first
        next_btn.wait_for(state="visible", timeout=5000)
        next_btn.click()
        print("[debug] Clicked Next >")
        return True
    except:
        print("[debug] No Next button found, end of questions.")
        return False

import os
import time
from scanner import extract_text_from_pics_and_get_score

def complete_exam_and_get_score(page):
    print("[debug] Completing exam by clicking final submits...")
    pics_dir = "pics"
    os.makedirs(pics_dir, exist_ok=True)
    try:
        page.locator("xpath=//div[@id='app']/div/main/div/div/div[2]/div/div/div[2]/div[3]/div/nav/div/div/div/div[2]/div[2]/div/button/span").click(timeout=20000)
        page.wait_for_timeout(1000)
        page.locator("xpath=//div[@id='app']/div[3]/div/div/div[3]/button[2]/span").click(timeout=20000)
        start_time = time.time()
        snapshot_count = 0
        while time.time() - start_time < 10:
            try:
                snap_path = os.path.join(pics_dir, f"popup_snapshot_{snapshot_count}.png")
                page.screenshot(path=snap_path)
                print(f"[debug] Saved screenshot {snap_path}")
                snapshot_count += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"[debug] Error during snapshot {snapshot_count}: {e}")
                time.sleep(0.5)
        print("[debug] Finished screenshots. Extracting score...")
        total_score = extract_text_from_pics_and_get_score()
        if total_score is not None:
            send_telegram_message(f"✅ Run completed with score: {total_score}/30 (from OCR+AI)")
            return total_score
        else:
            send_telegram_message("⚠️ Could not determine score from OCR+AI. Check pics folder.")
            return None
    except Exception as e:
        print(f"[error] Score extraction failed: {e}")
        page.screenshot(path="error_score_extraction.png", full_page=True)
        send_telegram_message(f"⚠️ Score extraction failed: {e}")
        raise

def restart_exam(page):
    print("[debug] Restarting exam...")
    page.goto("https://ksp-7module.one.th/course/97083ed2-2b6c-47b1-8864-71dbe15a7514/learn", timeout=60000)
    page.wait_for_timeout(1000)
    page.locator("xpath=//div[@id='app']/div[2]/div/div[3]/div").click()
    page.wait_for_timeout(500)
    page.locator("xpath=//div[@id='app']/div[2]/div/div[4]/div[2]/div[13]/button").click()
    page.wait_for_timeout(500)
    page.locator("xpath=(.//*[normalize-space(text()) and normalize-space(.)='Final Exam Module 4 batch 2'])[1]/following::p[1]").click()
    page.wait_for_timeout(500)
    page.locator("xpath=//div[@id='app']/div[2]/div/div/div/div/div[3]/div/div[2]/div[2]/div/div/div[2]/button/span/h4").click()
    page.wait_for_timeout(2000)
    page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=60000)
    page.wait_for_timeout(2000)
    print("[debug] Exam restarted successfully")

def perform_initial_login(page):
    print("[debug] Performing automated login sequence...")
    page.goto("https://ksp-7module.one.th/", timeout=60000)
    time.sleep(1)
    page.locator("xpath=//div[@id='app']/nav/div[3]/div/div/div[3]/button/span/h6").click()
    time.sleep(1)
    page.locator("xpath=//header[@id='menu1']/div/div/div/div[2]/a[3]/span/h6").click()
    time.sleep(1)
    page.locator("id=input-201").fill("0047841106017")
    time.sleep(1)
    page.locator("id=password").fill("Ednicewonder1984")
    time.sleep(1)
    page.locator("xpath=//div[@id='loginPage']/div/div/form/div[2]/div/div/div[2]/div/button").click()
    time.sleep(1)
    page.locator("xpath=//div[@id='loginPage']/div/div/form/button/span").click()
    time.sleep(1)
    page.locator("xpath=//div[@id='app']/nav/div[3]/div/div/div[3]/button/span/h6").click()
    time.sleep(1)
    page.locator("xpath=//header[@id='menu1']/div/div/div/div[2]/a[2]/span/h6").click()
    time.sleep(1)
    page.locator("div.v-responsive__content", has_text="Module 4").click()
    time.sleep(1)
    page.locator("xpath=//div[@id='courseDetail']/div/div/div[2]/div[2]/div/div[4]/div[3]/div/div/div/button/span/h6").click()
    time.sleep(1)
    page.locator("xpath=//div[@id='app']/div[2]/div/div[3]/div").click()
    time.sleep(1)
    page.locator("xpath=//div[@id='app']/div[2]/div/div[4]/div[2]/div[13]/button").click()
    time.sleep(1)
    page.locator("xpath=(.//*[normalize-space(text()) and normalize-space(.)='Final Exam Module 4 batch 2'])[1]/following::p[1]").click()
    time.sleep(1)
    page.locator("xpath=//div[@id='app']/div[2]/div/div/div/div/div[3]/div/div[2]/div[2]/div/div/div[2]/button/span/h4").click()
    time.sleep(5)
    page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=600000)
    time.sleep(2)
    print("[debug] Login sequence completed.")

# --- Persistent run state functions
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            run_number = state.get("run_number", 0)
            current_question_index = state.get("current_question_index", 0)
            print(f"[debug] Loaded run_number={run_number}, current_question_index={current_question_index}")
            return run_number, current_question_index
        except Exception as e:
            print(f"[debug] Failed to load state file: {e}")
    print("[debug] No state file found or failed to load, starting fresh")
    return 0, 0

def save_state(run_number, current_question_index):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "run_number": run_number,
                "current_question_index": current_question_index
            }, f, ensure_ascii=False, indent=2)
        print(f"[debug] Saved run_number={run_number}, current_question_index={current_question_index}")
    except Exception as e:
        print(f"[error] Failed to save state: {e}")

# --- Main brute-force rotation algorithm
def run_brute_force():
    memory = load_memory()
    run_number, current_question_index = load_state()
    num_options = 4

    with sync_playwright() as p:
        while True:  # Outer loop to restart on any error
            try:
                browser = p.chromium.launch(headless=False, channel="chrome")
                page = browser.new_page()
                perform_initial_login(page)

                while True:  # Your existing main loop
                    run_number += 1
                    print(f"\n=== Run {run_number} ===")
                    question_count = 0
                    chosen_answers = {}

                    question_hashes = []
                    question_texts = []
                    question_choices_list = []

                    # First pass: extract all questions and choices on exam pages
                    while question_count < TOTAL_QUESTIONS:
                        question_text, choices = extract_from_page(page)
                        q_hash = question_hash(question_text)

                        if q_hash not in memory:
                            memory[q_hash] = {"tries": [], "current_option": 1}

                        question_hashes.append(q_hash)
                        question_texts.append(question_text)
                        question_choices_list.append(choices)

                        question_count += 1
                        if not click_next_or_break(page):
                            break

                    # Reload to first question to answer
                    page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=60000)
                    time.sleep(2)

                    # Second pass: answer questions
                    for i in range(TOTAL_QUESTIONS):
                        q_hash = question_hashes[i]
                        q_text = question_texts[i]
                        choices = question_choices_list[i]

                        if i == current_question_index:
                            current_option = memory[q_hash].get("current_option", 1)
                            answer = current_option
                        else:
                            answer = 1  # safe default

                        click_answer(page, answer)
                        chosen_answers[q_hash] = (q_text, choices, answer)
                        append_to_csv(run_number, q_hash, q_text, choices, answer, None)

                        memory[q_hash].setdefault("tries", []).append({"answer": answer, "score": None})

                        if i < TOTAL_QUESTIONS - 1:
                            if not click_next_or_break(page):
                                print("[debug] Unexpected: no Next button when expected")
                                break
                        time.sleep(0.5)

                    save_memory(memory)
                    trim_memory(memory)

                    total_score = complete_exam_and_get_score(page)

                    # Update last tries' score
                    for q_hash in chosen_answers:
                        if memory[q_hash]["tries"]:
                            memory[q_hash]["tries"][-1]["score"] = total_score

                    # Update current option for current question
                    curr_q_hash = question_hashes[current_question_index]
                    memory[curr_q_hash]["current_option"] = memory[curr_q_hash].get("current_option", 1) + 1
                    if memory[curr_q_hash]["current_option"] > num_options:
                        memory[curr_q_hash]["current_option"] = 1
                        current_question_index += 1
                        if current_question_index >= TOTAL_QUESTIONS:
                            current_question_index = 0

                    save_memory(memory)
                    trim_memory(memory)
                    save_state(run_number, current_question_index)

                    print("\n=== SUMMARY OF QUESTIONS AFTER THIS RUN ===")
                    for idx, q_hash in enumerate(question_hashes, start=1):
                        print(f"[summary] Q{idx}: current_option = {memory[q_hash].get('current_option', 1)}, tries = {len(memory[q_hash].get('tries', []))}")

                    print(f"[INFO] Run {run_number} completed with score: {total_score}")
                    if total_score == 30:
                        print("🎉 Perfect score found!")
                        send_telegram_message("🎉 Perfect score of 30/30 achieved!")
                        return  # Stop after perfect score

                    restart_exam(page)
                    time.sleep(2)

            except Exception as e:
                print(f"[error] Exception caught: {e}")
                # Optional: save memory and state to not lose progress
                save_memory(memory)
                save_state(run_number, current_question_index)
                try:
                    browser.close()
                except:
                    pass
                print("[info] Restarting app from login after error...")
                time.sleep(10)  # Wait before restarting login



if __name__ == "__main__":
    run_brute_force()

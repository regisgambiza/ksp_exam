import os
import re
import json
import csv
import time
import hashlib
import requests
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
    # Load existing CSV rows into a dict by question_hash
    rows = {}
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            for row in reader:
                if len(row) >= 2:
                    rows[row[1]] = row

    # Update this question's row
    rows[q_hash] = [
        str(run_number),
        q_hash,
        question_text,
        "|".join(options),
        str(picked_answer),
        str(score if score is not None else "")
    ]

    # Trim to latest 30 entries
    while len(rows) > TOTAL_QUESTIONS:
        oldest_key = next(iter(rows))
        del rows[oldest_key]

    # Write back to CSV
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

def debate_alternative_answer(models, question, choices, exclude_answer):
    print(f"[debug] Debating next best answer excluding {exclude_answer}")
    prompt = f"""
Given this question, provide the next best possible answer **excluding option {exclude_answer}**.
Output ONLY in this format:
Answer: <number>
Confidence: <value>
Question:
{question}
Options:
{chr(10).join(f"{i+1}. {c}" for i, c in enumerate(choices))}
"""
    votes = []
    for model in models:
        text = ask_model(model, prompt)
        number, confidence = extract_number_and_confidence(text)
        if number != exclude_answer:
            votes.append((model, number, confidence))
    weighted = []
    for m, n, c in votes:
        weight = MODEL_WEIGHTS.get(m,1)
        weighted.extend([n] * int(weight * (c*2 +1)))
    counter = Counter(weighted)
    best = counter.most_common(1)[0][0] if counter else None
    print(f"[debug] Debate picked next best answer: {best}")
    return best

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

def click_submit_sequence(page):
    print("[debug] Clicking Submit sequence...")
    page.locator('span.v-btn__content', has_text="Submit").first.click()
    time.sleep(1)
    page.locator('span.v-btn__content', has_text="Submit").first.click()
    time.sleep(1)
    page.locator("div.lessons-btn").click()
    time.sleep(1)
    page.locator("button.v-expansion-panel-header").first.click()
    time.sleep(1)
    page.locator("div.v-list-item").first.click()
    print("[debug] Completed navigation to score page")

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
import re
from scanner import extract_text_from_pics_and_get_score  # import from scanner.py

def complete_exam_and_get_score(page):
    print("[debug] Completing exam by clicking final submits...")

    pics_dir = "pics"
    os.makedirs(pics_dir, exist_ok=True)

    try:
        # First submit click
        page.locator("xpath=//div[@id='app']/div/main/div/div/div[2]/div/div/div[2]/div[3]/div/nav/div/div/div/div[2]/div[2]/div/button/span").click(timeout=20000)
        page.wait_for_timeout(1000)

        # Second submit click
        page.locator("xpath=//div[@id='app']/div[3]/div/div/div[3]/button[2]/span").click(timeout=20000)
        print("[debug] Clicked second submit, starting intensive screenshot phase...")

        # Take screenshots for next 10 seconds
        start_time = time.time()
        snapshot_count = 0
        while time.time() - start_time < 10:
            try:
                snap_path = os.path.join(pics_dir, f"popup_snapshot_{snapshot_count}.png")
                page.screenshot(path=snap_path)
                print(f"[debug] Saved screenshot {snap_path}")
                snapshot_count += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"[debug] Error during snapshot {snapshot_count}: {e}")
                time.sleep(0.5)

        print("[debug] Finished taking screenshots. Now extracting score using OCR+AI from scanner.py...")

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
    try:
        # Navigate back to course page
        page.goto("https://ksp-7module.one.th/course/97083ed2-2b6c-47b1-8864-71dbe15a7514/learn", timeout=60000)
        page.wait_for_timeout(1000)
        
        # Click sequence to restart exam
        page.locator("xpath=//div[@id='app']/div[2]/div/div[3]/div").click()
        page.wait_for_timeout(500)
        page.locator("xpath=//div[@id='app']/div[2]/div/div[4]/div[2]/div[13]/button").click()
        page.wait_for_timeout(500)
        page.locator("xpath=(.//*[normalize-space(text()) and normalize-space(.)='Final Exam Module 4 batch 2'])[1]/following::p[1]").click()
        page.wait_for_timeout(500)
        page.locator("xpath=//div[@id='app']/div[2]/div/div/div/div/div[3]/div/div[2]/div[2]/div/div/div[2]/button/span/h4").click()
        page.wait_for_timeout(2000)
        
        # Open exam page
        page.goto("https://ksp-exam.alldemics.com/exam/4155", timeout=60000)
        page.wait_for_timeout(2000)
        print("[debug] Exam restarted successfully")
    except TimeoutError:
        print("[error] Failed to restart exam due to timeout")
        send_telegram_message("⚠️ Failed to restart exam due to timeout")
        raise
    except Exception as e:
        print(f"[error] Failed to restart exam: {e}")
        send_telegram_message(f"⚠️ Failed to restart exam: {e}")
        raise

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
    page.locator("xpath=//div[@id='app']/div/main/div/div/div[2]/div/div/div/div/header/div/div/div[4]/button/span")
    print("[debug] Login sequence completed.")

# --- Main logic
def run_brute_force():
    memory = load_memory()
    run_number = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        page = browser.new_page()
        perform_initial_login(page)
        current_question = 0
        while True:
            run_number += 1
            print(f"\n=== Run {run_number} ===")
            question_count = 0
            chosen_answers = {}
            while question_count < TOTAL_QUESTIONS:
                question_text, choices = extract_from_page(page)
                q_hash = question_hash(question_text)
                if q_hash not in memory:
                    print(f"[debug] New question detected, running models...")
                    votes = []
                    for model in MODEL_WEIGHTS:
                        prompt = f"""
You are an expert teacher. Rank options, then pick best.
Output: Rank: [...] Answer: <number> Confidence: <value>
Question:
{question_text}
Options:
{chr(10).join(f"{i+1}. {c}" for i,c in enumerate(choices))}
"""
                        text = ask_model(model, prompt)
                        number, confidence = extract_number_and_confidence(text)
                        votes.append((model, number, confidence))
                    weighted = []
                    for m, n, c in votes:
                        weighted.extend([n] * int(MODEL_WEIGHTS.get(m, 1) * (c * 2 + 1)))
                    counter = Counter(weighted)
                    best = counter.most_common(1)[0][0]
                    print(f"[debug] Initial consensus picked answer: {best}")
                    memory[q_hash] = {"best_answer": best, "tries": []}
                answer = memory[q_hash]["best_answer"]
                if question_count == current_question:
                    next_best = debate_alternative_answer(TOP_MODELS, question_text, choices, answer)
                    if next_best:
                        print(f"[debug] Trying alternative answer {next_best} for Q{question_count+1}")
                        answer = next_best
                click_answer(page, answer)
                time.sleep(0.5)
                chosen_answers[q_hash] = (question_text, choices, answer)
                append_to_csv(run_number, q_hash, question_text, choices, answer, None)
                save_memory(memory)
                trim_memory(memory)


                if not click_next_or_break(page):
                    print("[debug] No Next button found, assuming all questions answered.")
                    break
                question_count += 1
                time.sleep(1)
            total_score = complete_exam_and_get_score(page)

            # Update tries after exam completed
            for idx, (q_hash, (q_text, opts, ans)) in enumerate(chosen_answers.items(), start=1):
                mem = memory[q_hash]
                mem.setdefault("tries", []).append({"answer": ans, "score": total_score})

                scores_per_answer = {}
                for tr in mem["tries"]:
                    if tr["score"] is not None:
                        scores_per_answer.setdefault(tr["answer"], []).append(tr["score"])

                best = max(
                    (k for k in scores_per_answer if scores_per_answer[k]),
                    key=lambda x: sum(scores_per_answer[x]) / len(scores_per_answer[x]),
                    default=None
                )

                if best is not None:
                    mem["best_answer"] = best
                    avg_score_for_ans = sum(scores_per_answer.get(ans, [])) / len(scores_per_answer.get(ans, [])) if scores_per_answer.get(ans) else 0
                    avg_score_best = sum(scores_per_answer.get(best, [])) / len(scores_per_answer.get(best, [])) if scores_per_answer.get(best) else 0
                    status = "cracked" if ans == best else "not cracked"
                    explanation = (
                        "Current answer leads to best average score."
                        if status == "cracked" else
                        "Changing the answer did not improve the total score; continuing to try next answer."
                    )
                    whats_next = (
                        "move on to next question." if status == "cracked"
                        else "will try next best answer for this question in future runs."
                    )
                    print(f"[summary] Question {idx}")
                    print(f"[summary] Status: {status}")
                    print(f"[summary] Explanation: {explanation}")
                    print(f"[summary] What's next: {whats_next}")
                else:
                    print(f"[summary] Not enough data yet to determine best answer for question {idx}")

            save_memory(memory)
            trim_memory(memory)
            print(f"[INFO] Run {run_number} completed with score {total_score}/30")
            if total_score == 30:
                print("🎉 Perfect score found!")
                send_telegram_message("🎉 Perfect score of 30/30 achieved!")
                break
            current_question = (current_question + 1) % TOTAL_QUESTIONS
            restart_exam(page)







            

if __name__ == "__main__":
    run_brute_force()
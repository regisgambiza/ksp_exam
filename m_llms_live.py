import os
import re
import json
import time
import requests
from collections import Counter
from playwright.sync_api import sync_playwright

MODEL_WEIGHTS = {
    "llama3.1:8b": 5,
    "mistral:7b-instruct-q4_0": 4,
    "qwen2:7b-instruct-q4_0": 4,
    "gemma2:9b": 4,
    "deepseek-r1:8b": 3
}

TOP_MODELS = ["llama3.1:8b", "mistral:7b-instruct-q4_0", "qwen2:7b-instruct-q4_0"]
OLLAMA_URL = "http://localhost:11434/api/generate"
TIMEOUT = 90

def ask_model(model, prompt):
    print(f"[debug] Sending prompt to {model}")
    payload = {"model": model, "prompt": prompt, "stream": False}
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        text = r.json()["response"]
        return text
    except Exception as e:
        print(f"[debug] Error with {model}: {e}")
        return ""

def extract_number_and_confidence(text, num_choices=4):
    number, confidence = None, 0.5
    ranks = []

    # Try to extract ranking
    rank_match = re.search(r'rank[:=]\s*\[([^\]]+)\]', text.lower())
    if rank_match:
        try:
            ranks = [int(x) for x in re.findall(r'\d+', rank_match.group(1)) if 1 <= int(x) <= num_choices]
            print(f"[debug] Parsed ranks: {ranks}")
        except:
            pass

    # Extract final picked answer
    answer_match = re.search(r'answer[:=\s]*([1-4])', text.lower())
    if answer_match:
        number = int(answer_match.group(1))

    # Extract confidence
    conf_match = re.search(r'confidence[:=\s]*([0-9]*\.?[0-9]+)', text.lower())
    if conf_match:
        try:
            c = float(conf_match.group(1))
            confidence = min(max(c / 100.0 if c > 1 else c, 0), 1)
        except:
            print(f"[debug] Invalid confidence string: {conf_match.group(1)}")

    print(f"[debug] Parsed: answer={number} conf={confidence}")
    return number or 1, confidence


def weighted_majority_vote_with_confidence(votes):
    weighted = []
    for model, number, confidence in votes:
        weight = MODEL_WEIGHTS.get(model, 1)
        weighted.extend([number] * int(weight * (confidence * 2 + 1)))
    counter = Counter(weighted)
    most_common = counter.most_common(1)[0][0] if counter else None
    print(f"[debug] Weighted vote result: {most_common} counts={dict(counter)}")
    return most_common, counter

def debate_prompt(question, choices, previous_votes):
    votes_summary = ", ".join(f"{m}:{v}" for m, v, _ in previous_votes)
    return f"""
Given the question and conflicting votes: {votes_summary}
Decide the single best option. Output:
Answer: <number>
Confidence: <value>

Question: {question}
Options:
{chr(10).join(f"{i+1}. {c}" for i, c in enumerate(choices))}
"""

def append_to_log(q_num, question_text, choices, picked_answer):
    with open("exam_log.txt", "a", encoding="utf-8") as f:
        f.write(f"Question {q_num}\n")
        f.write(f"Question text: {question_text}\n")
        f.write("Options:\n")
        for i, c in enumerate(choices, 1):
            f.write(f"{i}. {c}\n")
        f.write(f"Picked answer: {picked_answer}\n")
        f.write("--------------------------------------\n")
    print(f"[debug] Logged question {q_num}")

def ask_multiple_models(question, choices):
    votes = []
    for model in MODEL_WEIGHTS.keys():
        prompt = f"""
            You are an expert Thai curriculum and assessment teacher.

            Read the question carefully, and analyze each option.
            Rank the following options from most appropriate to least appropriate for the question.

            Then pick the best option.

            Output ONLY in this format:
            Rank: [<ranked_option_numbers>]
            Answer: <number>
            Confidence: <value between 0 and 1>

            Question:
            {question}

            Options:
            {chr(10).join(f"{i+1}. {c}" for i, c in enumerate(choices))}
            """

        text = ask_model(model, prompt)
        number, confidence = extract_number_and_confidence(text)
        votes.append((model, number, confidence))
    return votes

def ask_top_models_only(question, choices):
    votes = []
    for model in TOP_MODELS:
        print(f"[debug] Sending debate prompt to {model}")
        debate_text = debate_prompt(question, choices, [])
        text = ask_model(model, debate_text)
        number, confidence = extract_number_and_confidence(text)
        votes.append((model, number, confidence))
    return votes

def run():
    with sync_playwright() as p:
        try:
            # Try to launch Chrome browser using Playwright's channel argument
            browser = p.chromium.launch(headless=False, channel="chrome")
            print("[debug] Launched Chrome via Playwright channel='chrome'.")
        except Exception as e:
            print(f"[debug] Could not launch Chrome channel, falling back to default Chromium: {e}")
            browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        for attempt in range(3):
            try:
                page.goto("https://ksp-7module.one.th", wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as e:
                print(f"[debug] Retry {attempt+1}/3 due to: {e}")
                time.sleep(5)

        input("[debug] Please login and press ENTER...")

        question_count = 0
        while question_count < 30:
            try:
                question_paragraphs = page.locator("div.container.app div.question p")
                question_paragraphs.first.wait_for(state="visible", timeout=5000)
                all_texts = question_paragraphs.all_inner_texts()
                question_text = "\n".join(all_texts)
                print(f"[debug] Extracted question paragraphs: {all_texts}")
                print(f"[debug] Combined question text: {question_text[:200]}...")
                choices = page.locator("div.choice p").all_inner_texts()

                question_count += 1
                print(f"[debug] Navigating to question {question_count}")

                votes = ask_multiple_models(question_text, choices)
                answer, counts = weighted_majority_vote_with_confidence(votes)

                if len(set(num for _, num, _ in votes)) > 1:
                    print("[debug] Debate triggered")
                    debate_votes = ask_top_models_only(question_text, choices)
                    answer, counts = weighted_majority_vote_with_confidence(debate_votes)

                if len(set(counts.keys())) > 1:
                    print("[debug] Tie-break triggered")
                    final_votes = ask_top_models_only(question_text, choices)
                    answer, counts = weighted_majority_vote_with_confidence(final_votes)

                append_to_log(question_count, question_text, choices, answer)
                print(f"[debug] Final picked answer: {answer}")

                if answer and 1 <= answer <= len(choices):
                    page.locator("div.col-12 button").nth(answer - 1).click()
                    time.sleep(1)
                    next_button_span = page.locator('span.v-btn__content', has_text="Next >")
                    if next_button_span.count() > 0:
                        next_button_span.locator("xpath=.." ).click()
                    else:
                        break
                else:
                    break

                time.sleep(2)

            except Exception as e:
                print(f"[debug] Exception: {e}")
                break

        input("Press ENTER to exit...")
        browser.close()
        print("[debug] Finished session")

if __name__ == "__main__":
    run()

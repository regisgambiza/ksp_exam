from navigation import perform_login, extract_questions, answer_question, complete_exam_and_get_score, restart_exam
from memory import load_memory, save_memory, load_state, save_state, append_to_csv, trim_memory
from telegram_notify import send_telegram_message
import time

def run_greedy_search():
    memory = load_memory()
    run_number, current_index = load_state()
    print("[greedy] Starting search with run_number =", run_number)
    # Example of control loop
    while True:
        run_number += 1
        print(f"[greedy] Run {run_number} starting...")
        perform_login()
        questions = extract_questions()
        for i, (q_hash, question_text, options) in enumerate(questions):
            current_option = memory.get(q_hash, {}).get("current_option", 1)
            answer_question(i, current_option)
            append_to_csv(run_number, q_hash, question_text, options, current_option)
        total_score = complete_exam_and_get_score()
        for q_hash, *_ in questions:
            memory.setdefault(q_hash, {}).setdefault("tries", []).append({"score": total_score})
        # increment option for current question
        curr_q_hash = questions[current_index][0]
        memory[curr_q_hash]["current_option"] = memory[curr_q_hash].get("current_option", 1) + 1
        if memory[curr_q_hash]["current_option"] > 4:
            memory[curr_q_hash]["current_option"] = 1
            current_index += 1
            if current_index >= len(questions):
                current_index = 0
        save_memory(memory)
        save_state(run_number, current_index)
        trim_memory(memory)
        if total_score >= 30:
            send_telegram_message(f"🎉 Perfect score of {total_score}/30!")
            break
        restart_exam()
        time.sleep(2)

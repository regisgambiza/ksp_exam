import json, os, csv
MEMORY_FILE = "question_memory.json"
STATE_FILE = "run_state.json"
CSV_FILE = "questions_log.csv"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memory(mem):
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            s = json.load(f)
            return s.get("run_number", 0), s.get("current_index", 0)
    return 0, 0

def save_state(run_number, current_index):
    with open(STATE_FILE, "w") as f:
        json.dump({"run_number": run_number, "current_index": current_index}, f, indent=2)

def append_to_csv(run, q_hash, text, options, picked):
    header = ["run","question_hash","question_text","options","picked_answer"]
    rows = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE) as f:
            r = csv.reader(f)
            _ = next(r, None)
            rows = list(r)
    rows.append([run, q_hash, text, "|".join(options), picked])
    with open(CSV_FILE,"w",newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

def trim_memory(mem):
    while len(mem) > 30:
        mem.pop(next(iter(mem)))

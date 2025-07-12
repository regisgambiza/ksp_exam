import json
from collections import defaultdict

def deduce_best_options(question_data):
    best_options = {}

    for question_id, data in question_data.items():
        option_stats = defaultdict(lambda: {"total_score": 0, "count": 0})

        # Gather scores for each option
        for attempt in data["tries"]:
            option = attempt["answer"]
            score = attempt["score"]
            option_stats[option]["total_score"] += score
            option_stats[option]["count"] += 1

        # Compute average scores
        option_averages = {}
        for option, stats in option_stats.items():
            avg_score = stats["total_score"] / stats["count"]
            option_averages[option] = avg_score

        # Find best option (highest average score)
        best_option = max(option_averages, key=lambda k: option_averages[k])

        best_options[question_id] = {
            "best_option": best_option,
            "average_scores": option_averages,
            "tries": {opt: option_stats[opt]["count"] for opt in option_stats}
        }

    return best_options


if __name__ == "__main__":
    # Load your JSON file
    with open("question_memory.json", "r") as f:
        question_data = json.load(f)

    # Deduce best options
    best_answers = deduce_best_options(question_data)

    print("=== BEST OPTIONS FOR EACH QUESTION ===\n")
    for idx, (qid, info) in enumerate(best_answers.items(), start=1):
        print(f"Question {idx}: Answer = {info['best_option']}")

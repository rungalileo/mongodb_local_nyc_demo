import csv
import json

input_file =  "/Users/pratyushaduvvuri/Downloads/escalations_dataset.csv"

output_file = "/Users/pratyushaduvvuri/Downloads/cleaned_escalations_dataset.csv"

with open(input_file, newline="", encoding="utf-8") as f_in, \
     open(output_file, "w", newline="", encoding="utf-8") as f_out:
    
    reader = csv.DictReader(f_in)
    writer = csv.DictWriter(f_out, fieldnames=["input", "escalated"])
    writer.writeheader()

    for row in reader:
        # Extract user_query from JSON string in "input" column
        try:
            parsed = json.loads(row["input"])
            user_query = parsed.get("state", {}).get("user_query", "")
        except Exception:
            user_query = ""

        # Escalated if metric column == 1.0
        # Strip column names to be safe
        metrics_val = row.get("metrics/Escalations Count", "").strip() or \
                      row.get("metrics/Escalations Count ", "").strip()

        try:
            escalated = 1 if float(metrics_val) == 1.0 else 0
        except Exception:
            escalated = 0

        writer.writerow({"input": user_query, "escalated": escalated})

print(f"Cleaned dataset saved to {output_file}")
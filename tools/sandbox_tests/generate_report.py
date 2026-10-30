import json

t1 = json.load(open("test_1_results.json"))
t2 = json.load(open("test_2_results.json"))

all_steps = t1 + t2
print(f"Total steps: {len(all_steps)}")

markdown_table = []
markdown_table.append("| Step | HTTP Status | PayPal Status or Issue | Debug ID | PASS or FAIL |")
markdown_table.append("| :--- | :---: | :--- | :---: | :---: |")

for r in all_steps:
    step = r["step"]
    http_status = r["http_status"]
    status_or_issue = r["status_or_issue"]
    debug_id = r["debug_id"]
    pf = r["pass_fail"]
    markdown_table.append(f"| {step} | {http_status} | {status_or_issue} | `{debug_id}` | **{pf}** |")

table_str = "\n".join(markdown_table)
with open("test_summary_table.md", "w") as f:
    f.write(table_str)

print(table_str)

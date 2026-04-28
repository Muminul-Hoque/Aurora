import csv
import json
import os
import re

CSV_PATH  = 'tracker.csv'
HTML_PATH = 'dashboard.html'


def sync():
    """
    Reads the outreach tracker CSV and injects its data into the
    dashboard HTML file so the web UI stays up to date.
    """
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found.")
        return

    data = []
    with open(CSV_PATH, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean_row = {}
            for k, v in row.items():
                if k:
                    # Remove non-alphanumeric chars from keys for JS safety
                    clean_key = re.sub(r'[^a-zA-Z]', '', str(k))
                    clean_row[clean_key] = v
            data.append(clean_row)

    if not os.path.exists(HTML_PATH):
        print(f"Error: {HTML_PATH} not found. Please create it first.")
        return

    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        html_content = f.read()

    start_marker = '<script id="prof-data" type="application/json">'
    end_marker   = '</script>'

    start_pos = html_content.find(start_marker)
    if start_pos == -1:
        print("Error: Could not find data start marker in HTML.")
        return

    start_data_pos = start_pos + len(start_marker)
    end_data_pos   = html_content.find(end_marker, start_data_pos)

    if end_data_pos == -1:
        print("Error: Could not find data end marker in HTML.")
        return

    json_data    = json.dumps(data, indent=4)
    updated_html = html_content[:start_data_pos] + json_data + html_content[end_data_pos:]

    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(updated_html)

    print(f"Successfully synced {len(data)} entries to the dashboard!")


if __name__ == "__main__":
    sync()

import requests
import urllib.parse
import json

token = "c7cda0a41de3446abf92b8b0154c65e7922123609fe"

targetUrl = urllib.parse.quote("https://in.bookmyshow.com/movies/kanpur/dhadak-2/buytickets/ET00399488/20250810")
url = f"http://api.scrape.do/?token={token}&url={targetUrl}"

html = requests.get(url).text

marker = "window.__INITIAL_STATE__ ="
start = html.find(marker)
if start == -1:
    raise RuntimeError("Could not find __INITIAL_STATE__ in HTML")

start += len(marker)

# Extract JSON using brace counting
brace_count = 0
in_string = False
escaped = False
json_start = None
for i, ch in enumerate(html[start:], start=start):
    if ch == '"' and not escaped:
        in_string = not in_string
    elif ch == "\\" and in_string:
        escaped = not escaped
        continue
    else:
        escaped = False

    if not in_string:
        if ch == '{':
            if brace_count == 0:
                json_start = i
            brace_count += 1
        elif ch == '}':
            brace_count -= 1
            if brace_count == 0 and json_start is not None:
                json_str = html[json_start:i+1]
                data = json.loads(json_str)
                with open("dhadak2(!).json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print("✅ Extracted and saved JSON to bms_state.json")
                break
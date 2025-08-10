import requests
import urllib.parse
import json
from bs4 import BeautifulSoup

token = "c7cda0a41de3446abf92b8b0154c65e7922123609fe"

def slugify(text: str) -> str:
    return text.strip().lower().replace(" ", "-")

def get_movie_venue_details(movie_name: str, target_date: str, movie_id: str, city: str) -> str:
    city_slug = slugify(city)
    movie_slug = slugify(movie_name)

    # Step 1: Find movie_id if not provided
    if not movie_id:
        search_url = f"https://in.bookmyshow.com/explore/movies-{city_slug}"
        encoded_url = urllib.parse.quote(search_url)
        api_url = f"http://api.scrape.do/?token={token}&url={encoded_url}"
        resp = requests.get(api_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        movie_id = None
        for a in soup.find_all("a", href=True):
            if f"/movies/{city_slug}/" in a["href"] and movie_slug in a["href"]:
                parts = a["href"].rstrip("/").split("/")
                if len(parts) >= 5:
                    movie_id = parts[-1]
                    break
        if not movie_id:
            raise ValueError(f"Movie '{movie_name}' not found in {city}.")

    # Step 2: Construct buytickets URL
    target_url = f"https://in.bookmyshow.com/movies/{city_slug}/{movie_slug}/buytickets/{movie_id}/{target_date}"
    encoded_target_url = urllib.parse.quote(target_url)
    scrape_url = f"http://api.scrape.do/?token={token}&url={encoded_target_url}"

    # Step 3: Extract JSON from _INITIAL_STATE_
    html = requests.get(scrape_url).text
    marker = "__INITIAL_STATE__"
    start = html.find(marker)
    if start == -1:
        raise RuntimeError("Could not find _INITIAL_STATE_ in HTML")

    start += len(marker)
    # Skip until first '{'
    while start < len(html) and html[start] not in '{':
        start += 1

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
                    break

    # Step 4: Extract venue and showtime details
    results = []
    show_dates = data.get("showtimesByEvent", {}).get("showDates", {})
    date_obj = show_dates.get(target_date, {})
    widgets = date_obj.get("dynamic", {}).get("data", {}).get("showtimeWidgets", [])

    for widget in widgets:
        if widget.get("type") == "groupList" and widget.get("id") == "List_1":
            for group in widget.get("data", []):
                if group.get("type") == "venueGroup" and group.get("id") == "Venue_GROUP_1":
                    for venue in group.get("data", []):
                        if venue.get("type") == "venue-card":
                            vdata = venue.get("additionalData", {})
                            venue_name = vdata.get("venueName")
                            venue_code = vdata.get("venueCode")
                            theatre_info = {
                                "venueName": venue_name,
                                "venueCode": venue_code,
                                "shows": []
                            }
                            for show in venue.get("showtimes", []):
                                show_time = show.get("title") or show.get("showTime")
                                session_id = show.get("additionalData", {}).get("sessionId")
                                categories = [
                                    {
                                        "seatType": cat.get("priceDesc"),
                                        "price": cat.get("curPrice")
                                    }
                                    for cat in show.get("additionalData", {}).get("categories", [])
                                ]
                                theatre_info["shows"].append({
                                    "time": show_time,
                                    "sessionId": session_id,
                                    "categories": categories
                                })
                            results.append(theatre_info)

    final_output = {
        "movieId": movie_id,
        "venues": results
    }

    return json.dumps(final_output, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    # Replace these values with what you want to test
    movie_name = "son of sardaar 2"
    target_date = "20250811"
    movie_id = ""  # empty string to auto-detect
    city = "Kanpur"

    result_json = get_movie_venue_details(movie_name, target_date, movie_id, city)
    print(result_json)

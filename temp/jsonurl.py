import requests
import urllib.parse
import json
import re
import difflib



def fetch_and_extract_mapping(movie_name,movie_id, city, target_date):
    city_slug = slugify(city)
    movie_slug = slugify(movie_name)
    """Fetches BookMyShow _INITIAL_STATE_ JSON and extracts venue→id, time→session_id mapping."""
    # Step 1: Fetch _INITIAL_STATE_ JSON
    target_url = f"https://in.bookmyshow.com/movies/{city_slug}/{movie_slug}/buytickets/{movie_id}/{target_date}"
    encoded_url = urllib.parse.quote(target_url)
    url = f"http://api.scrape.do/?token={token}&url={encoded_url}"

    html = requests.get(url).text
    marker = "__INITIAL_STATE__"
    start = html.find(marker)
    if start == -1:
        raise RuntimeError("Could not find _INITIAL_STATE_ in HTML")

    start += len(marker)

    # Extract JSON using brace counting
    brace_count = 0
    in_string = False
    escaped = False
    json_start = None
    json_data = None
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
                    json_data = json.loads(json_str)
                    with open("bms_state.json", "w", encoding="utf-8") as f:
                        json.dump(json_data, f, indent=2, ensure_ascii=False)
                    print("✅ Extracted and saved JSON to bms_state.json")
                    break

    if not json_data:
        raise RuntimeError("Could not parse _INITIAL_STATE_ JSON")

    # Step 2: Extract mapping list
    mapping_list = []
    show_dates = json_data.get("showtimesByEvent", {}).get("showDates", {})
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

                            for show in venue.get("showtimes", []):
                                show_time = show.get("title") or show.get("showTime")
                                session_id = show.get("additionalData", {}).get("sessionId")
                                mapping_list.append({
                                    "venueName": venue_name,
                                    "venueCode": venue_code,
                                    "time": show_time,
                                    "sessionId": session_id
                                })

    return json_data, mapping_list

json_data, mapping = fetch_and_extract_mapping("saiyaara","ET00447951", "kanpur", "20250810")
print(mapping)

import difflib

def find_session(mapping_list, venue_name, show_time, cutoff=0.6):
    """
    Finds sessionId and venueCode for given venueName and time using fuzzy matching.
    cutoff: similarity threshold (0 to 1), higher = stricter match.
    """
    venue_name_lower = venue_name.strip().lower()
    show_time_lower = show_time.strip().lower()

    # Get all unique venue names from mapping_list
    venue_names_in_mapping = [entry["venueName"].strip().lower() for entry in mapping_list]

    # Find closest match to user's input
    closest_matches = difflib.get_close_matches(venue_name_lower, venue_names_in_mapping, n=1, cutoff=cutoff)

    if not closest_matches:
        return None  # No similar venue found

    best_match = closest_matches[0]

    # Now search for entry with the best-matching venue name and exact time
    for entry in mapping_list:
        if entry["venueName"].strip().lower() == best_match and entry["time"].strip().lower() == show_time_lower:
            return {
                "sessionId": entry["sessionId"],
                "venueCode": entry["venueCode"],
                "matchedVenue": entry["venueName"]  # Optional: show the corrected venue name
            }

    return None  # No time match found

# Example usage:
result = find_session(mapping, "inox z square", "06:55 PM")  # Imperfect name
if result:
    print(f"Matched Venue: {result['matchedVenue']}")
    print(f"Session ID: {result['sessionId']}, Venue Code: {result['venueCode']}")
else:
    print("No matching show found")

def f(city_slug, movie_id, venue_id, session_id, date):
    print(f"https://in.bookmyshow.com/movies/{city_slug}/seat-layout/{movie_id}/{venue_id}/{session_id}/{date}")
    return f"https://in.bookmyshow.com/movies/{city_slug}/seat-layout/{movie_id}/{venue_id}/{session_id}/{date}"
f("kanpur", "ET00447951", "INZS", "70587", "20250810")

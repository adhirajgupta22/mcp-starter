import requests
import urllib.parse
import json
import re
import difflib
import asyncio
from typing import Annotated
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp import ErrorData, McpError
from mcp.server.auth.provider import AccessToken
from mcp.types import TextContent, ImageContent, INVALID_PARAMS, INTERNAL_ERROR
from pydantic import BaseModel, Field, AnyUrl
import re

import requests
from bs4 import BeautifulSoup
import urllib.parse
import json
from typing import Annotated
from pydantic import Field

import urllib.parse

import markdownify
import httpx
import readabilipy

token = "c7cda0a41de3446abf92b8b0154c65e7922123609fe"
def slugify(text):
    return re.sub(r'[^a-z0-9-]', '', re.sub(r'\s+', '-', text.strip().lower()))

@mcp.tool(description=(
    "This tool is for the booking of movie tickets. It Generates a direct seat-layout link on BookMyShow for booking tickets. "
    "Inputs must be provided exactly as specified: 'movie_id','movie_name', 'venue_name', 'time', 'date' (YYYYMMDD), and 'city' (full, correct name). "
    "The returned link takes the user directly to the seat selection page. "
    "Note: movie_id, session_id, and venue_id are internal identifiers and must NOT be shown to the user."
))
async def book_movie_tickets(
    movie_id: Annotated[str, Field(description="The exact internal movie ID (e.g., ET00440409)")],
    venue_n : Annotated[str, Field(description="The exact venue name (e.g., INOX)")],
    movie_name: Annotated[str, Field(description="The exact movie name (e.g., Dhadak 2)")],
    time: Annotated[str, Field(description="The exact time (e.g., 12:00)")],
    date: Annotated[str, Field(description="Date of the show in YYYYMMDD format (e.g., 20250810)")],
    city: Annotated[str, Field(description="Full, correct city name (e.g., Kanpur)")]
) -> str:
    """
    Constructs the full BookMyShow seat-layout URL for a specific movie showtime, given the required identifiers.

    Args:
        movie_id (str): Internal movie identifier from BMS
        movie_name (str): Exact movie name as listed on BMS
        venue_name (str): Internal venue name from BMS
        time (str): Time slot for the movie
        date (str): Show date in YYYYMMDD format.
        city (str): Full city name (properly spelled).

    Returns:
        str: A direct link to the seat selection page for the given movie showtime.
    """

    city_slug = slugify(city)
    movie_slug = slugify(movie_name)
    """Fetches BookMyShow _INITIAL_STATE_ JSON and extracts venue→id, time→session_id mapping."""
    # Step 1: Fetch _INITIAL_STATE_ JSON
    target_url = f"https://in.bookmyshow.com/movies/{city_slug}/{movie_slug}/buytickets/{movie_id}/{date}"
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
    date_obj = show_dates.get(date, {})
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
                                    "timer": show_time,
                                    "sessionId": session_id
                                })

    venue_name_lower = venue_n.strip().lower()
    show_time_lower = time.strip().lower()

    # Get all unique venue names from mapping_list
    venue_names_in_mapping = [entry["venueName"].strip().lower() for entry in mapping_list]

    # Find closest match to user's input
    closest_matches = difflib.get_close_matches(venue_name_lower, venue_names_in_mapping, n=1, cutoff=0.6)

    if not closest_matches:
        return None  # No similar venue found

    best_match = closest_matches[0]

    # Now search for entry with the best-matching venue name and exact time
    for entry in mapping_list:
        if entry["venueName"].strip().lower() == best_match and entry["timer"].strip().lower() == show_time_lower:
            return f"https://in.bookmyshow.com/movies/{city_slug}/seat-layout/{movie_id}/{entry["venueCode"]}/{entry["sessionId"]}/{date}"  
    return None
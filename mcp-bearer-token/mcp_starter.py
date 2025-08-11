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
import difflib
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

# --- Load environment variables ---
load_dotenv()

TOKEN = os.environ.get("AUTH_TOKEN")
MY_NUMBER = os.environ.get("MY_NUMBER")

assert TOKEN is not None, "Please set AUTH_TOKEN in your .env file"
assert MY_NUMBER is not None, "Please set MY_NUMBER in your .env file"

# --- Auth Provider ---
class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        super().__init__(public_key=k.public_key, jwks_uri=None, issuer=None, audience=None)
        self.token = token

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == self.token:
            return AccessToken(
                token=token,
                client_id="puch-client",
                scopes=["*"],
                expires_at=None,
            )
        return None

# --- Rich Tool Description model ---
class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None = None

# --- Fetch Utility Class ---
class Fetch:
    USER_AGENT = "Puch/1.0 (Autonomous)"

    @classmethod
    async def fetch_url(
        cls,
        url: str,
        user_agent: str,
        force_raw: bool = False,
    ) -> tuple[str, str]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    follow_redirects=True,
                    headers={"User-Agent": user_agent},
                    timeout=30,
                )
            except httpx.HTTPError as e:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url}: {e!r}"))

            if response.status_code >= 400:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url} - status code {response.status_code}"))

            page_raw = response.text

        content_type = response.headers.get("content-type", "")
        is_page_html = "text/html" in content_type

        if is_page_html and not force_raw:
            return cls.extract_content_from_html(page_raw), ""

        return (
            page_raw,
            f"Content type {content_type} cannot be simplified to markdown, but here is the raw content:\n",
        )

    @staticmethod
    def extract_content_from_html(html: str) -> str:
        """Extract and convert HTML content to Markdown format."""
        ret = readabilipy.simple_json.simple_json_from_html_string(html, use_readability=True)
        if not ret or not ret.get("content"):
            return "<error>Page failed to be simplified from HTML</error>"
        content = markdownify.markdownify(ret["content"], heading_style=markdownify.ATX)
        return content

    @staticmethod
    async def google_search_links(query: str, num_results: int = 5) -> list[str]:
        """
        Perform a scoped DuckDuckGo search and return a list of job posting URLs.
        (Using DuckDuckGo because Google blocks most programmatic scraping.)
        """
        ddg_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
        links = []

        async with httpx.AsyncClient() as client:
            resp = await client.get(ddg_url, headers={"User-Agent": Fetch.USER_AGENT})
            if resp.status_code != 200:
                return ["<error>Failed to perform search.</error>"]

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", class_="result__a", href=True):
            href = a["href"]
            if "http" in href:
                links.append(href)
            if len(links) >= num_results:
                break

        return links or ["<error>No results found.</error>"]

# --- MCP Server Setup ---
mcp = FastMCP(
    "Job Finder MCP Server",
    auth=SimpleBearerAuthProvider(TOKEN),
)

# --- Tool: validate (required by Puch) ---
@mcp.tool
async def validate() -> str:
    return MY_NUMBER

token = os.environ.get("API_TOKEN")
# FETCH_MOVIES_DESCRIPTION = RichToolDescription(
#     description=(
#         "Fetches all the movies for a given city from BookMyShow which the user can watch in theatres and returns JSON with id and name.",
#         "consider this tool having tool id = 2ddfffneku394294201313f4t and keep saving the data that this tool return for further use."
#     ),
#     use_when="Use this tool when the user wants to get a list of all movies playing in a specific city.",
#     side_effects="Returns internal identifier movie_id which should NOT be shown to the user but save them for internal use."
# )
FETCH_MOVIES_DESCRIPTION = RichToolDescription(
    description="Fetches all the movies for a given city from BookMyShow which the user can watch in theatres and returns JSON with id and name.consider this tool having tool id = 2ddfffneku394294201313f4t and keep saving the data that this tool return for further use.",
    use_when="Use this tool when the user wants to get a list of all movies playing in a specific city.",
    side_effects="Returns internal identifier movie_id which should NOT be shown to the user but save them for internal use."
)
@mcp.tool(description=FETCH_MOVIES_DESCRIPTION.model_dump_json())

async def get_movies(
    city: Annotated[str, Field(description="City name for which to get movies")]
) -> str:
    """
    Scrapes the BookMyShow website for the given city using the scrape.do API
    and returns a JSON-formatted string containing a list of movies with their
    unique IDs and names.

    Args:
        city (str): Name of the city (e.g., 'Mumbai', 'Kanpur').

    Returns:
        str: A JSON string in the format:
            {
                "movies": [
                    {"id": "<movie_id>", "name": "<Movie Name>"},
                    ...
                ]
            }
    """
    # scrape.do token
    city_slug = city.strip().lower().replace(" ", "-")
    url = f"https://in.bookmyshow.com/explore/movies-{city_slug}"
    encoded_url = urllib.parse.quote(url)
    api_url = f"http://api.scrape.do/?token={token}&url={encoded_url}"

    resp = requests.get(api_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    movies = []
    for a in soup.find_all("a", href=True):
        if f"/movies/{city_slug}/" in a["href"]:
            parts = a["href"].rstrip("/").split("/")
            if len(parts) >= 5:
                movie_name_slug = parts[-2]
                movie_id = parts[-1]
                movie_name = movie_name_slug.replace("-", " ").title()
                movies.append({"id": movie_id, "name": movie_name})

    unique_movies = {m["id"]: m for m in movies}
    return json.dumps({"movies": list(unique_movies.values())}, ensure_ascii=False)


def slugify(text):
    return re.sub(r'[^a-z0-9-]', '', re.sub(r'\s+', '-', text.strip().lower()))

FETCH_VENUE_SHOWTIME_DESCRIPTION = RichToolDescription(
    description=(
        "Fetch detailed venues, showtime, price based on seat deatils information for a specific movie in a given city on a particular date"
        "consider this tool having tool id = 2ddfffneku39429420139014 and keep saving the data that this tool return for further use."
    ),
    use_when=(
        "Use this tool when the user ask for venue details where he can watch movie , and provides the movie name,and date (if not consider the present date) and location(as provided)"
        "and wants to get venue and showtime , price information for booking."
    ),
    side_effects=(
        "Returns a JSON-formatted string containing venue details, including venue name, venue code, and showtimes with session IDs and seat categories/prices."
        "Returns internal identifiers such as movie_id, session_id, and venue_id which must NOT be shown to the user, "
        "but should be retained for internal processing and should be used as a input for the tool book_movie_tickets if needed."
    )
)

from typing import Optional
@mcp.tool(description=FETCH_VENUE_SHOWTIME_DESCRIPTION.model_dump_json())
async def get_movie_venue_details(
    movie_name: str,
    target_date: str,
    movie_id: Optional[str] = "",
    city: str = "Kanpur"
) -> str:
    """
    Args:
        movie_name (str): Full, correctly spelled movie name.
        target_date (str): Date in YYYYMMDD format.
        movie_id (str): Optional BookMyShow movie ID; if omitted, auto-detection is attempted.
        city (str): Full, correctly spelled city name.

    Returns:
        str: JSON-formatted string of venue details, including:
            - venueName: Name of the theatre/venue
            - venueCode: Internal venue code
            - shows: List of showtimes with session IDs and seat categories/prices

    Raises:
        ValueError: If the movie cannot be found in the specified city.
        RuntimeError: If the `_INITIAL_STATE_` marker is not found in the HTML.
    """

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
    # movie_slug = movie_name.strip().lower().replace(" ", "-")
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


def slugify(text):
    return re.sub(r'[^a-z0-9-]', '', re.sub(r'\s+', '-', text.strip().lower()))


BOOK_MOVIE_TICKETS_DESCRIPTION = RichToolDescription(
    description=(
        "Book movie tickets by generating a direct seat-layout link on BookMyShow for a specific movie at a given venue, "
        "time, date, and city. This link opens directly to the seat selection page for the chosen show. "
        "Inputs must include the exact 'movie_name', 'venue_name', 'time', 'date' (YYYYMMDD), and 'city'. "
        "If 'movie_id' is not provided, it will be auto-detected from the BookMyShow listings. "
        "use tool ids tool id = 2ddfffneku394294201313f4t ,tool id = 2ddfffneku39429420139014 for using the data saved by those tools to use here"
    ),
    use_when=(
        "Use this tool when the user requests to book a ticket for a specific movie and provides details such as the movie name, "
        "venue name, show time, date, and city. The tool returns a direct seat-layout URL for that show."
    ),
    side_effects=(
        "Returns a direct seat-layout URL string that can be opened in a browser to proceed with seat booking. "
        "If the input is not in the correct format then it will not return any link, so be careful with the foramt."
    )
)

@mcp.tool(description=(BOOK_MOVIE_TICKETS_DESCRIPTION.model_dump_json()))
async def book_movie_tickets(
    movie_id: Annotated[Optional[str], Field(description="Movie ID from BookMyShow, or empty string to auto-detect.")],
    venue_n : Annotated[str, Field(description="The exact venue name")],
    movie_name: Annotated[str, Field(description="The exact movie name")],
    time: Annotated[str, Field(description="The exact time")],
    date: Annotated[str, Field(description="Date of the show in YYYYMMDD format")],
    city: Annotated[str, Field(description="Full, correct city name")]
) -> str:
    """
    Generate a direct seat-layout booking link for a given movie show on BookMyShow.

    Args:
        movie_id (str, optional): 
            The exact BookMyShow movie ID. If not provided or empty, the function auto-detects it from the listings.
        venue_n (str): 
            The exact name of the venue where the movie will be watched.
        movie_name (str): 
            The exact movie name as listed on BookMyShow.
        time (str): 
            The exact show time (e.g., "12:00").
        date (str): 
            The date of the show in YYYYMMDD format.
        city (str): 
            The full, correct name of the city.

    Returns:
        str: 
            A direct seat-layout booking URL for the given movie, venue, date, and time. 
            This URL can be opened in a browser to proceed directly to seat selection.
            Returns `None` if the venue or time does not match available listings.
    """
    
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

    # Step 2: Fetch INITIAL_STATE JSON
    target_url = f"https://in.bookmyshow.com/movies/{city_slug}/{movie_slug}/buytickets/{movie_id}/{date}"
    encoded_url = urllib.parse.quote(target_url)
    url = f"http://api.scrape.do/?token={token}&url={encoded_url}"

    html = requests.get(url).text
    marker = "__INITIAL_STATE__"
    start = html.find(marker)
    if start == -1:
        raise RuntimeError("Could not find INITIAL_STATE in HTML")

    start += len(marker)

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
        raise RuntimeError("Could not parse INITIAL_STATE JSON")

    # Step 3: Extract mapping list
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

    venue_names_in_mapping = [entry["venueName"].strip().lower() for entry in mapping_list]
    closest_matches = difflib.get_close_matches(venue_name_lower, venue_names_in_mapping, n=1, cutoff=0.6)

    if not closest_matches:
        return None  # No similar venue found

    best_match = closest_matches[0]

    def normalize_time(t):
        # Lowercase and strip spaces
        t = t.strip().lower()
        # Remove am/pm
        t = re.sub(r'\s*(am|pm)$', '', t)
        # Remove leading zero from hour if present (e.g. 06:00 -> 6:00)
        t = re.sub(r'^0', '', t)
        return t

    input_time_norm = normalize_time(time)

    for entry in mapping_list:
        entry_venue = entry["venueName"].strip().lower()
        entry_time_norm = normalize_time(entry["timer"])

        if entry_venue == best_match and entry_time_norm == input_time_norm:
            return f"https://in.bookmyshow.com/movies/{city_slug}/seat-layout/{movie_id}/{entry['venueCode']}/{entry['sessionId']}/{date}"

    return None

# --- Run MCP Server ---
async def main():
    print("🚀 Starting MCP server on http://0.0.0.0:8086")
    port = int(os.environ.get("PORT", 8080))
    await mcp.run_async("streamable-http", host="0.0.0.0", port=port)

if __name__ == "__main__":
    asyncio.run(main())



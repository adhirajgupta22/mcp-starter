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

# --- Tool: job_finder (now smart!) ---
JobFinderDescription = RichToolDescription(
    description="Smart job tool: analyze descriptions, fetch URLs, or search jobs based on free text.",
    use_when="Use this to evaluate job descriptions or search for jobs using freeform goals.",
    side_effects="Returns insights, fetched job descriptions, or relevant job links.",
)

@mcp.tool(description=JobFinderDescription.model_dump_json())
async def job_finder(
    user_goal: Annotated[str, Field(description="The user's goal (can be a description, intent, or freeform query)")],
    job_description: Annotated[str | None, Field(description="Full job description text, if available.")] = None,
    job_url: Annotated[AnyUrl | None, Field(description="A URL to fetch a job description from.")] = None,
    raw: Annotated[bool, Field(description="Return raw HTML content if True")] = False,
) -> str:
    """
    Handles multiple job discovery methods: direct description, URL fetch, or freeform search query.
    """
    if job_description:
        return (
            f"📝 **Job Description Analysis**\n\n"
            f"---\n{job_description.strip()}\n---\n\n"
            f"User Goal: **{user_goal}**\n\n"
            f"💡 Suggestions:\n- Tailor your resume.\n- Evaluate skill match.\n- Consider applying if relevant."
        )

    if job_url:
        content, _ = await Fetch.fetch_url(str(job_url), Fetch.USER_AGENT, force_raw=raw)
        return (
            f"🔗 **Fetched Job Posting from URL**: {job_url}\n\n"
            f"---\n{content.strip()}\n---\n\n"
            f"User Goal: **{user_goal}**"
        )

    if "look for" in user_goal.lower() or "find" in user_goal.lower():
        links = await Fetch.google_search_links(user_goal)
        return (
            f"🔍 **Search Results for**: _{user_goal}_\n\n" +
            "\n".join(f"- {link}" for link in links)
        )

    raise McpError(ErrorData(code=INVALID_PARAMS, message="Please provide either a job description, a job URL, or a search query in user_goal."))


# Image inputs and sending images

MAKE_IMG_BLACK_AND_WHITE_DESCRIPTION = RichToolDescription(
    description="Convert an image to black and white and save it.",
    use_when="Use this tool when the user provides an image URL and requests it to be converted to black and white.",
    side_effects="The image will be processed and saved in a black and white format.",
)

@mcp.tool(description=MAKE_IMG_BLACK_AND_WHITE_DESCRIPTION.model_dump_json())
async def make_img_black_and_white(
    puch_image_data: Annotated[str, Field(description="Base64-encoded image data to convert to black and white")] = None,
) -> list[TextContent | ImageContent]:
    import base64
    import io

    from PIL import Image

    try:
        image_bytes = base64.b64decode(puch_image_data)
        image = Image.open(io.BytesIO(image_bytes))

        bw_image = image.convert("L")

        buf = io.BytesIO()
        bw_image.save(buf, format="PNG")
        bw_bytes = buf.getvalue()
        bw_base64 = base64.b64encode(bw_bytes).decode("utf-8")

        return [ImageContent(type="image", mimeType="image/png", data=bw_base64)]
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=str(e)))

token = os.environ.get("API_TOKEN")
@mcp.tool(description="Fetches movies for a given city from BookMyShow and returns JSON with id and name.\n"
          "Note: movie_id, session_id, and venue_id are internal identifiers and must NOT be shown to the user.")
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
    token = "c7cda0a41de3446abf92b8b0154c65e7922123609fe"  # scrape.do token
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

@mcp.tool(description=(
    "Fetch detailed venue and showtime information for a movie from BookMyShow.\n\n"
    "IMPORTANT INPUT REQUIREMENTS:\n"
    "1. City and movie names must be provided in full, correctly spelled,\n "
    "2. Date must be in YYYYMMDD format (e.g., '20250810').\n"
    "3. Movie ID (e.g., 'ET00399488') can be provided for faster results; "
    "if omitted, the tool will attempt to find it automatically.\n"
    "4. Inputs must be exact — incorrect spelling, partial names, or wrong formats will result in no data.\n"
    "Note: movie_id, session_id, and venue_id are internal identifiers and must NOT be shown to the user."
))
async def get_movie_venue_details(
    movie_name: Annotated[str, Field(description="Full, correctly spelled name of the movie (e.g., 'Dhadak 2').")],
    target_date: Annotated[str, Field(description="Target date in YYYYMMDD format (e.g., '20250810').")],
    movie_id: Annotated[str, Field(description="Movie ID from BookMyShow (e.g., 'ET00399488'), or empty string to auto-detect.")],
    city: Annotated[str, Field(description="Full, correctly spelled name of the city (e.g., 'Kanpur').")]
) -> str:
    """
    Fetch venue and showtime details for a given movie in a specified city on a given date from BookMyShow.

    This tool:
    1. Validates and slugifies the movie and city names for URL construction.
    2. Optionally auto-discovers the movie ID if not provided.
    3. Retrieves the HTML page for the Buy Tickets view via scrape.do proxy.
    4. Extracts the `_INITIAL_STATE_` JSON from the HTML.
    5. Parses and returns structured details of venues, showtimes, seat categories, and prices.

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
            if f"/movies/{city_slug}/" in a["href"] and movie_name.lower().replace(" ", "-") in a["href"]:
                parts = a["href"].rstrip("/").split("/")
                if len(parts) >= 5:
                    movie_id = parts[-1]
                    break
        if not movie_id:
            raise ValueError(f"Movie '{movie_name}' not found in {city}.")

    # Step 2: Construct buytickets URL
    movie_slug = movie_name.strip().lower().replace(" ", "-")
    target_url = f"https://in.bookmyshow.com/movies/{city_slug}/{movie_slug}/buytickets/{movie_id}/{target_date}"
    encoded_target_url = urllib.parse.quote(target_url)
    scrape_url = f"http://api.scrape.do/?token={token}&url={encoded_target_url}"

    # Step 3: Extract JSON from _INITIAL_STATE_
    html = requests.get(scrape_url).text
    marker = "__INITIAL_STATE__ ="
    start = html.find(marker)
    if start == -1:
        raise RuntimeError("Could not find _INITIAL_STATE_ in HTML")

    start += len(marker)
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

    return json.dumps(results, indent=2, ensure_ascii=False)

# --- Run MCP Server ---
async def main():
    print("🚀 Starting MCP server on http://0.0.0.0:8086")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8086)

if __name__ == "__main__":
    asyncio.run(main())



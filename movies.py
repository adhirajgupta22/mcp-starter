import requests
from bs4 import BeautifulSoup

# Your scrape.do API token and target URL
token = "c7cda0a41de3446abf92b8b0154c65e7922123609fe"
target_url = "https://in.bookmyshow.com/explore/movies-kanpur"

# Prepare scrape.do URL
import urllib.parse
encoded_url = urllib.parse.quote(target_url)
api_url = f"http://api.scrape.do/?token={token}&url={encoded_url}"

# Step 1: Get the main page content with the list of movies
response = requests.get(api_url)
html_content = response.text

# Step 2: Parse the HTML and extract movie URLs
soup = BeautifulSoup(html_content, 'html.parser')

# Extract all anchor tags with href containing '/movies/kanpur'
movie_links = []
for a_tag in soup.find_all('a', href=True):
    href = a_tag['href']
    if href.startswith("https://in.bookmyshow.com/movies/kanpur/"):
        movie_links.append(href)

# Remove duplicates (if any)
movie_links = list(set(movie_links))

print("Extracted movie URLs:")
for link in movie_links:
    print(link)

# Step 3: For demonstration, fetch the content of the first movie URL using scrape.do again
if movie_links:
    first_movie_url = movie_links[0]
    encoded_movie_url = urllib.parse.quote(first_movie_url)
    movie_api_url = f"http://api.scrape.do/?token={token}&url={encoded_movie_url}"

    movie_response = requests.get(movie_api_url)
    print("\nContent of the first movie page:")
    print(movie_response.text[:500])  # Print first 500 characters for preview

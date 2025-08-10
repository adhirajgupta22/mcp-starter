import requests
from bs4 import BeautifulSoup
import urllib.parse

# Your scrape.do API token
token = "c7cda0a41de3446abf92b8b0154c65e7922123609fe"

# The actual page you want to scrape
target_url = "https://in.bookmyshow.com/movies/kanpur/saiyaara/buytickets/ET00447951/20250810"

# URL encode the target URL
encoded_url = urllib.parse.quote(target_url)

# Create the scrape.do request URL
api_url = f"http://api.scrape.do/?token={token}&url={encoded_url}"

# Make the request to scrape.do API
response = requests.get(api_url)

# Check if request succeeded
if response.status_code == 200:
    # Parse the HTML content returned by scrape.do
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find all theater containers (update classes if they changed on the page)
    theaters = soup.find_all('div', class_='sc-1h5m8q1-0 fNPILz')

    if not theaters:
        print("No theaters found. The website structure may have changed or page didn't load correctly.")

    for theater in theaters:
        # Extract theater name
        name_tag = theater.find('span', class_='sc-1qdowf4-0 fbRYHb')
        theater_name = name_tag.text.strip() if name_tag else "No theater name found"

        print(f"Theater: {theater_name}")

        # Extract show times and formats
        showtimes = theater.find_all('div', class_='sc-1vhizuf-1 fxGebS')
        for show in showtimes:
            time = show.find('div', class_='sc-1vhizuf-2 jIiAgZ')
            format_ = show.find('div', class_='sc-1vhizuf-3 hBCNrz')
            if time and format_:
                print(f"  Time: {time.text.strip()}, Format: {format_.text.strip()}")

else:
    print(f"Failed to get data. Status code: {response.status_code}")

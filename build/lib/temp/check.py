import cloudscraper

url = "https://in.bookmyshow.com/explore/movies-kanpur"

# Create a cloudscraper session (acts like requests.Session but bypasses Cloudflare)
scraper = cloudscraper.create_scraper()

response = scraper.get(url)
print("Status Code:", response.status_code)
print("Response Preview:\n", response.text[:500])
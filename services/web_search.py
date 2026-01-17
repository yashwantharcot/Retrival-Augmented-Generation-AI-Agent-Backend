import os
import requests
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# Google Search API (Custom Search JSON API)
GOOGLE_API_KEY = os.getenv("GOOGLE_API")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")  # CSE ID

# YouTube API
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


def search_web(query: str, num_results: int = 3):
    """
    Search the web using Google Custom Search API.
    Returns a list of {title, link, snippet}.
    """
    if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
        raise ValueError("Google API key or Search Engine ID not set in environment")

    url = "https://www.googleapis.com/customsearch/v1"
    params = {"q": query, "key": GOOGLE_API_KEY, "cx": SEARCH_ENGINE_ID}
    resp = requests.get(url, params=params).json()

    results = []
    for item in resp.get("items", [])[:num_results]:
        results.append({
            "title": item.get("title"),
            "link": item.get("link"),
            "snippet": item.get("snippet")
        })
    return results


def search_youtube(query: str, max_results: int = 2):
    """
    Search YouTube videos related to the query.
    Returns a list of {title, link}.
    """
    if not YOUTUBE_API_KEY:
        raise ValueError("YouTube API key not set in environment")

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    request = youtube.search().list(
        q=query,
        part="snippet",
        type="video",
        maxResults=max_results
    )
    response = request.execute()

    results = []
    for item in response.get("items", []):
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        link = f"https://www.youtube.com/watch?v={video_id}"
        results.append({"title": title, "link": link})

    return results

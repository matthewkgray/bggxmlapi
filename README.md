# BGG API Python Client

> [!WARNING]
> **Disclaimer**: This project is currently in the alpha stage of development. It is not yet ready for production use and has not been field-tested. The code is AI-written and is pending a full review and vetting process.

[![PyPI version](https://badge.fury.io/py/bgg-api.svg)](https://badge.fury.io/py/bgg-api)
[![Tests](https://github.com/matthewkgray/bgg-api/actions/workflows/main.yml/badge.svg)](https://github.com/matthewkgray/bgg-api/actions)

A Pythonic, cached, and easy-to-use client for the BoardGameGeek (BGG) XML API2.

This library provides a clean, intuitive interface for accessing BGG data, while handling the complexities of the underlying XML API, including rate limiting, data parsing, and pagination.

## Features

-   **Easy to Use**: A simple and intuitive API.
-   **Lazy Loading**: Game and user data is fetched only when you access it, minimizing API calls.
-   **Caching**: API responses are cached to improve performance and respect BGG's rate limits.
-   **Robust**: Handles API errors and network issues gracefully.
-   **Typed**: Fully type-hinted for a better developer experience.

## Usage

### Getting a Game's Details

```python
from bgg_api import BGGClient

# Initialize the client. Caching is handled automatically.
client = BGGClient()

# Get a game by its BGG ID. Data is fetched lazily.
game = client.get_game(174430) # Gloomhaven

# Accessing properties triggers the API call
print(f"Game: {game.name} ({game.year_published})")
# Output: Game: Gloomhaven (2017)
```

### Fetching Game Ratings

The library handles pagination for you. You can pre-fetch a certain number of pages or fetch more as needed.

```python
from bgg_api import BGGClient

client = BGGClient()

# Get a game and pre-fetch the first page of ratings
game = client.get_game(30549, max_rating_pages=1) # Pandemic Legacy: Season 1

print(f"Initial ratings fetched for {game.name}: {len(game.ratings)}")

for rating in game.ratings:
    print(f"- {rating.username}: {rating.rating}")

# Fetch more pages if needed
if not game.ratings.all_fetched:
    print("\\nFetching more ratings...")
    game.ratings.fetch_more(2) # Fetch 2 more pages
    print(f"Total ratings now: {len(game.ratings)}")
```

### Getting a User's Collection

```python
from bgg_api import BGGClient

client = BGGClient()

# Get a user by their username
user = client.get_user("testuser")

print(f"User: {user.name} (Registered in {user.year_registered})")

# Iterate over the user's collection (games they own)
# The collection is fetched from the API upon first access.
print(f"\\n{user.name}'s Collection:")
for game in user.collection:
    # The game data was pre-populated from the collection call,
    # so accessing .name or .year_published does not make a new API call.
    print(f"- {game.name} ({game.year_published})")
```

### Searching for a Game

```python
from bgg_api import BGGClient

client = BGGClient()
results = client.search("pandemic")

print("Search results for 'pandemic':")
for game in results:
    print(f"- {game.name} ({game.year_published}) [ID: {game.id}]")
```

## Error Handling

The library uses custom exceptions for different error types:

-   `BGGAPIError`: For errors from the BGG API (e.g., game not found, invalid user).
-   `BGGNetworkError`: For network issues (e.g., connection timeouts).

```python
from bgg_api import BGGClient, BGGAPIError

client = BGGClient()
try:
    game = client.get_game(99999999) # A game that doesn't exist
    print(game.name)
except BGGAPIError as e:
    print(f"API Error: {e}")
```

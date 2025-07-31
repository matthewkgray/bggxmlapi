# BGG API Example Scripts

This directory contains example scripts demonstrating how to use the `bgg-api` Python library to perform common tasks.

## Setup

Before running these examples, make sure you have installed the library and its development dependencies from the root of the repository:

```bash
pip install -e .[dev]
```

## Scripts

### 1. `compare_game_ratings.py`

This script fetches and analyzes the ratings for two specified games. It identifies users who have rated both games and provides a summary of their preferences. It also analyzes ratings from users who have only rated one of the two games.

**Usage:**

```bash
python examples/compare_game_ratings.py <game1_id> <game2_id> [--pages <num_pages>]
```

**Example:**

To compare ratings for Gloomhaven (ID: 174430) and Pandemic Legacy: Season 1 (ID: 161936), fetching the first 10 pages (1000 ratings) for each:

```bash
python examples/compare_game_ratings.py 174430 161936 --pages 10
```

### 2. `find_common_collection_games.py`

This script finds the games that are present in the collections of two different BGG users. It can sort the resulting list by game name, year published, average rating, or rarity (number of owners).

**Usage:**

```bash
python examples/find_common_collection_games.py <user1> <user2> [--sort <criteria>]
```

**Sort Criteria:**
- `name` (default)
- `year`
- `rating`
- `rarity`

**Example:**

To find the common games between the users `octavian` and `testuser`, sorted by average rating:

```bash
python examples/find_common_collection_games.py octavian testuser --sort rating
```

**Note on BGG API Reliability:** The BGG API endpoint for fetching user collections can sometimes be slow or unavailable. The API may return a `202` status code, indicating the request has been queued for processing. The client will automatically retry, but if the BGG servers are under heavy load, the request may time out or return an empty collection. If you receive empty results for known users, this is the likely cause.

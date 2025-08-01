# bgg_api/client.py
from pathlib import Path
from typing import Optional, List
import requests
from lxml import etree
import time
import logging

import requests_cache

from .models import Game, User
from .exceptions import BGGNetworkError, BGGAPIError

log = logging.getLogger(__name__)

class BGGClient:
    """
    The main entry point for interacting with the BGG API.
    This class handles all HTTP requests, rate limiting, and caching.
    """

    def __init__(
        self,
        cache_dir: str = "~/.bgg_cache",
        cache_ttl: int = 3600,
        api_token: Optional[str] = None,
        max_retries: int = 5,
        retry_delay: int = 2,
    ):
        """
        Initializes the BGGClient.

        Args:
            cache_dir (str): The directory to use for caching API responses.
            cache_ttl (int): The time-to-live for cached data in seconds.
            api_token (str, optional): The BGG API token for authenticated requests.
            max_retries (int): Max number of retries for 202 status.
            retry_delay (int): Seconds to wait between retries for 202 status.
        """
        cache_path = Path(cache_dir).expanduser()
        self.session = requests_cache.CachedSession(
            backend="filesystem",
            cache_name=str(cache_path),
            expire_after=cache_ttl,
            allowable_methods=('GET', 'POST'),
            stale_if_error=True,
        )
        self.api_token = api_token
        self.api_url = "https://www.boardgamegeek.com/xmlapi2"
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _request(self, endpoint, params):
        """Internal method to handle requests and retries for 202 status."""
        url = f"{self.api_url}/{endpoint}"
        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, headers=headers)

                if response.status_code == 202:
                    log.warning(
                        f"BGG API returned 202 Accepted. Retrying in {self.retry_delay}s... (Attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(self.retry_delay)
                    continue # Retry the request

                response.raise_for_status()

                if not response.content:
                    raise BGGAPIError("BGG API returned an empty response.")

                xml_root = etree.fromstring(response.content)
                return xml_root

            except etree.XMLSyntaxError as e:
                raise BGGAPIError(f"Failed to parse XML response from BGG API: {e}") from e
            except requests.exceptions.RequestException as e:
                raise BGGNetworkError(f"Network error at {url}: {e}") from e

        raise BGGAPIError(f"Failed to get a valid response from {url} after {self.max_retries} retries.")


    def _get_game_data(self, game_id: int) -> etree._Element:
        """
        Internal method to fetch the raw XML data for a given game ID.
        """
        params = {
            "id": game_id,
            "stats": 1,  # Include statistics
        }
        return self._request("thing", params)

    def _get_game_ratings_page(self, game_id: int, page: int) -> etree._Element:
        """Internal method to fetch a single page of game ratings."""
        params = {
            "id": game_id,
            "ratingcomments": 1,
            "page": page,
            "pagesize": 100, # Max page size
        }
        return self._request("thing", params)

    def _get_user_data(self, username: str) -> etree._Element:
        """Internal method to fetch the raw XML data for a given username."""
        params = {"name": username}
        return self._request("user", params)

    def _get_collection_data(self, username: str) -> etree._Element:
        """Internal method to fetch the raw XML data for a user's collection."""
        params = {
            "username": username,
            "own": 1,       # Only fetch games they own
            "stats": 1,     # Include stats for the games
            "brief": 0,     # Get detailed info, not brief
        }
        return self._request("collection", params)

    def _search(self, query: str) -> etree._Element:
        """Internal method to fetch search results."""
        params = {
            "query": query,
            "type": "boardgame", # Default to searching for boardgames
        }
        return self._request("search", params)

    def get_user(self, username: str) -> User:
        """
        Retrieves a BGG user by their username.

        This method returns a User object without fetching data immediately.
        Data is fetched lazily when you access the User's properties.

        Args:
            username (str): The BGG username.

        Returns:
            User: A User object representing the BGG user.
        """
        return User(username=username, client=self)

    def get_game(self, game_id: int, max_rating_pages: int = 0) -> Game:
        """
        Retrieves a board game by its BGG ID.

        This method returns a Game object without fetching data immediately.
        Data is fetched lazily when you access the Game's properties.

        Args:
            game_id (int): The BGG ID of the game.
            max_rating_pages (int): The number of ratings pages to pre-fetch. Defaults to 0 (lazy).

        Returns:
            Game: A Game object representing the board game.
        """
        game = Game(game_id=game_id, client=self)
        if max_rating_pages > 0:
            # This will fetch the first N pages of ratings
            game.ratings.fetch_more(num_pages=max_rating_pages)
        return game


    def search(self, query: str) -> List[Game]:
        """
        Searches for games by name.

        Args:
            query (str): The search query.

        Returns:
            A list of Game objects matching the search query.
        """
        search_xml = self._search(query)

        games = []
        for item_el in search_xml.findall("item"):
            game_id = int(item_el.get("id"))
            game = Game(game_id=game_id, client=self)
            # Pre-populate the game's data with the search result
            game._set_xml_data_from_search_item(item_el)
            games.append(game)

        return games

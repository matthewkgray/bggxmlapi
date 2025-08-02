# bgg_api/models.py
from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional
from lxml import etree
import logging
import math

from .exceptions import BGGAPIError

if TYPE_CHECKING:
    from .client import BGGClient

log = logging.getLogger(__name__)

class Game:
    """
    Represents a single board game on BGG.
    It contains attributes for game details like ID, name, year published,
    and methods to retrieve more detailed information.
    """
    def __init__(self, game_id: int, client: "BGGClient"):
        self.id = game_id
        self._client = client
        self._xml_data: Optional[etree._Element] = None
        self.ratings = Ratings(self)

    def _fetch_data(self):
        """
        Fetches the game data from the BGG API if it hasn't been fetched yet.
        This method is called lazily when a property is accessed.
        """
        if self._xml_data is not None:
            return

        log.debug(f"Fetching game data for game_id={self.id}")
        response_xml = self._client._get_game_data(self.id)
        self._set_xml_data(response_xml)

    def _set_xml_data(self, xml_data: etree._Element):
        """Helper to set the xml data for the game from a 'thing' call."""
        if self._xml_data is not None:
            return # Data already set

        item = xml_data.find(f".//item[@id='{self.id}']")

        if item is None:
            raise BGGAPIError(f"Game with id {self.id} not found in provided XML.")

        self._xml_data = item

    def _set_xml_data_from_collection_item(self, xml_item: etree._Element):
        """Helper to set xml data from a '/collection' call's item element."""
        if self._xml_data is not None:
            return # Data already set
        self.id = int(xml_item.get("objectid"))
        self._xml_data = xml_item

    def _set_xml_data_from_search_item(self, xml_item: etree._Element):
        """Helper to set xml data from a '/search' call's item element."""
        if self._xml_data is not None:
            return # Data already set
        self.id = int(xml_item.get("id"))
        self._xml_data = xml_item

    def _get_links(self, link_type: str) -> List["Link"]:
        """Helper to retrieve a list of Link objects of a specific type."""
        self._fetch_data()
        if self._xml_data is None:
            return []

        links = []
        for link_el in self._xml_data.findall(f"./link[@type='{link_type}']"):
            try:
                link_id = int(link_el.get("id"))
            except (ValueError, TypeError):
                continue # Skip if id is not a valid integer

            links.append(
                Link(
                    link_type=link_type,
                    link_id=link_id,
                    value=link_el.get("value", "N/A"),
                )
            )
        return links

    @property
    def name(self) -> str:
        """The primary name of the game."""
        self._fetch_data()
        if self._xml_data is None:
            return "N/A"

        # Thing/Search style: <name type="primary" value="..."/>
        name_el = self._xml_data.find("./name[@type='primary']")
        if name_el is not None and name_el.get("value"):
            return name_el.get("value")

        # Collection style: <name>...</name>
        name_el = self._xml_data.find("name")
        if name_el is not None and name_el.text:
            return name_el.text

        # Fallback for any other <name> element with a value attribute
        if name_el is not None and name_el.get("value"):
            return name_el.get("value")

        return "N/A"

    @property
    def alternate_names(self) -> List[str]:
        """A list of the game's alternate names."""
        self._fetch_data()
        if self._xml_data is None: return []
        return [
            name_el.get("value")
            for name_el in self._xml_data.findall("./name[@type='alternate']")
            if name_el.get("value")
        ]

    @property
    def year_published(self) -> Optional[int]:
        """The year the game was published."""
        self._fetch_data()
        year_element = self._xml_data.find("yearpublished")
        if year_element is None:
            return None

        # For /thing and /search results, the year is in the 'value' attribute
        year_val = year_element.get("value")
        if year_val:
            return int(year_val)

        # For /collection results, the year is in the element's text
        if year_element.text and year_element.text.isdigit():
            return int(year_element.text)

        return None

    @property
    def thumbnail(self) -> Optional[str]:
        """The URL for the game's thumbnail image."""
        self._fetch_data()
        if self._xml_data is None: return None
        el = self._xml_data.find("thumbnail")
        return el.text if el is not None else None

    @property
    def image(self) -> Optional[str]:
        """The URL for the game's main image."""
        self._fetch_data()
        if self._xml_data is None: return None
        el = self._xml_data.find("image")
        return el.text if el is not None else None

    @property
    def description(self) -> Optional[str]:
        """The description of the game."""
        self._fetch_data()
        if self._xml_data is None: return None
        el = self._xml_data.find("description")
        return el.text if el is not None else None

    @property
    def min_play_time(self) -> Optional[int]:
        """The minimum playing time in minutes."""
        self._fetch_data()
        if self._xml_data is None: return None
        el = self._xml_data.find("minplaytime")
        if el is not None and el.get("value"):
            return int(el.get("value"))
        return None

    @property
    def max_play_time(self) -> Optional[int]:
        """The maximum playing time in minutes."""
        self._fetch_data()
        if self._xml_data is None: return None
        el = self._xml_data.find("maxplaytime")
        if el is not None and el.get("value"):
            return int(el.get("value"))
        return None

    @property
    def playing_time(self) -> Optional[int]:
        """The playing time in minutes."""
        self._fetch_data()
        if self._xml_data is None: return None
        el = self._xml_data.find("playingtime")
        if el is not None and el.get("value"):
            return int(el.get("value"))
        return None

    @property
    def min_age(self) -> Optional[int]:
        """The minimum recommended player age."""
        self._fetch_data()
        if self._xml_data is None: return None
        el = self._xml_data.find("minage")
        if el is not None and el.get("value"):
            return int(el.get("value"))
        return None

    @property
    def player_suggestions(self) -> "PlayerSuggestions":
        """The user-suggested player counts for the game."""
        self._fetch_data()
        if self._xml_data is None:
            return PlayerSuggestions([])

        suggestions = []
        poll = self._xml_data.find("./poll[@name='suggested_numplayers']")
        if poll is not None:
            for results_el in poll.findall("results"):
                player_count = results_el.get("numplayers", "N/A")
                votes = {"Best": 0, "Recommended": 0, "Not Recommended": 0}
                for result_el in results_el.findall("result"):
                    value = result_el.get("value")
                    try:
                        numvotes = int(result_el.get("numvotes", 0))
                    except (ValueError, TypeError):
                        numvotes = 0

                    if value in votes:
                        votes[value] = numvotes

                suggestions.append(
                    PlayerSuggestion(
                        player_count=player_count,
                        best_votes=votes["Best"],
                        recommended_votes=votes["Recommended"],
                        not_recommended_votes=votes["Not Recommended"],
                    )
                )
        return PlayerSuggestions(suggestions)

    @property
    def suggested_player_age(self) -> "PlayerAgeSuggestions":
        """The user-suggested player age for the game."""
        self._fetch_data()
        if self._xml_data is None:
            return PlayerAgeSuggestions([])

        suggestions = []
        poll = self._xml_data.find("./poll[@name='suggested_playerage']")
        if poll is not None:
            results_el = poll.find("results")
            if results_el is not None:
                for result_el in results_el.findall("result"):
                    age = result_el.get("value", "N/A")
                    try:
                        numvotes = int(result_el.get("numvotes", 0))
                    except (ValueError, TypeError):
                        numvotes = 0

                    suggestions.append(
                        PlayerAgeSuggestion(
                            age=age,
                            votes=numvotes,
                        )
                    )
        return PlayerAgeSuggestions(suggestions)

    @property
    def categories(self) -> List["Link"]:
        """List of game categories."""
        return self._get_links("boardgamecategory")

    @property
    def mechanics(self) -> List["Link"]:
        """List of game mechanics."""
        return self._get_links("boardgamemechanic")

    @property
    def families(self) -> List["Link"]:
        """List of game families."""
        return self._get_links("boardgamefamily")

    @property
    def expansions(self) -> List["Link"]:
        """List of game expansions."""
        return self._get_links("boardgameexpansion")

    @property
    def accessories(self) -> List["Link"]:
        """List of game accessories."""
        return self._get_links("boardgameaccessory")

    @property
    def integrations(self) -> List["Link"]:
        """List of game integrations."""
        return self._get_links("boardgameintegration")

    @property
    def compilations(self) -> List["Link"]:
        """List of game compilations."""
        return self._get_links("boardgamecompilation")

    @property
    def implementations(self) -> List["Link"]:
        """List of game implementations."""
        return self._get_links("boardgameimplementation")

    @property
    def designers(self) -> List["Link"]:
        """List of game designers."""
        return self._get_links("boardgamedesigner")

    @property
    def artists(self) -> List["Link"]:
        """List of game artists."""
        return self._get_links("boardgameartist")

    @property
    def publishers(self) -> List["Link"]:
        """List of game publishers."""
        return self._get_links("boardgamepublisher")

    @property
    def statistics(self) -> Optional["Statistics"]:
        """The game's statistics, including ratings and ranks."""
        self._fetch_data()
        if self._xml_data is None:
            return None

        stats_el = self._xml_data.find("./statistics/ratings")
        if stats_el is None:
            return None

        def _get_value(element, attr_name, type_conv, default=None):
            if element is None:
                return default
            val_str = element.get(attr_name)
            if val_str is None:
                return default
            try:
                return type_conv(val_str)
            except (ValueError, TypeError):
                # BGG API sometimes returns "Not Ranked"
                return default

        def _get_child_value(parent_el, child_name, type_conv, default=None):
            child = parent_el.find(child_name)
            return _get_value(child, "value", type_conv, default)

        ranks = []
        ranks_el = stats_el.find("ranks")
        if ranks_el is not None:
            for rank_el in ranks_el.findall("rank"):
                ranks.append(
                    Rank(
                        type=rank_el.get("type"),
                        id=rank_el.get("id"),
                        name=rank_el.get("name"),
                        friendly_name=rank_el.get("friendlyname"),
                        value=_get_value(rank_el, "value", int),
                        bayes_average=_get_value(rank_el, "bayesaverage", float),
                    )
                )

        return Statistics(
            users_rated=_get_child_value(stats_el, "usersrated", int, 0),
            average=_get_child_value(stats_el, "average", float, 0.0),
            bayes_average=_get_child_value(stats_el, "bayesaverage", float, 0.0),
            stddev=_get_child_value(stats_el, "stddev", float, 0.0),
            median=_get_child_value(stats_el, "median", int, 0),
            owned=_get_child_value(stats_el, "owned", int, 0),
            trading=_get_child_value(stats_el, "trading", int, 0),
            wanting=_get_child_value(stats_el, "wanting", int, 0),
            wishing=_get_child_value(stats_el, "wishing", int, 0),
            num_comments=_get_child_value(stats_el, "numcomments", int, 0),
            num_weights=_get_child_value(stats_el, "numweights", int, 0),
            average_weight=_get_child_value(stats_el, "averageweight", float, 0.0),
            ranks=ranks,
        )

    @property
    def average_rating(self) -> Optional[float]:
        """The average user rating for the game."""
        self._fetch_data()
        if self._xml_data is None: return None

        # Path for /thing results
        rating_el = self._xml_data.find("./statistics/ratings/average")
        if rating_el is not None:
            rating_val = rating_el.get("value")
            try:
                return float(rating_val)
            except (ValueError, TypeError):
                return None

        # Path for /collection results
        rating_el = self._xml_data.find("./stats/rating/average")
        if rating_el is not None:
            rating_val = rating_el.get("value")
            try:
                return float(rating_val)
            except (ValueError, TypeError):
                return None
        return None

    @property
    def owned_by(self) -> Optional[int]:
        """The number of users who own the game."""
        self._fetch_data()
        if self._xml_data is None: return None

        # Path for /thing results
        stats_el = self._xml_data.find("./statistics/ratings")
        if stats_el is not None:
            users_owned_val = stats_el.get("owned")
            if users_owned_val is None: # BGG API doesn't always return this
                # Fallback to usersrated as a proxy for popularity
                users_owned_val = stats_el.get("usersrated")

            try:
                return int(users_owned_val)
            except (ValueError, TypeError):
                return None

        # Path for /collection results
        stats_el = self._xml_data.find("./stats")
        if stats_el is not None:
            users_owned_val = stats_el.get("numowned")
            if users_owned_val is not None:
                try:
                    return int(users_owned_val)
                except (ValueError, TypeError):
                    return None

        return None


class User:
    """
    Represents a BGG user.
    """
    def __init__(self, username: str, client: "BGGClient"):
        self.username = username
        self._client = client
        self._xml_data: Optional[etree._Element] = None

    def _fetch_data(self):
        if self._xml_data is not None:
            return
        log.debug(f"Fetching data for user '{self.username}'")
        self._xml_data = self._client._get_user_data(self.username)

    @property
    def id(self) -> Optional[int]:
        self._fetch_data()
        user_id = self._xml_data.get("id")
        return int(user_id) if user_id else None

    @property
    def name(self) -> str:
        # The name from the user object can be different casing than the username
        self._fetch_data()
        return self._xml_data.get("name", self.username)

    @property
    def year_registered(self) -> Optional[int]:
        self._fetch_data()
        year_el = self._xml_data.find("yearregistered")
        if year_el is not None:
            year_val = year_el.get("value")
            if year_val and year_val.isdigit():
                return int(year_val)
        return None

    @property
    def collection(self) -> "Collection":
        """The user's game collection (games they own)."""
        return Collection(self)


class Collection:
    """
    Represents a user's collection of games.
    """
    def __init__(self, user: User):
        self._user = user
        self._games: Optional[List[Game]] = None

    def _fetch_data(self):
        if self._games is not None:
            return

        log.debug(f"Fetching collection for user '{self._user.username}'")
        collection_xml = self._user._client._get_collection_data(self._user.username)

        games = []
        for item_el in collection_xml.findall("item"):
            game_id = int(item_el.get("objectid"))
            # Create a game object but don't hit the API for it yet
            game = Game(game_id=game_id, client=self._user._client)
            # Pre-populate the game's XML data with what we got from the collection call
            game._set_xml_data_from_collection_item(item_el)
            games.append(game)

        self._games = games

    def __iter__(self):
        self._fetch_data()
        return iter(self._games)

    def __len__(self):
        self._fetch_data()
        return len(self._games)


class Ratings:
    """
    A container for a game's ratings, handling the logic for paginated fetching.
    """
    def __init__(self, game: Game):
        self._game = game
        self._ratings: List[Rating] = []
        self._pages_fetched = 0
        self._total_pages: Optional[int] = None
        self._total_ratings: Optional[int] = None

    def __iter__(self):
        return iter(self._ratings)

    def __len__(self):
        if self._total_ratings is not None:
            return self._total_ratings
        return len(self._ratings)

    @property
    def all_fetched(self) -> bool:
        """Returns True if all ratings have been fetched."""
        if self._total_pages is None:
            return False # We don't know yet
        return self._pages_fetched >= self._total_pages

    def fetch_more(self, num_pages: int = 1):
        """
        Fetches more pages of ratings from the BGG API.

        Args:
            num_pages (int): The number of additional pages to fetch.
        """
        if self.all_fetched:
            log.debug(f"All ratings already fetched for game {self._game.id}. Skipping fetch.")
            return

        start_page = self._pages_fetched + 1
        end_page = start_page + num_pages
        if self._total_pages is not None:
            end_page = min(end_page, self._total_pages + 1)

        for page_num in range(start_page, end_page):
            if self.all_fetched:
                break

            log.debug(f"Fetching ratings page {page_num} for game {self._game.id}")
            response_xml = self._game._client._get_game_ratings_page(
                self._game.id, page=page_num
            )

            self._game._set_xml_data(response_xml)

            comments_element = response_xml.find(f".//item[@id='{self._game.id}']/comments")
            if comments_element is None:
                self._total_pages = 0
                self._total_ratings = 0
                break

            if self._total_pages is None:
                self._total_ratings = int(comments_element.get("totalitems", 0))
                page_size = int(comments_element.get("pagesize", 100))
                self._total_pages = math.ceil(self._total_ratings / page_size) if page_size > 0 else 0

            new_ratings = []
            for comment_el in comments_element.findall("comment"):
                rating_val = comment_el.get("rating")
                if not rating_val:
                    continue

                try:
                    rating_float = float(rating_val)
                except (ValueError, TypeError):
                    log.warning(f"Could not parse rating '{rating_val}' for game {self._game.id}. Skipping.")
                    continue

                new_ratings.append(
                    Rating(
                        username=comment_el.get("username", "N/A"),
                        rating=rating_float,
                        comment=comment_el.get("value", ""),
                    )
                )

            self._ratings.extend(new_ratings)
            self._pages_fetched = page_num


class Rating:
    """A simple data object for a single rating."""
    def __init__(self, username: str, rating: float, comment: str = ""):
        self.username = username
        self.rating = rating
        self.comment = comment

    def __repr__(self):
        return f"Rating(username='{self.username}', rating={self.rating})"


class PlayerAgeSuggestion:
    """Represents the poll results for a specific player age."""

    def __init__(self, age: str, votes: int):
        self.age = age
        self.votes = votes

    def __repr__(self):
        return f"PlayerAgeSuggestion(age='{self.age}', votes={self.votes})"


class PlayerAgeSuggestions:
    """
    A container for a game's player age suggestions poll results.
    """

    def __init__(self, suggestions: List[PlayerAgeSuggestion]):
        self._suggestions = suggestions

    def __iter__(self):
        return iter(self._suggestions)

    def __len__(self):
        return len(self._suggestions)


class Rank:
    """Represents a single rank for a game."""

    def __init__(self, *, type: str, id: str, name: str, friendly_name: str, value: Optional[int], bayes_average: Optional[float]):
        self.type = type
        self.id = id
        self.name = name
        self.friendly_name = friendly_name
        self.value = value
        self.bayes_average = bayes_average

    def __repr__(self):
        return f"Rank(type='{self.type}', name='{self.name}', value={self.value}, bayes_average={self.bayes_average})"


class Statistics:
    """Represents the statistics for a game."""

    def __init__(
        self,
        *,
        users_rated: int,
        average: float,
        bayes_average: float,
        stddev: float,
        median: int,
        owned: int,
        trading: int,
        wanting: int,
        wishing: int,
        num_comments: int,
        num_weights: int,
        average_weight: float,
        ranks: List["Rank"],
    ):
        self.users_rated = users_rated
        self.average = average
        self.bayes_average = bayes_average
        self.stddev = stddev
        self.median = median
        self.owned = owned
        self.trading = trading
        self.wanting = wanting
        self.wishing = wishing
        self.num_comments = num_comments
        self.num_weights = num_weights
        self.average_weight = average_weight
        self.ranks = ranks

    def __repr__(self):
        return f"Statistics(users_rated={self.users_rated}, average={self.average:.5f}, bayes_average={self.bayes_average:.5f})"


class Link:
    """A generic link to another item on BGG."""

    def __init__(self, link_type: str, link_id: int, value: str):
        self.type = link_type
        self.id = link_id
        self.value = value

    def __repr__(self):
        return f"Link(type='{self.type}', id={self.id}, value='{self.value}')"


class PlayerSuggestion:
    """Represents the poll results for a specific player count."""

    def __init__(
        self, player_count: str, best_votes: int, recommended_votes: int, not_recommended_votes: int
    ):
        self.player_count = player_count
        self.best_votes = best_votes
        self.recommended_votes = recommended_votes
        self.not_recommended_votes = not_recommended_votes

    def __repr__(self):
        return (
            f"PlayerSuggestion(player_count='{self.player_count}', "
            f"best={self.best_votes}, recommended={self.recommended_votes}, not_recommended={self.not_recommended_votes})"
        )


class PlayerSuggestions:
    """
    A container for a game's player suggestions poll results.
    """

    def __init__(self, suggestions: List[PlayerSuggestion]):
        self._suggestions = suggestions

    def __iter__(self):
        return iter(self._suggestions)

    def __len__(self):
        return len(self._suggestions)

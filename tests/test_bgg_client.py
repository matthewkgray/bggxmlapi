import pytest
import responses
from pathlib import Path
from unittest.mock import patch

from bgg_api.client import BGGClient
from bgg_api.exceptions import BGGAPIError, BGGNetworkError

# Helper to load fixture files
def load_fixture(name):
    return (Path(__file__).parent / "fixtures" / name).read_text()

def mock_ratings_response(game_id, page, pagesize, totalitems):
    """Generates a mock XML response for a ratings page."""
    comments = ""
    start_user = (page - 1) * pagesize
    for i in range(pagesize):
        user_num = start_user + i
        if user_num < totalitems:
            comments += f'<comment username="user{user_num}" rating="{(user_num % 10) + 1}" value="comment {user_num}"/>'

    return f"""
    <items>
        <item id="{game_id}">
            <comments page="{page}" pagesize="{pagesize}" totalitems="{totalitems}">
                {comments}
            </comments>
        </item>
    </items>
    """

import requests

@pytest.fixture
def cached_bgg_client():
    """
    Returns a BGGClient instance with a real, empty cache for each test.
    """
    # Use a temporary directory for the cache
    client = BGGClient(cache_dir="/tmp/bgg_api_test_cache_real")
    # Clear the cache before the test runs
    client.session.cache.clear()
    return client

@pytest.fixture
def bgg_client():
    # Use a non-existent cache dir for tests to avoid writing to the filesystem
    client = BGGClient(cache_dir="/tmp/bgg_api_test_cache")
    # For testing, we don't want to deal with the cache, so we replace the
    # cached session with a regular one. This lets `responses` work correctly.
    client.session = requests.Session()
    return client

@responses.activate
def test_get_game_lazy_loading(bgg_client):
    """Test that game data is fetched lazily."""
    game_id = 174430
    mock_url = f"{bgg_client.api_url}/thing"
    responses.add(
        responses.GET,
        mock_url,
        body=load_fixture("thing_174430.xml"),
        status=200,
        content_type="application/xml",
    )

    game = bgg_client.get_game(game_id)

    # No API call should be made yet
    assert len(responses.calls) == 0

    # Accessing a property should trigger the API call
    assert game.name == "Gloomhaven"
    assert len(responses.calls) == 1
    assert responses.calls[0].request.params["id"] == str(game_id)

    # Accessing another property should not trigger another API call
    assert game.year_published == 2017
    assert len(responses.calls) == 1


@responses.activate
def test_get_game_player_suggestions(bgg_client):
    """Test parsing of player suggestions poll."""
    game_id = 174430
    mock_url = f"{bgg_client.api_url}/thing"
    responses.add(
        responses.GET,
        mock_url,
        body=load_fixture("thing_174430.xml"),
        status=200,
        content_type="application/xml",
    )

    game = bgg_client.get_game(game_id)
    suggestions = game.player_suggestions

    assert len(suggestions) == 5

    sugs = list(suggestions)

    s1 = sugs[0]
    assert s1.player_count == "1"
    assert s1.best_votes == 10
    assert s1.recommended_votes == 20
    assert s1.not_recommended_votes == 5

    s2 = sugs[1]
    assert s2.player_count == "2"
    assert s2.best_votes == 50
    assert s2.recommended_votes == 30
    assert s2.not_recommended_votes == 0

    s4plus = sugs[4]
    assert s4plus.player_count == "4+"
    assert s4plus.not_recommended_votes == 1


@responses.activate
def test_get_user_and_collection(bgg_client):
    """Test lazy loading of user and their collection."""
    username = "testuser"
    user_url = f"{bgg_client.api_url}/user"
    collection_url = f"{bgg_client.api_url}/collection"

    responses.add(
        responses.GET, user_url, body=load_fixture("user_testuser.xml"), status=200
    )
    responses.add(
        responses.GET, collection_url, body=load_fixture("collection_testuser.xml"), status=200
    )

    user = bgg_client.get_user(username)
    # No API calls yet
    assert len(responses.calls) == 0

    # Access user property
    assert user.year_registered == 2010
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url.startswith(user_url)

    # Access collection
    collection = user.collection
    # Still no new API call
    assert len(responses.calls) == 1

    # Iterate over collection to trigger fetch
    games = list(collection)
    assert len(responses.calls) == 2
    assert responses.calls[1].request.url.startswith(collection_url)

    assert len(games) == 2
    assert games[0].name == "Gloomhaven"
    assert games[1].id == 30549

    # Accessing pre-populated data should not trigger more API calls
    assert games[0].year_published == 2017
    assert len(responses.calls) == 2

@responses.activate
def test_search(bgg_client):
    """Test searching for a game."""
    query = "pandemic"
    search_url = f"{bgg_client.api_url}/search"
    responses.add(
        responses.GET, search_url, body=load_fixture("search_pandemic.xml"), status=200
    )

    results = bgg_client.search(query)
    assert len(responses.calls) == 1
    assert responses.calls[0].request.params["query"] == query

    assert len(results) == 2
    assert results[0].name == "Pandemic Legacy: Season 1"
    assert results[1].year_published == 2008

    # Accessing pre-populated data should not trigger more API calls
    assert results[0].id == 30549
    assert len(responses.calls) == 1

@responses.activate
def test_client_retry_logic(bgg_client):
    """Test that the client retries on a 202 status code."""
    bgg_client.retry_delay = 0.01 # Speed up test
    game_id = 123
    thing_url = f"{bgg_client.api_url}/thing"

    # Simulate BGG queueing the request then returning success
    responses.add(responses.GET, thing_url, status=202)
    responses.add(responses.GET, thing_url, body=f'<items><item id="{game_id}"/></items>', status=200)

    game = bgg_client.get_game(game_id)
    # This should trigger the API calls
    game._fetch_data()

    assert len(responses.calls) == 2

@responses.activate
def test_client_retry_failure(bgg_client):
    """Test that the client gives up after max retries."""
    bgg_client.retry_delay = 0.01
    bgg_client.max_retries = 3
    thing_url = f"{bgg_client.api_url}/thing"

    responses.add(responses.GET, thing_url, status=202)
    responses.add(responses.GET, thing_url, status=202)
    responses.add(responses.GET, thing_url, status=202)

    game = bgg_client.get_game(123)
    with pytest.raises(BGGAPIError):
        game._fetch_data()

    assert len(responses.calls) == 3

@responses.activate
def test_network_error_wrapper(bgg_client):
    """Test that requests exceptions are wrapped in BGGNetworkError."""
    thing_url = f"{bgg_client.api_url}/thing"
    responses.add(responses.GET, thing_url, body=requests.exceptions.ConnectionError("Test connection error"))

    game = bgg_client.get_game(123)
    with pytest.raises(BGGNetworkError):
        game._fetch_data()


@responses.activate
def test_auth_token_header(bgg_client):
    """Test that the client sends the Authorization header if a token is provided."""
    token = "test-token-123"
    client = BGGClient(api_token=token)
    # We need to replace the session for `responses` to work
    client.session = requests.Session()

    thing_url = f"{client.api_url}/thing"
    responses.add(
        responses.GET,
        thing_url,
        body='<items><item id="123"/></items>',
        status=200,
    )

    game = client.get_game(123)
    game._fetch_data() # Trigger the call

    assert len(responses.calls) == 1
    sent_headers = responses.calls[0].request.headers
    assert "Authorization" in sent_headers
    assert sent_headers["Authorization"] == f"Bearer {token}"


@responses.activate
def test_get_owned_by_from_collection_item(bgg_client):
    """Test that owned_by is parsed correctly from a collection item's stats."""
    username = "testuser"
    collection_url = f"{bgg_client.api_url}/collection"

    responses.add(
        responses.GET,
        collection_url,
        body=load_fixture("collection_testuser.xml"),
        status=200,
    )

    user = bgg_client.get_user(username)
    collection = user.collection
    game = list(collection)[0]

    # The collection call should be the only one made
    assert len(responses.calls) == 1

    # The value should come directly from the `numowned` attribute in the fixture
    assert game.owned_by == 50000

    # No new API calls should be made
    assert len(responses.calls) == 1


@responses.activate
def test_client_backoff_on_429(bgg_client):
    """Test that the client backs off and retries on a 429 status code."""
    bgg_client.initial_backoff = 0.01  # Speed up test
    bgg_client.max_retries = 5
    game_id = 456
    thing_url = f"{bgg_client.api_url}/thing"

    # Simulate BGG rate limiting us, then returning success
    responses.add(responses.GET, thing_url, status=429)
    responses.add(responses.GET, thing_url, status=429)
    responses.add(responses.GET, thing_url, status=429)
    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id}"/></items>',
        status=200,
    )

    game = bgg_client.get_game(game_id)
    # This should trigger the API calls with backoff
    game._fetch_data()

    assert len(responses.calls) == 4


@responses.activate
@patch("time.sleep")
def test_client_backoff_decay(mock_sleep, bgg_client):
    """Test that the backoff delay decays after successful requests."""
    # Configure client for predictable testing
    bgg_client.initial_backoff = 2.0
    bgg_client.backoff_factor = 2.0
    bgg_client.backoff_decay = 0.9
    bgg_client._current_backoff = bgg_client.initial_backoff
    bgg_client.max_retries = 5
    bgg_client.rate_limit_qps = 0  # Disable throttling for this test
    game_id = 123
    thing_url = f"{bgg_client.api_url}/thing"

    # --- Step 1: First request fails once, then succeeds ---
    responses.add(responses.GET, thing_url, status=429)
    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id}"/></items>',
        status=200,
    )

    game = bgg_client.get_game(game_id)
    game._fetch_data()  # Trigger API call

    # It should have slept for the initial backoff time (2.0s)
    mock_sleep.assert_called_once_with(2.0)
    # backoff starts at 2.0
    # failure occurs, sleep(2.0), backoff becomes 2.0 * 2.0 = 4.0
    # success occurs, backoff becomes max(2.0, 4.0 * 0.9) = 3.6
    assert bgg_client._current_backoff == pytest.approx(3.6)
    assert len(responses.calls) == 2

    # --- Step 2: Make another successful request ---
    game_id_2 = 456
    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id_2}"/></items>',
        status=200,
    )
    # Reset mock to test subsequent calls
    mock_sleep.reset_mock()

    game2 = bgg_client.get_game(game_id_2)
    game2._fetch_data()

    # No new sleep calls should have happened
    mock_sleep.assert_not_called()
    # Backoff (3.6) should decay further: max(2.0, 3.6 * 0.9) = 3.24
    assert bgg_client._current_backoff == pytest.approx(3.24)
    assert len(responses.calls) == 3

    # --- Step 3: Repeated successful requests should decay back to initial ---
    for _ in range(20):
        # Use a new game id each time to avoid caching
        next_id = 789 + _
        responses.add(
            responses.GET,
            thing_url,
            body=f'<items><item id="{next_id}"/></items>',
            status=200,
        )
        g = bgg_client.get_game(next_id)
        g._fetch_data()

    # After many successes, it should be very close to the initial backoff
    assert bgg_client._current_backoff == pytest.approx(bgg_client.initial_backoff)


@responses.activate
@patch("time.sleep")
@patch("time.monotonic")
def test_client_throttling(mock_monotonic, mock_sleep, bgg_client):
    """Test that the client throttles requests based on rate_limit_qps."""
    # Configure client for predictable testing
    bgg_client.initial_backoff = 2.0
    bgg_client.rate_limit_qps = 5  # As per user request
    bgg_client._current_backoff = bgg_client.initial_backoff
    bgg_client._last_request_time = 0  # Reset for test
    game_id = 789
    thing_url = f"{bgg_client.api_url}/thing"

    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id}"/></items>',
        status=200,
    )

    # --- First call ---
    mock_monotonic.return_value = 1000.0
    game = bgg_client.get_game(game_id)
    game._fetch_data()  # Trigger API call

    # The first call should not sleep, but it should set the last request time.
    mock_sleep.assert_not_called()
    assert bgg_client._last_request_time == 1000.0

    # --- Second call, immediately after (0.08s later) ---
    mock_sleep.reset_mock()
    game_id_2 = 790
    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id_2}"/></items>',
        status=200,
    )
    mock_monotonic.return_value = 1000.08

    game2 = bgg_client.get_game(game_id_2)
    game2._fetch_data()

    # Expected interval = backoff / qps = 2.0 / 5 = 0.4s
    # Elapsed time = 1000.08 - 1000.0 = 0.08s
    # Expected sleep time = 0.4 - 0.08 = 0.32s
    mock_sleep.assert_called_once_with(pytest.approx(0.32))
    # The last request time should be updated to the time the new request was made
    assert bgg_client._last_request_time == 1000.08


    # --- Third call, after enough time has passed ---
    mock_sleep.reset_mock()
    game_id_3 = 791
    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id_3}"/></items>',
        status=200,
    )
    # Pretend the last request (including sleep) took 0.5s
    mock_monotonic.return_value = 1000.08 + 0.5

    game3 = bgg_client.get_game(game_id_3)
    game3._fetch_data()

    # Elapsed time = (1000.08 + 0.5) - 1000.08 = 0.5s
    # Expected interval is 0.4s. Since 0.5 > 0.4, no sleep is needed.
    mock_sleep.assert_not_called()
    assert bgg_client._last_request_time == 1000.58


@responses.activate
@patch("time.sleep")
@patch("time.monotonic")
def test_throttling_only_for_live_requests(mock_monotonic, mock_sleep, cached_bgg_client):
    """Test that throttling is skipped for cached responses."""
    client = cached_bgg_client
    client.rate_limit_qps = 2
    client.initial_backoff = 1.0
    client._current_backoff = 1.0


    game_id = 999
    thing_url = f"{client.api_url}/thing"
    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id}"/></items>',
        status=200,
    )

    # --- First call (live request) ---
    # Not throttled as it's the first.
    mock_monotonic.return_value = 1000.0
    client._last_request_time = 0
    game = client.get_game(game_id)
    game._fetch_data()
    assert len(responses.calls) == 1
    mock_sleep.assert_not_called()
    assert client._last_request_time == 1000.0

    # --- Second call (cached) ---
    # Should not be throttled as it's from the cache.
    mock_monotonic.return_value = 1000.1
    game._fetch_data()
    assert len(responses.calls) == 1
    mock_sleep.assert_not_called()
    # last_request_time should not be updated for cached requests
    assert client._last_request_time == 1000.0

    # --- Third call (new, live request) ---
    # Should be throttled.
    game_id_2 = 998
    responses.add(
        responses.GET,
        thing_url,
        body=f'<items><item id="{game_id_2}"/></items>',
        status=200,
    )
    game2 = client.get_game(game_id_2)
    mock_monotonic.return_value = 1000.2
    game2._fetch_data()
    assert len(responses.calls) == 2
    # Interval = 1.0 / 2 = 0.5. Elapsed = 1000.2 - 1000.0 = 0.2. Sleep = 0.3
    mock_sleep.assert_called_once_with(pytest.approx(0.3))
    assert client._last_request_time == 1000.2


class TestGameCarcassonne:
    """Tests for the comprehensive Carcassonne game object (ID 822)."""

    @pytest.fixture(scope="function")
    def game(self, bgg_client):
        """Fixture to set up the Carcassonne game object."""
        game_id = 822
        mock_url = f"{bgg_client.api_url}/thing"
        responses.add(
            responses.GET,
            mock_url,
            body=load_fixture("thing_822.xml"),
            status=200,
            content_type="application/xml",
        )
        # The game object is created once for the class, and data is fetched lazily.
        g = bgg_client.get_game(game_id)
        # Prefetch data for all tests in this class
        g._fetch_data()
        return g

    @responses.activate
    def test_basic_properties(self, game):
        """Test basic string and URL properties."""
        assert game.name == "Carcassonne"
        assert game.thumbnail == "https://cf.geekdo-images.com/okM0dq_bEXnbyQTOvHfwRA__thumb/img/88274KiOg94wziybVHyW8AeOiXg=/fit-in/200x150/filters:strip_icc()/pic6544250.png"
        assert game.image == "https://cf.geekdo-images.com/okM0dq_bEXnbyQTOvHfwRA__original/img/aVZEXAI-cUtuunNfPhjeHlS4fwQ=/0x0/filters:format(png)/pic6544250.png"
        assert "Carcassonne is a tile placement game" in game.description

    @responses.activate
    def test_play_time_properties(self, game):
        """Test the various play time properties."""
        assert game.min_play_time == 30
        assert game.max_play_time == 45
        assert game.playing_time == 45

    @responses.activate
    def test_age_and_year(self, game):
        """Test age and year published properties."""
        assert game.min_age == 7
        assert game.year_published == 2000

    @responses.activate
    def test_alternate_names(self, game):
        """Test the alternate_names property."""
        alt_names = game.alternate_names
        assert len(alt_names) == 22
        assert "Каркассон" in alt_names
        assert "カルカソンヌ" in alt_names
        assert "카르카손" in alt_names

    @responses.activate
    def test_suggested_player_age(self, game):
        """Test the suggested_player_age poll parsing."""
        suggestions = game.suggested_player_age
        assert len(suggestions) == 12

        sugs = list(suggestions)
        assert sugs[0].age == "2"
        assert sugs[0].votes == 2
        assert sugs[5].age == "8"
        assert sugs[5].votes == 360

    @responses.activate
    def test_links(self, game):
        """Test a few of the link properties."""
        # Categories
        categories = game.categories
        assert len(categories) == 2
        assert categories[0].link_id == 1035
        assert categories[0].value == "Medieval"
        assert categories[1].type == "boardgamecategory"

        # Mechanics
        mechanics = game.mechanics
        assert len(mechanics) == 9
        assert mechanics[0].value == "Area Majority / Influence"

        # Designers
        designers = game.designers
        assert len(designers) == 1
        assert designers[0].link_id == 398
        assert designers[0].value == "Klaus-Jürgen Wrede"

        # Publishers
        publishers = game.publishers
        assert len(publishers) == 39
        assert publishers[0].value == "Hans im Glück"
        assert any(p.value == "Rio Grande Games" for p in publishers)

    @responses.activate
    def test_statistics_properties(self, game):
        """Test the game statistics properties."""
        stats = game.statistics
        assert stats.users_rated == 134561
        assert stats.average == pytest.approx(7.41263)
        assert stats.bayes_average == pytest.approx(7.29634)
        assert stats.stddev == pytest.approx(1.312)
        assert stats.median == 0
        assert stats.owned == 211938
        assert stats.trading == 2045
        assert stats.wanting == 697
        assert stats.wishing == 10319
        assert stats.num_comments == 22734
        assert stats.num_weights == 8492
        assert stats.average_weight == pytest.approx(1.888)

        assert len(stats.ranks) == 2
        rank1 = stats.ranks[0]
        assert rank1.type == "subtype"
        assert rank1.id == "1"
        assert rank1.name == "boardgame"
        assert rank1.friendly_name == "Board Game Rank"
        assert rank1.value == 233
        assert rank1.bayes_average == pytest.approx(7.29634)

        rank2 = stats.ranks[1]
        assert rank2.type == "family"
        assert rank2.id == "5499"
        assert rank2.name == "familygames"
        assert rank2.friendly_name == "Family Game Rank"
        assert rank2.value == 56
        assert rank2.bayes_average == pytest.approx(7.289)


class TestRatingsFetching:
    """Tests for the new ratings fetching functionality."""

    GAME_ID = 12345
    TOTAL_RATINGS = 250 # Should result in 3 pages (100, 100, 50)
    TOTAL_PAGES = 3
    PAGE_SIZE = 100

    def _get_ratings_calls(self, calls):
        """Helper to filter for ratings API calls."""
        return [
            c for c in calls if "ratingcomments" in c.request.params
        ]

    @responses.activate
    def test_fetch_all_ratings(self, bgg_client):
        """Test that `fetch_all_ratings=True` fetches all rating pages."""
        mock_url = f"{bgg_client.api_url}/thing"

        # Mock the initial game data fetch
        responses.add(
            responses.GET,
            mock_url,
            body=f'<items><item id="{self.GAME_ID}"/></items>',
            status=200,
            match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "stats": "1"})]
        )

        # Mock all pages
        for i in range(1, self.TOTAL_PAGES + 1):
            responses.add(
                responses.GET,
                mock_url,
                body=mock_ratings_response(self.GAME_ID, i, self.PAGE_SIZE, self.TOTAL_RATINGS),
                status=200,
                match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "ratingcomments": "1", "page": str(i), "pagesize": str(self.PAGE_SIZE)})]
            )

        game = bgg_client.get_game(self.GAME_ID, fetch_all_ratings=True)

        ratings_calls = self._get_ratings_calls(responses.calls)
        assert len(ratings_calls) == self.TOTAL_PAGES
        assert len(game.ratings._ratings) == self.TOTAL_RATINGS
        assert game.ratings.all_fetched is True

    @responses.activate
    def test_fetch_randomized_ratings(self, bgg_client):
        """Test that `randomize_ratings=True` fetches a random subset of pages."""
        TOTAL_PAGES_RANDOM = 5
        TOTAL_RATINGS_RANDOM = 450
        PAGES_TO_FETCH = 3
        mock_url = f"{bgg_client.api_url}/thing"

        # Mock the initial game data fetch
        responses.add(
            responses.GET,
            mock_url,
            body=f'<items><item id="{self.GAME_ID}"/></items>',
            status=200,
            match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "stats": "1"})]
        )

        for i in range(1, TOTAL_PAGES_RANDOM + 1):
             responses.add(
                responses.GET,
                mock_url,
                body=mock_ratings_response(self.GAME_ID, i, self.PAGE_SIZE, TOTAL_RATINGS_RANDOM),
                status=200,
                match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "ratingcomments": "1", "page": str(i), "pagesize": str(self.PAGE_SIZE)})]
            )

        game = bgg_client.get_game(self.GAME_ID, max_rating_pages=PAGES_TO_FETCH, randomize_ratings=True)

        ratings_calls = self._get_ratings_calls(responses.calls)
        assert len(ratings_calls) == PAGES_TO_FETCH

        requested_pages = {int(call.request.params["page"]) for call in ratings_calls}
        # For game_id=12345, seeded shuffle of [1,2,3,4,5] is [3, 5, 1, 2, 4]
        # First call is always page 1 for metadata.
        # Then we take the next 2 pages from the shuffled list that are not page 1.
        # Those are 3 and 5.
        assert requested_pages == {1, 3, 5}
        assert len(game.ratings._ratings) == 250


    @responses.activate
    def test_randomized_ratings_are_deterministic(self, bgg_client):
        """Test that randomized page fetching is deterministic."""
        TOTAL_PAGES_RANDOM = 5
        TOTAL_RATINGS_RANDOM = 450
        PAGES_TO_FETCH = 3
        mock_url = f"{bgg_client.api_url}/thing"

        # Mock the initial game data fetch
        responses.add(
            responses.GET,
            mock_url,
            body=f'<items><item id="{self.GAME_ID}"/></items>',
            status=200,
            match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "stats": "1"})]
        )

        for i in range(1, TOTAL_PAGES_RANDOM + 1):
             responses.add(
                responses.GET,
                mock_url,
                body=mock_ratings_response(self.GAME_ID, i, self.PAGE_SIZE, TOTAL_RATINGS_RANDOM),
                status=200,
                match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "ratingcomments": "1", "page": str(i), "pagesize": str(self.PAGE_SIZE)})]
            )

        # Client 1
        bgg_client.get_game(self.GAME_ID, max_rating_pages=PAGES_TO_FETCH, randomize_ratings=True)
        ratings_calls1 = self._get_ratings_calls(responses.calls)
        requested_pages1 = sorted([int(call.request.params["page"]) for call in ratings_calls1])

        # Reset responses for the next client
        responses.reset()

        # Re-add mocks for client 2
        responses.add(
            responses.GET,
            mock_url,
            body=f'<items><item id="{self.GAME_ID}"/></items>',
            status=200,
            match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "stats": "1"})]
        )
        for i in range(1, TOTAL_PAGES_RANDOM + 1):
             responses.add(
                responses.GET,
                mock_url,
                body=mock_ratings_response(self.GAME_ID, i, self.PAGE_SIZE, TOTAL_RATINGS_RANDOM),
                status=200,
                match=[responses.matchers.query_param_matcher({"id": str(self.GAME_ID), "ratingcomments": "1", "page": str(i), "pagesize": str(self.PAGE_SIZE)})]
            )

        # Client 2
        bgg_client.get_game(self.GAME_ID, max_rating_pages=PAGES_TO_FETCH, randomize_ratings=True)
        ratings_calls2 = self._get_ratings_calls(responses.calls)
        requested_pages2 = sorted([int(call.request.params["page"]) for call in ratings_calls2])

        assert requested_pages1 == requested_pages2
        assert requested_pages1 == [1, 3, 5]

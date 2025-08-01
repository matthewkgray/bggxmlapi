import pytest
import responses
from pathlib import Path
from unittest.mock import patch

from bgg_api.client import BGGClient
from bgg_api.exceptions import BGGAPIError, BGGNetworkError

# Helper to load fixture files
def load_fixture(name):
    return (Path(__file__).parent / "fixtures" / name).read_text()

import requests

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

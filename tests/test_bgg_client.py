import pytest
import responses
from pathlib import Path

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

import pytest
import responses
import requests

from bgg_api.client import BGGClient
from bgg_api.snapshot import RankSnapshot
from bgg_api.exceptions import BGGNetworkError

@pytest.fixture
def sample_csv_data():
    """Provides a sample of the rankings CSV data for testing."""
    return """\
ID,Name,Year,Rank,Average,Bayes average,Users rated,URL,Thumbnail
174430,Gloomhaven,2017,1,8.8,8.5,45000,/boardgame/174430/gloomhaven,thumb1.jpg
161936,Pandemic Legacy: Season 1,2015,2,8.6,8.4,40000,/boardgame/161936/pandemic-legacy-season-1,thumb2.jpg
822,Carcassonne,2000,150,7.4,7.2,100000,/boardgame/822/carcassonne,thumb3.jpg
"""

@pytest.fixture
def bgg_client():
    """Returns a BGGClient instance for testing, with caching disabled."""
    # Use a non-existent cache dir for tests to avoid writing to the filesystem
    client = BGGClient(cache_dir="/tmp/bgg_api_test_cache_snapshot")
    # For testing, we don't want to deal with the cache, so we replace the
    # cached session with a regular one. This lets `responses` work correctly.
    client.session = requests.Session()
    return client

class TestRankSnapshot:
    def test_initialization_and_parsing(self, sample_csv_data):
        snapshot = RankSnapshot(sample_csv_data)
        assert snapshot.header == ["ID", "Name", "Year", "Rank", "Average", "Bayes average", "Users rated", "URL", "Thumbnail"]
        assert len(snapshot.rows) == 3
        assert len(snapshot.id_map) == 3
        assert len(snapshot.rank_map) == 3

    def test_data_accessors(self, sample_csv_data):
        snapshot = RankSnapshot(sample_csv_data)
        game_id = 174430
        assert snapshot.name(game_id) == "Gloomhaven"
        assert snapshot.year(game_id) == 2017
        assert snapshot.rank(game_id) == 1
        assert snapshot.average_rating(game_id) == 8.8
        assert snapshot.bayes_average_rating(game_id) == 8.5
        assert snapshot.users_rated(game_id) == 45000
        assert snapshot.url(game_id) == "/boardgame/174430/gloomhaven"
        assert snapshot.thumbnail(game_id) == "thumb1.jpg"

    def test_get_id_at_rank(self, sample_csv_data):
        snapshot = RankSnapshot(sample_csv_data)
        assert snapshot.get_id_at_rank(1) == 174430
        assert snapshot.get_id_at_rank(2) == 161936
        assert snapshot.get_id_at_rank(150) == 822
        assert snapshot.get_id_at_rank(999) is None

    def test_all_ids(self, sample_csv_data):
        snapshot = RankSnapshot(sample_csv_data)
        ids = snapshot.ids()
        assert set(ids) == {174430, 161936, 822}

    def test_nonexistent_game(self, sample_csv_data):
        snapshot = RankSnapshot(sample_csv_data)
        game_id = 999999
        assert snapshot.name(game_id) == "???"
        assert snapshot.rank(game_id) == 0

    def test_empty_csv(self):
        snapshot = RankSnapshot("")
        assert snapshot.header == []
        assert len(snapshot.rows) == 0
        assert snapshot.ids() == []

    def test_malformed_csv(self, capsys):
        csv_data = """\
ID,Name,Year,Rank,Average,Bayes average,Users rated,URL,Thumbnail
174430,Gloomhaven,2017,1,8.8,8.5,45000,/boardgame/174430/gloomhaven,thumb1.jpg
161936,Pandemic Legacy,not-a-year,2,8.6,8.4,40000,/boardgame/161936/pandemic-legacy-season-1,thumb2.jpg
822,Carcassonne,2000,150,7.4,7.2,100000,/boardgame/822/carcassonne,thumb3.jpg
"""
        snapshot = RankSnapshot(csv_data)
        # The malformed line should be skipped, the other two should be parsed
        assert len(snapshot.rows) == 2
        assert snapshot.ids() == [174430, 822]
        captured = capsys.readouterr()
        assert "Skipping malformed line" in captured.out
        assert "not-a-year" in captured.out


@responses.activate
def test_get_rank_snapshot_success(bgg_client, sample_csv_data):
    date_str = "2024-01-15"
    url = f"{bgg_client.snapshot_url}/{date_str}.csv"
    responses.add(
        responses.GET,
        url,
        body=sample_csv_data,
        status=200,
        content_type="text/plain",
    )

    snapshot = bgg_client.get_rank_snapshot(date_str)

    assert isinstance(snapshot, RankSnapshot)
    assert snapshot.rank(174430) == 1
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == url

@responses.activate
def test_get_rank_snapshot_network_error(bgg_client):
    date_str = "2024-01-16"
    url = f"{bgg_client.snapshot_url}/{date_str}.csv"
    responses.add(
        responses.GET,
        url,
        status=404,
    )

    with pytest.raises(BGGNetworkError):
        bgg_client.get_rank_snapshot(date_str)

    assert len(responses.calls) == 1

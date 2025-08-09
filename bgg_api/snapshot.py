import csv
from typing import List, Dict, Any, Optional

class RankSnapshot:
    """
    Represents a snapshot of BGG rankings from a specific date.
    This class parses CSV data from the bgg-ranking-historicals repository
    and provides methods to access the ranking data.
    """

    def __init__(self, csv_data: str):
        """
        Initializes the RankSnapshot with CSV data.

        Args:
            csv_data (str): A string containing the CSV data.
        """
        self.header: List[str] = []
        self.rows: List[List[Any]] = []
        self.id_map: Dict[int, List[Any]] = {}
        self.rank_map: Dict[int, int] = {}
        self._defaults = [0, "???", 0, 0, 0.0, 0.0, 0, "-", "-"]

        reader = csv.reader(csv_data.strip().split("\n"))
        try:
            self.header = next(reader)
            for line in reader:
                if not line:
                    continue  # Skip empty lines

                try:
                    #  ID,Name,Year,Rank,Average,Bayes average,Users rated,URL,Thumbnail
                    typed_line = [
                        int(line[0]),      # ID
                        line[1],           # Name
                        int(line[2]),      # Year
                        int(line[3]),      # Rank
                        float(line[4]),    # Average
                        float(line[5]),    # Bayes average
                        int(line[6]),      # Users rated
                        line[7],           # URL
                        line[8],           # Thumbnail
                    ]
                    self.rows.append(typed_line)
                    game_id = typed_line[0]
                    rank = typed_line[3]
                    self.id_map[game_id] = typed_line
                    self.rank_map[rank] = game_id
                except (ValueError, IndexError) as e:
                    # Handle potential malformed lines in the CSV
                    # For example, if a value can't be converted to int/float
                    print(f"Skipping malformed line: {line} - Error: {e}")

        except StopIteration:
            # Handle empty CSV data
            pass

    def ids(self) -> List[int]:
        """Returns a list of all game IDs in the snapshot."""
        return [row[0] for row in self.rows]

    def get_game_info(self, game_id: int) -> Optional[List[Any]]:
        """
        Retrieves all information for a given game ID.

        Args:
            game_id (int): The BGG ID of the game.

        Returns:
            A list of values for the game, or None if not found.
        """
        return self.id_map.get(game_id)

    def name(self, game_id: int) -> str:
        """Returns the name of the game for a given ID."""
        return self.id_map.get(game_id, self._defaults)[1]

    def year(self, game_id: int) -> int:
        """Returns the publication year of the game for a given ID."""
        return self.id_map.get(game_id, self._defaults)[2]

    def rank(self, game_id: int) -> int:
        """Returns the rank of the game for a given ID."""
        return self.id_map.get(game_id, self._defaults)[3]

    def average_rating(self, game_id: int) -> float:
        """Returns the average rating of the game for a given ID."""
        return self.id_map.get(game_id, self._defaults)[4]

    def bayes_average_rating(self, game_id: int) -> float:
        """Returns the bayesian average rating of the game for a given ID."""
        return self.id_map.get(game_id, self._defaults)[5]

    def users_rated(self, game_id: int) -> int:
        """Returns the number of users who rated the game for a given ID."""
        return self.id_map.get(game_id, self._defaults)[6]

    def url(self, game_id: int) -> str:
        """Returns the BGG URL for the game."""
        return self.id_map.get(game_id, self._defaults)[7]

    def thumbnail(self, game_id: int) -> str:
        """Returns the thumbnail URL for the game."""
        return self.id_map.get(game_id, self._defaults)[8]

    def get_id_at_rank(self, rank: int) -> Optional[int]:
        """
        Returns the game ID at a specific rank.

        Args:
            rank (int): The rank to look up.

        Returns:
            The game ID at that rank, or None if not found.
        """
        return self.rank_map.get(rank)

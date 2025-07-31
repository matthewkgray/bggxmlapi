import argparse
import logging
from bgg_api import BGGClient, BGGAPIError, Game
from typing import List, Callable

# Configure logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

def get_sort_key(sort_choice: str) -> Callable[[Game], any]:
    """Returns a lambda function to use as a sort key."""
    if sort_choice == "rarity":
        # We need to add a way to get ownership stats
        return lambda game: getattr(game, 'owned_by', 999999)
    elif sort_choice == "rating":
        # We need to add a way to get the average rating
        return lambda game: getattr(game, 'average_rating', 0.0)
    elif sort_choice == "year":
        return lambda game: getattr(game, 'year_published', 0)
    else:  # Default to sorting by name
        return lambda game: game.name

def find_common_games(user1_name: str, user2_name: str, sort_by: str):
    """
    Finds games that are in both users' collections and sorts them.
    """
    client = BGGClient()

    try:
        log.info(f"Fetching collection for '{user1_name}'...")
        user1 = client.get_user(user1_name)
        user1_collection = {game.id: game for game in user1.collection}
        log.info(f"Found {len(user1_collection)} games in '{user1_name}'s collection.")

        log.info(f"Fetching collection for '{user2_name}'...")
        user2 = client.get_user(user2_name)
        user2_collection = {game.id: game for game in user2.collection}
        log.info(f"Found {len(user2_collection)} games in '{user2_name}'s collection.")

        common_game_ids = set(user1_collection.keys()) & set(user2_collection.keys())
        log.info(f"\\nFound {len(common_game_ids)} common games in both collections.")

        if not common_game_ids:
            return

        common_games: List[Game] = [user1_collection[game_id] for game_id in common_game_ids]

        # The game objects from the collection call should have stats.
        # We will add properties to the Game model to easily access them.
        sort_key_func = get_sort_key(sort_by)
        is_reverse = sort_by in ["rating", "year"] # Higher is better/newer
        common_games.sort(key=sort_key_func, reverse=is_reverse)

        print(f"\\n--- Common Games for {user1_name} and {user2_name} (sorted by {sort_by}) ---")
        for game in common_games:
            rating_val = game.average_rating
            owners_val = game.owned_by
            year_val = game.year_published or "N/A"

            rating_str = f"{rating_val:.2f}" if isinstance(rating_val, float) else "N/A"
            owners_str = f"{owners_val}" if isinstance(owners_val, int) else "N/A"

            print(f"- {game.name} ({year_val}) "
                  f"| Avg Rating: {rating_str} | Owned by: {owners_str}")

    except BGGAPIError as e:
        log.error(f"API Error: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Find common games in two BGG users' collections.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Example Usage:
python examples/find_common_collection_games.py testuser octavian --sort rating

This command finds all games owned by both 'testuser' and 'octavian' and
sorts them by their average BGG rating in descending order.
"""
    )
    parser.add_argument("user1", help="The BGG username of the first user.")
    parser.add_argument("user2", help="The BGG username of the second user.")
    parser.add_argument(
        "--sort",
        choices=["name", "rating", "year", "rarity"],
        default="name",
        help="The criteria to sort the common games by. 'rarity' sorts by fewest owners. Default is 'name'.",
    )
    args = parser.parse_args()

    find_common_games(args.user1, args.user2, args.sort)

if __name__ == "__main__":
    main()

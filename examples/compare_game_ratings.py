import argparse
import logging
from scipy.stats import pearsonr
from bgg_api import BGGClient, BGGAPIError

# Configure logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

def analyze_game_ratings(game1_id: int, game2_id: int, pages: int):
    """
    Fetches ratings for two games, compares the user ratings, and
    provides a summary of preferences.
    """
    client = BGGClient()

    try:
        log.info(f"Fetching details for Game 1 (ID: {game1_id}) and Game 2 (ID: {game2_id})...")
        game1 = client.get_game(game1_id)
        game2 = client.get_game(game2_id)

        # Trigger the lazy loading of names
        log.info(f"Game 1: {game1.name}")
        log.info(f"Game 2: {game2.name}")

        # Fetch ratings pages
        log.info(f"Fetching the first {pages} page(s) of ratings for each game...")
        if not game1.ratings.all_fetched:
            game1.ratings.fetch_more(pages)
        if not game2.ratings.all_fetched:
            game2.ratings.fetch_more(pages)

        log.info(f"Fetched {len(game1.ratings._ratings)} ratings for {game1.name}.")
        log.info(f"Fetched {len(game2.ratings._ratings)} ratings for {game2.name}.")

        # Create a dictionary for faster lookups from the fetched ratings
        game1_ratings = {r.username: r.rating for r in game1.ratings._ratings if r.username != "N/A"}
        game2_ratings = {r.username: r.rating for r in game2.ratings._ratings if r.username != "N/A"}

        # Find common raters
        common_raters = set(game1_ratings.keys()) & set(game2_ratings.keys())
        log.info(f"\\nFound {len(common_raters)} users who rated both games.")

        if not common_raters:
            log.warning("No common raters found with the specified number of pages. Try increasing the page count.")
            return

        # Analyze preferences of common raters
        prefer_game1 = 0
        prefer_game2 = 0
        no_preference = 0
        total_rating_game1 = 0
        total_rating_game2 = 0

        for user in common_raters:
            rating1 = game1_ratings[user]
            rating2 = game2_ratings[user]
            total_rating_game1 += rating1
            total_rating_game2 += rating2
            if rating1 > rating2:
                prefer_game1 += 1
            elif rating2 > rating1:
                prefer_game2 += 1
            else:
                no_preference += 1

        # --- Analysis of users who rated both games ---
        print("\\n--- Analysis of Common Raters ---")
        print(f"Total users who rated both: {len(common_raters)}")
        print(f"Users who prefer '{game1.name}': {prefer_game1} ({prefer_game1/len(common_raters):.1%})")
        print(f"Users who prefer '{game2.name}': {prefer_game2} ({prefer_game2/len(common_raters):.1%})")
        print(f"Users with no preference (same rating): {no_preference} ({no_preference/len(common_raters):.1%})")
        print(f"Average rating for '{game1.name}' among these users: {total_rating_game1/len(common_raters):.2f}")
        print(f"Average rating for '{game2.name}' among these users: {total_rating_game2/len(common_raters):.2f}")

        # Calculate correlation coefficient
        if len(common_raters) > 1:
            ratings1 = [game1_ratings[u] for u in common_raters]
            ratings2 = [game2_ratings[u] for u in common_raters]
            correlation, p_value = pearsonr(ratings1, ratings2)
            print(f"Correlation of ratings among common raters: {correlation:.4f} (p-value: {p_value:.4f})")


        # --- Analysis of users who rated only one game ---
        game1_only_raters = set(game1_ratings.keys()) - common_raters
        game2_only_raters = set(game2_ratings.keys()) - common_raters

        # Avg rating for Game 1 from users who ONLY rated Game 1
        g1_only_total_rating = sum(game1_ratings[u] for u in game1_only_raters)
        g1_only_avg = g1_only_total_rating / len(game1_only_raters) if game1_only_raters else 0

        # Avg rating for Game 2 from users who ONLY rated Game 2
        g2_only_total_rating = sum(game2_ratings[u] for u in game2_only_raters)
        g2_only_avg = g2_only_total_rating / len(game2_only_raters) if game2_only_raters else 0

        print("\\n--- Analysis of Exclusive Raters ---")
        print(f"Found {len(game1_only_raters)} users who only rated '{game1.name}'.")
        print(f"  - Average rating for '{game1.name}' among these users: {g1_only_avg:.2f}")
        print(f"Found {len(game2_only_raters)} users who only rated '{game2.name}'.")
        print(f"  - Average rating for '{game2.name}' among these users: {g2_only_avg:.2f}")


    except BGGAPIError as e:
        log.error(f"API Error: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Compare user ratings for two BoardGameGeek games.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Example Usage:
python examples/compare_game_ratings.py 174430 161936 --pages 5

This command compares 'Gloomhaven' (174430) and 'Pandemic Legacy: Season 1' (161936),
fetching up to 500 ratings for each to find common raters and analyze their preferences.
"""
    )
    parser.add_argument("game1_id", type=int, help="The BGG ID of the first game.")
    parser.add_argument("game2_id", type=int, help="The BGG ID of the second game.")
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="The number of rating pages to fetch for each game (100 ratings per page). Default is 2.",
    )
    args = parser.parse_args()

    analyze_game_ratings(args.game1_id, args.game2_id, args.pages)

if __name__ == "__main__":
    main()

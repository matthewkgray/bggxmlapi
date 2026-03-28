import argparse
import logging
import statistics
from scipy.stats import pearsonr
from bgg_api import BGGClient, BGGAPIError
from bgg_api.stats import calculate_correlation

# Configure logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

def analyze_game_ratings(game1_id: int, game2_id: int, pages: int, pref_thresh: float, offline: bool, correlation_method: str = 'pearson'):
    """
    Fetches ratings for two games, compares the user ratings, and
    provides a summary of preferences.
    """
    client = BGGClient(
        api_token="YOUR_BGG_TOKEN",
        only_use_cache=offline
    )

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
        log.info(f"\nFound {len(common_raters)} users who rated both games ({len(game1_ratings)} and {len(game2_ratings)} of the games individually).")

        if not common_raters:
            log.warning("No common raters found with the specified number of pages. Try increasing the page count.")
            return

        # Analyze preferences of common raters
        prefer_game1 = 0
        prefer_game2 = 0
        strong_prefer_game1 = 0
        strong_prefer_game2 = 0
        no_preference = 0
        total_rating_game1 = 0
        total_rating_game2 = 0

        for user in common_raters:
            rating1 = game1_ratings[user]
            rating2 = game2_ratings[user]
            total_rating_game1 += rating1
            total_rating_game2 += rating2
            
            diff = rating1 - rating2
            if rating1 > rating2:
                prefer_game1 += 1
                if diff > pref_thresh:
                    strong_prefer_game1 += 1
            elif rating2 > rating1:
                prefer_game2 += 1
                if (-diff) > pref_thresh:
                    strong_prefer_game2 += 1
            else:
                no_preference += 1

        # --- Analysis of users who rated both games ---
        print("\n--- Analysis of Common Raters ---")
        print(f"Total users who rated both: {len(common_raters)}")
        print(f"Users who prefer '{game1.name}': {prefer_game1} ({prefer_game1/len(common_raters):.1%})")
        print(f"  - Strong preference (>{pref_thresh} pts): {strong_prefer_game1} ({strong_prefer_game1/len(common_raters):.1%})")
        print(f"Users who prefer '{game2.name}': {prefer_game2} ({prefer_game2/len(common_raters):.1%})")
        print(f"  - Strong preference (>{pref_thresh} pts): {strong_prefer_game2} ({strong_prefer_game2/len(common_raters):.1%})")
        print(f"Users with no preference (same rating): {no_preference} ({no_preference/len(common_raters):.1%})")
        
        # Combined strong preference
        any_strong = strong_prefer_game1 + strong_prefer_game2
        print(f"Users with strong preference for EITHER (>{pref_thresh} pts): {any_strong} ({any_strong/len(common_raters):.1%})")
        avg1 = total_rating_game1/len(common_raters)
        avg2 = total_rating_game2/len(common_raters)
        print(f"Average rating for '{game1.name}' among these users: {avg1:.2f}")
        print(f"Average rating for '{game2.name}' among these users: {avg2:.2f}")

        if len(common_raters) > 1:
            raters_list = list(common_raters)
            ratings1 = [game1_ratings[u] for u in raters_list]
            ratings2 = [game2_ratings[u] for u in raters_list]
            var1 = statistics.variance(ratings1)
            var2 = statistics.variance(ratings2)
            print(f"Variance of ratings for '{game1.name}' among these users: {var1:.2f}")
            print(f"Variance of ratings for '{game2.name}' among these users: {var2:.2f}")

        # Calculate correlation coefficient
        if len(common_raters) > 1:
            ratings1 = [game1_ratings[u] for u in common_raters]
            ratings2 = [game2_ratings[u] for u in common_raters]
            correlation, p_value = calculate_correlation(ratings1, ratings2, method=correlation_method)
            print(f"{correlation_method.capitalize()} correlation of ratings among common raters: {correlation:.4f} (p-value: {p_value:.4f})")


        # --- Analysis of users who rated only one game ---
        game1_only_raters = set(game1_ratings.keys()) - common_raters
        game2_only_raters = set(game2_ratings.keys()) - common_raters

        # Avg rating for Game 1 from users who ONLY rated Game 1
        g1_only_ratings = [game1_ratings[u] for u in game1_only_raters]
        g1_only_avg = statistics.mean(g1_only_ratings) if g1_only_ratings else 0
        g1_only_var = statistics.variance(g1_only_ratings) if len(g1_only_ratings) > 1 else 0

        # Avg rating for Game 2 from users who ONLY rated Game 2
        g2_only_ratings = [game2_ratings[u] for u in game2_only_raters]
        g2_only_avg = statistics.mean(g2_only_ratings) if g2_only_ratings else 0
        g2_only_var = statistics.variance(g2_only_ratings) if len(g2_only_ratings) > 1 else 0

        print("\n--- Analysis of Exclusive Raters ---")
        print(f"Found {len(game1_only_raters)} users who only rated '{game1.name}'.")
        print(f"  - Average rating: {g1_only_avg:.2f}")
        print(f"  - Variance: {g1_only_var:.2f}")
        print(f"Found {len(game2_only_raters)} users who only rated '{game2.name}'.")
        print(f"  - Average rating: {g2_only_avg:.2f}")
        print(f"  - Variance: {g2_only_var:.2f}")


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
    parser.add_argument(
        "--preference-threshold",
        type=float,
        default=1.0,
        help="The threshold for a 'strong preference' (difference in points). Default is 1.0.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Only use cached data and never fetch from the network. Default is False.",
    )
    parser.add_argument(
        "--correlation",
        choices=["pearson", "spearman"],
        default="pearson",
        help="Correlation method to use. Default is 'pearson'.",
    )
    args = parser.parse_args()
    
    analyze_game_ratings(args.game1_id, args.game2_id, args.pages, args.preference_threshold, args.offline, correlation_method=args.correlation)

if __name__ == "__main__":
    main()

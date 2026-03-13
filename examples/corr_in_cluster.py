import argparse
import logging
import itertools
from scipy.stats import pearsonr
from bgg_api import BGGClient, BGGAPIError

# Configure logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

def get_related_games(game_id: int, client: BGGClient, collected_games: dict, ignore_expansions: bool = True) -> None:
    """
    Recursively finds all related games for a given game ID.
    Populates collected_games with BGG game objects.
    """
    if game_id in collected_games:
        return

    collected_games[game_id] = None # Placeholder
    
    try:
        game = client.get_game(game_id)
        log.info(f"Traversing: {game.name} (ID: {game.id})")
        
        collected_games[game_id] = game
        
        related_ids = set()
        if not ignore_expansions:
            for link in game.expansions:
                if not link.inbound:
                    related_ids.add(link.id)
        for link in game.implementations:
            related_ids.add(link.id)
        for link in game.integrations:
            related_ids.add(link.id)
            
        for rid in related_ids:
            get_related_games(rid, client, collected_games, ignore_expansions=ignore_expansions)
                
    except BGGAPIError as e:
        log.error(f"Error fetching game {game_id}: {e}")
        if collected_games[game_id] is None:
             del collected_games[game_id]
    except Exception as e:
        log.error(f"Unexpected error for game {game_id}: {e}")
        if collected_games[game_id] is None:
             del collected_games[game_id]

def main():
    parser = argparse.ArgumentParser(
        description="Get correlation coefficient between all pairs of games in a cluster.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("game_id", type=int, help="The BGG ID of the starting game in the cluster.")
    parser.add_argument("--include-expansions", action="store_true", help="Include game expansions in the traversal.")
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="The number of rating pages to fetch for each game (100 ratings per page). Default is 2.",
    )
    args = parser.parse_args()

    client = BGGClient(api_token="YOUR_BGG_TOKEN")

    log.info(f"Finding cluster starting from game ID: {args.game_id}")
    collected_games_map = {}
    get_related_games(args.game_id, client, collected_games_map, ignore_expansions=not args.include_expansions)
    
    games = [g for g in collected_games_map.values() if g is not None]
    if not games:
        log.error("No games found in cluster.")
        return

    log.info(f"Cluster found with {len(games)} games.")

    # Fetch ratings
    game_ratings = {}
    for game in games:
        log.info(f"Fetching {args.pages} page(s) of ratings for {game.name}...")
        try:
            if not game.ratings.all_fetched:
                game.ratings.fetch_more(args.pages)
            
            # Store ratings: {username: rating}
            ratings = {r.username: r.rating for r in game.ratings._ratings if r.username != "N/A"}
            game_ratings[game.id] = ratings
        except Exception as e:
            log.error(f"Failed to fetch ratings for {game.name}: {e}")
            game_ratings[game.id] = {}

    # Output Summary Table
    print("\n--- Game Summary ---")
    print(f"{'ID':<7} | {'Ratings Fetched':<15} | {'Name'}")
    print("-" * 60)
    for game in sorted(games, key=lambda x: x.id):
        fetched_count = len(game_ratings.get(game.id, {}))
        print(f"{game.id:<7} | {fetched_count:<15} | {game.name}")

    # Calculate Pairwise Correlations
    print("\n--- Pairwise Correlation Analysis ---")
    header = f"{'Game A':<30} | {'Game B':<30} | {'Co-raters':<10} | {'Corr':<7} | {'p-value'}"
    print(header)
    print("-" * len(header))

    game_pairs = list(itertools.combinations(sorted(games, key=lambda x: x.id), 2))
    
    for g1, g2 in game_pairs:
        r1 = game_ratings[g1.id]
        r2 = game_ratings[g2.id]
        
        common_users = set(r1.keys()) & set(r2.keys())
        co_rater_count = len(common_users)
        
        corr_str = "N/A"
        p_val_str = "N/A"
        
        if co_rater_count > 1:
            try:
                v1 = [r1[u] for u in common_users]
                v2 = [r2[u] for u in common_users]
                correlation, p_value = pearsonr(v1, v2)
                corr_str = f"{correlation:.4f}"
                p_val_str = f"{p_value:.4f}"
            except Exception as e:
                log.debug(f"Correlation calculation failed for {g1.name} vs {g2.name}: {e}")

        # Truncate names for table
        n1 = (g1.name[:27] + '..') if len(g1.name) > 30 else g1.name
        n2 = (g2.name[:27] + '..') if len(g2.name) > 30 else g2.name
        
        print(f"{n1:<30} | {n2:<30} | {co_rater_count:<10} | {corr_str:<7} | {p_val_str}")

if __name__ == "__main__":
    main()

import argparse
import logging
import datetime
from bgg_api import BGGClient, BGGAPIError
from get_game_graph import get_related_games, format_cluster_name, calculate_cluster_stats

# Configure logging
log = logging.getLogger(__name__)
# Set level to WARNING to avoid chatty logs from get_game_graph traversal by default, 
# or keep INFO if user wants to see progress. The user asked for a list output, 
# so we typically want clean stdout.
logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")

def main():
    parser = argparse.ArgumentParser(
        description="List game clusters by rank, skipping games already visited.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--date", type=str, help="Date for ranking snapshot (YYYY-MM-DD). Defaults to yesterday.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of clusters to list. Default 100.")
    parser.add_argument("--rank-limit", type=int, default=1000, help="Maximum rank to check. Default 1000.")
    args = parser.parse_args()

    # Determine date
    if args.date:
        date_str = args.date
    else:
        # Default to yesterday to be safe for snapshot availability
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    client = BGGClient(api_token="af0a696a-7be1-4701-841a-17704c6892cc")

    print(f"Fetching rank snapshot for {date_str}...")
    try:
        snapshot = client.get_rank_snapshot(date_str)
    except Exception as e:
        log.error(f"Failed to fetch snapshot for {date_str}: {e}")
        return

    visited_games = set()
    clusters_found = 0
    current_rank = 1

    visited_game_info = {} # Maps game_id -> {rep_name, rep_rank, games_list}
    deduped_games = [] # List of {name, rank, rep_name, rep_rank, games_list}

    print(f"{'Rank':<6} | {'Cluster Name':<60} | {'#G':<4} | {'#X':<4}")
    print("-" * 86)

    while clusters_found < args.limit and current_rank <= args.rank_limit:
        game_id = snapshot.get_id_at_rank(current_rank)
        
        if not game_id:
            # Rank might be missing or skipped in snapshot
            current_rank += 1
            continue
            
        if game_id in visited_games:
            # Access info about the cluster leader
            info = visited_game_info.get(game_id)
            if info:
                deduped_games.append({
                    'name': snapshot.name(game_id),
                    'rank': current_rank,
                    'rep_name': info['rep_name'],
                    'rep_rank': info['rep_rank'],
                    'games_list': info['games_list']
                })
            current_rank += 1
            continue

        # Found a new game start
        collected_games = {}
        # We suppress logs for clarity, or user can enable debug
        get_related_games(game_id, client, collected_games)
        
        # Filter out failed fetches
        valid_games = [g for g in collected_games.values() if g is not None]
        
        if not valid_games:
             current_rank += 1
             continue
        
        cluster_name = format_cluster_name(valid_games)
        
        # Identify boardgames for the summary list
        boardgames_list = [g['name'] for g in valid_games if g.get('type') == 'boardgame']
        # Sort so the main game is first, or keep alphabetical, or sorted by users_rated? 
        # format_cluster_name sorts by users_rated, let's just stick to that or similar.
        # Let's re-sort by name for the list display or just store them. 
        # User asked for "list of all the *games*".
        boardgames_list.sort() 
        
        # Mark all found games as visited and store metadata
        for gid in collected_games.keys():
            visited_games.add(gid)
            visited_game_info[gid] = {
                'rep_name': cluster_name, # or just main game name? User said "higher ranked game... that ranked higher"
                 # Actually, current_rank IS the rank of the representative game here (since we are processing it).
                'rep_rank': current_rank, 
                'games_list': boardgames_list
            }
            
        stats = calculate_cluster_stats(valid_games)
        
        num_games = stats['type_counts'].get('boardgame', 0)
        num_expansions = stats['type_counts'].get('boardgameexpansion', 0)
        
        print(f"{clusters_found + 1:<6} | {cluster_name[:60]:<60} | {num_games:<4} | {num_expansions:<4}")
        
        clusters_found += 1
        current_rank += 1

    if deduped_games:
        print("\n--- Deduped Games Summary ---")
        # Columns: Rank, Game, Representative (Rank), Cluster Games
        print(f"{'Rank':<6} | {'Game':<40} | {'Rep (Rank)':<30} | {'Cluster Games'}")
        print("-" * 150)
        for d in deduped_games:
            rep_str = f"{d['rep_name'][:20]} ({d['rep_rank']})"
            games_str = ", ".join(d['games_list'])
            print(f"{d['rank']:<6} | {d['name'][:40]:<40} | {rep_str:<30} | {games_str}")

if __name__ == "__main__":
    main()

import argparse
import logging
from bgg_api import BGGClient, BGGAPIError

# Configure logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

def get_related_games(game_id: int, client: BGGClient, collected_games: dict) -> None:
    """
    Recursively finds all related games for a given game ID.
    Traverses expansions, implementations, and integrations.
    Populates collected_games with {id: {'name': name, 'users_rated': count}}.
    """
    if game_id in collected_games:
        return

    # Placeholder to prevent infinite recursion before fetch completes if there are self-references (unlikely but safe)
    # We'll update this with real data after fetch
    collected_games[game_id] = None 
    
    try:
        game = client.get_game(game_id)
        
        # Trigger fetch and access data
        name = game.name
        log.info(f"Processing: {name} (ID: {game.id})")
        
        users_rated = 0
        if game.statistics:
            users_rated = game.statistics.users_rated

        collected_games[game_id] = {
            'name': name,
            'users_rated': users_rated
        }
        
        # Collect related game IDs
        related_ids = set()
        
        for link in game.expansions:
            related_ids.add(link.id)
        for link in game.implementations:
            related_ids.add(link.id)
        for link in game.integrations:
            related_ids.add(link.id)
            
        # Recurse
        for rid in related_ids:
            get_related_games(rid, client, collected_games)
                
    except BGGAPIError as e:
        log.error(f"Error fetching game {game_id}: {e}")
        # Remove from collected if failed so we don't have None or can retry
        if collected_games[game_id] is None:
             del collected_games[game_id]
    except Exception as e:
        log.error(f"Unexpected error for game {game_id}: {e}")
        if collected_games[game_id] is None:
             del collected_games[game_id]

def format_cluster_name(games_data: list) -> str:
    """
    Formats the cluster name: MainGame (+GameA, GameB, +N)
    games_data is a list of dicts: {'name': str, 'users_rated': int}
    """
    if not games_data:
        return "Empty Cluster"
        
    # Sort by users_rated descending
    sorted_games = sorted(games_data, key=lambda x: x['users_rated'], reverse=True)
    
    main_game = sorted_games[0]['name']
    
    if len(sorted_games) == 1:
        return main_game
        
    parts = [main_game, " (+"]
    extras = []
    
    # Add GameA
    if len(sorted_games) > 1:
        extras.append(sorted_games[1]['name'])
        
    # Add GameB
    if len(sorted_games) > 2:
        extras.append(sorted_games[2]['name'])
        
    # Add +N
    remaining = len(sorted_games) - 3
    if remaining > 0:
        extras.append(f"+{remaining}")
        
    parts.append(", ".join(extras))
    parts.append(")")
    
    return "".join(parts).replace(" (+)", "") # Handle edge case if logical but unlikely

def main():
    parser = argparse.ArgumentParser(
        description="Recursively find all related games (expansions, implementations, integrations).",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("game_id", type=int, help="The BGG ID of the starting game.")
    args = parser.parse_args()

    client = BGGClient(api_token="af0a696a-7be1-4701-841a-17704c6892cc")

    log.info(f"Starting traversal from game ID: {args.game_id}")
    collected_games = {}
    get_related_games(args.game_id, client, collected_games)
    
    # Filter out any None entries fromfailed fetches
    valid_games = [g for g in collected_games.values() if g is not None]
    
    print("\n--- Cluster Analysis ---")
    cluster_name = format_cluster_name(valid_games)
    print(f"Cluster Name: {cluster_name}")
    
    sorted_ids = sorted(collected_games.keys())
    print(f"Total count: {len(valid_games)}")
    print("BGG IDs:", sorted_ids)

if __name__ == "__main__":
    main()

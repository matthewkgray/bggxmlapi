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

import textwrap

def print_wrapped_row(columns, widths, indent=" | "):
    """
    Prints a row with wrapped text for the last column or specific columns.
    Simple implementation: wraps the last column to fit remaining width.
    columns: list of strings
    widths: list of integers (width for each column). Last one can be 0 (auto-fill).
    """
    # Calculate available width for the last column
    fixed_width = sum(widths[:-1]) + len(indent) * (len(widths) - 1)
    max_total_width = 150
    last_col_width = max(20, max_total_width - fixed_width)
    
    # Wrap the last column
    last_col_content = columns[-1]
    wrapped_lines = textwrap.wrap(last_col_content, width=last_col_width)
    
    if not wrapped_lines:
        wrapped_lines = [""]
        
    # Print the first line
    row_str = ""
    for i in range(len(columns) - 1):
        row_str += f"{columns[i]:<{widths[i]}}{indent}"
    row_str += wrapped_lines[0]
    print(row_str)
    
    # Print subsequent lines indented
    indent_padding = " " * fixed_width
    for line in wrapped_lines[1:]:
        print(f"{indent_padding}{indent}{line}")

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
    cluster_hit_counts = {} # Maps rep_rank -> {'name': cluster_name, 'count': int, 'games_list': list}

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
                # Increment hit count
                if info['rep_rank'] not in cluster_hit_counts:
                     # Should not happen as we init below, but safe guard
                     cluster_hit_counts[info['rep_rank']] = {'name': info['rep_name'], 'count': 0, 'games_list': info['games_list']}
                cluster_hit_counts[info['rep_rank']]['count'] += 1
                
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
        boardgames_list.sort() 
        
        # Init hit count for this new cluster (1 because we found the leader)
        cluster_hit_counts[current_rank] = {'name': cluster_name, 'count': 1, 'games_list': boardgames_list}
        
        # Mark all found games as visited and store metadata
        for gid in collected_games.keys():
            visited_games.add(gid)
            visited_game_info[gid] = {
                'rep_name': cluster_name, 
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
        widths = [6, 40, 30, 0] # 0 = auto fill rest
        print(f"{'Rank':<{widths[0]}} | {'Game':<{widths[1]}} | {'Rep (Rank)':<{widths[2]}} | {'Cluster Games'}")
        print("-" * 150)
        for d in deduped_games:
            rep_str = f"{d['rep_name'][:20]} ({d['rep_rank']})"
            games_str = ", ".join(d['games_list'])
            
            cols = [
                str(d['rank']),
                d['name'][:40],
                rep_str,
                games_str
            ]
            print_wrapped_row(cols, widths)
            
    if cluster_hit_counts:
        print("\n--- Top Clusters by Ranked Members ---")
        # Columns: Rank, Cluster Name, Ranked Members, All Cluster Games
        widths = [6, 40, 15, 0]
        print(f"{'Rank':<{widths[0]}} | {'Cluster Name':<{widths[1]}} | {'Ranked Members':<{widths[2]}} | {'All Cluster Games'}")
        print("-" * 150)
        
        # Sort by count desc
        sorted_clusters = sorted(cluster_hit_counts.values(), key=lambda x: x['count'], reverse=True)
        
        # Print top 20 or all if fewer
        for i, c in enumerate(sorted_clusters[:20]):
             games_str = ", ".join(c['games_list'])
             cols = [
                 str(i + 1),
                 c['name'][:40], # Limit name len in column
                 str(c['count']),
                 games_str
             ]
             print_wrapped_row(cols, widths)

if __name__ == "__main__":
    main()

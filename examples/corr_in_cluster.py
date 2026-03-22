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
    parser.add_argument("--sort-by-corr", action="store_true", help="Sort the correlation table by correlation coefficient descending.")
    parser.add_argument("--sort-by-coraters", action="store_true", help="Sort the correlation table by co-rater count descending.")
    parser.add_argument("--thresh", type=float, default=0.7, help="Correlation threshold for transitive reclustering. Default is 0.7.")
    parser.add_argument("--min-coraters", type=int, default=10, help="Minimum number of co-raters required to consider a pair for reclustering. Default is 10.")
    parser.add_argument(
        "--linethresh",
        type=str,
        default="0.8,0.7,0.6,0.5",
        help="Comma-separated thresholds for graph edge styles (bold, solid, dashed, dotted). Default is 0.8,0.7,0.6,0.5.",
    )
    parser.add_argument("--offline", action="store_true", help="Run in strict offline mode using only cached data.")
    args = parser.parse_args()

    # Parse linethresh
    try:
        l_thresh = [float(x.strip()) for x in args.linethresh.split(",")]
        if len(l_thresh) < 4:
            raise ValueError("Need 4 thresholds for linethresh.")
    except Exception as e:
        log.error(f"Invalid linethresh format: {e}. Using defaults.")
        l_thresh = [0.8, 0.7, 0.6, 0.5]

    client = BGGClient(api_token="YOUR_BGG_TOKEN", only_use_cache=args.offline)

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
    header = f"{'Game A (ID)':<35} | {'Game B (ID)':<35} | {'Co-raters':<10} | {'Corr':<7} | {'p-value'}"
    print(header)
    print("-" * len(header))

    game_pairs = list(itertools.combinations(sorted(games, key=lambda x: x.id), 2))
    
    results = []
    for g1, g2 in game_pairs:
        r1 = game_ratings[g1.id]
        r2 = game_ratings[g2.id]
        
        common_users = set(r1.keys()) & set(r2.keys())
        co_rater_count = len(common_users)
        
        correlation = None
        p_value = None
        
        if co_rater_count > 1:
            try:
                v1 = [r1[u] for u in common_users]
                v2 = [r2[u] for u in common_users]
                correlation, p_value = pearsonr(v1, v2)
            except Exception as e:
                log.debug(f"Correlation calculation failed for {g1.name} vs {g2.name}: {e}")

        results.append({
            'g1': g1,
            'g2': g2,
            'co_rater_count': co_rater_count,
            'correlation': correlation,
            'p_value': p_value
        })

    if args.sort_by_corr:
        # Sort by correlation descending, placing None (N/A) at the end
        results.sort(key=lambda x: (x['correlation'] is not None, x['correlation']), reverse=True)
    elif args.sort_by_coraters:
        # Sort by co-rater count descending
        results.sort(key=lambda x: x['co_rater_count'], reverse=True)

    for res in results:
        g1, g2 = res['g1'], res['g2']
        corr_str = f"{res['correlation']:.4f}" if res['correlation'] is not None else "N/A"
        p_val_str = f"{res['p_value']:.4f}" if res['p_value'] is not None else "N/A"

        # Label with ID
        n1_label = f"{g1.name} ({g1.id})"
        n2_label = f"{g2.name} ({g2.id})"

        # Truncate labels for table
        n1 = (n1_label[:32] + '..') if len(n1_label) > 35 else n1_label
        n2 = (n2_label[:32] + '..') if len(n2_label) > 35 else n2_label
        
        print(f"{n1:<35} | {n2:<35} | {res['co_rater_count']:<10} | {corr_str:<7} | {p_val_str}")

    # Reclustering (Transitive Agglomeration)
    print(f"\n--- Reclustered Groups (Correlation > {args.thresh} and Co-raters >= {args.min_coraters}) ---")
    
    # Build adjacency list for games with corr > thresh and co-raters >= min-coraters
    adj = {g.id: set() for g in games}
    for res in results:
        if res['correlation'] is not None and res['correlation'] > args.thresh and res['co_rater_count'] >= args.min_coraters:
            adj[res['g1'].id].add(res['g2'].id)
            adj[res['g2'].id].add(res['g1'].id)
            
    # Find connected components
    visited = set()
    clusters = []
    
    game_lookup = {g.id: g for g in games}
    
    for gid in sorted(game_lookup.keys()):
        if gid not in visited:
            # New component
            component = set()
            stack = [gid]
            while stack:
                curr = stack.pop()
                if curr not in visited:
                    visited.add(curr)
                    component.add(curr)
                    stack.extend(adj[curr] - visited)
            clusters.append(component)
            
    # Print clusters
    for i, cluster in enumerate(sorted(clusters, key=len, reverse=True), 1):
        print(f"\nGroup {i}:")
        for gid in sorted(cluster):
            g = game_lookup[gid]
            print(f"  - {g.name} ({gid})")

    # Graph Visualization (Mermaid.js)
    graph_filename = f"bggid_{args.game_id}_graph.html"
    log.info(f"Generating graph visualization: {graph_filename}")
    
    mermaid_lines = ["graph TD"]
    link_styles = []
    edge_count = 0
    
    # Define nodes: G1["Name (ID)"]
    for g in games:
        # Sanitize name for Mermaid: remove characters that break labels
        # and double quote to be safe.
        clean_name = g.name.replace('"', "'").replace('[', '(').replace(']', ')')
        mermaid_lines.append(f'    G{g.id}["{clean_name} ({g.id})"]')
        
    for res in results:
        corr = res['correlation']
        if corr is not None and corr > l_thresh[3]:
            g1_id = res['g1'].id
            g2_id = res['g2'].id
            
            # Use non-directional edge for robustness
            label = f"{corr:.2f}"
            mermaid_lines.append(f'    G{g1_id} -- "{label}" --- G{g2_id}')
            
            styles = []
            if corr > l_thresh[0]:
                styles.append("stroke-width:4px")
            elif corr > l_thresh[1]:
                styles.append("stroke-width:2px")
            elif corr > l_thresh[2]:
                styles.append("stroke-dasharray: 5 5")
            elif corr > l_thresh[3]:
                styles.append("stroke-dasharray: 2 2")
            
            if styles:
                link_styles.append(f"    linkStyle {edge_count} {','.join(styles)}")
            
            edge_count += 1
            
    mermaid_content = "\n".join(mermaid_lines + link_styles)
    
    html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>BGG Correlation Graph - ID {args.game_id}</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>mermaid.initialize({{startOnLoad:true}});</script>
    <style>
        body {{ font-family: sans-serif; background: #f4f4f9; padding: 20px; }}
        .mermaid {{ background: white; border: 1px solid #ddd; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; }}
    </style>
</head>
<body>
    <h1>BGG Correlation Graph (Seed ID: {args.game_id})</h1>
    <p>Thresholds: >{l_thresh[0]} bold, >{l_thresh[1]} solid, >{l_thresh[2]} dashed, >{l_thresh[3]} dotted</p>
    <div class="mermaid">
{mermaid_content}
    </div>
</body>
</html>
"""
    try:
        with open(graph_filename, "w", encoding="utf-8") as f:
            f.write(html_template)
    except Exception as e:
        log.error(f"Failed to write graph file: {e}")

if __name__ == "__main__":
    main()

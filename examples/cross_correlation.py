import argparse
import logging
import math
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from lxml import etree
from scipy.stats import pearsonr
import requests_cache
from bgg_api import BGGClient

# Configure logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

def main():
    parser = argparse.ArgumentParser(
        description="Compute cross-correlation matrix for all games in the local cache.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=["all", "full"],
        default="all",
        help="Filter mode:\n"
             "  all: Include any game with at least one page of cached ratings.\n"
             "  full: Include only games where all rating pages are cached (or at least 100 pages)."
    )
    parser.add_argument("--min-coraters", type=int, default=10, help="Minimum overlapping raters to show correlation. Default is 10.")
    parser.add_argument("--min-ratings", type=int, default=100, help="Minimum total ratings a game must have in the cache. Default is 100.")
    args = parser.parse_args()

    client = BGGClient()
    session = client.session
    if not isinstance(session, requests_cache.CachedSession):
        log.error("BGGClient is not using a CachedSession. Cannot scan cache.")
        return

    log.info("Scanning cache for game data and ratings...")
    
    game_names = {} # id -> name
    game_total_ratings = {} # id -> total usersrated
    game_cached_pages = {} # id -> set of page numbers
    
    # Iterate through cache
    for response in session.cache.responses.values():
        if response is None:
            continue
        url = response.url
        if "boardgamegeek.com/xmlapi2/thing" not in url:
            continue
            
        parsed_url = urlparse(url)
        params = parse_qs(parsed_url.query)
        
        # Get IDs from the multi-id request or single-id
        ids = params.get("id", [])
        if not ids:
            continue
        
        # Rating pages usually have ratingcomments=1 and single id
        if params.get("ratingcomments") == ["1"]:
            gid = int(ids[0])
            page = int(params.get("page", ["1"])[0])
            if gid not in game_cached_pages:
                game_cached_pages[gid] = set()
            game_cached_pages[gid].add(page)
        else:
            # Metadata request (stats=1)
            try:
                root = etree.fromstring(response.content)
                for item in root.findall("item"):
                    gid = int(item.get("id"))
                    name_el = item.find("name[@type='primary']")
                    if name_el is not None:
                        game_names[gid] = name_el.get("value")
                    
                    stats_el = item.find("statistics/ratings/usersrated")
                    if stats_el is not None:
                        game_total_ratings[gid] = int(stats_el.get("value"))
            except Exception:
                continue

    # Identify games to include
    selected_gids = []
    for gid, pages in game_cached_pages.items():
        total_in_cache = len(pages) * 100
        
        # Determine if we have "full" data
        is_full = False
        if gid in game_total_ratings:
            total_expected = game_total_ratings[gid]
            # Max pages BGG usually serves is 100? Actually lets just check if we have enough
            if len(pages) >= math.ceil(total_expected / 100) or len(pages) >= 100:
                is_full = True
        
        if args.mode == "full" and not is_full:
            continue
            
        if total_in_cache < args.min_ratings:
            continue
            
        selected_gids.append(gid)

    if not selected_gids:
        log.error("No games matched the criteria in the cache.")
        return

    log.info(f"Computing correlations for {len(selected_gids)} games...")

    # Load all ratings for selected games
    all_game_ratings = {} # gid -> {username: rating}
    for gid in selected_gids:
        game = client.get_game(gid)
        # We know they are in cache, fetch_more will use cache
        pages = sorted(list(game_cached_pages[gid]))
        max_page = max(pages)
        game.ratings.fetch_more(num_pages=max_page)
        
        ratings = {r.username: r.rating for r in game.ratings._ratings if r.username != "N/A"}
        all_game_ratings[gid] = ratings

    # Sort selected games by ID or name for the matrix
    selected_gids.sort(key=lambda x: game_names.get(x, str(x)))

    # Print Matrix Header
    print("\nCross-Correlation Matrix (overlapping raters >= {})".format(args.min_coraters))
    name_width = 25
    col_width = 10
    
    header = " " * name_width + "|"
    for gid in selected_gids:
        name = game_names.get(gid, str(gid))
        short_name = (name[:col_width-2] + "..") if len(name) > col_width else name
        header += "{:^{}}|".format(short_name, col_width)
    print(header)
    print("-" * len(header))

    # Compute and print rows
    for g1_id in selected_gids:
        name = game_names.get(g1_id, str(g1_id))
        short_name = (name[:name_width-2] + "..") if len(name) > name_width else name
        row_str = "{:<{}}|".format(short_name, name_width)
        
        r1 = all_game_ratings[g1_id]
        
        for g2_id in selected_gids:
            if g1_id == g2_id:
                row_str += "{:^{}}|".format("1.00", col_width)
                continue
                
            r2 = all_game_ratings[g2_id]
            common_users = set(r1.keys()) & set(r2.keys())
            
            if len(common_users) >= args.min_coraters:
                v1 = [r1[u] for u in common_users]
                v2 = [r2[u] for u in common_users]
                try:
                    corr, _ = pearsonr(v1, v2)
                    row_str += "{:^{}.2f}|".format(corr, col_width)
                except Exception:
                    row_str += "{:^{}}|".format("N/A", col_width)
            else:
                row_str += "{:^{}}|".format("-", col_width)
        
        print(row_str)

    print("\nLegend:")
    for gid in selected_gids:
        print(f"ID {gid}: {game_names.get(gid, 'Unknown')} ({len(all_game_ratings[gid])} ratings in cache)")

if __name__ == "__main__":
    main()

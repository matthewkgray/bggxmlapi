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
    parser.add_argument("--refresh", action="store_true", help="Allow fetching from network if data is missing or expired. Default is False (offline only).")
    args = parser.parse_args()

    # Initialize with user's token and default to offline mode
    client = BGGClient(
        api_token="YOUR_BGG_TOKEN",
        only_use_cache=not args.refresh
    )
    session = client.session
    if not isinstance(session, requests_cache.CachedSession):
        log.error("BGGClient is not using a CachedSession. Cannot scan cache.")
        return

    log.info("Scanning cache for game data and ratings (Offline Mode: {})...".format(not args.refresh))
    
    game_names = {} # id -> name
    game_total_ratings = {} # id -> total usersrated
    game_cached_pages = {} # id -> set of page numbers
    game_ratings_data = {} # id -> {username: rating}
    
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
        
        try:
            root = etree.fromstring(response.content)
            # Rating pages usually have ratingcomments=1 and single id
            if params.get("ratingcomments") == ["1"]:
                gid = int(ids[0])
                page = int(params.get("page", ["1"])[0])
                if gid not in game_cached_pages:
                    game_cached_pages[gid] = set()
                    game_ratings_data[gid] = {}
                game_cached_pages[gid].add(page)
                
                # Extract ratings directly from this cached response
                for item in root.findall("item"):
                    if gid not in game_names:
                        name_el = item.find("name[@type='primary']")
                        if name_el is not None:
                            game_names[gid] = name_el.get("value")
                            
                    comments = item.find("comments")
                    if comments is not None:
                        total_items_str = comments.get("totalitems")
                        if total_items_str and gid not in game_total_ratings:
                            try:
                                game_total_ratings[gid] = int(total_items_str)
                            except ValueError:
                                pass
                                
                        for comment in comments.findall("comment"):
                            username = comment.get("username")
                            rating = comment.get("rating")
                            if username and rating and username != "N/A":
                                try:
                                    game_ratings_data[gid][username] = float(rating)
                                except ValueError:
                                    continue
            else:
                # Metadata request (stats=1)
                for item in root.findall("item"):
                    gid = int(item.get("id"))
                    if gid not in game_names:
                        name_el = item.find("name[@type='primary']")
                        if name_el is not None:
                            game_names[gid] = name_el.get("value")
                    
                    if gid not in game_total_ratings:
                        stats_el = item.find("statistics/ratings/usersrated")
                        if stats_el is not None:
                            game_total_ratings[gid] = int(stats_el.get("value"))
        except Exception:
            continue

    # Identify games to include
    selected_gids = []
    for gid in game_ratings_data.keys():
        pages = game_cached_pages.get(gid, set())
        total_in_cache = len(game_ratings_data[gid])
        
        # Determine if we have "full" data
        is_full = False
        if gid in game_total_ratings:
            total_expected = game_total_ratings[gid]
            # If we have matches for ~all expected ratings, or we have 100 pages
            if total_in_cache >= (total_expected * 0.95) or len(pages) >= 100:
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

    # Load all ratings for selected games (already in game_ratings_data)
    all_game_ratings = {gid: game_ratings_data[gid] for gid in selected_gids}

    # Sort selected games by ID or name for the matrix
    selected_gids.sort(key=lambda x: game_names.get(x, str(x)))

    # Compute and print correlations as a list
    print(f"\nCross-Correlation List (overlapping raters >= {args.min_coraters})")
    
    correlations = []
    
    for i, g1_id in enumerate(selected_gids):
        r1 = all_game_ratings[g1_id]
        name1 = game_names.get(g1_id, str(g1_id))
        
        for j in range(i + 1, len(selected_gids)):
            g2_id = selected_gids[j]
            r2 = all_game_ratings[g2_id]
            name2 = game_names.get(g2_id, str(g2_id))
            
            common_users = set(r1.keys()) & set(r2.keys())
            
            if len(common_users) >= args.min_coraters:
                v1 = [r1[u] for u in common_users]
                v2 = [r2[u] for u in common_users]
                try:
                    corr, _ = pearsonr(v1, v2)
                    if not math.isnan(corr):
                        correlations.append((corr, name1, name2, len(common_users)))
                except Exception:
                    pass

    # Sort primarily by correlation descending
    correlations.sort(key=lambda x: x[0], reverse=True)
    
    for corr, name1, name2, co_raters in correlations:
        print(f"{corr:5.2f} : {name1} - {name2} ({co_raters} co-raters)")

    print("\nIncluded Games:")
    for gid in selected_gids:
        cached_count = len(all_game_ratings[gid])
        total_count = game_total_ratings.get(gid, "Unknown")
        print(f"ID {gid}: {game_names.get(gid, 'Unknown')} ({cached_count} / {total_count} ratings in cache)")

if __name__ == "__main__":
    main()

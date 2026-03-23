import argparse
import logging
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
from lxml import etree
import numpy as np
from scipy.stats import spearmanr
import requests_cache
from bgg_api import BGGClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Phase 1: Candidate Filtering")
    parser.add_argument("--min-games", type=int, default=50, help="Min games rated in cache to be considered")
    parser.add_argument("--top-m", type=int, default=1000, help="Number of top candidates to output")
    args = parser.parse_args()

    # Initialize client assuming offline usage
    client = BGGClient(only_use_cache=True)
    session = client.session

    if not isinstance(session, requests_cache.CachedSession):
        log.error("BGGClient is not using a CachedSession. Cannot scan cache.")
        return

    log.info("Scanning cache for game data and ratings...")

    game_ratings = defaultdict(dict) # gid -> username -> rating
    game_bgg_average = {} # gid -> average

    for response in session.cache.responses.values():
        if response is None or "boardgamegeek.com/xmlapi2/thing" not in response.url:
            continue
        try:
            parsed_url = urlparse(response.url)
            params = parse_qs(parsed_url.query)
            ids = params.get("id", [])
            if not ids: 
                continue
            
            root = etree.fromstring(response.content)
            
            if params.get("ratingcomments") == ["1"]:
                gid = int(ids[0])
                for item in root.findall("item"):
                    comments = item.find("comments")
                    if comments is not None:
                        for comment in comments.findall("comment"):
                            username = comment.get("username")
                            rating = comment.get("rating")
                            if username and rating and username != "N/A":
                                try:
                                    game_ratings[gid][username] = float(rating)
                                except ValueError:
                                    pass
            elif params.get("stats") == ["1"]:
                for item in root.findall("item"):
                    gid = int(item.get("id"))
                    stats_el = item.find("statistics/ratings/average")
                    if stats_el is not None:
                        game_bgg_average[gid] = float(stats_el.get("value"))
                    else:
                        bayesaverage_el = item.find("statistics/ratings/bayesaverage")
                        if bayesaverage_el is not None:
                            game_bgg_average[gid] = float(bayesaverage_el.get("value"))
        except Exception as e:
            pass

    log.info(f"Loaded ratings for {len(game_ratings)} games")
    log.info(f"Loaded BGG averages for {len(game_bgg_average)} games")

    # Find users and their ratings specifically for games where we have the BGG average
    user_ratings = defaultdict(dict) # username -> gid -> rating
    valid_game_count = 0
    for gid, ratings in game_ratings.items():
        if gid not in game_bgg_average:
            continue
        valid_game_count += 1
        for username, rating in ratings.items():
            user_ratings[username][gid] = rating

    log.info(f"Found {len(user_ratings)} unique users across {valid_game_count} valid games")

    # Filter users and calculate correlation
    candidates = []
    
    log.info(f"Filtering users with >= {args.min_games} ratings and calculating correlations...")
    for username, ratings in user_ratings.items():
        if len(ratings) < args.min_games:
            continue
        
        gids = list(ratings.keys())
        u_rats = [ratings[g] for g in gids]
        b_rats = [game_bgg_average[g] for g in gids]
        
        # Spearman correlation to evaluate rank prediction
        corr, _ = spearmanr(u_rats, b_rats)
        
        if not np.isnan(corr):
            candidates.append({
                "username": username,
                "ratings_count": len(ratings),
                "correlation": corr
            })

    log.info(f"Evaluating {len(candidates)} candidates that met the minimum game threshold")

    # Prioritize by correlation and volume (heuristically: correlation * log10(ratings_count))
    # We only care about positive correlations here
    for c in candidates:
        if c["correlation"] > 0:
            c["score"] = c["correlation"] * np.log10(c["ratings_count"])
        else:
            c["score"] = c["correlation"]

    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    top_m = candidates[:args.top_m]
    
    print(f"\nTop {len(top_m)} candidates found:")
    for i, c in enumerate(top_m[:20]):
        print(f"{i+1:3d}. {c['username']:20s} - Score: {c['score']:6.3f} (Correlation: {c['correlation']:6.3f}, Ratings: {c['ratings_count']:4d})")
        
    if len(top_m) > 20:
        print(f"... and {len(top_m) - 20} more users.")

if __name__ == "__main__":
    main()

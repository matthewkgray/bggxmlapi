import argparse
import logging
import time
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
from lxml import etree
import numpy as np
from scipy.stats import spearmanr
import requests_cache
from bgg_api import BGGClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def evaluate_cohort(cohort_ratings, bgg_averages, validation_games):
    """Calculates the spearman rank correlation of the cohort vs bgg averages."""
    if not cohort_ratings:
        return 0.0
    
    # Calculate average rating per game in the cohort
    game_avg_rating = defaultdict(list)
    for u, ratings in cohort_ratings.items():
        for gid, r in ratings.items():
            if gid in validation_games:
                game_avg_rating[gid].append(r)
    
    y_cohort = []
    y_bgg = []
    
    for gid in validation_games:
        if gid in game_avg_rating:
            y_cohort.append(np.mean(game_avg_rating[gid]))
            y_bgg.append(bgg_averages[gid])
            
    if len(y_cohort) < 5:
        return 0.0 # Not enough data points
        
    corr, _ = spearmanr(y_cohort, y_bgg)
    return corr if not np.isnan(corr) else 0.0

def evaluate_hypothetical_user(new_user_sparse_ratings, cohort_ratings, bgg_averages, validation_games):
    """Calculates the correlation if a single user's sparse ratings were added to the cohort."""
    # Build hypothetical cohort averages
    game_avg_rating = defaultdict(list)
    for u, ratings in cohort_ratings.items():
        for gid, r in ratings.items():
            if gid in validation_games:
                game_avg_rating[gid].append(r)
                
    for gid, r in new_user_sparse_ratings.items():
        if gid in validation_games:
            game_avg_rating[gid].append(r)
            
    y_cohort = []
    y_bgg = []
    
    for gid in validation_games:
        if gid in game_avg_rating:
            y_cohort.append(np.mean(game_avg_rating[gid]))
            y_bgg.append(bgg_averages[gid])
            
    if len(y_cohort) < 5:
        return 0.0
        
    corr, _ = spearmanr(y_cohort, y_bgg)
    return corr if not np.isnan(corr) else 0.0


def load_cached_data(session):
    """
    Parses the cache for /thing (game averages + sparse candidate ratings) 
    and /collection (dense downloaded cohorts).
    """
    game_bgg_average = {}
    game_usersrated = {}
    sparse_user_ratings = defaultdict(dict)
    downloaded_collections = defaultdict(dict)
    game_names = {}
    
    log.info("Parsing cache. This may take a moment...")
    
    for response in session.cache.responses.values():
        if response is None:
            continue
            
        url = response.url
        try:
            parsed_url = urlparse(url)
            params = parse_qs(parsed_url.query)
            root = etree.fromstring(response.content)

            # 1. Sparse game ratings and BGG averages
            if "boardgamegeek.com/xmlapi2/thing" in url:
                ids = params.get("id", [])
                if not ids: continue
                
                if params.get("stats") == ["1"]:
                    for item in root.findall("item"):
                        gid = int(item.get("id"))
                        name_el = item.find("name[@type='primary']")
                        if name_el is not None:
                            game_names[gid] = name_el.get("value")
                            
                        stats_el = item.find("statistics/ratings/average")
                        if stats_el is not None:
                            game_bgg_average[gid] = float(stats_el.get("value"))
                        
                        usersrated_el = item.find("statistics/ratings/usersrated")
                        if usersrated_el is not None:
                            try:
                                game_usersrated[gid] = int(usersrated_el.get("value"))
                            except ValueError:
                                game_usersrated[gid] = 1
                elif params.get("ratingcomments") == ["1"]:
                    gid = int(ids[0])
                    for item in root.findall("item"):
                        comments = item.find("comments")
                        if comments is not None:
                            for comment in comments.findall("comment"):
                                username = comment.get("username")
                                rating = comment.get("rating")
                                if username and rating and username != "N/A":
                                    try:
                                        sparse_user_ratings[username][gid] = float(rating)
                                    except ValueError:
                                        pass
                                        
            # 2. Downloaded user collections
            elif "boardgamegeek.com/xmlapi2/collection" in url:
                username_param = params.get("username")
                if not username_param: continue
                
                username = username_param[0]
                has_ratings = False
                for item in root.findall("item"):
                    gid = int(item.get("objectid"))
                    rating_el = item.find("stats/rating")
                    if rating_el is not None:
                        rating_val = rating_el.get("value")
                        if rating_val and rating_val != "N/A":
                            try:
                                downloaded_collections[username][gid] = float(rating_val)
                                has_ratings = True
                            except ValueError:
                                pass
                
                # If they have an empty collection or just 0 ratings, we still mark them as "downloaded"
                if not has_ratings and username not in downloaded_collections:
                    downloaded_collections[username] = {}
                    
        except Exception:
            pass
            
    return game_bgg_average, sparse_user_ratings, downloaded_collections, game_usersrated, game_names

def find_worst_predicted_games(cohort_ratings, bgg_averages, validation_games, game_usersrated, game_names, top_n=10):
    """
    Fits a linear line mapping cohort averages to BGG averages, 
    calculates the residual for each game, and weights by log10(usersrated) 
    to find the most egregious missed predictions.
    """
    # Calculate average rating per game in the cohort
    game_avg_rating = defaultdict(list)
    for u, ratings in cohort_ratings.items():
        for gid, r in ratings.items():
            if gid in validation_games:
                game_avg_rating[gid].append(r)
    
    valid_gids = []
    y_cohort = []
    y_bgg = []
    
    for gid in validation_games:
        if gid in game_avg_rating:
            valid_gids.append(gid)
            y_cohort.append(np.mean(game_avg_rating[gid]))
            y_bgg.append(bgg_averages[gid])
            
    if len(y_cohort) < 5:
        log.error("Not enough data to find worst games")
        return

    # Fit a linear regression y_bgg = m * y_cohort + b
    m, b = np.polyfit(y_cohort, y_bgg, 1)
    
    log.info(f"Line of best fit mapping Cohort to BGG: y = {m:.3f}x + {b:.3f}")
    
    worst_games = []
    for gid, cohort_avg, true_bgg in zip(valid_gids, y_cohort, y_bgg):
        predicted_bgg = m * cohort_avg + b
        residual = abs(true_bgg - predicted_bgg)
        
        # If no usersrated found, default to 1 so log evaluates to 0
        users_count = game_usersrated.get(gid, 1)
        if users_count < 2:
             users_count = 2 # Prevent log mapping 1 to 0 completely removing the score
             
        weighted_error = residual * np.log10(users_count)
        
        worst_games.append({
            "gid": gid,
            "name": game_names.get(gid, f"Game {gid}"),
            "residual": residual,
            "weighted_error": weighted_error,
            "cohort_avg": cohort_avg,
            "predicted_bgg": predicted_bgg,
            "true_bgg": true_bgg,
            "usersrated": users_count
        })
        
    worst_games.sort(key=lambda x: x["weighted_error"], reverse=True)
    
    print("\n==================================")
    print(f"Top {top_n} Worst Predicted Games by Current Cohort")
    print("==================================")
    for i, g in enumerate(worst_games[:top_n]):
        print(f"{i+1:2d}. {g['name']} (ID: {g['gid']})")
        print(f"    Weighted Error: {g['weighted_error']:.3f}")
        print(f"    Raw Residual:   {g['residual']:.3f} rating points")
        print(f"    Prediction:     {g['predicted_bgg']:.2f} (Cohort Avg: {g['cohort_avg']:.2f})")
        print(f"    Actual BGG:     {g['true_bgg']:.2f} (Total Raters: {g['usersrated']:,})")
        print()

def main():
    parser = argparse.ArgumentParser(description="Phase 3: Iterative Expansion")
    parser.add_argument("--exclude", nargs="*", default=["averagerating"], help="Users to exclude")
    parser.add_argument("--greedy", action="store_true", help="Find user with highest marginal improvement (Greedy selection)")
    parser.add_argument("--next-top", action="store_true", help="Just pick the highest scoring Phase 1 candidate without marginal test")
    parser.add_argument("--find-worst-game", action="store_true", help="Find the game with the easiest BGG prediction error to correct weighted by usersrated")
    parser.add_argument("--min-games", type=int, default=50, help="Min validation games rated by candidate to test")
    parser.add_argument("--api-token", default="YOUR_BGG_TOKEN", help="BGG API Token")
    args = parser.parse_args()
    
    if not any([args.greedy, args.next_top, args.find_worst_game]):
        log.error("Please specify either --greedy, --next-top, or --find-worst-game")
        return

    # Load cache
    offline_client = BGGClient(only_use_cache=True)
    bgg_averages, sparse_ratings, dense_cohort_collections, game_usersrated, game_names = load_cached_data(offline_client.session)
    
    validation_games = set(bgg_averages.keys())
    log.info(f"Loaded {len(validation_games)} validation games with exact BGG averages.")
    log.info(f"Found {len(sparse_ratings)} total candidate profiles (sparse data).")
    
    # Prune cohort data to exclude people in the exclude list
    exclude_users = set(args.exclude)
    for ext in exclude_users:
        dense_cohort_collections.pop(ext, None)
        
    cohort_users = list(dense_cohort_collections.keys())
    log.info(f"Current dense cohort size: {len(cohort_users)}")
    if len(cohort_users) > 0:
        log.info(f"Current cohort members: {', '.join(cohort_users)}")
        
    current_corr = evaluate_cohort(dense_cohort_collections, bgg_averages, validation_games)
    log.info(f"==> Current Cohort Validation Correlation: {current_corr:.4f}")

    if args.find_worst_game:
        find_worst_predicted_games(dense_cohort_collections, bgg_averages, validation_games, game_usersrated, game_names)
        return

    # Prepare candidate pool
    candidates = {}
    for u, ratings in sparse_ratings.items():
        if u in exclude_users or u in cohort_users:
            continue
        valid_ratings = {gid: r for gid, r in ratings.items() if gid in validation_games}
        if len(valid_ratings) >= args.min_games:
            candidates[u] = valid_ratings
            
    log.info(f"Candidate pool for next iteration: {len(candidates)} users (min_games={args.min_games})")
    if not candidates:
        log.warning("No candidates available to expand cohort!")
        return

    best_user = None
    best_corr = -1.0
    
    if args.greedy:
        log.info("Running greedy evaluation. This will recalculate the entire hypothetical cohort correlation for each candidate...")
        
        # Test marginal improvement
        for i, (u, c_ratings) in enumerate(candidates.items()):
            if i > 0 and i % 1000 == 0:
                log.info(f"  ... Evaluated {i}/{len(candidates)} candidates")
                
            c_corr = evaluate_hypothetical_user(c_ratings, dense_cohort_collections, bgg_averages, validation_games)
            
            if c_corr > best_corr:
                best_corr = c_corr
                best_user = u
                
    elif args.next_top:
        log.info("Finding next top user based on raw single-user correlation (Phase 1 logic)...")
        # Quick Phase 1 recalculation just for candidates
        for u, c_ratings in candidates.items():
            gids = list(c_ratings.keys())
            u_rats = [c_ratings[g] for g in gids]
            b_rats = [bgg_averages[g] for g in gids]
            corr, _ = spearmanr(u_rats, b_rats)
            
            # Use heuristic score: corr * log10(N)
            if not np.isnan(corr) and corr > 0:
                score = corr * np.log10(len(c_ratings))
                if score > best_corr: # reusing best_corr var for highest score
                    best_corr = score
                    best_user = u
                    
    if not best_user:
        log.error("Failed to identify a valid best user to expand.")
        return

    log.info(f"Selected candidate: '{best_user}'")
    if args.greedy:
        log.info(f"  Predicted new correlation: {best_corr:.4f} (Improvement: {best_corr - current_corr:+.4f})")
    else:
        log.info(f"  Single-user Phase 1 Score: {best_corr:.4f}")
        
    log.info(f"Fetching full collection for '{best_user}' to add to our dense matrix...")
    
    online_client = BGGClient(api_token=args.api_token, only_use_cache=False, rate_limit_qps=2)
    user = online_client.get_user(best_user)
    
    try:
        user.collection.fetch(own=None, rated=1)
        
        fetched_count = sum(1 for g in user.collection if g.user_rating is not None)
        log.info(f"Successfully downloaded {fetched_count} ratings for {best_user}.")
    except Exception as e:
        log.error(f"Failed to fetch collection for {best_user}: {e}")
        return
        
    log.info("Expansion step complete. Re-run this script to incrementally add more users or verify the dense correlation.")
    
if __name__ == "__main__":
    main()

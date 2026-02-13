import argparse
import logging
import random
import math
import time
from collections import Counter, defaultdict
from bgg_api import BGGClient, BGGAPIError, BGGRequestQueued

# Configure logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

def analyze_top_raters(game_id: int, sample_size: int, max_pages: int, seed: int):
    # backoff_decay=0.5 allows faster recovery after a success
    client = BGGClient(
        api_token="af0a696a-7be1-4701-841a-17704c6892cc",
        backoff_decay=0.5
    )
    import bgg_api
    log.info(f"Using bgg_api from: {bgg_api.__file__}")

    if seed is not None:
        random.seed(seed)
        log.info(f"Using random seed: {seed}")
    
    try:
        log.info(f"Fetching game details for ID: {game_id}...")
        game = client.get_game(game_id)
        log.info(f"Game: {game.name}")

        # 1. Fetch the first page to determine total pages
        log.info("Fetching first page of ratings to determine total count...")
        # access private method for manual control
        response_xml = client._get_game_ratings_page(game_id, page=1)
        
        comments_element = response_xml.find(f".//item[@id='{game_id}']/comments")
        if comments_element is None:
            log.warning("No ratings found for this game.")
            return

        total_ratings = int(comments_element.get("totalitems", 0))
        page_size = int(comments_element.get("pagesize", 100))
        total_pages = math.ceil(total_ratings / page_size) if page_size > 0 else 0
        
        log.info(f"Total ratings: {total_ratings}, Total pages: {total_pages}")
        
        if total_pages == 0:
            return

        # 2. Fetch ratings from the end (highest ratings first)
        high_raters = []
        pages_to_fetch = min(max_pages, total_pages)
        start_page = total_pages
        end_page = max(0, total_pages - pages_to_fetch)

        log.info(f"Fetching up to {pages_to_fetch} pages, starting from page {start_page} backwards...")
        
        for page_num in range(start_page, end_page, -1):
            log.info(f"Fetching page {page_num}...")
            response_xml = client._get_game_ratings_page(game_id, page=page_num)
            comments_element = response_xml.find(f".//item[@id='{game_id}']/comments")
            
            if comments_element is None:
                continue

            for comment_el in comments_element.findall("comment"):
                rating_val = comment_el.get("rating")
                username = comment_el.get("username")
                
                if not rating_val or not username:
                    continue
                
                try:
                    rating = float(rating_val)
                except ValueError:
                    continue
                
                if rating >= 9.0:
                    high_raters.append(username)
                
                # Optimization: if we see a rating below 9, and we assume sorted order...
                # BGG ratings are not strictly sorted by rating value in the API response 
                # (they sort of are, but it's not guaranteed to be perfect monolithically across pages if fetching live)
                # However, usually page 1 is lowest and last page is highest.
                # We will just filter what we get.

        log.info(f"Found {len(high_raters)} users who rated the game 9 or 10.")
        
        if not high_raters:
            log.warning("No high raters found.")
            return

        # 3. Sample users
        sampled_users = high_raters
        if len(high_raters) > sample_size:
            # random.sample is not stable (order changes if k changes).
            # We want stable prefixes so increasing N adds new users to the end.
            # So we shuffle the full list once, then take the first N.
            random.shuffle(high_raters) 
            sampled_users = high_raters[:sample_size]
            log.info(f"Randomly sampled {sample_size} users.")
        else:
            log.info(f"Using all {len(high_raters)} users.")

        # 4. Fetch collections and analyze
        user_stats = []
        all_rated_games = []
        
        log.info("Fetching collections for sampled users...")

        # Serial fetching logic with linear backoff
        fetched_users = {} # username -> collection object
        
        for i, username in enumerate(sampled_users):
            log.info(f"[{i+1}/{len(sampled_users)}] Fetching collection for {username}...")
            
            user = client.get_user(username)
            backoff = 5
            max_poll_attempts = 20 # Should be enough even with slow processing
            
            for attempt in range(max_poll_attempts):
                try:
                    # Try to fetch, effectively polling until 200 OK
                    user.collection.fetch(handle_accepted=False, own=None)
                    
                    # If we return, it succeeded
                    fetched_users[username] = user.collection
                    # log.info(f"Successfully fetched collection for {username}.") 
                    # (Success already logged by BGGClient)
                    break 
                    
                except BGGRequestQueued:
                    log.info(f"{username} queued (202). Waiting {backoff}s before retry (Attempt {attempt+1}/{max_poll_attempts})...")
                    time.sleep(backoff)
                    backoff += 5 # Linear backoff: 5, 10, 15, 20...
                    
                except Exception as e:
                    log.error(f"Error fetching data for {username}: {e}")
                    break
            else:
                log.warning(f"Gave up on {username} after {max_poll_attempts} attempts.")

        # Process fetched collections
        for username, collection in fetched_users.items():
            try:
                 
                rated_games = [g for g in collection if g.user_rating is not None]
                if not rated_games:
                    continue
                    
                avg_rating = sum(g.user_rating for g in rated_games) / len(rated_games)
                user_stats.append({
                    "username": username,
                    "rated_count": len(rated_games),
                    "avg_rating": avg_rating
                })
                
                all_rated_games.extend(rated_games)
            except Exception as e:
                 log.error(f"Error processing collection for {username}: {e}")
        
        if not user_stats:
            log.warning("No user data could be retrieved.")
            return

        # 5. Compute aggregate stats
        total_games_rated_sum = sum(s["rated_count"] for s in user_stats)
        avg_games_rated = total_games_rated_sum / len(user_stats)
        
        # Calculate Group Bias (average difference between user rating and BGG average)
        total_delta_sum = 0.0
        total_delta_count = 0
        
        game_stats = defaultdict(lambda: {"sum": 0.0, "count": 0, "obj": None, "bgg_avg": None})
        
        for g in all_rated_games:
            if g.user_rating is None:
                continue
            
            # Get BGG average. 
            # Note: collection items have 'average_rating' property if stats=1 was used.
            bgg_avg = g.average_rating
            
            game_stats[g.id]["sum"] += g.user_rating
            game_stats[g.id]["count"] += 1
            game_stats[g.id]["obj"] = g
            if bgg_avg:
                 game_stats[g.id]["bgg_avg"] = bgg_avg
                 
            if bgg_avg:
                total_delta_sum += (g.user_rating - bgg_avg)
                total_delta_count += 1
                
        group_bias = total_delta_sum / total_delta_count if total_delta_count > 0 else 0.0
        log.info(f"Group Bias (avg user rating - bgg avg): {group_bias:+.2f}")

        # Most rated games (frequency) AND Smoothed Delta Score
        N = len(user_stats)
        # Smoothing: Strong prior to dampen single-user outliers.
        # We assume N "ghost" users who think the game is average (delta=0).
        smoothing_count = float(N)
        
        ranked_games = []
        for gid, stats in game_stats.items():
            count = stats["count"]
            total_sum = stats["sum"]
            bgg_avg = stats["bgg_avg"]
            
            if not bgg_avg:
                continue # Skip games with no BGG average (rare)
            
            raw_avg = total_sum / count if count > 0 else 0
            raw_delta = raw_avg - bgg_avg
            adjusted_delta = raw_delta - group_bias
            
            # Clamp the effective delta to avoiding boosting "garbage" games that 1 person happens to like.
            # Max delta of 3.0 prevents a 10 vs 5 (+5) from dominating a 9 vs 8 (+1) just by magnitude.
            effective_delta = min(adjusted_delta, 3.0)
            
            # Dampened Delta Score:
            # dampened_delta = (Count * EffectiveDelta) / (Count + Smoothing)
            dampened_delta = (count * effective_delta) / (count + smoothing_count)

            # Bayesian Smoothed Raw Average
            # We dampen the raw average towards the BGG average (the prior) to prevent 
            # single 10.0 ratings from dominating.
            bayesian_avg = (total_sum + (smoothing_count * bgg_avg)) / (count + smoothing_count)

            # Final Score mixes the dampened delta with the smoothed raw average
            # Weight is 0.1 to ensure the Delta (Lift) is the primary driver.
            # Typical Dampened Delta ~ 1.0 - 2.0
            # Typical Smoothed Raw Avg ~ 7.0 - 9.0
            # 0.1 * 8.0 = 0.8, which is a nice secondary boost without dominating.
            score = dampened_delta + (0.1 * bayesian_avg)
            
            ranked_games.append({
                "id": gid,
                "name": stats["obj"].name,
                "count": count,
                "raw_avg": raw_avg,
                "bgg_avg": bgg_avg,
                "score": score,
                "raw_delta": raw_delta
            })
            
        # Sort by Score descending
        ranked_games.sort(key=lambda x: x["score"], reverse=True)
        
        # Optimize: Fetch primary names for the top 20 games to avoid localized names
        top_games = ranked_games[:20]
        top_game_ids = [g["id"] for g in top_games]
        
        if top_game_ids:
            try:
                log.info("Fetching primary names for top games...")
                # Fetch fresh game data which prioritizes primary names
                primary_games = client.get_games(top_game_ids)
                primary_name_map = {g.id: g.name for g in primary_games}
                
                # Update names in our ranked list
                for item in top_games:
                    if item["id"] in primary_name_map:
                        item["name"] = primary_name_map[item["id"]]
            except Exception as e:
                log.warning(f"Failed to fetch primary names: {e}")
        
        log.info("-" * 40)
        log.info("RESULTS")
        log.info("-" * 40)
        log.info(f"Analyzed {len(user_stats)} users.")
        log.info(f"Average number of games rated per user: {avg_games_rated:.1f}")
        
        log.info(f"\nTop Games by Relative Preference (Score = Dampened Delta from BGG Avg):")
        log.info(f"(Group Bias: {group_bias:+.2f}, Smoothing: N={smoothing_count:.1f})")
        print(f"{'Count':<6} {'Score':<6} {'Delta':<6} {'GrpAvg':<6} {'BGGAvg':<6} {'Name'}")
        
        for item in top_games:
            print(f"{item['count']:<6} {item['score']:<+6.2f} {item['raw_delta']:<+6.2f} {item['raw_avg']:<6.2f} {item['bgg_avg']:<6.2f} {item['name']}")

        # Histogram of number of games rated per user
        log.info("\nDistribution of Games Rated per User:")
        
        if not user_stats:
            return

        ratings_counts = [s["rated_count"] for s in user_stats]
        min_rated = min(ratings_counts)
        max_rated = max(ratings_counts)
        
        # Determine bin size
        if max_rated - min_rated < 20:
            bin_size = 1
        elif max_rated - min_rated < 100:
            bin_size = 10
        else:
            bin_size = max(10, (max_rated - min_rated) // 10)
            # Round to nice number
            if bin_size > 100:
                bin_size = 100
            elif bin_size > 50:
                bin_size = 50
            elif bin_size > 10:
                bin_size = 25

        buckets = defaultdict(int)
        for count in ratings_counts:
            bucket_idx = count // bin_size
            buckets[bucket_idx] += 1
            
        min_bucket = min_rated // bin_size
        max_bucket = max_rated // bin_size
        
        for b in range(min_bucket, max_bucket + 1):
            count = buckets[b]
            if count == 0:
                continue
            
            range_start = b * bin_size
            range_end = range_start + bin_size - 1
            bar = "#" * count
            print(f"{range_start:>4}-{range_end:<4}: {count} {bar}")

    except BGGAPIError as e:
        log.error(f"API Error: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")

def main():
    parser = argparse.ArgumentParser(description="Analyze top raters (9/10) of a BGG game.")
    parser.add_argument("gameid", type=int, help="BGG Game ID")
    parser.add_argument("--sample", type=int, default=10, help="Number of users to sample (default: 10)")
    parser.add_argument("--pages", type=int, default=5, help="Number of pages to fetch from the end (default: 5)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling (default: 42)")
    
    args = parser.parse_args()
    
    analyze_top_raters(args.gameid, args.sample, args.pages, args.seed)

if __name__ == "__main__":
    main()

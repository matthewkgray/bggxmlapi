import argparse
import logging
import time

from phase1_offline_filtering import get_top_candidates
from bgg_api import BGGClient
from bgg_api.exceptions import BGGAPIError, BGGNetworkError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Phase 2: Candidate Iterative Expansion")
    parser.add_argument("--top-m", type=int, default=3, help="Number of top candidates to expand")
    parser.add_argument("--min-games", type=int, default=50, help="Min games rated in cache to be considered")
    args = parser.parse_args()

    log.info("Starting Phase 2 Iterative Expansion...")

    # Set up client for Phase 1 (offline)
    offline_client = BGGClient(only_use_cache=True)
    
    # Exclude candidates we know we don't want
    exclude_users = ["averagerating"]
    
    log.info("Running Phase 1 off-line filter to get top candidates")
    top_candidates = get_top_candidates(
        offline_client.session, 
        min_games=args.min_games, 
        top_m=args.top_m, 
        exclude_users=exclude_users
    )
    
    if not top_candidates:
        log.warning("No candidates found.")
        return

    log.info(f"Top {len(top_candidates)} candidates selected for expansion:")
    for c in top_candidates:
        log.info(f" - {c['username']} (Score: {c['score']:.3f})")

    # Set up a new client for Phase 2 (online network fetching)
    # Using the user's API token and conservative rate limiting
    online_client = BGGClient(
        api_token="YOUR_BGG_TOKEN",
        only_use_cache=False,
        rate_limit_qps=2 # Be gentle
    )

    log.info("Fetching collections for top candidates...")
    
    expanded_data = {}
    
    for c in top_candidates:
        username = c["username"]
        log.info(f"Fetching collection for user: {username}")
        
        try:
            user = online_client.get_user(username)
            collection = user.collection
            
            # Explicitly fetch, which will trigger API calls and cache the response
            # BGGClient handles the 202 Accepted retries automatically
            # We want all items they have rated, whether they own them or not.
            collection.fetch(own=None, rated=1)
            
            # Extract their ratings for the games we fetched
            user_ratings = {}
            for game in collection:
                rating = game.user_rating
                if rating is not None:
                    user_ratings[game.id] = rating
            
            expanded_data[username] = user_ratings
            log.info(f"Successfully fetched {len(user_ratings)} ratings for {username}.")
            
            # Small courteous delay between users
            time.sleep(2)
            
        except BGGNetworkError as e:
            log.error(f"Network error fetching collection for {username}: {e}")
        except BGGAPIError as e:
            log.error(f"API error fetching collection for {username}: {e}")
        except Exception as e:
            log.error(f"Unexpected error fetching collection for {username}: {e}")

    log.info(f"Phase 2 expansion complete. Downloaded collection data for {len(expanded_data)} users.")

if __name__ == "__main__":
    main()

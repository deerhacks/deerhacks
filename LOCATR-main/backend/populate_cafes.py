import asyncio
import os
import json
import logging
import sys

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

# Log to file instead of stdout
logging.basicConfig(
    filename='populate.log',
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.services.google_places import search_places
from app.agents.vibe_matcher import _score_venue, _NEUTRAL_VIBE
from app.services.snowflake import SnowflakeIntelligence

def log_msg(msg):
    with open("populate.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)

sem = asyncio.Semaphore(5)

async def score_and_save(sf, v, index, total):
    async with sem:
        try:
            log_msg(f"[{index}/{total}] Scoring {v.get('name')} ...")
            result = await _score_venue(v, _NEUTRAL_VIBE)
            if result and "vibe_dimensions" in result:
                dims = result["vibe_dimensions"]
                if len(dims) == 50:
                    try:
                        sf.save_vibe_vector(
                            venue_id=v.get("venue_id"),
                            name=v.get("name"),
                            lat=v.get("lat"),
                            lng=v.get("lng"),
                            vector=dims,
                            primary_vibe=result.get("primary_style", "cozy")
                        )
                        log_msg(f"   --> Saved {v.get('name')} to Snowflake.") # Only runs if no exception
                    except Exception as e:
                        log_msg(f"   --> FAILED to save {v.get('name')}: {e}")
                else:
                    log_msg(f"   --> Bad dimensions for {v.get('name')}: {len(dims)}")
            else:
                log_msg(f"   --> Scoring failed for {v.get('name')}.")
        except Exception as e:
            log_msg(f"   --> Error processing {v.get('name')}: {e}")

async def main():
    log_msg("Connecting to Snowflake...")
    try:
        sf = SnowflakeIntelligence(
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            account=os.environ["SNOWFLAKE_ACCOUNT"]
        )
        log_msg("Connected.")
        
        drop_table = "DROP TABLE IF EXISTS CAFE_VIBE_VECTORS"
        create_table = """
        CREATE TABLE CAFE_VIBE_VECTORS (
            VENUE_ID VARCHAR PRIMARY KEY,
            NAME VARCHAR,
            LATITUDE FLOAT,
            LONGITUDE FLOAT,
            H3_INDEX VARCHAR,
            VIBE_VECTOR VECTOR(FLOAT, 50),
            PRIMARY_VIBE VARCHAR,
            UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
        try:
            with sf.conn.cursor() as cur:
                cur.execute(drop_table)
                cur.execute(create_table)
        except Exception as e:
            log_msg(f"Failed to ensure table: {e}")
            
    except Exception as e:
        log_msg(f"Snowflake connection failed: {e}")
        return

    log_msg("Fetching cafes in Downtown Toronto...")
    queries = ["cafe", "coffee shop", "bakery cafe", "dessert cafe", "tea house"]
    all_venues = []
    seen = set()
    for q in queries:
        venues = await search_places(query=q, location="Downtown Toronto", max_results=20)
        for v in venues:
            vid = v.get("venue_id")
            if vid and vid not in seen:
                all_venues.append(v)
                seen.add(vid)
                
    log_msg(f"Found {len(all_venues)} unique cafes. Starting parallel scoring...")
    
    tasks = []
    for i, v in enumerate(all_venues):
        tasks.append(score_and_save(sf, v, i+1, len(all_venues)))
        
    await asyncio.gather(*tasks)
    log_msg("All venues processed.")

if __name__ == "__main__":
    asyncio.run(main())

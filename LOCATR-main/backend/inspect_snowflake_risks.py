import os
import sys
from dotenv import load_dotenv

# Add current directory to path for imports
sys.path.append(os.getcwd())

from app.services.snowflake import SnowflakeIntelligence

# Load from current dir if in backend
load_dotenv(dotenv_path='.env')

try:
    sf = SnowflakeIntelligence(
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        account=os.getenv('SNOWFLAKE_ACCOUNT')
    )

    print("--- VENUE_RISK_EVENTS ---")
    with sf.conn.cursor() as cur:
        cur.execute("SELECT VENUE_ID, VENUE_NAME, RISK_DESCRIPTION FROM VENUE_RISK_EVENTS")
        rows = cur.fetchall()
        if not rows:
            print("No risk events found.")
        for row in rows:
            print(f"ID: {row[0]} | Name: {row[1]} | Risk: {row[2]}")
except Exception as e:
    print(f"ERROR: {e}")

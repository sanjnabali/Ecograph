"""
scripts/test_neo4j.py
Quick Neo4j connection diagnostic - run this first to see the exact error.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / ".env", override=True)

import os, time
import neo4j

uri = os.getenv("NEO4J_URI", "")
user = os.getenv("NEO4J_USERNAME", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "")
database = os.getenv("NEO4J_DATABASE", "neo4j")

print(f"neo4j driver version : {neo4j.__version__}")
print(f"URI : {uri}")
print(f"Username : {user}")
print(f"Database : {database}")
print(f"Password : {'*' * len(password)} (len={len(password)})")
print()

if not uri:
    print("X NEO4J_URI is empty - check your .env file")
    sys.exit(1)
if not password:
    print("X NEO4J_PASSWORD is empty - check your .env file")
    sys.exit(1)

# — Try bolt:// if neo4j+s:// fails —
schemes_to_try = [uri]
if uri.startswith("neo4j+s://"):
    host = uri.replace("neo4j+s://", "")
    schemes_to_try += [
        f"neo4j+ssc://{host}",
        f"bolt://{host}",
        f"bolt+s://{host}",
        f"bolt+ssc://{host}",
    ]

for scheme_uri in schemes_to_try:
    print(f"Trying URI: {scheme_uri} ...")
    try:
        driver = neo4j.GraphDatabase.driver(
            scheme_uri,
            auth=(user, password),
            connection_timeout=15,
        )
        driver.verify_connectivity()
        print(f"✅ Connected successfully with: {scheme_uri}")

        # Run a quick query
        with driver.session(database=database) as s:
            result = s.run("RETURN 1 AS n").single()
            print(f"✅ Query returned: {result['n']}")

        driver.close()
        print()
        print("=" * 50)
        print(f"SUCCESS - use this URI in your .env: {scheme_uri}")
        print(f"NEO4J_URI={scheme_uri}")
        print("=" * 50)
        sys.exit(0)

    except neo4j.exceptions.AuthError as e:
        print(f"X AUTH ERROR - wrong username or password: {e}")
        print()
        print("Fix: Go to console.neo4j.io -> your instance -> 'Reset Password'")
        sys.exit(1)

    except Exception as e:
        print(f"X {type(e).__name__}: {e}")
        print()

print("=" * 50)
print("All URI schemes failed.")
print()
print("Checklist:")
print(" 1. Is the instance RUNNING (not paused)?")
print("    https://console.neo4j.io - look for green 'Running' badge")
print(" 2. Did you copy the FULL password from the .txt file Neo4j gave you?")
print(" 3. Is your internet/VPN blocking port 7687?")
print("    Test: curl -v telnet://a1289c49.databases.neo4j.io:7687")
print(" 4. Try creating a BRAND NEW AuraDB Free instance and update .env")
print("=" * 50)
sys.exit(1)
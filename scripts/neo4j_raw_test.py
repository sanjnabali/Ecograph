"""
scripts/neo4j_raw_test.py
Test Neo4j connection via the HTTP Query API (port 443).
Run: .venv\Scripts\python.exe scripts\neo4j_raw_test.py
"""
import sys
import base64
import json
from pathlib import Path
import requests

# Read .env
env_path = Path(__file__).parents[1] / ".env"
creds = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        creds[k.strip()] = v.strip()

API_URL = creds.get("NEO4J_QUERY_API", "")
USER = creds.get("NEO4J_USERNAME", "neo4j")
PASSWORD = creds.get("NEO4J_PASSWORD", "")

print(f"Query API : {API_URL}")
print(f"Username : {USER}")
print(f"Password : {PASSWORD[:4]}...{PASSWORD[-4:]} (len={len(PASSWORD)})")
print()

if not API_URL:
    print("ERROR: NEO4J_QUERY_API is not set in .env")
    print("Get it from: console.neo4j.io -> instance -> 'Query API URL'")
    sys.exit(1)

# Make HTTP request
auth_str = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

payload = {"statement": "RETURN 'Hello from AuraDB' AS msg, 42 AS answer"}
print(f"POST {API_URL}")
print(f"Payload: {json.dumps(payload)}")
print()

try:
    resp = requests.post(API_URL, json=payload, headers=headers, timeout=15)
except requests.exceptions.ConnectionError as e:
    print(f"CONNECTION ERROR: {e}")
    print("\nThis means HTTPS port 443 is blocked (very unlikely).")
    sys.exit(1)

print(f"HTTP Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")
print()

if resp.status_code == 200 or resp.status_code == 202:
    print("=" * 50)
    print("SUCCESS! Neo4j Query API is working.")
    print("Now run:")
    print(" .venv\\Scripts\\python.exe scripts\\run_pipeline.py --steps 5")
    print("=" * 50)
elif resp.status_code == 401:
    print("-" * 50)
    print("AUTH ERROR - Wrong password.")
    print("The Query API URL is correct but the password is wrong.")
    print()
    print("Unfortunately AuraDB Free does NOT have a 'Reset Password' button.")
    print("You need to:")
    print(" 1. DELETE this instance at console.neo4j.io")
    print(" 2. Create a NEW instance")
    print(" 3. SAVE the password from the download popup (shown only ONCE)")
    print(" 4. Update .env with the new NEO4J_QUERY_API and NEO4J_PASSWORD")
    print("-" * 50)
elif resp.status_code == 404:
    print("-" * 50)
    print("404 NOT FOUND - The Query API URL is wrong.")
    print("Go to console.neo4j.io -> instance -> copy 'Query API URL'")
    print("-" * 50)
else:
    print(f"Unexpected status {resp.status_code}")

# 1. Print driver version
try:
    import neo4j
    print(f"neo4j driver version: {neo4j.__version__}")
except ImportError:
    print("ERROR: neo4j package not installed")
    sys.exit(1)

# 2. Read credentials directly from .env
from pathlib import Path
env_path = Path(__file__).parents[1] / ".env"
creds = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        creds[k.strip()] = v.strip()

URI = creds.get("NEO4J_URI", "")
USER = creds.get("NEO4J_USERNAME", "neo4j")
PASSWORD = creds.get("NEO4J_PASSWORD", "")
DATABASE = creds.get("NEO4J_DATABASE", "neo4j")

print(f"URI : {URI}")
print(f"Username : {USER}")
print(f"Database : {DATABASE}")
print(f"Password : {PASSWORD[:4]}...{PASSWORD[-4:]} (len={len(PASSWORD)})")
print()

if "PASTE" in URI or not URI:
    print("X You haven't updated NEO4J_URI in .env yet!")
    print(" Open .env and paste your new instance details.")
    sys.exit(1)

# 3. Raw connection
print(f"Connecting to {URI} ...")
try:
    driver = neo4j.GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    driver.verify_connectivity()
    print("■ verify_connectivity() passed!")

    with driver.session(database=DATABASE) as session:
        rec = session.run("RETURN 'Hello AuraDB' AS msg").single()
        print(f"■ Query result: {rec['msg']}")

    driver.close()
    print()
    print("=" * 50)
    print("SUCCESS - Neo4j is working. Now run:")
    print(" .venv\\Scripts\\python.exe scripts\\run_pipeline.py --steps 5")
    print("=" * 50)

except neo4j.exceptions.AuthError as e:
    print("F X Wrong username or password: {e}")
    print(" Go to console.neo4j.io -> your instance -> Reset Password")

except neo4j.exceptions.ServiceUnavailable as e:
    print(f"X Service unavailable: {e}")
    print()
    print("This means the driver version is incompatible with AuraDB.")
    print("Run this to fix it:")
    print()
    print(" .venv\\Scripts\\pip.exe install \"neo4j>=5.19,<6\" --force-reinstall")
    print()
    print("Then re-run this test.")

except Exception as e:
    print(f"X {type(e).__name__}: {e}")
    print()
    print("If 'routing' is in the error:")
    print(" .venv\\Scripts\\pip.exe install \"neo4j>=5.19,<6\" --force-reinstall")
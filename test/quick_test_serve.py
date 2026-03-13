"""Test GEO content serving via Lambda Function URL and CloudFront.

Tests:
1. Lambda Function URL direct (passthrough mode)
2. Lambda Function URL direct (async mode)
3. Lambda Function URL direct (sync mode)
4. CloudFront as normal user (should get original content)
5. CloudFront with ?ua=genaibot (should route to GEO origin)
"""

import requests

URL_PATH = "/world/3149600"
FUNC_URL = "https://s3nfxuhskmxt73okobizyeb64i0fwoeh.lambda-url.us-east-1.on.aws"
CF_DOMAIN = "https://d1sv1ydutd4m98.cloudfront.net"

# --- Lambda Function URL direct tests ---

print("=== Test 1: Function URL — passthrough (default) ===", flush=True)
resp = requests.get(f"{FUNC_URL}{URL_PATH}", timeout=30)
print(f"Status: {resp.status_code}", flush=True)
print(f"X-GEO-Source: {resp.headers.get('X-GEO-Source', 'missing')}", flush=True)
print(f"X-GEO-Optimized: {resp.headers.get('X-GEO-Optimized', 'missing')}", flush=True)
print(f"Body preview: {resp.text[:200]}", flush=True)

print("\n=== Test 2: Function URL — async mode ===", flush=True)
resp = requests.get(f"{FUNC_URL}{URL_PATH}?mode=async", timeout=30)
print(f"Status: {resp.status_code}", flush=True)
print(f"Body: {resp.text[:300]}", flush=True)

print("\n=== Test 3: Function URL — sync mode (may take ~40s) ===", flush=True)
resp = requests.get(f"{FUNC_URL}{URL_PATH}?mode=sync", timeout=120)
print(f"Status: {resp.status_code}", flush=True)
print(f"X-GEO-Source: {resp.headers.get('X-GEO-Source', 'missing')}", flush=True)
print(f"X-GEO-Duration-Ms: {resp.headers.get('X-GEO-Duration-Ms', 'missing')}", flush=True)
print(f"Body preview: {resp.text[:300]}", flush=True)

# --- CloudFront tests ---

print("\n=== Test 4: CloudFront as normal user ===", flush=True)
resp = requests.get(f"{CF_DOMAIN}{URL_PATH}", headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
print(f"Status: {resp.status_code}", flush=True)
print(f"X-Cache: {resp.headers.get('X-Cache', 'missing')}", flush=True)
has_geo = resp.headers.get("X-GEO-Optimized") == "true"
print(f"GEO optimized: {has_geo} (expected: False)", flush=True)

print("\n=== Test 5: CloudFront with ?ua=genaibot ===", flush=True)
resp = requests.get(f"{CF_DOMAIN}{URL_PATH}?ua=genaibot", timeout=30)
print(f"Status: {resp.status_code}", flush=True)
print(f"X-GEO-Source: {resp.headers.get('X-GEO-Source', 'missing')}", flush=True)
print(f"X-GEO-Optimized: {resp.headers.get('X-GEO-Optimized', 'missing')}", flush=True)
print(f"Body preview: {resp.text[:300]}", flush=True)

print("\n=== Done ===", flush=True)

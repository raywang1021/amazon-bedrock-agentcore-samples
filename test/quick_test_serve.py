import requests

URL_PATH = "/world/3149599"
API_GW = "https://h77cl56kzg.execute-api.us-east-1.amazonaws.com/prod"
CF_DOMAIN = "https://d1sv1ydutd4m98.cloudfront.net"

print("=== Test 1: API Gateway direct ===", flush=True)
resp = requests.get(f"{API_GW}{URL_PATH}", timeout=10)
print(f"Status: {resp.status_code}", flush=True)
print(f"X-GEO-Optimized: {resp.headers.get('X-GEO-Optimized', 'missing')}", flush=True)
print(f"Body preview: {resp.text[:200]}", flush=True)

print("\n=== Test 2: CloudFront as normal user ===", flush=True)
resp = requests.get(f"{CF_DOMAIN}{URL_PATH}", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
print(f"Status: {resp.status_code}", flush=True)
has_geo = "GEO Optimized" in resp.text
print(f"Contains GEO content: {has_geo} (expected: False)", flush=True)
print(f"X-Cache: {resp.headers.get('X-Cache', 'missing')}", flush=True)

print("\n=== Test 3: CloudFront as GPTBot ===", flush=True)
resp = requests.get(
    f"{CF_DOMAIN}{URL_PATH}",
    headers={"User-Agent": "Mozilla/5.0 (compatible; GPTBot/1.0)"},
    timeout=10,
)
print(f"Status: {resp.status_code}", flush=True)
has_geo = "GEO Optimized" in resp.text
print(f"Contains GEO content: {has_geo} (expected: True)", flush=True)
print(f"X-Cache: {resp.headers.get('X-Cache', 'missing')}", flush=True)
print(f"X-GEO-Optimized: {resp.headers.get('X-GEO-Optimized', 'missing')}", flush=True)
print(f"Body preview: {resp.text[:300]}", flush=True)

print("\n=== Done ===", flush=True)

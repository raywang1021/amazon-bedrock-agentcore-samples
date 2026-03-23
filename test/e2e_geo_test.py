#!/usr/bin/env python3
"""E2E test: parse list page for latest article, then test GEO edge serving.

Supports two site types:
  1. SETN (via CloudFront): /News.aspx?NewsID=<id>  (querystring-based)
  2. TVBS: /<category>/<id>  (path-based)

Usage:
  python test/e2e_geo_test.py                          # test both sites
  python test/e2e_geo_test.py --site setn              # SETN only
  python test/e2e_geo_test.py --site tvbs              # TVBS only
  python test/e2e_geo_test.py --mode sync              # wait for GEO content
  python test/e2e_geo_test.py --mode passthrough       # default, async generation
"""

import argparse
import re
import sys
import time

import requests

# --- Site configs ---
SITES = {
    "setn": {
        "list_url": "https://dlmwhof468s34.cloudfront.net/viewall.aspx?pagegroupid=0",
        "link_pattern": r'href="(/News\.aspx\?NewsID=(\d+))"',
        "base_url": "https://dlmwhof468s34.cloudfront.net",
        "sort_key": lambda m: int(m.group(2)),  # sort by NewsID desc
    },
    "tvbs": {
        "list_url": "https://dq324v08a4yas.cloudfront.net/realtime",
        "link_pattern": r'href="/((?:life|world|politics|entertainment|local|health|money|sports|china|tech|travel|focus|fun)/(\d+))"',
        "base_url": "https://dq324v08a4yas.cloudfront.net",
        "sort_key": lambda m: int(m.group(2)),  # sort by article ID desc
    },
}

UA_BOT = "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)"
UA_NORMAL = "Mozilla/5.0 (compatible; GEOTest/1.0)"


def fetch_latest_article(site_key: str) -> str | None:
    """Parse list page and return the latest article's full URL."""
    cfg = SITES[site_key]
    print(f"[{site_key}] Fetching list: {cfg['list_url']}")
    resp = requests.get(cfg["list_url"], headers={"User-Agent": UA_NORMAL}, timeout=15)
    resp.raise_for_status()

    matches = list(re.finditer(cfg["link_pattern"], resp.text))
    if not matches:
        print(f"[{site_key}] No article links found!")
        return None

    # Deduplicate and sort by ID descending (latest first)
    seen = set()
    unique = []
    for m in matches:
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            unique.append(m)

    unique.sort(key=cfg["sort_key"], reverse=True)
    latest_path = unique[0].group(1)
    url = f"{cfg['base_url']}/{latest_path}" if not latest_path.startswith("/") else f"{cfg['base_url']}{latest_path}"
    print(f"[{site_key}] Latest article: {url}")
    return url


def test_geo_serving(url: str, site_key: str, mode: str = "passthrough") -> bool:
    """Test GEO edge serving for a URL. Returns True if passed."""
    print(f"\n{'='*70}")
    print(f"[{site_key}] Testing: {url}")
    print(f"[{site_key}] Mode: {mode}")
    print(f"{'='*70}")

    # 1. First, purge any existing cache
    purge_url = f"{url}{'&' if '?' in url else '?'}ua=genaibot&purge=true"
    print(f"\n[1] Purging cache...")
    resp = requests.get(purge_url, headers={"User-Agent": UA_BOT}, timeout=15)
    print(f"    Status: {resp.status_code}")

    # 2. Request with bot UA (triggers GEO generation)
    test_url = f"{url}{'&' if '?' in url else '?'}ua=genaibot"
    if mode != "passthrough":
        test_url += f"&mode={mode}"

    print(f"\n[2] Requesting as AI bot (mode={mode})...")
    start = time.time()
    resp = requests.get(test_url, headers={"User-Agent": UA_BOT}, timeout=120)
    elapsed = time.time() - start
    print(f"    Status: {resp.status_code}")
    print(f"    Time: {elapsed:.1f}s")
    print(f"    Content-Length: {len(resp.text)} chars")

    # Check response headers
    geo_optimized = resp.headers.get("X-GEO-Optimized", "")
    geo_source = resp.headers.get("X-GEO-Source", "")
    handler_ms = resp.headers.get("X-GEO-Handler-Ms", "")
    duration_ms = resp.headers.get("X-GEO-Duration-Ms", "")

    print(f"    X-GEO-Optimized: {geo_optimized}")
    print(f"    X-GEO-Source: {geo_source}")
    print(f"    X-GEO-Handler-Ms: {handler_ms}")
    if duration_ms:
        print(f"    X-GEO-Duration-Ms: {duration_ms}")

    # 3. Validate based on mode
    passed = True

    if mode == "sync":
        if geo_optimized != "true":
            print(f"    ✗ Expected X-GEO-Optimized: true, got: {geo_optimized}")
            passed = False
        if geo_source not in ("generated", "cache"):
            print(f"    ✗ Expected X-GEO-Source: generated or cache, got: {geo_source}")
            passed = False
        if not resp.text.strip().startswith("<"):
            print(f"    ✗ Response doesn't look like HTML")
            passed = False
    elif mode == "async":
        if resp.status_code != 202:
            print(f"    ✗ Expected 202, got: {resp.status_code}")
            passed = False
    else:  # passthrough
        if resp.status_code != 200:
            print(f"    ✗ Expected 200, got: {resp.status_code}")
            passed = False
        # Passthrough returns original content, GEO generation happens async
        if geo_source == "cache" and geo_optimized == "true":
            print(f"    ℹ Cache hit — GEO content already available")
        else:
            print(f"    ℹ Passthrough — GEO content generating in background")

    # 4. If passthrough/async, wait and retry to check if GEO content is ready
    if mode in ("passthrough", "async") and passed:
        print(f"\n[3] Waiting 5s then checking if GEO content is ready...")
        time.sleep(5)
        check_url = f"{url}{'&' if '?' in url else '?'}ua=genaibot"
        resp2 = requests.get(check_url, headers={"User-Agent": UA_BOT}, timeout=30)
        geo2 = resp2.headers.get("X-GEO-Optimized", "")
        src2 = resp2.headers.get("X-GEO-Source", "")
        print(f"    Status: {resp2.status_code}")
        print(f"    X-GEO-Optimized: {geo2}")
        print(f"    X-GEO-Source: {src2}")
        if geo2 == "true":
            print(f"    ✓ GEO content is ready (source: {src2})")
        else:
            print(f"    ℹ GEO content still generating (this is normal for first request)")

    if passed:
        print(f"\n✓ [{site_key}] Test PASSED")
    else:
        print(f"\n✗ [{site_key}] Test FAILED")

    return passed


def main():
    parser = argparse.ArgumentParser(description="E2E GEO edge serving test")
    parser.add_argument("--site", choices=["setn", "tvbs", "both"], default="both")
    parser.add_argument("--mode", choices=["passthrough", "async", "sync"], default="passthrough")
    args = parser.parse_args()

    sites = ["setn", "tvbs"] if args.site == "both" else [args.site]
    results = {}

    for site in sites:
        url = fetch_latest_article(site)
        if not url:
            results[site] = False
            continue
        results[site] = test_geo_serving(url, site, args.mode)

    # Summary
    print(f"\n{'='*70}")
    print("Summary:")
    for site, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {site}: {status}")

    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()

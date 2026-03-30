#!/bin/bash
# End-to-end test suite for GEO Edge Serving Infrastructure
# Run after any code change + deploy
#
# Usage: bash test/e2e_test.sh [CF_DOMAIN] [ALB_DNS]
#   Defaults:
#     CF_DOMAIN  = d1sv1ydutd4m98.cloudfront.net
#     ALB_DNS    = geo-agent-alb-705379192.us-east-1.elb.amazonaws.com

set -euo pipefail

CF_DOMAIN="${1:-d1sv1ydutd4m98.cloudfront.net}"
ALB_DNS="${2:-geo-agent-alb-705379192.us-east-1.elb.amazonaws.com}"
TEST_PATH="/world/3149599"
REGION="us-east-1"
TABLE="geo-content"
PASS=0
FAIL=0

green() { printf "\033[32m%s\033[0m\n" "$1"; }
red()   { printf "\033[31m%s\033[0m\n" "$1"; }
info()  { printf "\033[36m▶ %s\033[0m\n" "$1"; }

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    green "  ✅ $label (expected=$expected)"
    PASS=$((PASS + 1))
  else
    red "  ❌ $label (expected=$expected, got=$actual)"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" expected="$2" actual="$3"
  if echo "$actual" | grep -qi "$expected"; then
    green "  ✅ $label (contains '$expected')"
    PASS=$((PASS + 1))
  else
    red "  ❌ $label (expected to contain '$expected')"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_empty() {
  local label="$1" actual="$2"
  if [ -n "$actual" ] && [ "$actual" != "null" ]; then
    green "  ✅ $label (value=$actual)"
    PASS=$((PASS + 1))
  else
    red "  ❌ $label (empty or null)"
    FAIL=$((FAIL + 1))
  fi
}

purge() {
  curl -s "https://${CF_DOMAIN}${TEST_PATH}?ua=genaibot&purge=true&_t=$(date +%s)" > /dev/null
  # Also delete directly from DDB to be sure (in case CF cached the purge response)
  aws dynamodb delete-item --table-name "$TABLE" \
    --key "{\"url_path\":{\"S\":\"${TEST_PATH}\"}}" \
    --region "$REGION" 2>/dev/null || true
  sleep 2
}

ddb_status() {
  aws dynamodb get-item --table-name "$TABLE" \
    --key "{\"url_path\":{\"S\":\"${TEST_PATH}\"}}" \
    --region "$REGION" --output json 2>/dev/null
}

echo ""
echo "=========================================="
echo " GEO Edge Serving — E2E Test Suite"
echo "=========================================="
echo " CF Domain : $CF_DOMAIN"
echo " ALB DNS   : $ALB_DNS"
echo " Test Path : $TEST_PATH"
echo "=========================================="
echo ""

# ------------------------------------------
# 1. Purge
# ------------------------------------------
info "Test 1: Purge"
# Seed a record first so purge has something to delete
aws dynamodb put-item --table-name "$TABLE" \
  --item "{\"url_path\":{\"S\":\"${TEST_PATH}\"},\"status\":{\"S\":\"ready\"},\"geo_content\":{\"S\":\"test\"}}" \
  --region "$REGION" 2>/dev/null
PURGE_RESP=$(curl -s "https://${CF_DOMAIN}${TEST_PATH}?ua=genaibot&purge=true&_t=$(date +%s)")
PURGE_STATUS=$(echo "$PURGE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
assert_eq "purge response status" "purged" "$PURGE_STATUS"
# Verify DDB is empty
sleep 1
DDB_CHK=$(aws dynamodb get-item --table-name "$TABLE" \
  --key "{\"url_path\":{\"S\":\"${TEST_PATH}\"}}" \
  --region "$REGION" --query 'Item.status.S' --output text 2>/dev/null || echo "None")
assert_eq "DDB record deleted" "None" "$DDB_CHK"
echo ""

# ------------------------------------------
# 2. Passthrough (cache miss, default mode)
# ------------------------------------------
info "Test 2: Passthrough (cache miss)"
purge
PT_HEADERS=$(curl -s -D - -o /dev/null "https://${CF_DOMAIN}${TEST_PATH}?ua=genaibot&_t=$(date +%s)" 2>&1)
PT_CODE=$(echo "$PT_HEADERS" | grep -i "^HTTP/" | tail -1 | awk '{print $2}')
PT_SOURCE=$(echo "$PT_HEADERS" | grep -i "x-geo-source" | tr -d '\r' | awk '{print $2}')
assert_eq "HTTP status" "200" "$PT_CODE"
assert_eq "X-GEO-Source" "passthrough" "$PT_SOURCE"
echo ""

# ------------------------------------------
# 3. DDB record — processing/ready + TTL
# ------------------------------------------
info "Test 3: DDB record (status + TTL)"
sleep 2
DDB_ITEM=$(ddb_status)
DDB_STATUS=$(echo "$DDB_ITEM" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Item',{}).get('status',{}).get('S',''))" 2>/dev/null || echo "")
DDB_TTL=$(echo "$DDB_ITEM" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Item',{}).get('ttl',{}).get('N',''))" 2>/dev/null || echo "")
if [ "$DDB_STATUS" = "processing" ] || [ "$DDB_STATUS" = "ready" ]; then
  green "  ✅ DDB status ($DDB_STATUS)"
  PASS=$((PASS + 1))
else
  red "  ❌ DDB status (expected processing|ready, got=$DDB_STATUS)"
  FAIL=$((FAIL + 1))
fi
assert_not_empty "DDB ttl field" "$DDB_TTL"
echo ""

# ------------------------------------------
# 4. Wait for generator → cache hit
# ------------------------------------------
info "Test 4: Cache hit (waiting up to 90s for generator...)"
READY=false
for i in $(seq 1 18); do
  CHK=$(aws dynamodb get-item --table-name "$TABLE" \
    --key "{\"url_path\":{\"S\":\"${TEST_PATH}\"}}" \
    --region "$REGION" --query 'Item.status.S' --output text 2>/dev/null || echo "")
  if [ "$CHK" = "ready" ]; then
    READY=true
    green "  Generator completed after ~$((i * 5))s"
    break
  fi
  printf "  ⏳ %ds...\r" "$((i * 5))"
  sleep 5
done

if [ "$READY" = true ]; then
  HIT_HEADERS=$(curl -s -D - -o /dev/null "https://${CF_DOMAIN}${TEST_PATH}?ua=genaibot&_t=$(date +%s)" 2>&1)
  HIT_CODE=$(echo "$HIT_HEADERS" | grep -i "^HTTP/" | tail -1 | awk '{print $2}')
  HIT_SOURCE=$(echo "$HIT_HEADERS" | grep -i "x-geo-source" | tr -d '\r' | awk '{print $2}')
  HIT_OPT=$(echo "$HIT_HEADERS" | grep -i "x-geo-optimized" | tr -d '\r' | awk '{print $2}')
  assert_eq "HTTP status" "200" "$HIT_CODE"
  assert_eq "X-GEO-Source" "cache" "$HIT_SOURCE"
  assert_eq "X-GEO-Optimized" "true" "$HIT_OPT"
else
  red "  ❌ Generator did not complete within 90s"
  FAIL=$((FAIL + 1))
fi
echo ""

# ------------------------------------------
# 5. Async mode
# ------------------------------------------
info "Test 5: Async mode"
purge
ASYNC_HEADERS=$(curl -s -D - -o /tmp/geo_async_body.txt "https://${CF_DOMAIN}${TEST_PATH}?ua=genaibot&mode=async&_t=$(date +%s)" 2>&1)
ASYNC_CODE=$(echo "$ASYNC_HEADERS" | grep -i "^HTTP/" | tail -1 | awk '{print $2}')
ASYNC_BODY=$(cat /tmp/geo_async_body.txt)
assert_eq "HTTP status" "202" "$ASYNC_CODE"
assert_contains "body contains generating" "generating" "$ASYNC_BODY"
echo ""

# ------------------------------------------
# 6. Direct ALB access (should timeout/fail)
# ------------------------------------------
info "Test 6: Direct ALB access (should be blocked by SG)"
ALB_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "http://${ALB_DNS}${TEST_PATH}" 2>/dev/null || true)
if [ -z "$ALB_CODE" ] || [ "$ALB_CODE" = "000" ]; then
  green "  ✅ ALB blocked (timeout/connection refused)"
  PASS=$((PASS + 1))
else
  red "  ❌ ALB reachable (HTTP $ALB_CODE — expected timeout)"
  FAIL=$((FAIL + 1))
fi
echo ""

# ------------------------------------------
# Cleanup: purge test data
# ------------------------------------------
purge > /dev/null 2>&1

# ------------------------------------------
# Summary
# ------------------------------------------
echo "=========================================="
TOTAL=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
  green " All $TOTAL tests passed ✅"
else
  red " $FAIL/$TOTAL tests failed ❌"
fi
echo "=========================================="
exit "$FAIL"

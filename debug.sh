#!/bin/bash

echo "================================================="
echo "FACEBOOK CAPTION TRUNCATION DEBUG (MINIMAL)"
echo "================================================="

echo ""
echo "1. CAPTION GENERATION (SOURCE OF TRUTH)"
echo "-------------------------------------------------"
grep -Rni "caption" social/daily_news social/formatter.py social/ | head -n 50

echo ""
echo "2. FINAL TEXT BEFORE SENDING TO FACEBOOK"
echo "-------------------------------------------------"
grep -Rni "message\|caption\|description" social/platforms/facebook.py | head -n 80

echo ""
echo "3. FACEBOOK API PAYLOAD (MOST IMPORTANT)"
echo "-------------------------------------------------"
grep -Rni "payload\|data=\|json=" social/platforms/facebook.py | head -n 80

echo ""
echo "4. TRUNCATION / LIMIT LOGIC (ROOT CAUSE ZONE)"
echo "-------------------------------------------------"
grep -Rni "truncate\|limit\|max\|slice\|\[:\]" social/ | head -n 80

echo ""
echo "5. STRING BUILDING (WHERE CAPTION GETS COMBINED)"
echo "-------------------------------------------------"
grep -Rni "join\|format\|f\"" social/daily_news social/formatter.py social/ | head -n 80

echo ""
echo "6. FACEBOOK POST CALL (FINAL HANDOFF)"
echo "-------------------------------------------------"
grep -Rni "graph.facebook\|/feed\|requests.post\|session.post" social/platforms/facebook.py

echo ""
echo "================================================="
echo "DONE - CHECK ABOVE IN THIS ORDER:"
echo "1 → 2 → 3 → 4 → 6"
echo "================================================="
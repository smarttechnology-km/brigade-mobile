#!/bin/bash
# Simple uptime monitoring script for Render deployment
# This can be used with UptimeRobot or other monitoring services
#
# Usage as a cron job (add to your local machine, runs every 5 minutes):
#   */5 * * * * /path/to/keep-server-warm.sh
#
# Or use with UptimeRobot: https://uptimerobot.com/
#   - Create a new "HTTP(s) Monitoring" check
#   - Set URL to: https://your-backend.onrender.com/api/health
#   - Set interval to 5 minutes
#   - Friendly name: "Police API Health"

BACKEND_URL="${RENDER_BACKEND_URL:-https://brigade-mobile.onrender.com}"
HEALTH_ENDPOINT="${BACKEND_URL}/api/health"
TIMEOUT=30

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pinging server at ${HEALTH_ENDPOINT}..."

# Try to reach the health endpoint
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout $TIMEOUT --max-time $TIMEOUT "${HEALTH_ENDPOINT}")

if [ "$HTTP_STATUS" == "200" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Server health check passed (200 OK)"
    exit 0
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ Server returned status ${HTTP_STATUS}"
    exit 1
fi

# Long-term Memory

This file stores important information that should persist across sessions.

## Project Context

### Download Server Infrastructure

- Static file server runs on port 8001 via script `/root/.nanobot/workspace/scripts/check_and_start_server.sh`
- Download directory is `/root/.nanobot/workspace/output`, displaying files sorted by modification time (newest first)
- Cron job `auto_start_download_server` runs every 6 hours and executes `/root/.nanobot/workspace/scripts/check_and_start_server.sh` on port 8001
- Server script skips starting the server if it is already running, exiting with code 0
- Server script cleans up stale PID files before restarting the server
---

*This file is automatically updated by nanobot when important information should be remembered.*

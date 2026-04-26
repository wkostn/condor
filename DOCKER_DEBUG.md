# Docker Debugging Guide for Condor Routines

## Overview

All routines are designed to run inside the Docker container where all dependencies (telegram, config_manager, Hummingbot API) are available.

## Quick Debug Commands

### 1. Run a Test Script
```bash
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_news_reader.py"
```

### 2. Interactive Python Shell
```bash
docker exec -it hummingbird-condor-1 bash
cd /app
uv run python

# Then in Python:
from routines.news_reader import run, Config
import asyncio

config = Config(assets=["BTC", "ETH"], lookback_hours=24)
context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
result = asyncio.run(run(config, context))
print(result.text)
```

### 3. Add Debug Prints
Add `logger.info()` or `print()` statements to your routine, then:

```bash
# Sync your changes
cd /home/wkadmin/projects/openclaw/hummingbird
docker cp apps/condor/routines/your_routine.py hummingbird-condor-1:/app/routines/

# Run the test
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_your_routine.py"
```

### 4. Check Logs in Real-Time
```bash
# Follow container logs
docker logs -f hummingbird-condor-1

# In another terminal, trigger your routine
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_news_reader.py"
```

## Development Workflow

### Step-by-Step: Modify → Test → Debug

```bash
# 1. Edit routine locally in VS Code
# /home/wkadmin/projects/openclaw/hummingbird/apps/condor/routines/news_reader.py

# 2. Sync to Docker
cd /home/wkadmin/projects/openclaw/hummingbird
docker cp apps/condor/routines/news_reader.py hummingbird-condor-1:/app/routines/

# 3. Test immediately
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_news_reader.py"

# 4. If errors, add debug prints and repeat steps 2-3
```

### Quick Sync & Test One-Liner
```bash
cd /home/wkadmin/projects/openclaw/hummingbird && \
docker cp apps/condor/routines/news_reader.py hummingbird-condor-1:/app/routines/ && \
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_news_reader.py"
```

## Debugging Techniques

### 1. Add Print Statements
```python
# In your routine
async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    print(f"DEBUG: Config = {config}")
    print(f"DEBUG: Starting with assets: {config.assets}")
    
    result = await some_function()
    print(f"DEBUG: Got result: {len(result)} items")
    
    return RoutineResult(...)
```

### 2. Use Logger
```python
import logging
logger = logging.getLogger(__name__)

async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    logger.info(f"Starting routine with config: {config}")
    logger.debug(f"Fetching data from API...")
    
    try:
        result = await fetch_data()
        logger.info(f"Successfully fetched {len(result)} items")
    except Exception as e:
        logger.error(f"Error fetching data: {e}", exc_info=True)
        return f"Error: {e}"
```

### 3. Test Individual Functions
Create a quick test script:

```python
# test_debug.py (inside Docker)
import asyncio
from routines.news_reader import _fetch_cointelegraph_news

async def test():
    result = await _fetch_cointelegraph_news(["BTC"], 24, 10)
    print(f"Got {len(result)} articles:")
    for article in result:
        print(f"  - {article.headline}")

asyncio.run(test())
```

Run it:
```bash
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python test_debug.py"
```

### 4. Interactive Debugging with ipdb
Add breakpoint in code:
```python
import ipdb; ipdb.set_trace()  # Execution will pause here
```

Run with interactive terminal:
```bash
docker exec -it hummingbird-condor-1 bash
cd /app
uv run python tests/routines/test_news_reader.py
```

## Testing Shortcuts

### Test All Routines
```bash
cd /home/wkadmin/projects/openclaw/hummingbird
for routine in news_reader funding_monitor vpin_calc sentiment_tracker smallcap_screener meme_scanner rwa_monitor tier_allocator; do
  echo "Testing $routine..."
  docker exec hummingbird-condor-1 bash -c "cd /app && timeout 30 uv run python tests/routines/test_${routine}.py" || echo "FAILED: $routine"
done
```

### Quick Routine Test Function (add to .bashrc)
```bash
# Add this to ~/.bashrc for quick testing
test_routine() {
    local routine=$1
    cd /home/wkadmin/projects/openclaw/hummingbird && \
    docker cp apps/condor/routines/${routine}.py hummingbird-condor-1:/app/routines/ && \
    docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_${routine}.py"
}

# Usage: test_routine news_reader
```

## Common Issues

### Issue: "No module named 'X'"
**Solution:** Make sure you're running inside Docker, not locally.

### Issue: Changes not reflected
**Solution:** Always sync after editing:
```bash
docker cp apps/condor/routines/your_file.py hummingbird-condor-1:/app/routines/
```

### Issue: Test hangs or times out
**Solution:** Add timeout to command:
```bash
docker exec hummingbird-condor-1 bash -c "cd /app && timeout 30 uv run python tests/routines/test_news_reader.py"
```

### Issue: API not responding
**Solution:** Check Hummingbot API is running:
```bash
docker exec hummingbird-condor-1 bash -c "curl -s http://hummingbot-api:8000/health || echo 'API not available'"
```

## VS Code Remote Container (Alternative)

For a better debugging experience, you can use VS Code Remote - Containers:

1. Install "Remote - Containers" extension
2. Open Command Palette (Ctrl+Shift+P)
3. Select "Remote-Containers: Attach to Running Container"
4. Choose `hummingbird-condor-1`
5. Open folder `/app`
6. Set breakpoints and use F5 to debug normally

This gives you full VS Code debugging inside the container with all dependencies available.

---

**Bottom Line:** Edit locally, sync to Docker, test in Docker. Fast iteration cycle with all dependencies available. 🚀

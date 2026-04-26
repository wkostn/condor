# Routine Test Scripts

Test scripts for validating routine functionality.

## Available Tests

### validate_setup
- **test_validate_setup.py** - Basic test with mock BTC data
- **test_live_validation.py** - Full integration test with live market data (scans candidates via high_vol_coin_levels, validates each with validate_setup)

### morning_scan
- **test_morning_scan.py** - Test morning market scan routine

### tech_overlay
- **test_tech_overlay.py** - Test technical indicator calculations

## Running Tests

From the condor app root (or from anywhere via Docker exec):

```bash
# Run inside Docker container (recommended)
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_validate_setup.py"
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_live_validation.py"
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_morning_scan.py"
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_tech_overlay.py"

# Or sync and run after making changes
docker cp tests/routines/test_validate_setup.py hummingbird-condor-1:/app/tests/routines/
docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_validate_setup.py"
```

## Test Structure

Each test should:
1. Import the routine from `routines.{routine_name}`
2. Create a mock context object
3. Call the routine with test config
4. Validate the response structure
5. Print results for manual inspection

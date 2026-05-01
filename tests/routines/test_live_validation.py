"""Test validate_setup with live candidates from high_vol_coin_levels."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.high_vol_coin_levels import run as run_scan, Config as ScanConfig
from routines.validate_setup import run as run_validate, Config as ValidateConfig
from telegram.ext import ContextTypes


async def test_live():
    """Fetch live candidates and validate them."""
    
    # Mock context
    context = type('Context', (), {
        '_chat_id': 0,
        'user_data': {},
        'bot': None,
    })()
    
    # Step 1: Get candidates
    print("=" * 70)
    print("STEP 1: Fetching live high-vol candidates...")
    print("=" * 70)
    
    scan_config = ScanConfig(
        candidates=5,
        min_volume_usd=25_000_000,
    )
    
    try:
        scan_result = await run_scan(scan_config, context)
        
        if isinstance(scan_result, str):
            print(f"❌ Scan failed: {scan_result}")
            return
        
        print(scan_result.text)
        print()
        
        # Get candidate data
        candidates = scan_result.table_data if hasattr(scan_result, 'table_data') else []
        
        if not candidates:
            print("No candidates found")
            return
        
        # Step 2: Validate each candidate
        print("\n" + "=" * 70)
        print("STEP 2: Validating each candidate...")
        print("=" * 70)
        
        for idx, candidate in enumerate(candidates, 1):
            print(f"\n{'─' * 70}")
            print(f"Candidate #{idx}: {candidate['trading_pair']} ({candidate['bias']})")
            print(f"Score: {candidate['score']} | ATR: {candidate['atr_pct']}% | Price: ${candidate['last_price']}")
            print(f"{'─' * 70}")
            
            # Build validation config from candidate
            validate_config = ValidateConfig(
                trading_pair=candidate['trading_pair'],
                connector="binance_perpetual",
                bias=candidate['bias'],
                last_price=candidate['last_price'],
                pullback_level=candidate['pullback_level'],
                breakout_level=candidate['breakout_level'],
                breakdown_level=candidate['breakdown_level'],
                invalid_long_level=candidate['invalid_long_level'],
                invalid_short_level=candidate['invalid_short_level'],
                atr_pct=candidate['atr_pct'],
                proximity_pct=1.5,
                max_stop_pct=4.0,  # Match agent's ~4% budget
            )
            
            try:
                validation = await run_validate(validate_config, context)
                
                if isinstance(validation, str):
                    print(f"  ❌ Validation failed: {validation}")
                    continue
                
                print(validation.text if hasattr(validation, 'text') else str(validation))
                
                if hasattr(validation, 'table_data') and validation.table_data:
                    data = validation.table_data[0]
                    print(f"\n  🎯 DECISION: {data['decision']}")
                    print(f"  📊 QUALITY: {data['quality_score']}/100")
                    print(f"  ✓ READY: {data['ready']}")
                    
            except Exception as e:
                print(f"  ❌ Error validating: {e}")
                import traceback
                traceback.print_exc()
        
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Total candidates scanned: {len(candidates)}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_live())

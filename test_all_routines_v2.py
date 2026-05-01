#!/usr/bin/env python3
"""Comprehensive routine testing - runs each routine and documents results."""
import sys
sys.path.insert(0, '/app')

import asyncio
import json
import traceback
from datetime import datetime

from routines.base import discover_routines

# Mock context
class MockContext:
    def __init__(self):
        self._chat_id = 123456789
        self.bot = None
        self._user_data = {
            "preferences": {"general": {"active_server": "main"}},
        }
    
    @property
    def user_data(self):
        return self._user_data


async def test_routine(name: str, info) -> dict:
    """Test one routine comprehensively."""
    result = {
        "name": name,
        "description": info.description,
        "status": "unknown",
        "timestamp": datetime.now().isoformat(),
    }
    
    try:
        # Check config schema
        config_class = info.config_class
        schema = config_class.model_json_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Find required fields without defaults
        missing_defaults = []
        for field in required:
            field_info = properties.get(field, {})
            if "default" not in field_info:
                missing_defaults.append(field)
        
        result["config_schema"] = {
            "total_fields": len(properties),
            "required_fields": len(required),
            "missing_defaults": missing_defaults,
        }
        
        if missing_defaults:
            result["status"] = "CONFIG_ERROR"
            result["error"] = f"Required fields lack defaults: {', '.join(missing_defaults)}"
            return result
        
        # Instantiate config with defaults
        try:
            config = config_class()
            result["config_values"] = {k: str(v)[:100] for k, v in config.model_dump().items()}
        except Exception as e:
            result["status"] = "CONFIG_INSTANTIATION_ERROR"
            result["error"] = f"{type(e).__name__}: {str(e)}"
            result["traceback"] = traceback.format_exc()
            return result
        
        # Run the routine
        context = MockContext()
        try:
            routine_result = await asyncio.wait_for(
                info.run_fn(config, context),
                timeout=30.0  # 30 second timeout
            )
            
            result["status"] = "SUCCESS"
            if routine_result:
                result["output_type"] = str(type(routine_result).__name__)
                if hasattr(routine_result, 'text'):
                    result["output_length"] = len(routine_result.text)
                elif isinstance(routine_result, str):
                    result["output_length"] = len(routine_result)
            else:
                result["output_note"] = "Returned None"
                
        except asyncio.TimeoutError:
            result["status"] = "TIMEOUT"
            result["error"] = "Routine exceeded 30s timeout"
        except Exception as e:
            result["status"] = "RUNTIME_ERROR"
            result["error"] = f"{type(e).__name__}: {str(e)}"
            result["traceback"] = traceback.format_exc()
    
    except Exception as e:
        result["status"] = "TEST_ERROR"
        result["error"] = f"{type(e).__name__}: {str(e)}"
        result["traceback"] = traceback.format_exc()
    
    return result


async def main():
    print("="*80)
    print("COMPREHENSIVE CONDOR ROUTINE TEST")
    print("="*80)
    print()
    
    routines = discover_routines()
    print(f"Testing {len(routines)} routines...")
    print()
    
    results = []
    for name in sorted(routines.keys()):
        print(f"[{len(results)+1}/{len(routines)}] Testing: {name}")
        result = await test_routine(name, routines[name])
        results.append(result)
        
        status_icon = {
            "SUCCESS": "✅",
            "CONFIG_ERROR": "❌",
            "CONFIG_INSTANTIATION_ERROR": "❌",
            "RUNTIME_ERROR": "❌",
            "TIMEOUT": "⏱️",
            "TEST_ERROR": "❌",
        }.get(result["status"], "❓")
        
        print(f"   {status_icon} {result['status']}")
        if result.get("error"):
            error_lines = result["error"].split("\\n")
            for line in error_lines[:2]:
                print(f"      {line}")
        print()
    
    # Summary
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print()
    
    by_status = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r["name"])
    
    for status in sorted(by_status.keys()):
        names = by_status[status]
        print(f"{status} ({len(names)}):")
        for name in names:
            print(f"  • {name}")
        print()
    
    # Detailed results
    output_file = "/tmp/routine_test_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"📄 Detailed results: {output_file}")
    print()
    
    # Action items
    failures = [r for r in results if r["status"] != "SUCCESS"]
    if failures:
        print("="*80)
        print("ACTION ITEMS")
        print("="*80)
        print()
        for fail in failures:
            print(f"❌ {fail['name']}")
            print(f"   Status: {fail['status']}")
            if "config_schema" in fail and fail["config_schema"].get("missing_defaults"):
                print(f"   Missing defaults: {', '.join(fail['config_schema']['missing_defaults'])}")
            if fail.get("error"):
                print(f"   Error: {fail['error'][:200]}")
            print()
    
    return 0 if len(failures) == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

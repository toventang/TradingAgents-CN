#!/usr/bin/env python3
"""
Simple test to debug the project initialization issues
"""
import os
import sys

# Set Python encoding to UTF-8
os.environ['PYTHONIOENCODING'] = 'utf-8'

print("[TEST] Starting simple main.py test...")
print(f"[TEST] Python version: {sys.version}")
print(f"[TEST] Current directory: {os.getcwd()}")

try:
    print("\n[TEST 1] Importing logger...")
    from tradingagents.utils.logging_manager import get_logger
    logger = get_logger('test')
    logger.info("Logger initialized successfully")
    
    print("\n[TEST 2] Importing default config...")
    from tradingagents.default_config import DEFAULT_CONFIG
    logger.info(f"Default config loaded: {list(DEFAULT_CONFIG.keys())[:5]}")
    
    print("\n[TEST 3] Creating custom config...")
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "google"
    config["backend_url"] = "https://generativelanguage.googleapis.com/v1beta"
    config["deep_think_llm"] = "gemini-2.0-flash"
    config["quick_think_llm"] = "gemini-2.0-flash"
    config["max_debate_rounds"] = 1
    config["online_tools"] = True
    
    if not os.getenv("GOOGLE_API_KEY"):
        config["quick_api_key"] = "mock_google_api_key"
        config["deep_api_key"] = "mock_google_api_key"
    
    logger.info(f"Config prepared: llm_provider={config['llm_provider']}")
    
    print("\n[TEST 4] Importing TradingAgentsGraph...")
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    logger.info("TradingAgentsGraph imported")
    
    print("\n[TEST 5] Initializing TradingAgentsGraph...")
    ta = TradingAgentsGraph(debug=True, config=config)
    logger.info("TradingAgentsGraph initialized successfully!")
    
    print("\n[TEST 6] Running propagate...")
    _, decision = ta.propagate("NVDA", "2024-05-10")
    print(f"\n[TEST] Decision result: {decision}")
    
    print("\n[SUCCESS] All tests passed!")
    
except Exception as e:
    print(f"\n[ERROR] Test failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

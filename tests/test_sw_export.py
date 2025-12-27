import asyncio
import sys
import os
sys.path.append(os.getcwd())

from app.agent.llm_client import LLMClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    client = LLMClient()
    prompt = "A simple 100x100x20mm plate"
    print(f"Testing SW Macro Gen for: '{prompt}'...")
    
    try:
        code = await client.generate_solidworks_macro(prompt)
        print("\n--- GENERATED CODE ---\n")
        print(code[:500] + "\n...[truncated]...")
        
        # Validation checks
        if "Dim swApp As Object" in code:
            print("\n✅ Verification Passed: Standard init found.")
        else:
            print("\n❌ Verification Failed: Missing 'Dim swApp' init.")
            
        if "Part.FeatureManager.FeatureExtrusion2" in code:
             print("✅ Verification Passed: Extrusion call found.")
             
    except Exception as e:
        print(f"❌ Test Failed: {e}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

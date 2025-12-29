import asyncio
from pathlib import Path
from dotenv import load_dotenv
import os

# Load env vars
load_dotenv()

from app.services.generation_service import GenerationService

# Ensure outputs dir exists
Path("outputs").mkdir(exist_ok=True)

async def run_debug():
    print("Starting Debug Run...")
    service = GenerationService(output_dir=Path("outputs"))
    
    prompt = "a small rectangle box of 10 x 30 x 5 mm"
    print(f"Generating for prompt: '{prompt}'")
    
    try:
        result = await service.generate(prompt)
        print("\nGeneration Successful!")
        print(f"GLB Path: {result.geometry_path}")
        print(f"Metadata: {result.metadata}")
    except Exception as e:
        print(f"\nGeneration FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_debug())

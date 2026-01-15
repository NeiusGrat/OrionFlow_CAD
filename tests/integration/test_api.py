import requests
import json

BASE_URL = "http://localhost:8000"

def test_generate(prompt):
    print(f"\n--- Testing Prompt: '{prompt}' ---")
    try:
        response = requests.post(f"{BASE_URL}/generate", json={"prompt": prompt})
        if response.status_code == 200:
            data = response.json()
            print(f"Success! Job ID: {data['job_id']}")
            print(f"Detected Part Type: {data['feature_graph']['part_type']}")
            print(f"Parameters: {data['parameters']}")
            print(f"Files created: {data['files'].keys()}")
            return data
        else:
            print(f"Failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    # Test 1: Rectangle (Should be box)
    test_generate("a 20x30 rectangle plate")

    # Test 2: Cylinder (Should be cylinder)
    test_generate("a cylinder with radius 5 and height 50")
    
    # Test 3: Invalid (Should fail validation IF we forced strictness, but we have defaults. 
    # Let's try negative to trigger sanity check)
    # The extraction logic currently defaults to 10 or 5, so it's hard to trigger neg from text unless we force it.
    # But we can verify that the intent parser works.

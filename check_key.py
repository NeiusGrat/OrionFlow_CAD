# check_key.py
import os
from dotenv import load_dotenv

# 1. Load the .env file
load_dotenv()

# 2. Try to get the key
api_key = os.getenv("GROQ_API_KEY")

if api_key:
    print(f"✅ Success! Found key starting with: {api_key[:8]}...")
else:
    print("❌ Error: Key not found. Check your .env file location.")
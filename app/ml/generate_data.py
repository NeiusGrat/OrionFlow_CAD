import random
import json

data = []

for _ in range(5000):
    radius = random.randint(5, 100)
    height = random.randint(10, 200)

    prompt = f"make a cylinder with radius {radius} and height {height}"

    data.append({
        "prompt": prompt,
        "radius": radius,
        "height": height
    })

with open("dataset.json", "w") as f:
    json.dump(data, f, indent=2)

print("Dataset generated:", len(data))

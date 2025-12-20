import json
import joblib
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.ensemble import GradientBoostingRegressor

# load data
with open("dataset.json") as f:
    data = json.load(f)

texts = [d["prompt"] for d in data]
radius_targets = [d["radius"] for d in data]
height_targets = [d["height"] for d in data]

# vectorize text
vectorizer = CountVectorizer()
X = vectorizer.fit_transform(texts)

# train models
radius_model = GradientBoostingRegressor()
height_model = GradientBoostingRegressor()

radius_model.fit(X, radius_targets)
height_model.fit(X, height_targets)

# save artifacts
joblib.dump(vectorizer, "app/models/vectorizer.joblib")
joblib.dump(radius_model, "app/models/radius_model.joblib")
joblib.dump(height_model, "app/models/height_model.joblib")

print("Models trained and saved")

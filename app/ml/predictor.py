import joblib
from app.ml.rules import rule_based_extract

# load models once
vectorizer = joblib.load("app/models/vectorizer.joblib")
radius_model = joblib.load("app/models/radius_model.joblib")
height_model = joblib.load("app/models/height_model.joblib")

def predict_parameters(prompt: str) -> dict:
    """
    Hybrid predictor:
    1. Use rule-based extraction
    2. Fill missing params with ML
    """
    params = rule_based_extract(prompt)

    missing = []
    if "radius" not in params:
        missing.append("radius")
    if "height" not in params:
        missing.append("height")

    if not missing:
        return params

    X = vectorizer.transform([prompt])

    if "radius" in missing:
        params["radius"] = float(radius_model.predict(X)[0])

    if "height" in missing:
        params["height"] = float(height_model.predict(X)[0])

    return params

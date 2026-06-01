import os


class OnshapeClient:
    def __init__(self):
        self.base_url = "https://cad.onshape.com"
        self.access_key = os.getenv("ONSHAPE_ACCESS_KEY")
        self.secret_key = os.getenv("ONSHAPE_SECRET_KEY")

    def post(self, endpoint: str, payload: dict):
        _url = f"{self.base_url}{endpoint}"
        _headers = {"Accept": "application/json", "Content-Type": "application/json"}
        # NOTE: auth signing is assumed handled elsewhere
        # For now, we are just implementing the architecture.
        # Authentic requests would fail without real signing.
        # response = requests.post(_url, json=payload, headers=_headers)
        # response.raise_for_status()
        # return response.json()

        # MOCK RESPONSE for now to allow architecture verification without keys
        return {"status": "mock_success", "payload_received": payload}

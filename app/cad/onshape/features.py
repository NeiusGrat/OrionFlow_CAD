from .client import OnshapeClient


class OnshapeFeatureAdapter:
    def __init__(self, client: OnshapeClient, document_id, workspace_id, element_id):
        self.client = client
        self.document_id = document_id
        self.workspace_id = workspace_id
        self.element_id = element_id

    def extrude(self, depth):
        endpoint = f"/api/features/d/{self.document_id}/w/{self.workspace_id}/e/{self.element_id}"
        payload = {
            "featureType": "extrude",
            "depth": depth,
            "operation": "NEW"
        }
        return self.client.post(endpoint, payload)

from .client import OnshapeClient


class OnshapeSketchAdapter:
    def __init__(self, client: OnshapeClient, document_id, workspace_id, element_id):
        self.client = client
        self.document_id = document_id
        self.workspace_id = workspace_id
        self.element_id = element_id

    def create_sketch(self, sketch_id):
        endpoint = f"/api/sketches/d/{self.document_id}/w/{self.workspace_id}/e/{self.element_id}"
        payload = {
            "name": sketch_id,
            "plane": "TOP"
        }
        return self.client.post(endpoint, payload)

    def add_rectangle(self, width, height):
        # Simplified placeholder
        payload = {
            "type": "rectangle",
            "width": width,
            "height": height
        }
        return self.client.post("/api/sketch/geometry", payload)

    def add_circle(self, radius):
        payload = {
            "type": "circle",
            "radius": radius
        }
        return self.client.post("/api/sketch/geometry", payload)

from abc import ABC, abstractmethod
import cadquery as cq

class BasePart(ABC):
    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def build(self) -> cq.Workplane:
        """
        Builds and returns the CadQuery geometry.
        """
        pass

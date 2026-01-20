
from build123d import *

def check_geometry():
    print("Checking raw Build123d geometry...")
    with BuildPart() as p:
        with BuildSketch(Plane.XY) as s:
            Rectangle(50, 30)
        extrude(amount=20)
    
    print(f"Solid has {len(p.edges())} edges")
    for i, e in enumerate(p.edges()):
        print(f"Edge {i}: Length={e.length:.4f}")

if __name__ == "__main__":
    check_geometry()

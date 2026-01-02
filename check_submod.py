import build123d
try:
    import build123d.constraints
    print("build123d.constraints exists")
    print(dir(build123d.constraints))
    print("Coincident" in dir(build123d.constraints))
except ImportError:
    print("build123d.constraints DOES NOT exist")

# Check BuildSketch methods
from build123d import BuildSketch
print("BuildSketch methods:", [x for x in dir(BuildSketch) if "constrain" in x])

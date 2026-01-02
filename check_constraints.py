from build123d import *
import build123d
print([x for x in dir(build123d) if "Constraint" in x])
print([x for x in dir(build123d) if "Fixed" in x])
print([x for x in dir(build123d) if "Rigid" in x])

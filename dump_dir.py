import build123d
with open("build123d_dir.txt", "w") as f:
    for x in dir(build123d):
        f.write(x + "\n")

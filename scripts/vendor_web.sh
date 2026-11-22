#!/bin/sh
# Vendor the dashboard's third-party files into src/sdd/web/static/vendor/ (M09.1).
# Run in the dev container:  docker compose -f docker-compose.dev.yml exec dev sh scripts/vendor_web.sh
# Each npm tarball is downloaded from registry.npmjs.org and checked against the sha512 pinned below
# before anything is copied. The output is committed; nothing is fetched at runtime or in CI.
# To upgrade a package, edit its version and sha512 here and re-run.
set -eu
cd "$(dirname "$0")/.."
exec python3 - <<'PY'
import base64, hashlib, io, json, pathlib, re, shutil, sys, tarfile, urllib.request

FINAL = pathlib.Path("src/sdd/web/static/vendor")
OUT = FINAL.parent / ".vendor-new"  # built here, swapped in only when every pin has matched

# name, version, sha512 (npm "integrity", base64), licence
PINS = {
    "three": ("0.187.0", "Qiu7R+Cmh8CstZsY1uJOSWnVlfo7ZtNLV7mF8Jltk3LB3AtDu9cRZlcnRKkAk8Y4z6KKw35z7Y7Urd7jWY8etA==", "MIT"),
    "d3-force-3d": ("3.0.6", "4tsKHUPLOVkyfEffZo1v6sFHvGFwAIIjt/W8IThbp08DYAsXZck+2pSHEG5W1+gQgEvFLdZkYvmJAbRM2EzMnA==", "MIT"),
    "d3-binarytree": ("1.0.2", "cElUNH+sHu95L04m92pG73t2MEJXKu+GeKUN1TJkFsu93E5W8E9Sc3kHEGJKgenGvj19m6upSn2EunvMgMD2Yw==", "MIT"),
    "d3-octree": ("1.1.0", "F8gPlqpP+HwRPMO/8uOu5wjH110+6q4cgJvgJT6vlpy3BEaDIKlTZrgHKZSp/i1InRpVfh4puY/kvL6MxK930A==", "MIT"),
    "d3-dispatch": ("3.0.2", "sAzH4Y4nsLo8eSqw5jKiZt+LU2wZmL/qS+OkxQGjhwazB/D7TY34R/QK1eshfGr7cZEKymKZ/Haem7m+lu98Sg==", "ISC"),
    "d3-quadtree": ("3.0.2", "9Lu9mqJKRbIk0d6mKDjpvPURaPdwHVK5CYbcdd0/4vBgz4ldz/7TIOse3kNERsByGNfld58KEco507AztJWyTQ==", "ISC"),
    "d3-timer": ("3.0.2", "1Il1aliroVSErrv5aulRBxAY+7+DnaoLIWGd1C6SsBTWDeobWiP/V69vwb8vT6abR1kKwaNe1196pmaQ1fK90A==", "ISC"),
    "@fontsource/inter": ("5.3.0", "RofMylZmjlJEfELXeNHFWBRcSs75rGU/6bV2S2jfnvv/3rPXPGe0LgUJTklcHZ9lM4OZmAVFhcJPnACfb91A3g==", "OFL-1.1"),
    "@fontsource/jetbrains-mono": ("5.3.0", "fqDfB5I9f1p1TV486aUgB9t8zP84P0O1FtQR5Ol9vjwPy+S+EIGlVYm1cvj2W5shcZMTg2nZFdVMoH5wFu8a1A==", "OFL-1.1"),
}
THREE_FILES = {  # tarball path -> vendored name under vendor/three/
    "build/three.module.js": "three.module.js",
    "build/three.core.js": "three.core.js",
    "examples/jsm/controls/OrbitControls.js": "OrbitControls.js",
    "examples/jsm/renderers/CSS2DRenderer.js": "CSS2DRenderer.js",
}
FONT_WEIGHTS = ("400", "500", "600")
D3_DEPS = ("d3-binarytree", "d3-octree", "d3-dispatch", "d3-quadtree", "d3-timer")
KEEP = {"cytoscape.min.js", "LICENSE-cytoscape.txt"}  # vendored by hand earlier, kept as is


def fetch(name):
    version, pin, _ = PINS[name]
    url = f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-{version}.tgz"
    data = urllib.request.urlopen(url, timeout=60).read()
    got = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if got != pin:
        sys.exit(f"{name}@{version}: sha512 mismatch\n  pinned {pin}\n  got    {got}")
    tar = tarfile.open(fileobj=io.BytesIO(data))
    return {m.name.removeprefix("package/"): tar.extractfile(m).read() for m in tar if m.isfile()}


def rewrite(text, mapping):
    # bare `from 'x'` / `from "x"` -> relative path; an import map would be an inline script
    def sub(m):
        spec = m.group(2)
        if spec not in mapping:
            sys.exit(f"unmapped bare import {spec!r}")
        return f"{m.group(1)}{mapping[spec]}{m.group(3)}"
    bare = r"""[A-Za-z@][^'"]*"""
    text = re.sub(rf"""^(\s*(?:import|export|\}})[^\n'"]*from\s+['"])({bare})(['"])""", sub, text, flags=re.M)
    text = re.sub(rf"""^(\s*import\s+['"])({bare})(['"])""", sub, text, flags=re.M)  # side-effect import
    return re.sub(rf"""^([^\n*/]*\bimport\(\s*['"])({bare})(['"]\s*\))""", sub, text, flags=re.M)  # dynamic


if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir()
for name in KEEP:
    shutil.copy(FINAL / name, OUT / name)

manifest = []
licences = {}


def record(name, files, lic_file, lic_bytes):
    (OUT / lic_file).parent.mkdir(parents=True, exist_ok=True)
    (OUT / lic_file).write_bytes(lic_bytes)
    version, pin, licence = PINS[name]
    manifest.append({"package": name, "version": version, "sha512": pin, "licence": licence,
                     "files": sorted(files), "licence_file": lic_file})


# three.js: bare `three` -> sibling file
pkg = fetch("three")
files = []
for src, dest in THREE_FILES.items():
    text = pkg[src].decode()
    text = rewrite(text, {"three": "./three.module.js"}) if dest in ("OrbitControls.js", "CSS2DRenderer.js") else text
    (OUT / "three").mkdir(parents=True, exist_ok=True)
    (OUT / "three" / dest).write_text(text, encoding="utf-8")
    files.append(f"three/{dest}")
record("three", files, "three/LICENSE", pkg["LICENSE"])

# d3-force-3d and its dependencies: src/*.js as ESM, bare d3-* imports -> ../<package>/index.js
mapping = {n: f"../{n}/index.js" for n in ("d3-force-3d", *D3_DEPS)}
for name in ("d3-force-3d", *D3_DEPS):
    pkg = fetch(name)
    files = []
    dist = f"dist/{name}.mjs"
    if dist in pkg:  # d3-dispatch, d3-quadtree, d3-timer ship one self-contained ESM bundle, no src/
        dest = f"{name}/index.js"
        (OUT / dest).parent.mkdir(parents=True, exist_ok=True)
        (OUT / dest).write_text(pkg[dist].decode(), encoding="utf-8")
        files.append(dest)
    for path, body in pkg.items():
        if path.startswith("src/") and path.endswith(".js"):
            dest = f"{name}/{path.removeprefix('src/')}"
            (OUT / dest).parent.mkdir(parents=True, exist_ok=True)
            (OUT / dest).write_text(rewrite(body.decode(), mapping), encoding="utf-8")
            files.append(dest)
    record(name, files, f"{name}/LICENSE", pkg["LICENSE"])

# fonts: latin 400/500/600 woff2 only, under vendor/fonts/
for name, stem in (("@fontsource/inter", "inter"), ("@fontsource/jetbrains-mono", "jetbrains-mono")):
    pkg = fetch(name)
    files = []
    for w in FONT_WEIGHTS:
        src = f"files/{stem}-latin-{w}-normal.woff2"
        dest = f"fonts/{stem}-latin-{w}-normal.woff2"
        (OUT / dest).parent.mkdir(parents=True, exist_ok=True)
        (OUT / dest).write_bytes(pkg[src])
        files.append(dest)
    record(name, files, f"fonts/LICENSE-{stem}.txt", pkg["LICENSE"])

# cytoscape was vendored by hand before this script existed (M05a): kept as is, pinned by the sha512
# of the file itself (not of an npm tarball); its version string is inside the file
CYTOSCAPE = ("3.30.2", "EY3U1MWdgKx0P1dqTE4inlKz2cpXtWpsR1YUyD855Hs6RL/A0cyvrKh60EpE8wDZ814cTe1KgRK+sG0Rn792vQ==")
cy = (OUT / "cytoscape.min.js").read_bytes()
got = base64.b64encode(hashlib.sha512(cy).digest()).decode()
if got != CYTOSCAPE[1] or f'"{CYTOSCAPE[0]}"'.encode() not in cy:
    sys.exit(f"cytoscape.min.js does not match its pin\n  pinned {CYTOSCAPE[1]}\n  got    {got}")
manifest.append({"package": "cytoscape", "version": CYTOSCAPE[0], "sha512": got, "licence": "MIT",
                 "files": ["cytoscape.min.js"], "licence_file": "LICENSE-cytoscape.txt"})
(OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
shutil.rmtree(FINAL)  # every pin matched: swap the staged tree in
OUT.rename(FINAL)
print(f"vendored {len(manifest)} packages into {FINAL}")
PY

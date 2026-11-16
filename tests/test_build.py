"""Release checks: what each built distribution contains, and the version policy.

Every distribution is built once per session with ``uv build --offline
--no-build-isolation``: the build backend is the copy of hatchling pinned in
the workspace's dev group, so nothing is fetched beyond ``uv sync``. Then:

- each codec's wheel holds exactly its own subpackage, ``gnsswire/<name>/``,
  file for file as in ``src/``, and its ``.dist-info``; never
  ``gnsswire/__init__.py`` (the namespace is shared) and never another codec;
  the ``gnsswire`` wheel, which installs every codec, holds its
  ``.dist-info`` only;
- each wheel imports with nothing but the standard library and the wheels
  of its declared ``gnsswire`` dependencies, each unpacked into its own
  directory, so the namespace is assembled from separate installs;
- each wheel and sdist carries the MIT licence, declared as PEP 639
  metadata;
- each sdist holds its own package directory only, and every file under a
  ``tests/data`` directory in it is listed in ``THIRD_PARTY`` below, with
  its notice file beside it (THIRD_PARTY_NOTICES.md at the root lists them);
- metadata and versions follow the policy in README.md, "Versions".
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = sorted(p.name for p in (ROOT / "packages").iterdir() if p.is_dir())
# The distribution that installs every codec and has no modules of its own.
META = "gnsswire"
CODECS = [name for name in PACKAGES if name != META]
LICENSE = (ROOT / "LICENSE").read_text()

# Committed files whose content is not only this project's own, by the notice
# file that carries their licence and attribution. They are test data and reach
# the sdists, never the wheels.
THIRD_PARTY = {
    "packages/rtcm3/tests/data/public.hex": "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/rtcm3/tests/data/rtklib.hex": "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/rtcm3/tests/data/rtklib-msm.hex": "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/rtcm3/tests/data/rtklib-station.hex": "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/rtcm3/tests/data/rtklib-igs.hex": "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/rtcm3/tests/data/rtklib-igs-decoded.json":
        "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/rtcm3/tests/data/rtklib-antenna.hex": "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/rtcm3/tests/data/rtklib-antenna-decoded.json":
        "packages/rtcm3/tests/THIRD_PARTY_NOTICES.md",
    "packages/nmea/tests/data/gpsd-zed-f9p.nmea": "packages/nmea/tests/THIRD_PARTY_NOTICES.md",
    "packages/skytraq/tests/data/rtklib-decoded.txt":
        "packages/skytraq/tests/THIRD_PARTY_NOTICES.md",
    "packages/rinex/tests/data/rtklib-read.json": "packages/rinex/tests/THIRD_PARTY_NOTICES.md",
    "packages/nav/tests/data/rtklib-decoded.txt": "packages/nav/tests/THIRD_PARTY_NOTICES.md",
}


def pyproject(name: str) -> dict:
    return tomllib.loads((ROOT / "packages" / name / "pyproject.toml").read_text())


def project(name: str) -> dict:
    return pyproject(name)["project"]


def dist_name(name: str) -> str:
    return f"{project(name)['name'].replace('-', '_')}-{project(name)['version']}"


def gnsswire_deps(name: str) -> dict[str, Requirement]:
    reqs = (Requirement(r) for r in project(name)["dependencies"])
    return {r.name.removeprefix("gnsswire-"): r for r in reqs if r.name.startswith("gnsswire-")}


@pytest.fixture(scope="session")
def dists(tmp_path_factory) -> Path:
    uv = os.environ.get("UV") or shutil.which("uv")
    if uv is None:
        pytest.fail("uv not found: the build check needs uv (run the gate as `uv run pytest`)")
    out = tmp_path_factory.mktemp("dist")
    done = subprocess.run([uv, "build", "--all-packages", "--offline", "--no-build-isolation",
                           "--wheel", "--sdist", "--quiet", "-o", str(out)],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, f"uv build failed:\n{done.stderr}"
    return out


def wheel(dists: Path, name: str) -> Path:
    return dists / f"{dist_name(name)}-py3-none-any.whl"


def sdist_names(dists: Path, name: str) -> list[str]:
    with tarfile.open(dists / f"{dist_name(name)}.tar.gz") as t:
        return [n.removeprefix(dist_name(name) + "/") for n in t.getnames()]


def sources(name: str) -> set[str]:
    src = ROOT / "packages" / name / "src"
    return {p.relative_to(src).as_posix() for p in (src / "gnsswire" / name).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


@pytest.mark.parametrize("name", PACKAGES)
def test_wheel_holds_only_its_subpackage(dists, name):
    names = zipfile.ZipFile(wheel(dists, name)).namelist()
    info = f"{dist_name(name)}.dist-info/"
    code = {n for n in names if not n.startswith(info)}
    assert code == (set() if name == META else sources(name))
    assert "gnsswire/__init__.py" not in names
    assert {n.removeprefix(info) for n in names if n.startswith(info)} >= {"METADATA", "WHEEL",
                                                                          "RECORD"}


@pytest.mark.parametrize("name", PACKAGES)
def test_wheel_metadata(dists, name):
    with zipfile.ZipFile(wheel(dists, name)) as z:
        meta = z.read(f"{dist_name(name)}.dist-info/METADATA").decode()
        tags = z.read(f"{dist_name(name)}.dist-info/WHEEL").decode()
        licence = z.read(f"{dist_name(name)}.dist-info/licenses/LICENSE").decode()
    headers = [line.split(": ", 1) for line in meta.split("\n\n", 1)[0].splitlines()]
    field = {}
    for key, value in headers:
        field.setdefault(key, []).append(value)
    p = project(name)
    assert field["Name"] == [p["name"]] and field["Version"] == [p["version"]]
    assert field["Requires-Python"] == [p["requires-python"]]
    assert sorted(map(Requirement, field.get("Requires-Dist", [])), key=str) \
        == sorted(map(Requirement, p["dependencies"]), key=str)
    assert field["License-Expression"] == ["MIT"] and field["License-File"] == ["LICENSE"]
    assert licence == LICENSE
    assert "Tag: py3-none-any" in tags
    assert meta.split("\n\n", 1)[1].strip() == (ROOT / "packages" / name / "README.md") \
        .read_text().strip()
    assert field["Author"] == [AUTHORS]
    urls = dict(u.split(", ", 1) for u in field["Project-URL"])
    assert urls["Homepage"] == REPOSITORY and urls["Issues"] == f"{REPOSITORY}/issues"
    assert urls["Changelog"] == f"{REPOSITORY}/blob/main/RELEASES.md"
    assert urls["Source"] == (REPOSITORY if name == META
                              else f"{REPOSITORY}/tree/main/packages/{name}")
    assert field["Classifier"] == p["classifiers"]


AUTHORS = "Trace Navigation LLC"
REPOSITORY = "https://github.com/tracenav/gnsswire"


@pytest.mark.parametrize("name", PACKAGES)
def test_metadata_is_complete(name):
    # Every distribution, new ones included: authors, project URLs and the
    # classifiers of every Python version CI tests that a classifier exists for.
    p = project(name)
    assert p["authors"] == [{"name": AUTHORS}]
    assert set(p["urls"]) == {"Homepage", "Source", "Changelog", "Issues"}
    assert all(u.startswith(REPOSITORY) for u in p["urls"].values())
    minimum = int(p["requires-python"].removeprefix(">=3."))
    versions = {f"Programming Language :: Python :: 3.{v}" for v in range(minimum, 15)}
    assert versions <= set(p["classifiers"])
    assert not any(c.startswith("License ::") for c in p["classifiers"])   # PEP 639
    assert p["classifiers"] == project(META)["classifiers"]


@pytest.mark.parametrize("name", PACKAGES)
def test_readme_links_the_repository(name):
    # A README read on the package index must reach the repository it refers to.
    text = (ROOT / "packages" / name / "README.md").read_text()
    assert f"]({REPOSITORY}#readme)" in text
    for line_no, line in enumerate(text.splitlines()):
        if "repository README" in line.replace("\n", " "):
            assert "[repository README](" in line, (name, line_no, line)


@pytest.mark.parametrize("name", PACKAGES)
def test_wheel_imports_with_its_dependencies_alone(dists, tmp_path, name):
    # Each wheel in its own directory, named after the codec it holds (the
    # gnsswire wheel holds none, so it adds no directory to the namespace).
    args = []
    for each in [name, *gnsswire_deps(name)]:
        target = tmp_path / each
        zipfile.ZipFile(wheel(dists, each)).extractall(target)
        args.append(f"{'' if each == META else each}={target}")
    # -I -S: no site-packages, so only the standard library and the unpacked wheels.
    code = """if True:
        import importlib, os, sys
        wheels = [arg.split("=", 1) for arg in sys.argv[1:]]
        sys.path[:0] = [path for _, path in wheels]
        import gnsswire
        norm = lambda p: os.path.normcase(os.path.realpath(p))
        assert sorted(map(norm, gnsswire.__path__)) == sorted(
            norm(os.path.join(path, "gnsswire")) for codec, path in wheels if codec), \\
            gnsswire.__path__
        for codec, path in wheels:
            if codec:
                module = importlib.import_module("gnsswire." + codec)
                assert norm(module.__file__).startswith(norm(path)), module.__file__
    """
    done = subprocess.run([sys.executable, "-I", "-S", "-c", code, *args],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("name", PACKAGES)
def test_sdist_holds_only_its_package(dists, name):
    names = sdist_names(dists, name)
    assert {"PKG-INFO", "pyproject.toml", "README.md", "LICENSE"} <= set(names)
    if name == META:
        # hatchling adds the repository's .gitignore to every sdist.
        assert set(names) <= {"PKG-INFO", "pyproject.toml", "README.md", "LICENSE", ".gitignore"}
        return
    assert {n for n in names if n.startswith("src/")} == {f"src/{s}" for s in sources(name)}
    assert all(n.split("/")[0] in {"src", "tests", "PKG-INFO", "pyproject.toml", "README.md",
                                   "LICENSE", ".gitignore"} for n in names), names
    data = {f"packages/{name}/{n}" for n in names if "/data/" in f"/{n}"}
    assert data == {f for f in THIRD_PARTY if f.startswith(f"packages/{name}/")}
    notices = {THIRD_PARTY[f].removeprefix(f"packages/{name}/") for f in data}
    assert notices <= set(names), f"{name}: sdist lacks {notices - set(names)}"


@pytest.mark.parametrize("name", PACKAGES)
def test_sdist_carries_the_licence(dists, name):
    with tarfile.open(dists / f"{dist_name(name)}.tar.gz") as t:
        licence = t.extractfile(f"{dist_name(name)}/LICENSE").read().decode()
        info = t.extractfile(f"{dist_name(name)}/PKG-INFO").read().decode()
    assert licence == LICENSE
    headers = info.split("\n\n", 1)[0].splitlines()
    assert "License-Expression: MIT" in headers and "License-File: LICENSE" in headers


# --- licence (no build needed) ---------------------------------------------------------

def test_licence_is_mit():
    assert LICENSE.startswith("MIT License\n\nCopyright (c) 2026 Trace Navigation LLC\n")


@pytest.mark.parametrize("name", PACKAGES)
def test_distribution_declares_the_licence(name):
    p = project(name)
    assert p["license"] == "MIT" and p["license-files"] == ["LICENSE"]
    # Each distribution is built from its own directory, so it holds a copy of the root file.
    assert (ROOT / "packages" / name / "LICENSE").read_text() == LICENSE


def test_third_party_list_matches_the_repository():
    data = {p.relative_to(ROOT).as_posix() for p in (ROOT / "packages").glob("*/tests/data/*")}
    assert data == set(THIRD_PARTY)
    root = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for path, notice in THIRD_PARTY.items():
        assert path in root, f"{path} is not in THIRD_PARTY_NOTICES.md"
        assert notice in root, f"{notice} is not in THIRD_PARTY_NOTICES.md"
        assert path.rsplit("/tests/", 1)[1] in f"tests/{(ROOT / notice).read_text()}", \
            f"{notice} does not name {path}"


@pytest.mark.parametrize("notice", sorted(set(THIRD_PARTY.values())))
def test_notice_holds_the_upstream_licence_unchanged(notice):
    # Each notice records the sha256 of the upstream licence file it quotes in a
    # ```text block; the block must be that file, byte for byte.
    text = (ROOT / notice).read_text()
    recorded = re.findall(r"sha256\s+([0-9a-f]{64})", text)
    quoted = re.findall(r"^```text\n(.*?)^```$", text, re.S | re.M)
    assert recorded and len(recorded) == len(quoted)
    assert [hashlib.sha256(q.encode()).hexdigest() for q in quoted] == recorded


# --- build backend -----------------------------------------------------------------------

def test_pinned_build_backend_satisfies_every_distribution():
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]["dev"]
    pins = [Requirement(r) for r in dev if Requirement(r).name == "hatchling"]
    assert len(pins) == 1 and len(pins[0].specifier) == 1
    (pin,) = pins[0].specifier
    assert pin.operator == "=="
    for name in PACKAGES:
        system = pyproject(name)["build-system"]
        assert system["build-backend"] == "hatchling.build"
        (req,) = map(Requirement, system["requires"])
        assert req.name == "hatchling" and Version(pin.version) in req.specifier, (name, req)


# --- version policy (README.md, "Versions") ---------------------------------------------

def next_compatibility(version: Version) -> Version:
    major, minor = version.release[:2]
    return Version(f"0.{minor + 1}") if major == 0 else Version(f"{major + 1}")


@pytest.mark.parametrize("name", PACKAGES)
def test_version_is_major_minor_patch(name):
    version = Version(project(name)["version"])
    assert str(version) == project(name)["version"] and len(version.release) == 3
    assert not (version.pre or version.post or version.dev or version.local)


def test_requires_python_is_shared():
    assert len({project(name)["requires-python"] for name in PACKAGES}) == 1


@pytest.mark.parametrize("name", PACKAGES)
def test_gnsswire_dependencies_pin_the_compatible_range(name):
    for dep, req in gnsswire_deps(name).items():
        tested = Version(project(dep)["version"])
        upper = next_compatibility(tested)
        lowers = [Version(s.version) for s in req.specifier if s.operator == ">="]
        assert len(req.specifier) == 2 and len(lowers) == 1, req
        assert req.specifier == SpecifierSet(f">={lowers[0]},<{upper}"), req
        assert lowers[0] <= tested, f"{req} excludes the workspace's {dep} {tested}"


def test_meta_distribution_installs_every_codec():
    assert sorted(gnsswire_deps(META)) == sorted(CODECS)
    assert len(project(META)["dependencies"]) == len(CODECS)   # and nothing else
    assert not (ROOT / "packages" / META / "src").exists()


RELEASE_HEADING = re.compile(r"Version \d+\.\d+\.\d+ \(\d{4}-(\d\d|XX)-(\d\d|XX)\)")


def test_release_notes_have_their_form():
    # Per release, newest first: the heading, a line of "=" as long, then
    # "* " items with "  * " sub-items; nothing else.
    lines = (ROOT / "RELEASES.md").read_text().splitlines()
    headings = [i for i, line in enumerate(lines) if line.startswith("Version ")]
    assert headings and headings[0] == 0
    for start, end in zip(headings, [*headings[1:], len(lines)]):
        heading, underline, *items = lines[start:end]
        assert RELEASE_HEADING.fullmatch(heading), heading
        assert underline == "=" * len(heading), heading
        assert items and items[0].startswith("* "), heading
        for item in items:
            assert re.fullmatch(r"(  )?\* \S.*", item), item
    versions = [Version(lines[i].split()[1]) for i in headings]
    assert versions == sorted(versions, reverse=True)


def test_release_notes_name_every_version():
    notes = (ROOT / "RELEASES.md").read_text()
    for name in PACKAGES:
        p = project(name)
        named = rf"(?<![\w-]){re.escape(p['name'])} {re.escape(p['version'])}(?![\w.])"
        assert re.search(named, notes), f"{p['name']} {p['version']}"

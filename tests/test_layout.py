"""Workspace rules that keep each codec separately installable and alike."""

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CODECS = ["nmea", "ubx", "rtcm3", "spartn", "skytraq"]
# What each package may import from the gnsswire namespace besides itself.
MAY_IMPORT = {"bits": set(), "nmea": set(), "ubx": set(), "rtcm3": {"bits"}, "spartn": {"bits"},
              "skytraq": set(), "rinex": set(), "nav": {"bits"}}
INTERFACE = {"parse": ["buf", "offset"], "scan": ["buf", "offset"],
             "decode": ["frame"], "encode": ["message"]}


def sources(package: str) -> list[Path]:
    return sorted((ROOT / "packages" / package / "src" / "gnsswire" / package).rglob("*.py"))


def test_every_package_is_listed():
    # Besides the codecs, packages/gnsswire is the distribution that installs them all.
    assert sorted(p.name for p in (ROOT / "packages").iterdir() if p.is_dir()) \
        == sorted([*MAY_IMPORT, "gnsswire"])


def test_meta_distribution_has_no_modules():
    # Its wheel must not own the shared namespace or any part of it.
    files = {p.relative_to(ROOT / "packages" / "gnsswire").as_posix()
             for p in (ROOT / "packages" / "gnsswire").rglob("*") if p.is_file()}
    assert files == {"LICENSE", "README.md", "pyproject.toml"}


@pytest.mark.parametrize("package", sorted(MAY_IMPORT))
def test_namespace_has_no_init(package):
    # An __init__.py at the gnsswire level would make one distribution own the namespace.
    assert not (ROOT / "packages" / package / "src" / "gnsswire" / "__init__.py").exists()
    assert sources(package), f"{package} has no modules"


@pytest.mark.parametrize("package", sorted(MAY_IMPORT))
def test_imports_are_stdlib_or_allowed(package):
    allowed = {package} | MAY_IMPORT[package]
    for path in sources(package):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                parts = name.split(".")
                if parts[0] == "gnsswire":
                    assert len(parts) > 1 and parts[1] in allowed, f"{path}: imports {name}"
                else:
                    assert parts[0] in sys.stdlib_module_names, f"{path}: third-party import {name}"


@pytest.mark.parametrize("codec", CODECS)
def test_codec_interface(codec):
    # Options such as ``strict`` may follow, keyword-only.
    module = importlib.import_module(f"gnsswire.{codec}")
    for name, params in INTERFACE.items():
        sig = inspect.signature(getattr(module, name)).parameters.values()
        assert [p.name for p in sig if p.kind is not p.KEYWORD_ONLY] == params, name
    for name in ("Frame", "NeedMore", "Invalid"):
        assert inspect.isclass(getattr(module, name)), name


def exceptions(module) -> list[type]:
    return [obj for name in dir(module) if inspect.isclass(obj := getattr(module, name))
            and issubclass(obj, Exception) and obj.__module__.startswith(module.__name__)]


@pytest.mark.parametrize("package", sorted(MAY_IMPORT))
def test_one_error_base_per_distribution(package):
    # README.md, "Use": every exception a codec defines derives from its
    # Error, itself a ValueError, so one except clause catches them all.
    module = importlib.import_module(f"gnsswire.{package}")
    base = getattr(module, "Error", None) if package != "bits" else module.BitError
    assert inspect.isclass(base) and issubclass(base, ValueError)
    found = exceptions(module)
    assert base in found
    assert all(issubclass(e, base) for e in found), [e for e in found if not issubclass(e, base)]


@pytest.mark.parametrize("codec", CODECS)
def test_decode_of_what_parse_returns_without_a_frame(codec):
    # decode(parse(...)) on NeedMore or Invalid is a mistake of the caller; it
    # raises the codec's NoFrame, which is its Error and a TypeError.
    module = importlib.import_module(f"gnsswire.{codec}")
    assert issubclass(module.NoFrame, module.Error) and issubclass(module.NoFrame, TypeError)
    need_more = module.parse(b"", 0)
    assert isinstance(need_more, module.NeedMore)
    invalid = module.parse(b"\x00" * 64, 0)
    assert isinstance(invalid, module.Invalid)
    for result in (need_more, invalid, None, b"\x00" * 64):
        with pytest.raises(module.NoFrame, match="Frame"):
            module.decode(result)

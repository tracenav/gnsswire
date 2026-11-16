"""Every ```python block in the READMEs runs and its assertions hold.

The blocks of one README run in order in one namespace, so a later block can
use names from an earlier one. Code that is not meant to run (signatures,
shell, TOML) goes in another fence. Each distribution's README must have at
least one example, since it is the page an index shows.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = sorted(p.name for p in (ROOT / "packages").iterdir() if p.is_dir())
FENCE = re.compile(r"^```python\n(.*?)^```$", re.S | re.M)


def blocks(path: Path) -> list[tuple[int, str]]:
    """(first line number, code) of each ```python block."""
    text = path.read_text()
    return [(text.count("\n", 0, m.start(1)) + 1, m.group(1)) for m in FENCE.finditer(text)]


READMES = [ROOT / "README.md"] + [ROOT / "packages" / p / "README.md" for p in PACKAGES]


@pytest.mark.parametrize("package", PACKAGES)
def test_distribution_readme_has_an_example(package):
    assert blocks(ROOT / "packages" / package / "README.md"), f"{package}: no ```python block"


LINK = re.compile(r"\]\(([^)#:]+)(?:#[^)]*)?\)")


def test_repository_readme_links_resolve():
    # Every document the README links to by a relative path is in the repository.
    links = LINK.findall((ROOT / "README.md").read_text())
    assert links and all((ROOT / link).is_file() for link in links), links


@pytest.mark.parametrize("readme", READMES, ids=lambda p: str(p.relative_to(ROOT)))
def test_readme_examples_run(readme):
    namespace: dict = {"__name__": "__readme__"}
    for line, code in blocks(readme):
        # Pad with newlines so a traceback names the README's own line numbers.
        exec(compile("\n" * (line - 1) + code, str(readme), "exec"), namespace)

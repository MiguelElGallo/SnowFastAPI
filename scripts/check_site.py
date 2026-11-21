"""Verify generated local links, assets and fragments at the GitHub Pages project path."""

import sys
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]
SITE = ROOT / PROJECT["site_dir"]
BASE = PROJECT["site_url"]
ORIGIN = urlsplit(BASE)


class Page(HTMLParser):
    def __init__(self, file):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.feed(file.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if anchor := fields.get("id"):
            self.ids.add(anchor)
        for attr in ("href", "src"):
            if value := fields.get(attr):
                self.links.append(value)


def main():
    pages = {f: Page(f) for f in SITE.rglob("*.html")}
    if SITE / "index.html" not in pages:
        sys.exit("Build the site before checking links.")
    errors = set()
    checked = 0
    for file, page in pages.items():
        url = urljoin(BASE, file.relative_to(SITE).as_posix())
        for link in page.links:
            target = urlsplit(urljoin(url, link))
            if target.netloc != ORIGIN.netloc or target.scheme != ORIGIN.scheme:
                continue
            if not target.path.startswith(ORIGIN.path):
                errors.add(f"{file.relative_to(SITE)}: outside project path: {link}")
                continue
            path = SITE / unquote(target.path.removeprefix(ORIGIN.path))
            if path.is_dir():
                path = path / "index.html"
            checked += 1
            if not path.is_file():
                errors.add(f"{file.relative_to(SITE)}: missing file: {link}")
            elif target.fragment and path in pages and unquote(target.fragment) not in pages[path].ids:
                errors.add(f"{file.relative_to(SITE)}: missing fragment: {link}")
    if errors:
        sys.exit("\n".join(sorted(errors)))
    print(f"Checked {checked} same-site links and assets across {len(pages)} HTML pages.")


if __name__ == "__main__":
    main()

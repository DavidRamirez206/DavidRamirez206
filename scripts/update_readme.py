"""
Refreshes the generated parts of the profile README.

Each run:
  1. Collects the languages of every repository the token can see: owned,
     collaborated on, organization repositories and repositories contributed to.
  2. Draws the languages card, the animated banner and the coffee cup.
  3. Downloads one icon per language and per tool, in dark and light variants.
  4. Downloads the GIFs listed in GIFS.
  5. Rewrites the README blocks delimited by the GIFS, LANGS, TOOLS and FUN markers.

Every image is produced twice so GitHub can serve the one that matches the
visitor's color scheme. The output depends only on the data GitHub returns, so
running it again with the same data leaves the repository unchanged.

Standard library only. Requires the METRICS_TOKEN environment variable.
"""

import base64
import functools
import json
import math
import os
import random
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- configuration

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ICONS = ROOT / "icons"
LANG_DIR = ICONS / "langs"
TOOL_DIR = ICONS / "tools"
GIF_DIR = ICONS / "gifs"

MAX_LANGS = 16        # Languages shown in the icon row.
CARD_LANGS = 8        # Languages listed in the card; the rest are grouped as "Other".
MIN_SHARE = 0.003     # Languages below this share of the total are ignored.
ICON_SIZE = 40        # Icon size in pixels.

# Simple Icons major release used for both the icons and their brand colors.
# Pinned because jsDelivr's "latest" alias serves stale files from an old
# release for icons that were removed, and only removes them on a new major.
SIMPLE_ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@16"
BRAND_MIN_CONTRAST = 3.0  # WCAG ratio a brand color needs against both icon tiles.

FONT = "'Plus Jakarta Sans','Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"

THEMES = {
    "dark": {
        "bg1": "#0B0A1A", "bg2": "#161437", "card": "#0D1117", "border": "#30363D",
        "text": "#E6EDF3", "muted": "#8B949E", "track": "#21262D",
        "a1": "#A78BFA", "a2": "#60A5FA", "a3": "#C084FC", "glow": "#7C3AED",
        "icon_bg": "#242938", "icon_fg": "#E6EDF3",
        "series": ["#A78BFA", "#818CF8", "#60A5FA", "#22D3EE", "#C084FC",
                   "#F472B6", "#2DD4BF", "#FBBF24"],
        "other": "#484F58",
    },
    "light": {
        "bg1": "#F5F3FF", "bg2": "#E0E7FF", "card": "#FFFFFF", "border": "#D0D7DE",
        "text": "#1F2328", "muted": "#57606A", "track": "#EAEEF2",
        "a1": "#6D28D9", "a2": "#2563EB", "a3": "#9333EA", "glow": "#8B5CF6",
        "icon_bg": "#F4F2ED", "icon_fg": "#1F2328",
        "series": ["#7C3AED", "#4F46E5", "#2563EB", "#0891B2", "#9333EA",
                   "#DB2777", "#0D9488", "#D97706"],
        "other": "#AFB8C1",
    },
}

# GIFs shown under the header, in order: (name, direct .gif URL, width).
# Only add GIFs you have the right to publish. Entries removed from this list
# are deleted from the repository on the next run.
GIFS: list[tuple[str, str, str]] = []

# Icon sources are tried in order until one returns a usable image:
#   skill:<id>  https://skillicons.dev
#   dev:<id>    https://devicon.dev
#   si:<slug>   https://simpleicons.org (drawn in the theme's foreground color)
#   si:<slug>:brand  the same icon in its brand color when that color has a
#               contrast ratio of at least BRAND_MIN_CONTRAST on both tiles;
#               otherwise drawn in the theme's foreground color as above
#   glyph:<id>  an original icon drawn by this script
#   file:<path> an image committed to the repository (SVG or PNG); skipped while missing.
#               "{theme}" in the path is replaced by "dark" or "light" to use a
#               separate image per theme.
# Devicon logos keep their own colors, so a logo that is black or very dark is
# taken from Simple Icons or drawn as a glyph to stay visible on the dark tile.
TOOLS: dict[str, list[tuple[str, list[str]]]] = {
    "Mobile": [
        ("Flutter", ["skill:flutter", "dev:flutter"]),
        ("Dart", ["skill:dart", "dev:dart"]),
        ("Kotlin", ["skill:kotlin", "dev:kotlin"]),
        ("Android Studio", ["skill:androidstudio", "dev:androidstudio"]),
        ("Android", ["dev:android", "si:android"]),
        ("iOS", ["si:ios", "dev:apple"]),
    ],
    "Frameworks": [
        ("Next.js", ["skill:nextjs", "dev:nextjs"]),
        ("NestJS", ["skill:nestjs", "dev:nestjs"]),
        ("Spring Boot", ["skill:spring", "dev:spring"]),
        ("Django", ["skill:django", "dev:django"]),
    ],
    "Libraries & Runtimes": [
        ("React", ["skill:react", "dev:react"]),
        ("Node.js", ["skill:nodejs", "dev:nodejs"]),
    ],
    "Architecture & Networking": [
        ("Clean Architecture", ["glyph:clean"]),
        ("SSH", ["glyph:ssh"]),
        ("Tunneling", ["glyph:tunnel"]),
        ("TCP", ["glyph:tcp"]),
        ("UDP", ["glyph:udp"]),
    ],
    "Cloud": [
        ("AWS", ["skill:aws", "dev:amazonwebservices"]),
        ("Google Cloud", ["skill:gcp", "dev:googlecloud"]),
        ("Cloudflare", ["skill:cloudflare", "dev:cloudflare"]),
    ],
    "Containers & CI/CD": [
        ("Docker", ["skill:docker", "dev:docker"]),
        ("Kubernetes", ["skill:kubernetes", "dev:kubernetes"]),
        ("Terraform", ["skill:terraform", "dev:terraform"]),
        ("Jenkins", ["skill:jenkins", "dev:jenkins"]),
        ("GitHub Actions", ["skill:githubactions", "dev:githubactions"]),
    ],
    "OS & Shell": [
        ("Linux", ["skill:linux", "dev:linux"]),
        ("Bash", ["skill:bash", "dev:bash"]),
        ("PowerShell", ["skill:powershell", "dev:powershell"]),
    ],
    "Testing & Quality": [
        ("SonarQube", ["si:sonarqubeserver:brand", "dev:sonarqube"]),
        ("Playwright", ["dev:playwright"]),
        ("Selenium", ["skill:selenium", "dev:selenium"]),
        ("Postman", ["skill:postman", "dev:postman"]),
        ("Newman", ["glyph:newman"]),
    ],
    "Security": [
        ("OWASP", ["si:owasp:brand"]),
        ("OWASP ZAP", ["si:zap:brand"]),
        ("Snort", ["glyph:snort"]),
        ("Tor", ["si:torproject:brand"]),
    ],
    "Data": [
        ("PostgreSQL", ["skill:postgres", "dev:postgresql"]),
        ("Oracle", ["glyph:oracle"]),
        ("MongoDB", ["skill:mongodb", "dev:mongodb"]),
    ],
    "Version Control & Artifacts": [
        ("Git", ["skill:git", "dev:git"]),
        ("GitHub", ["skill:github", "dev:github"]),
        ("GitLab", ["skill:gitlab", "dev:gitlab"]),
        ("Bitbucket", ["skill:bitbucket", "dev:bitbucket"]),
        ("Nexus", ["glyph:nexus"]),
    ],
    "Productivity": [
        ("Jira", ["si:jira", "dev:jira"]),
        ("IntelliJ IDEA", ["skill:idea", "dev:intellij"]),
        ("VS Code", ["skill:vscode", "dev:vscode"]),
        ("Google Colab", ["dev:googlecolab"]),
    ],
    "Exploring": [
        ("Scala", ["skill:scala", "dev:scala"]),
    ],
}

# Decorative icons for the "Side quests" section: things I enjoy, not my stack.
FUN: list[tuple[str, list[str]]] = [
    ("Coffee", ["glyph:coffee"]),
    ("Tails OS", ["si:tails", "glyph:monogram"]),
    ("Root mode", ["glyph:root"]),
    ("Anonymous", ["file:icons/custom/anonymous-{theme}.svg",
                   "file:icons/custom/anonymous.svg", "file:icons/custom/anonymous.png"]),
    ("More coffee", ["glyph:coffee"]),
]

# Explicit icon sources for GitHub language names. Languages not listed here
# are still shown: their sources are guessed from the name, and a monogram is
# drawn as the last resort.
LANG_SOURCES: dict[str, list[str]] = {
    "Java": ["skill:java"], "Python": ["skill:py"], "JavaScript": ["skill:js"],
    "TypeScript": ["skill:ts"], "HTML": ["skill:html"], "CSS": ["skill:css"],
    "SCSS": ["skill:sass"], "Sass": ["skill:sass"], "C": ["skill:c"],
    "C++": ["skill:cpp"], "C#": ["skill:cs"], "Go": ["skill:go"],
    "Rust": ["skill:rust"], "Kotlin": ["skill:kotlin"], "PHP": ["skill:php"],
    "Ruby": ["skill:ruby"], "Swift": ["skill:swift"], "Dart": ["skill:dart"],
    "Scala": ["skill:scala"], "R": ["skill:r"], "Shell": ["skill:bash"],
    "PowerShell": ["skill:powershell"], "Lua": ["skill:lua"],
    "Haskell": ["skill:haskell"], "Elixir": ["skill:elixir"],
    "Clojure": ["skill:clojure"], "Perl": ["skill:perl"], "Vue": ["skill:vue"],
    "Svelte": ["skill:svelte"], "Solidity": ["skill:solidity"],
    "Julia": ["skill:julia"], "MATLAB": ["skill:matlab"], "TeX": ["skill:latex", "dev:latex"],
    "Nix": ["skill:nix"], "OCaml": ["skill:ocaml"], "Zig": ["skill:zig"],
    "HCL": ["skill:terraform"], "Markdown": ["skill:md"],
    "Dockerfile": ["skill:docker"], "PLpgSQL": ["skill:postgres"],
    "PLSQL": ["glyph:oracle"], "GDScript": ["skill:godot"],
    "Erlang": ["skill:erlang"], "Fortran": ["skill:fortran"],
    "Jupyter Notebook": ["dev:jupyter"], "Groovy": ["glyph:groovy"],
    "Objective-C": ["dev:objectivec"], "Visual Basic .NET": ["dev:visualbasic"],
    "F#": ["dev:fsharp"], "Blade": ["skill:laravel", "dev:laravel"],
    "Makefile": ["dev:cmake"], "CMake": ["skill:cmake", "dev:cmake"],
    "Batchfile": ["glyph:monogram"],
}

IGNORE = {"Procfile", "Roff", "Rich Text Format", "Text"}

# ---------------------------------------------------------------- GitHub data

TOKEN = os.environ.get("METRICS_TOKEN") or os.environ.get("GITHUB_TOKEN")
UA = {"User-Agent": "profile-readme-updater"}


def http_get(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read() if r.status == 200 else None
    except (urllib.error.URLError, TimeoutError):
        return None


def graphql(query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={**UA, "Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    if body.get("errors"):
        # Organization policies can hide some repositories; keep the rest.
        print("GraphQL warnings:", [e.get("message") for e in body["errors"]], file=sys.stderr)
    return body.get("data") or {}


LANG_FRAGMENT = """
  nodes {
    nameWithOwner
    languages(first: 25, orderBy: {field: SIZE, direction: DESC}) {
      edges { size node { name } }
    }
  }
  pageInfo { hasNextPage endCursor }
"""

Q_OWNED = """
query($cursor: String) {
  viewer {
    repositories(first: 100, after: $cursor,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {%s}
  }
}""" % LANG_FRAGMENT

Q_CONTRIB = """
query($cursor: String) {
  viewer {
    repositoriesContributedTo(first: 100, after: $cursor, includeUserRepositories: true,
      contributionTypes: [COMMIT, PULL_REQUEST, PULL_REQUEST_REVIEW, REPOSITORY]) {%s}
  }
}""" % LANG_FRAGMENT


def collect_languages() -> tuple[dict[str, int], int]:
    """Returns the total bytes per language and the number of repositories scanned."""
    repos: dict[str, list] = {}
    for query, key in ((Q_OWNED, "repositories"), (Q_CONTRIB, "repositoriesContributedTo")):
        cursor = None
        while True:
            conn = (graphql(query, {"cursor": cursor}).get("viewer") or {}).get(key) or {}
            for repo in conn.get("nodes") or []:
                if repo:
                    repos[repo["nameWithOwner"]] = repo["languages"]["edges"]
            info = conn.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            cursor = info["endCursor"]

    totals: dict[str, int] = {}
    for edges in repos.values():
        for e in edges:
            name = e["node"]["name"]
            if name not in IGNORE:
                totals[name] = totals.get(name, 0) + e["size"]
    print(f"Scanned {len(repos)} repositories", file=sys.stderr)
    return totals, len(repos)


# ---------------------------------------------------------------- icons

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def has_shapes(data: bytes | None) -> bool:
    """skillicons answers unknown ids with an SVG that has no drawable shapes."""
    return bool(data) and b"<svg" in data[:400] and re.search(
        rb"<(path|rect|circle|ellipse|polygon|polyline|line)\b", data) is not None


def tile(inner: str, theme: str) -> bytes:
    """Rounded square in the theme's icon background, matching skillicons."""
    bg = THEMES[theme]["icon_bg"]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
        f'<rect width="256" height="256" rx="60" fill="{bg}"/>{inner}</svg>'
    ).encode()


def embed(raw: bytes, theme: str) -> bytes:
    b64 = base64.b64encode(raw).decode()
    return tile(f'<image x="48" y="48" width="160" height="160" href="data:image/svg+xml;base64,{b64}"/>', theme)


def glyph(name: str, theme: str, label: str) -> bytes:
    """Original icons for concepts that have no logo."""
    t = THEMES[theme]
    fg, a1, a2, a3 = t["icon_fg"], t["a1"], t["a2"], t["a3"]
    font = "font-family=\"Arial,Helvetica,sans-serif\" font-weight=\"800\" text-anchor=\"middle\""
    shapes = {
        "clean": (
            f'<circle cx="128" cy="128" r="84" fill="{a2}" opacity=".35"/>'
            f'<circle cx="128" cy="128" r="62" fill="{a1}" opacity=".55"/>'
            f'<circle cx="128" cy="128" r="40" fill="{a3}" opacity=".8"/>'
            f'<circle cx="128" cy="128" r="18" fill="{fg}"/>'
            f'<path d="M128 44v168M44 128h168" stroke="{t["icon_bg"]}" stroke-width="4" opacity=".6"/>'
        ),
        "ssh": (
            f'<rect x="40" y="58" width="176" height="140" rx="18" fill="none" stroke="{fg}" stroke-width="12"/>'
            f'<path d="M72 104l28 24-28 24" fill="none" stroke="{a1}" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M116 158h52" stroke="{a2}" stroke-width="14" stroke-linecap="round"/>'
        ),
        "tunnel": (
            f'<path d="M48 196V128a80 80 0 0 1 160 0v68" fill="none" stroke="{fg}" stroke-width="14" stroke-linecap="round"/>'
            f'<path d="M84 196v-68a44 44 0 0 1 88 0v68" fill="none" stroke="{a1}" stroke-width="10" stroke-linecap="round"/>'
            f'<path d="M36 196h184" stroke="{fg}" stroke-width="10" stroke-linecap="round"/>'
            f'<circle cx="128" cy="150" r="10" fill="{a2}"/>'
        ),
        "tcp": (
            f'<path d="M52 92h132m-26-24 26 24-26 24" fill="none" stroke="{a1}" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M204 136H72m26-24-26 24 26 24" fill="none" stroke="{a2}" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<text x="128" y="214" font-size="46" fill="{fg}" {font}>TCP</text>'
        ),
        "udp": (
            f'<circle cx="62" cy="104" r="12" fill="{a1}"/><circle cx="104" cy="104" r="12" fill="{a1}" opacity=".8"/>'
            f'<circle cx="146" cy="104" r="12" fill="{a2}" opacity=".7"/>'
            f'<path d="M172 80l28 24-28 24" fill="none" stroke="{a2}" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<text x="128" y="200" font-size="46" fill="{fg}" {font}>UDP</text>'
        ),
        "coffee": coffee_shapes(t),
        "root": (
            f'<rect x="40" y="80" width="176" height="128" rx="18" fill="none" stroke="{fg}" stroke-width="12"/>'
            f'<text x="92" y="168" font-size="64" fill="{a1}" {font}>#</text>'
            f'<path d="M126 166h56" stroke="{a2}" stroke-width="13" stroke-linecap="round"/>'
            f'<path d="M98 32l14 14 16-20 16 20 14-14v24H98z" fill="{a3}"/>'
        ),
        "oracle": (
            # Oracle's rounded "O" capsule; Simple Icons no longer ships the logo
            # and Devicon only has the wordmark, which is unreadable at icon size.
            '<rect x="36" y="82" width="184" height="92" rx="46" fill="none" '
            'stroke="#EA1B22" stroke-width="22"/>'
        ),
        # The next three replace logos whose only sources are a hairline drawing
        # (Snort) or carry a wordmark that is unreadable at icon size.
        "snort": (
            f'<ellipse cx="128" cy="136" rx="80" ry="58" fill="none" stroke="{fg}" stroke-width="14"/>'
            f'<ellipse cx="100" cy="136" rx="14" ry="24" fill="{a1}"/>'
            f'<ellipse cx="156" cy="136" rx="14" ry="24" fill="{a1}"/>'
        ),
        "nexus": (
            f'<path d="M128 40l76 44v88l-76 44-76-44V84z" fill="none" stroke="{fg}" stroke-width="14" stroke-linejoin="round"/>'
            f'<text x="128" y="160" font-size="84" fill="{a1}" {font}>N</text>'
        ),
        "groovy": f'<path d="{star_path(128, 134, 92, 38)}" fill="{a2}" stroke="{fg}" stroke-width="6" stroke-linejoin="round"/>',
        "newman": (
            f'<rect x="40" y="52" width="176" height="152" rx="18" fill="none" stroke="{fg}" stroke-width="12"/>'
            f'<path d="M40 90h176" stroke="{fg}" stroke-width="10"/>'
            f'<path d="M74 126l24 20-24 20" fill="none" stroke="{a1}" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M150 124l34 22-34 22z" fill="{a2}"/>'
        ),
    }
    if name in shapes:
        return tile(shapes[name], theme)
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z0-9#+]+", label))[:2] or label[:2]
    return tile(f'<text x="128" y="160" font-size="92" fill="{a1}" {font}>{esc(letters)}</text>', theme)


def star_path(cx: float, cy: float, outer: float, inner: float) -> str:
    """Five-pointed star with its top point up, as a closed path."""
    points = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        angle = math.pi / 5 * i - math.pi / 2
        points.append(f"{cx + r * math.cos(angle):.1f} {cy + r * math.sin(angle):.1f}")
    return "M" + "L".join(points) + "Z"


def coffee_shapes(t: dict) -> str:
    """A cup with rising steam; the steam loops forever."""
    steam = "".join(
        f'<path d="M{x} 104c-10-14 10-22 0-36s10-22 0-36" fill="none" stroke="{t["muted"]}" '
        f'stroke-width="9" stroke-linecap="round" opacity="0">'
        f'<animate attributeName="opacity" values="0;.85;0" dur="2.4s" begin="{d}s" repeatCount="indefinite"/>'
        f'<animateTransform attributeName="transform" type="translate" values="0 10;0 -8" dur="2.4s" begin="{d}s" repeatCount="indefinite"/></path>'
        for x, d in ((100, 0), (128, .8), (156, 1.6))
    )
    return (
        steam
        + f'<path d="M58 116h124v34a52 52 0 0 1-52 52h-20a52 52 0 0 1-52-52z" fill="{t["a1"]}"/>'
        + f'<path d="M182 128h10a24 24 0 0 1 0 48h-14" fill="none" stroke="{t["a1"]}" stroke-width="12"/>'
        + f'<path d="M50 214h150" stroke="{t["a2"]}" stroke-width="12" stroke-linecap="round"/>'
        + f'<ellipse cx="120" cy="118" rx="58" ry="8" fill="{t["a3"]}" opacity=".6"/>'
    )


def coffee_icon(theme: str) -> str:
    """Standalone coffee cup without a tile, used inline across the README."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
        f'{coffee_shapes(THEMES[theme])}</svg>'
    )


def local_file(rel: str, theme: str) -> bytes | None:
    path = ROOT / rel.replace("{theme}", theme)
    if not path.is_file():
        return None
    data = path.read_bytes()
    if path.suffix.lower() == ".svg":
        return embed(data, theme)
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(data).decode()
    return tile(f'<image x="40" y="40" width="176" height="176" href="data:{mime};base64,{b64}"/>', theme)


def relative_luminance(hex_color: str) -> float:
    """WCAG 2 relative luminance of a #RRGGBB or RRGGBB color."""
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)))
    return (lb + 0.05) / (la + 0.05)


@functools.cache
def brand_colors() -> dict[str, str]:
    """slug -> brand hex from the Simple Icons data file, downloaded once per run."""
    data = http_get(f"{SIMPLE_ICONS}/data/simple-icons.json")
    try:
        return {i["slug"]: f"#{i['hex']}" for i in json.loads(data or b"[]") if "slug" in i and "hex" in i}
    except (ValueError, TypeError, KeyError):
        return {}


def icon_color(slug_name: str, theme: str, brand: bool) -> str:
    """The brand color when it is readable on both tiles, else the theme's foreground."""
    color = brand_colors().get(slug_name) if brand else None
    if color and all(contrast(color, t["icon_bg"]) >= BRAND_MIN_CONTRAST for t in THEMES.values()):
        return color
    return THEMES[theme]["icon_fg"]


def guessed_sources(name: str) -> list[str]:
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return [f"skill:{s}", f"dev:{s}", f"si:{s}", "glyph:monogram"]


def fetch_icon(sources: list[str], theme: str, label: str) -> bytes | None:
    for source in sources:
        kind, _, ident = source.partition(":")
        if kind == "skill":
            data = http_get(f"https://skillicons.dev/icons?i={ident}&theme={theme}")
            if has_shapes(data):
                return data
        elif kind == "dev":
            for variant in ("original", "plain"):
                data = http_get(
                    f"https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/{ident}/{ident}-{variant}.svg")
                if has_shapes(data):
                    return embed(data, theme)
        elif kind == "si":
            name, _, variant = ident.partition(":")
            data = http_get(f"{SIMPLE_ICONS}/icons/{name}.svg")
            if has_shapes(data):
                color = icon_color(name, theme, variant == "brand")
                colored = data.replace(b"<svg ", f'<svg fill="{color}" '.encode(), 1)
                return embed(colored, theme)
        elif kind == "file":
            data = local_file(ident, theme)
            if data:
                return data
        elif kind == "glyph":
            return glyph(ident, theme, label)
    return None


def sync_icons(items: list[tuple[str, list[str], str]], folder: Path) -> list[tuple[str, str]]:
    """items: (name, sources, tooltip). Writes <slug>-dark.svg and <slug>-light.svg,
    removes icons that are no longer listed and returns (tooltip, base path)."""
    folder.mkdir(parents=True, exist_ok=True)
    keep, result = set(), []
    for name, sources, tooltip in items:
        base = folder / slug(name)
        complete = True
        for theme in THEMES:
            path = base.with_name(f"{base.name}-{theme}.svg")
            data = fetch_icon(sources, theme, name)
            if data:
                write_if_changed(path, data)
            # If a CDN is down, the copy from the previous run is kept.
            complete = complete and path.exists()
            keep.add(path.name)
        if complete:
            result.append((tooltip, base.relative_to(ROOT).as_posix()))
        else:
            print(f"No icon for {name}", file=sys.stderr)
    for old in folder.glob("*.svg"):
        if old.name not in keep:
            old.unlink()
    return result


def picture(base: str, label: str, size: int = ICON_SIZE) -> str:
    return (
        f'<picture><source media="(prefers-color-scheme: dark)" srcset="./{base}-dark.svg" />'
        f'<img src="./{base}-light.svg" width="{size}" height="{size}" alt="{esc(label)}" title="{esc(label)}" /></picture>'
    )


def sync_gifs() -> str:
    GIF_DIR.mkdir(parents=True, exist_ok=True)
    keep, html = set(), []
    for name, url, width in GIFS:
        path = GIF_DIR / f"{slug(name)}.gif"
        data = http_get(url)
        if data and data[:6] in (b"GIF87a", b"GIF89a"):
            write_if_changed(path, data)
        elif data:
            print(f"Skipped {name}: the URL did not return a GIF", file=sys.stderr)
        if path.exists():
            keep.add(path.name)
            html.append(f'  <img src="./{path.relative_to(ROOT).as_posix()}" width="{width}" alt="{esc(name)}" />')
        else:
            print(f"Could not download {name}", file=sys.stderr)
    for old in GIF_DIR.glob("*.gif"):
        if old.name not in keep:
            old.unlink()
    return '<p align="center">\n' + "\n".join(html) + "\n</p>" if html else ""


# ---------------------------------------------------------------- drawings

def languages_card(ranked: list[tuple[str, int]], grand: int, repos: int, theme: str) -> str:
    t = THEMES[theme]
    top = ranked[:CARD_LANGS]
    rest = grand - sum(s for _, s in top)
    rows = [(n, s / grand, t["series"][i % len(t["series"])]) for i, (n, s) in enumerate(top)]
    if rest / grand >= 0.005:
        rows.append(("Other", rest / grand, t["other"]))

    W, pad, bar_y, bar_h = 840, 32, 92, 12
    cols, row_h = 3, 30
    legend_y = bar_y + bar_h + 34
    H = legend_y + math.ceil(max(len(rows), 1) / cols) * row_h + 16
    inner = W - 2 * pad

    segs, x = [], pad
    for i, (_, share, color) in enumerate(rows):
        w = inner * share
        gap = 2 if i < len(rows) - 1 else 0
        segs.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{max(w - gap, 0.5):.1f}" height="{bar_h}" fill="{color}"/>')
        x += w

    legend, col_w = [], inner / cols
    for i, (name, share, color) in enumerate(rows):
        cx = pad + (i % cols) * col_w
        cy = legend_y + (i // cols) * row_h
        delay = 0.15 + i * 0.07
        legend.append(
            f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" begin="{delay:.2f}s" dur="0.5s" fill="freeze"/>'
            f'<circle cx="{cx + 6:.1f}" cy="{cy}" r="6" fill="{color}"/>'
            f'<text x="{cx + 20:.1f}" y="{cy + 5}" class="name">{esc(name)}</text>'
            f'<text x="{cx + col_w - 18:.1f}" y="{cy + 5}" class="pct" text-anchor="end">{share:.1%}</text></g>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<style>
  text {{ font-family: {FONT}; }}
  .title {{ font-size: 18px; font-weight: 700; fill: {t["text"]}; letter-spacing: .3px; }}
  .sub {{ font-size: 12.5px; fill: {t["muted"]}; }}
  .name {{ font-size: 14px; font-weight: 600; fill: {t["text"]}; }}
  .pct {{ font-size: 13px; fill: {t["muted"]}; font-variant-numeric: tabular-nums; }}
</style>
<defs>
  <linearGradient id="edge" x1="0" x2="1"><stop offset="0" stop-color="{t["a1"]}"/><stop offset="1" stop-color="{t["a2"]}"/></linearGradient>
  <clipPath id="bar"><rect x="{pad}" y="{bar_y}" width="0" height="{bar_h}" rx="6">
    <animate attributeName="width" from="0" to="{inner}" dur="1.1s" fill="freeze" calcMode="spline" keySplines="0.22 1 0.36 1" keyTimes="0;1"/>
  </rect></clipPath>
</defs>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" fill="{t["card"]}" stroke="{t["border"]}"/>
<rect x="{pad}" y="0.5" width="64" height="3" rx="1.5" fill="url(#edge)"/>
<text x="{pad}" y="44" class="title">Most used languages</text>
<text x="{pad}" y="66" class="sub">Across {repos} repositories · public, private and organizations</text>
<rect x="{pad}" y="{bar_y}" width="{inner}" height="{bar_h}" rx="6" fill="{t["track"]}"/>
<g clip-path="url(#bar)">{"".join(segs)}</g>
{"".join(legend)}
</svg>'''


def banner(theme: str) -> str:
    """Original animated banner: rotating energy rings, a pulsing core, flowing
    waves and drifting particles. A fixed seed keeps it identical across runs."""
    t = THEMES[theme]
    W, H, cx, cy = 1200, 240, 600, 120
    rnd = random.Random(206)

    rings = []
    for i, (r, dash, dur, color, width, op) in enumerate([
        (54, "2 10", 14, t["a1"], 2, .9),
        (78, "24 14 4 14", 22, t["a2"], 1.6, .75),
        (104, "1 7", 30, t["a3"], 2, .6),
        (132, "60 20 8 20", 40, t["a1"], 1.2, .45),
        (164, "2 16", 55, t["a2"], 1.4, .3),
    ]):
        turn = "360" if i % 2 == 0 else "-360"
        rings.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-dasharray="{dash}" stroke-linecap="round" opacity="{op}">'
            f'<animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" '
            f'to="{turn} {cx} {cy}" dur="{dur}s" repeatCount="indefinite"/></circle>'
        )

    orbits = [
        f'<circle r="{size}" fill="{color}" filter="url(#soft)">'
        f'<animateMotion dur="{dur}s" repeatCount="indefinite" '
        f'path="M {cx + r} {cy} A {r} {r} 0 1 1 {cx - r} {cy} A {r} {r} 0 1 1 {cx + r} {cy}"/></circle>'
        for r, dur, color, size in [(78, 6, t["a2"], 3.5), (104, 9, t["a3"], 3), (132, 13, t["a1"], 2.5)]
    ]

    waves = []
    for i, (amp, y0, dur, op) in enumerate([(18, cy, 7, .55), (26, cy + 6, 9, .4), (12, cy - 8, 5.5, .35)]):
        pts = " ".join(
            f"{x},{y0 + amp * math.sin((x / W) * math.pi * (3 + i) + i):.1f}" for x in range(0, W + 1, 20))
        waves.append(
            f'<polyline points="{pts}" fill="none" stroke="url(#fade)" stroke-width="1.6" opacity="{op}" '
            f'stroke-dasharray="6 10"><animate attributeName="stroke-dashoffset" from="0" '
            f'to="{-160 if i % 2 else 160}" dur="{dur}s" repeatCount="indefinite"/></polyline>'
        )

    particles = []
    for _ in range(46):
        x, y = rnd.uniform(20, W - 20), rnd.uniform(H * .35, H - 10)
        rise, dur, begin = rnd.uniform(40, 110), rnd.uniform(4, 9), rnd.uniform(0, 6)
        size, color = rnd.uniform(.8, 2.4), rnd.choice([t["a1"], t["a2"], t["a3"]])
        particles.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{size:.1f}" fill="{color}" opacity="0">'
            f'<animate attributeName="cy" from="{y:.0f}" to="{y - rise:.0f}" dur="{dur:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0;.9;0" dur="{dur:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite"/></circle>'
        )

    center = "#FFFFFF" if theme == "dark" else t["card"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{t["bg1"]}"/><stop offset="1" stop-color="{t["bg2"]}"/>
  </linearGradient>
  <radialGradient id="core" cx="50%" cy="50%" r="50%">
    <stop offset="0" stop-color="{t["a3"]}" stop-opacity=".95"/>
    <stop offset=".45" stop-color="{t["glow"]}" stop-opacity=".55"/>
    <stop offset="1" stop-color="{t["glow"]}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="fade" x1="0" x2="1">
    <stop offset="0" stop-color="{t["a1"]}" stop-opacity="0"/>
    <stop offset=".5" stop-color="{t["a1"]}"/>
    <stop offset="1" stop-color="{t["a2"]}" stop-opacity="0"/>
  </linearGradient>
  <filter id="soft" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="1.6"/></filter>
  <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="18"/></filter>
  <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">
    <circle cx="1" cy="1" r="1" fill="{t["muted"]}" opacity=".18"/>
  </pattern>
  <clipPath id="frame"><rect width="{W}" height="{H}" rx="20"/></clipPath>
</defs>
<g clip-path="url(#frame)">
  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <rect width="{W}" height="{H}" fill="url(#dots)"/>
  {"".join(waves)}
  <circle cx="{cx}" cy="{cy}" r="120" fill="url(#core)" filter="url(#blur)" opacity=".7">
    <animate attributeName="r" values="105;135;105" dur="5s" repeatCount="indefinite"/>
  </circle>
  {"".join(rings)}
  <circle cx="{cx}" cy="{cy}" r="26" fill="url(#core)">
    <animate attributeName="r" values="22;32;22" dur="3s" repeatCount="indefinite"/>
  </circle>
  <circle cx="{cx}" cy="{cy}" r="6" fill="{center}" opacity=".9"/>
  {"".join(orbits)}
  {"".join(particles)}
</g>
</svg>'''


# ---------------------------------------------------------------- README

def replace_block(text: str, name: str, content: str) -> str:
    pattern = re.compile(rf"(<!-- {name}:START -->)(.*?)(<!-- {name}:END -->)", re.S)
    if not pattern.search(text):
        sys.exit(f"README is missing the <!-- {name}:START --> / <!-- {name}:END --> markers")
    body = f"\n{content}\n" if content else "\n"
    return pattern.sub(lambda m: f"{m.group(1)}{body}{m.group(3)}", text)


def langs_block(icons: list[tuple[str, str]]) -> str:
    card = (
        '<p align="center">\n  <picture>\n'
        '    <source media="(prefers-color-scheme: dark)" srcset="./icons/languages-dark.svg" />\n'
        '    <img src="./icons/languages-light.svg" width="100%" alt="Most used languages" />\n'
        "  </picture>\n</p>"
    )
    row = "\n".join(f"  {picture(p, label)}" for label, p in icons)
    return f'{card}\n\n<p align="center">\n{row}\n</p>'


def tools_block(groups: dict[str, list[tuple[str, str]]]) -> str:
    rows = [
        f'  <tr>\n    <td align="right"><b>{esc(group)}</b></td>\n'
        f'    <td>{" ".join(picture(p, label) for label, p in icons)}</td>\n  </tr>'
        for group, icons in groups.items() if icons
    ]
    return '<table align="center">\n' + "\n".join(rows) + "\n</table>"


def fun_block(icons: list[tuple[str, str]]) -> str:
    row = " ".join(picture(p, label, 48) for label, p in icons)
    return f'<p align="center">\n  {row}\n</p>'


def write_if_changed(path: Path, content: str | bytes) -> None:
    data = content.encode("utf-8") if isinstance(content, str) else content
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


# ---------------------------------------------------------------- main

def main() -> None:
    if not TOKEN:
        sys.exit("METRICS_TOKEN is not set")

    totals, repo_count = collect_languages()
    grand = sum(totals.values()) or 1
    ranked = sorted(
        ((n, s) for n, s in totals.items() if s / grand >= MIN_SHARE),
        key=lambda kv: (-kv[1], kv[0]),
    )

    ICONS.mkdir(exist_ok=True)
    for theme in THEMES:
        write_if_changed(ICONS / f"languages-{theme}.svg", languages_card(ranked, grand, repo_count, theme))
        write_if_changed(ICONS / f"banner-{theme}.svg", banner(theme))
        write_if_changed(ICONS / f"coffee-{theme}.svg", coffee_icon(theme))

    lang_icons = sync_icons(
        [(n, LANG_SOURCES.get(n, guessed_sources(n)), f"{n} · {s / grand:.1%}") for n, s in ranked[:MAX_LANGS]],
        LANG_DIR,
    )

    flat = [(label, sources, label) for items in TOOLS.values() for label, sources in items]
    synced = dict(sync_icons(flat, TOOL_DIR))
    groups = {g: [(label, synced[label]) for label, _ in items if label in synced] for g, items in TOOLS.items()}

    fun = sync_icons([(label, sources, label) for label, sources in FUN], ICONS / "fun")

    text = README.read_text(encoding="utf-8")
    text = replace_block(text, "GIFS", sync_gifs())
    text = replace_block(text, "LANGS", langs_block(lang_icons))
    text = replace_block(text, "TOOLS", tools_block(groups))
    text = replace_block(text, "FUN", fun_block(fun))
    write_if_changed(README, text)

    print("Languages:", ", ".join(f"{n} {s / grand:.1%}" for n, s in ranked), file=sys.stderr)


if __name__ == "__main__":
    main()

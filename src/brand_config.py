from dataclasses import dataclass, field
from pathlib import Path

import yaml

from config import BRANDS_DIR


@dataclass
class Market:
    name: str
    notes: str = ""


@dataclass
class BrandConfig:
    slug: str
    name: str
    voice: str
    target_audience: str
    usps: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    competitors: list[dict] = field(default_factory=list)
    markets: list[Market] = field(default_factory=list)
    blog_base_url: str = ""

    @property
    def docs_file(self) -> str:
        return str(Path(BRANDS_DIR) / self.slug / "docs.md")

    @property
    def links_file(self) -> str:
        return str(Path(BRANDS_DIR) / self.slug / "links.yaml")


def list_brands() -> list[str]:
    """Return every brand slug that has a profile.yaml under brands/."""
    if not Path(BRANDS_DIR).is_dir():
        return []
    return sorted(
        p.parent.name for p in Path(BRANDS_DIR).glob("*/profile.yaml")
    )


def get_brand_config(slug: str) -> BrandConfig:
    profile_path = Path(BRANDS_DIR) / slug / "profile.yaml"
    if not profile_path.exists():
        available = list_brands()
        hint = f" Available: {', '.join(available)}" if available else " No brands configured yet — run: python main.py init-brand <slug>"
        raise ValueError(f"Unknown brand: {slug!r}.{hint}")

    with open(profile_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    markets = [Market(**m) if isinstance(m, dict) else Market(name=m) for m in data.get("markets", [])]

    return BrandConfig(
        slug=slug,
        name=data.get("name", slug),
        voice=data.get("voice", "Clear, direct, and helpful."),
        target_audience=data.get("target_audience", ""),
        usps=data.get("usps", []),
        avoid=data.get("avoid", []),
        competitors=data.get("competitors", []),
        markets=markets,
        blog_base_url=data.get("blog_base_url", ""),
    )


_TEMPLATE_PROFILE = """\
name: "{name}"

# How this brand should sound. Be specific — this drives every generated post's tone.
voice: >
  Clear, direct, and helpful. Speaks as a knowledgeable peer, not a salesperson.

# Who the content is written for.
target_audience: >
  Describe the reader: their role, their problem, what they're trying to decide.

# Key selling points to weave in naturally — not a features dump.
usps:
  - "Replace with a real differentiator"
  - "Add another"

# Things generated content must never say (inaccurate claims, banned phrases, etc.)
avoid:
  - "Fabricated statistics or testimonials"
  - "Overhyped marketing language (\\"revolutionary\\", \\"game-changing\\")"

# Optional — named competitors, used for fair \\"best for X\\" style comparisons.
competitors: []
#  - name: "Competitor Inc"
#    notes: "Positioning, what they're strong/weak at"

# Optional — target markets/regions. Leave empty for a single, unspecified market.
markets: []
#  - name: "Singapore"
#    notes: "Local terms, currency, or context to reference"

# Optional — base URL of this brand's blog, used to validate internal links.
blog_base_url: ""
"""

_TEMPLATE_DOCS = """\
# {name} — Knowledge Base

Add whatever product/service facts, pricing, policies, or positioning the
generator should treat as ground truth. Content here is pulled into the
generation prompt automatically, matched to each post's keyword.

Use `## Headings` to break this into topics — the generator scores and
pulls in only the sections relevant to each post's keyword.
"""


def scaffold_brand(slug: str, name: str = None) -> Path:
    """Create a new brand folder with starter profile.yaml + docs.md. Returns the folder path."""
    brand_dir = Path(BRANDS_DIR) / slug
    if brand_dir.exists():
        raise FileExistsError(f"Brand '{slug}' already exists at {brand_dir}")
    brand_dir.mkdir(parents=True)
    display_name = name or slug.replace("-", " ").replace("_", " ").title()
    (brand_dir / "profile.yaml").write_text(_TEMPLATE_PROFILE.format(name=display_name), encoding="utf-8")
    (brand_dir / "docs.md").write_text(_TEMPLATE_DOCS.format(name=display_name), encoding="utf-8")
    return brand_dir

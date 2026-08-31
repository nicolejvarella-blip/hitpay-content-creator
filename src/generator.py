import json
import re
import time
from datetime import date
from pathlib import Path

import yaml
from slugify import slugify

from config import OPENROUTER_MODEL
from src.brand_config import BrandConfig, Market, get_brand_config
from src.llm_client import APIStatusError, OpenRouterClient

_NON_RETRYABLE_STATUS_CODES = (400, 401, 403, 404, 422)


def _messages_create_with_retry(client, max_retries=4, **kwargs):
    """Call client.messages.stream with exponential backoff on transient errors.

    Uses streaming to avoid long-generation timeouts. Returns the same shape
    as messages.create() so callers are unchanged.
    """
    for attempt in range(max_retries):
        try:
            with client.messages.stream(**kwargs) as stream:
                return stream.get_final_message()
        except APIStatusError as e:
            if e.status_code in _NON_RETRYABLE_STATUS_CODES or attempt >= max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
        except Exception:
            if attempt >= max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def _load_relevant_docs(docs_path: str, keyword: str, max_chars: int = 30000) -> str:
    """Pull sections from a brand's docs.md that are relevant to the keyword."""
    path = Path(docs_path)
    if not path.exists():
        return ""

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    raw_sections = re.split(r'\n(?=## )', content)
    terms = [t.lower() for t in re.split(r'\W+', keyword) if len(t) > 2]
    scored = []
    for section in raw_sections:
        text_lower = section.lower()
        score = sum(text_lower.count(t) for t in terms)
        if score > 0:
            scored.append((score, section))

    scored.sort(key=lambda x: x[0], reverse=True)

    parts = []
    total = 0
    for _, section in scored:
        if total + len(section) > max_chars:
            break
        parts.append(section.strip())
        total += len(section)

    return "\n\n---\n\n".join(parts) if parts else ""


def _load_blog_links(links_path: str) -> list[dict]:
    """Load internal blog links from a brand's links.yaml, if it exists."""
    path = Path(links_path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("posts", []) if data else []


def _validate_internal_links(content: str, blog_links: list[dict], blog_base_url: str) -> list[str]:
    """Flag any link to the brand's own domain that isn't in the known-good list."""
    if not blog_base_url:
        return []
    import httpx

    escaped = re.escape(blog_base_url)
    found = re.findall(rf"{escaped}/[^\s\)\]\"']+", content)
    if not found:
        return []

    known_urls = {link["url"].rstrip("/") for link in blog_links}
    warnings = []
    for url in found:
        clean = url.rstrip(".,)/")
        if clean not in known_urls:
            warnings.append(f"Internal link not in approved list (possible hallucination): {clean}")
            continue
        try:
            r = httpx.head(clean, follow_redirects=True, timeout=6)
            if r.status_code == 404:
                warnings.append(f"Internal link returns 404: {clean}")
        except Exception:
            pass
    return warnings


def _build_system_prompt(brand: BrandConfig) -> str:
    usps = "\n".join(f"- {u}" for u in brand.usps) or "- (none listed — add USPs to brands/{}/profile.yaml)".format(brand.slug)
    avoid = "\n".join(f"- {a}" for a in brand.avoid) or "- Fabricated statistics, testimonials, or claims not grounded in the knowledge base"

    competitor_section = ""
    if brand.competitors:
        comp_lines = "\n".join(
            f"- **{c.get('name', 'Unknown')}**: {c.get('notes', '')}" for c in brand.competitors
        )
        competitor_section = f"""
## Competitor Comparisons
When the post compares {brand.name} against a competitor, follow these rules:
1. Never disparage a competitor — no claims they're bad, overpriced, or untrustworthy.
2. Where relevant, give each competitor a "Best for:" line that is factually true but narrow
   enough that most readers self-select toward {brand.name} without any negative framing.
3. {brand.name}'s "Best for:" line should be broad and inclusive — the clear default choice.

Known competitors:
{comp_lines}
"""

    return f"""You are a senior content strategist and writer for {brand.name}. Your job is to produce authoritative, fact-grounded content that genuinely helps the reader — not marketing copy.

## Brand Voice
{brand.voice}

## Target Audience
{brand.target_audience or "Not specified — write for an informed, time-pressed professional."}

## Key Differentiators (weave in naturally, don't list them as features)
{usps}

## Always Avoid
{avoid}
{competitor_section}
## Writing Philosophy
- Lead with the reader's problem and factual context, not the brand's features
- Bring real, concrete detail — specific numbers, scenarios, or examples beat generic claims
- Never use hollow marketing language: "seamlessly", "unlock", "revolutionize", "game-changer", "cutting-edge"
- Short sentences, active voice, confident and declarative
- Explain any acronym or jargon on first use, then use the short form
- Keep paragraphs tight — 2–4 sentences max

## SEO Structure
- One H1 (the title) — do NOT include it in the `content` field, it's added separately
- 3–6 H2 sections with genuinely useful, specific content
- Primary keyword in the title, first 100 words, one H2, and the meta description
- Natural keyword variants throughout — never repeat the exact phrase more than 3 times
- Tables or lists wherever comparison or enumeration is the clearest format

## AEO Optimisation (Answer Engine Optimisation — apply to every article)
1. **Quick Answer block (REQUIRED, always first)** — the very first element, before any intro prose:
   `**Quick Answer:** [2–3 sentences that directly and completely answer the article's primary query, self-contained enough that an AI engine could quote it alone as the full answer.]`
2. **H2/H3 as questions** — phrase headings the way a person would actually type or ask them.
   ✅ "How does X affect Y for small teams?"  ❌ "Overview of X"
3. **FAQ section (REQUIRED)** — close with `## Frequently Asked Questions`, at least 5 Q&A pairs:
   - Each answer opens with the direct answer (yes/no or the fact itself), then elaborates in 2–4 sentences
   - Format exactly as:
     ```
     **Q: Question phrased as a user would type it?**
     Answer text here.
     ```
   - Each answer must stand alone — an AI engine may extract it without the question.
4. **Numbered lists for any process or step-by-step flow** — never describe steps in prose.
5. **At least one structured comparison** (table or clear side-by-side) where the topic allows one.
6. Every factual claim needs a specific, extractable detail (a number, timeframe, or named entity) —
   vague claims ("fast", "easy", "affordable") are not citable and should be avoided.
7. Do not open any sentence or FAQ answer with "I" or "We". Avoid rhetorical questions in body copy.

### Schema block (REQUIRED at the very end of `content`)
List which schema types apply, exactly as:
```
[SCHEMA: FAQPage, HowTo]
```
`FAQPage` always applies. Add `HowTo` if there's a step-by-step process. Add `Product` or
`SoftwareApplication` only if a specific product/tool is described in detail.

## Output
Return ONLY a valid JSON object with exactly these fields (no markdown code fences, no extra text):
{{
  "title": "Compelling title under 65 chars — keyword-rich but human",
  "meta_title": "SEO title tag 55–60 chars",
  "meta_description": "150–160 char description naming the core value prop",
  "overview": "2–3 sentence executive summary. State the problem and what the reader will learn.",
  "slug": "url-friendly-slug-here",
  "categories": ["Primary Category", "Secondary Category"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "content": "Full markdown: (1) Quick Answer block first; (2) intro; (3) H2/H3 as questions; (4) FAQ section with 5+ Q&A pairs; (5) [SCHEMA] block. No H1. 900-1200 words excluding FAQ."
}}
"""


def _build_market_section(market: Market | None) -> str:
    if not market:
        return ""
    notes = f"\nContext to use: {market.notes}\n" if market.notes else ""
    return f"""
## Market Focus: {market.name} — STRICT REQUIREMENT
This post must be written specifically for the {market.name} market. Use local
terminology, currency, and references appropriate to {market.name} throughout.
{notes}"""


def _build_internal_links_section(brand: BrandConfig, blog_links: list[dict], market: Market | None) -> str:
    if not blog_links:
        return ""
    lines = [f"\n## {brand.name} URLs — Use 2-3 as Internal Backlinks if Genuinely Relevant"]
    lines.append("Link naturally in-content — never force a link or dump as a list. Skip if none fit.\n")
    for link in blog_links:
        topics_str = ", ".join(link.get("topics", []))
        lines.append(f"- [{link['title']}]({link['url']}) — {topics_str}")
    return "\n".join(lines)


def generate_blog_post(
    keyword: str,
    brand: str,
    market: str = None,
    aeo_prompt: str = None,
    category: str = None,
    max_tokens: int = 16000,
    on_status=None,
    source_material: str = None,
    model: str = None,
) -> dict:
    """Generate a blog post for the given keyword under the given brand.

    Args:
        keyword: The topic/keyword to write about
        brand: Brand slug (must exist under brands/<slug>/profile.yaml)
        market: Optional market name (must match one configured in the brand's profile)
        aeo_prompt: Optional primary AEO question the post must answer
        category: Optional preferred category hint
        max_tokens: Claude response token limit
        on_status: Optional callback(message: str) for progress updates
        source_material: Optional raw source doc (brief, PRD, press release) to ground the post in
        model: Optional OpenRouter model slug override
    """
    def status(msg):
        if on_status:
            on_status(msg)

    brand_config = get_brand_config(brand)

    market_obj = None
    if market:
        market_obj = next((m for m in brand_config.markets if m.name.lower() == market.lower()), None)
        if not market_obj:
            market_obj = Market(name=market)

    status("Loading brand knowledge base...")
    product_docs = _load_relevant_docs(brand_config.docs_file, keyword)
    if product_docs:
        status("Found relevant sections in brand docs")

    blog_links = _load_blog_links(brand_config.links_file)

    system_prompt = _build_system_prompt(brand_config)
    resolved_model = model or OPENROUTER_MODEL
    status(f"Generating post with {resolved_model}...")
    client = OpenRouterClient()

    docs_section = f"\n## {brand_config.name} Knowledge Base — Use for Factual Accuracy\n{product_docs}\n" if product_docs else ""
    market_section = _build_market_section(market_obj)
    links_section = _build_internal_links_section(brand_config, blog_links, market_obj)

    aeo_line = f'\nPrimary AEO question this post must answer: "{aeo_prompt}"\n' if aeo_prompt else ""
    category_line = f'\nPreferred category for this post: {category}\n' if category else ""

    launch_section = ""
    if source_material:
        launch_section = f"""
## SOURCE MATERIAL — GROUND THE POST IN THIS
Treat this as the authoritative source for facts, features, or claims in this post.
Do NOT invent details not present here or in the knowledge base below. Strip any
internal-only notes (team instructions, pricing rationale, etc.) — write only
customer-facing content.

SOURCE MATERIAL:
\"\"\"
{source_material}
\"\"\"
"""

    user_prompt = f"""Write a blog post about: "{keyword}"
{aeo_line}{category_line}{launch_section}{market_section}
{docs_section}
{links_section}
Ground your post in the knowledge base above where it applies. Do not invent facts, statistics,
or specifics not present in these sources.

OUTPUT LENGTH: The content field must be 900-1200 words (body only, excluding FAQ). Each FAQ
answer is 2-4 sentences. Be concise and factual rather than padded.

Return the JSON object now."""

    response = _messages_create_with_retry(
        client,
        model=resolved_model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if response.stop_reason == "max_tokens":
        raise ValueError(f"Response hit the max_tokens limit ({max_tokens}). Increase max_tokens and retry.")

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()

    try:
        post_data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            post_data = json.loads(repair_json(raw))
        except Exception as e:
            raise ValueError(f"Response could not be parsed after repair attempt. JSON error: {e}")

    post_data["date"] = date.today().isoformat()
    post_data["keyword"] = keyword
    post_data["country"] = market or ""
    post_data["status"] = "generated"
    post_data["brand"] = brand
    post_data["model"] = resolved_model

    if not post_data.get("slug"):
        post_data["slug"] = slugify(post_data["title"])
    else:
        post_data["slug"] = slugify(post_data["slug"])

    link_warnings = _validate_internal_links(post_data.get("content", ""), blog_links, brand_config.blog_base_url)
    if link_warnings:
        post_data["link_warnings"] = link_warnings
        status(f"Link warnings: {len(link_warnings)} issue(s) found")

    return post_data


def _scrape_url(url: str) -> dict:
    """Fetch a page and return {title, keyword, content} as plain text."""
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(url, timeout=20, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ContentCreator/1.0)"
    })
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    title = ""
    for sel in ["h1", "article h2", ".post-title", ".entry-title", "title"]:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break

    body_el = soup.select_one("article") or soup.select_one("main") or soup.body
    content = body_el.get_text(separator="\n", strip=True) if body_el else soup.get_text(separator="\n", strip=True)
    keyword = title or url.split("/")[-1].replace("-", " ").strip()

    return {"title": title, "keyword": keyword, "content": content}


def rewrite_blog_post(url: str, brand: str, market: str = None, on_status=None) -> dict:
    """Scrape an existing blog post URL and rewrite it with full AEO/SEO optimisation."""
    def status(msg):
        if on_status:
            on_status(msg)

    brand_config = get_brand_config(brand)

    market_obj = None
    if market:
        market_obj = next((m for m in brand_config.markets if m.name.lower() == market.lower()), None)
        if not market_obj:
            market_obj = Market(name=market)

    status("Fetching existing post...")
    scraped = _scrape_url(url)
    keyword = scraped["keyword"]
    existing_title = scraped["title"]
    existing_content = scraped["content"]
    status(f'Fetched: "{existing_title}"')

    product_docs = _load_relevant_docs(brand_config.docs_file, keyword)
    blog_links = _load_blog_links(brand_config.links_file)

    system_prompt = _build_system_prompt(brand_config)
    status("Rewriting with Claude...")
    client = OpenRouterClient()

    docs_section = f"\n## {brand_config.name} Knowledge Base — Use for Factual Accuracy\n{product_docs}\n" if product_docs else ""
    market_section = _build_market_section(market_obj)
    links_section = _build_internal_links_section(brand_config, blog_links, market_obj)

    user_prompt = f"""You are rewriting an existing blog post. Produce a significantly improved
version using every directive in the system prompt (AEO structure, voice, backlinks, etc.).

## Existing Article
URL: {url}
Title: {existing_title}

--- EXISTING CONTENT START ---
{existing_content[:6000]}
--- EXISTING CONTENT END ---

Keep the same core topic and keyword focus: "{keyword}"
Preserve any accurate facts or useful examples from the original. Remove outdated
information and anything that violates the system prompt rules.
{market_section}
{docs_section}
{links_section}
OUTPUT LENGTH: The content field must be 900-1200 words (body only, excluding FAQ).

Return the JSON object now."""

    response = _messages_create_with_retry(
        client,
        model=OPENROUTER_MODEL,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if response.stop_reason == "max_tokens":
        raise ValueError("Response hit the max_tokens limit. Increase max_tokens and retry.")

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()

    try:
        post_data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            post_data = json.loads(repair_json(raw))
        except Exception as e:
            raise ValueError(f"Response could not be parsed after repair attempt. JSON error: {e}")

    post_data["date"] = date.today().isoformat()
    post_data["keyword"] = keyword
    post_data["country"] = market or ""
    post_data["status"] = "generated"
    post_data["brand"] = brand
    post_data["source_url"] = url

    if not post_data.get("slug"):
        post_data["slug"] = slugify(post_data["title"])
    else:
        post_data["slug"] = slugify(post_data["slug"])

    link_warnings = _validate_internal_links(post_data.get("content", ""), blog_links, brand_config.blog_base_url)
    if link_warnings:
        post_data["link_warnings"] = link_warnings
        status(f"Link warnings: {len(link_warnings)} issue(s) found")

    return post_data

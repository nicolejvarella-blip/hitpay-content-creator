# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Commands

```bash
python main.py init-brand SLUG --name "Display Name"   # scaffold brands/SLUG/
python main.py generate "keyword" --brand SLUG          # generate a blog post
python main.py rewrite URL --brand SLUG                 # rewrite an existing post
python main.py list --brand SLUG --status writing        # list posts
python main.py export --all                              # export for Framer CMS
```

## Architecture

CLI only (Click, `main.py` → `src/cli.py`). No web server, no OAuth, no
hosted database — this was descoped from the original HitPay-specific
version to run entirely locally.

**Generation pipeline** (`src/generator.py`):
1. Loads the target brand's profile (`src/brand_config.py` reads
   `brands/<slug>/profile.yaml`) — voice, target audience, USPs, competitors,
   markets
2. Pulls keyword-relevant sections from `brands/<slug>/docs.md`
3. Optionally pulls internal backlinks from `brands/<slug>/links.yaml`
4. Builds one generic AEO/SEO system prompt (`_build_system_prompt`) —
   Quick Answer block, question-phrased H2/H3, FAQ, schema block — driven
   entirely by the brand profile fields, not hardcoded brand facts
5. Calls Claude via OpenRouter (`src/llm_client.py` — shaped like the
   Anthropic Messages API so call sites read like they're calling Anthropic
   directly) with streaming + exponential backoff retry
6. Returns a structured dict: title, slug, meta_title, meta_description,
   content, categories, tags

**Post lifecycle**: `writing` → `ready_to_publish` → `published` — file-based
in `posts/{status}/`, tracked in local SQLite (`src/database.py`, one
`content.db` file, `brand` column separates brands).

**Key modules**:
- `src/generator.py` — prompt construction + Claude API call
- `src/brand_config.py` — loads/scaffolds brand profiles from `brands/`
- `src/llm_client.py` — OpenRouter client shaped like the Anthropic SDK
- `src/database.py` — SQLite post tracking
- `src/post_writer.py` — markdown file I/O + Framer CMS CSV export/import
- `config.py` — env vars and paths

## Multi-brand

Every brand is a folder under `brands/<slug>/` with `profile.yaml` (voice,
audience, USPs, avoid-list, competitors, markets) and `docs.md` (freeform
facts, split into `## Headings` — the generator keyword-matches sections
into the prompt). `python main.py init-brand <slug>` scaffolds both files.
There is no hardcoded brand anywhere in the generation code — everything
brand-specific lives under `brands/`.

## What was removed from the original HitPay version

This started as a fork of a HitPay-internal tool. Removed: the FastAPI web
UI + Google OAuth (`api.py`, `static/`), Supabase/Postgres, GA4 analytics,
the HitPay knowledge MCP integration, live competitor/blog scraping infra,
and social-repurposing to X/Threads/LinkedIn/Reddit/YouTube. All of that was
tightly coupled to HitPay's own infrastructure and payment-industry content;
none of it is brand-agnostic. If a future need justifies rebuilding any of
it generically, treat it as new work rather than resurrecting the old code.

# content-creator

A CLI tool that generates SEO- and AEO-optimized blog posts for one or more
brands, using Claude (via OpenRouter). Every post gets a mandatory "Quick
Answer" block, question-phrased headings, an FAQ section, and a schema block
— structured so both search engines and AI answer engines can cite it.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENROUTER_API_KEY
```

Get a key at https://openrouter.ai/settings/keys (add a few dollars of
credit at https://openrouter.ai/settings/credits — generation is
pay-per-use).

## Quick start

```bash
python main.py init-brand acme --name "Acme Co"   # scaffolds brands/acme/
# edit brands/acme/profile.yaml (voice, audience, USPs) and docs.md (facts)

python main.py generate "how to price a saas product" --brand acme
python main.py list --brand acme
python main.py view 1
python main.py export --all
```

## Commands

```bash
python main.py init-brand SLUG [--name "Display Name"]   # scaffold a new brand
python main.py brands                                     # list configured brands
python main.py generate KEYWORD --brand SLUG [--market M] [--source FILE] [--model SLUG]
python main.py rewrite URL --brand SLUG [--market M]      # rewrite an existing post
python main.py list [--status writing|ready_to_publish|published] [--brand SLUG]
python main.py view POST_ID
python main.py edit POST_ID [--field FIELD] [--editor]
python main.py status POST_ID STATUS
python main.py export POST_ID | --all [--status ...] [--brand ...]
python main.py delete POST_ID
```

## Multi-brand

Each brand lives under `brands/<slug>/`:

```
brands/acme/
  profile.yaml   # voice, target audience, USPs, competitors, markets
  docs.md        # product/service facts — keyword-matched into every generation
  links.yaml     # optional — internal blog links for backlinking
```

Posts from every brand share one local SQLite database (`content.db`) and are
tagged by brand, so `list`/`export` can filter across or within brands.

## Storage

- Posts are markdown files in `posts/{writing,ready_to_publish,published}/`
- Metadata is tracked in `content.db` (SQLite, local file, gitignored)
- `export --all` produces a Framer CMS-ready CSV

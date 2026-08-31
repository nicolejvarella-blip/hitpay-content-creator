import click
import json
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm

from src.generator import generate_blog_post, rewrite_blog_post
from src.brand_config import list_brands, scaffold_brand
from src.database import (
    init_db, save_post, get_post, list_posts,
    update_post_status, update_post_fields, delete_post, get_post_by_slug
)
from src.post_writer import (
    write_post_file, move_post_file, read_post_content,
    read_full_post_file, update_post_file, export_to_csv
)
from config import POSTS_DIR, EDITOR

console = Console()

STATUS_COLORS = {
    "writing": "yellow",
    "ready_to_publish": "bright_blue",
    "published": "green",
}
STATUS_ICONS = {
    "writing": "✏️",
    "ready_to_publish": "🔵",
    "published": "✅",
}
VALID_STATUSES = ["writing", "ready_to_publish", "published"]
EDITABLE_FIELDS = ["title", "meta_title", "meta_description", "overview", "categories", "tags", "slug"]


def _require_brand(brand):
    if brand:
        return brand
    brands = list_brands()
    if len(brands) == 1:
        return brands[0]
    if not brands:
        console.print("[red]No brands configured yet.[/] Run [cyan]python main.py init-brand <slug>[/] first.")
        raise click.Abort()
    console.print(f"[red]Multiple brands configured — pass --brand.[/] Available: {', '.join(brands)}")
    raise click.Abort()


@click.group()
@click.version_option("2.0.0", prog_name="content-creator")
def cli():
    """SEO/AEO Content Creator\n\nGenerate, manage, and export brand blog content."""
    init_db()
    for d in ["writing", "ready_to_publish", "published", "exports"]:
        Path(POSTS_DIR, d).mkdir(parents=True, exist_ok=True)


@cli.command("init-brand")
@click.argument("slug")
@click.option("--name", help="Display name for the brand (defaults to a title-cased version of the slug).")
def init_brand(slug, name):
    """Scaffold a new brand profile under brands/<slug>/."""
    try:
        brand_dir = scaffold_brand(slug, name)
    except FileExistsError as e:
        console.print(f"[red]{e}[/]")
        raise click.Abort()
    console.print(f"\n[green]✓ Created brand '{slug}'[/] at {brand_dir}")
    console.print(f"  Edit [cyan]{brand_dir}/profile.yaml[/] (voice, audience, USPs) and [cyan]{brand_dir}/docs.md[/] (facts) before generating.\n")


@cli.command("brands")
def brands_cmd():
    """List configured brands."""
    brands = list_brands()
    if not brands:
        console.print("\n[yellow]No brands configured yet.[/] Run [cyan]python main.py init-brand <slug>[/] to create one.\n")
        return
    console.print("\n[bold]Configured brands:[/]")
    for b in brands:
        console.print(f"  [cyan]{b}[/]")
    console.print()


@cli.command()
@click.argument("keyword")
@click.option("--brand", "-b", help="Brand slug (required if more than one brand is configured).")
@click.option("--market", "-m", help="Target market name, if the brand profile defines one.")
@click.option("--source", "source_file", type=click.Path(exists=True), help="Path to a source doc (brief, PRD, press release) to ground the post in.")
@click.option("--model", help="Override the OpenRouter model slug for this generation.")
def generate(keyword, brand, market, source_file, model):
    """Generate a new blog post for KEYWORD.\n\nExample: content-creator generate "how to price a saas product" --brand acme"""
    brand = _require_brand(brand)
    console.print()
    console.rule(f"[bold cyan]Generating blog post[/]")
    console.print(f"[dim]Brand:[/] [magenta]{brand}[/]  [dim]Keyword:[/] [yellow]{keyword}[/]\n")

    source_material = None
    if source_file:
        source_material = Path(source_file).read_text(encoding="utf-8")

    def on_status(msg):
        console.print(f"  [dim]→[/] {msg}")

    try:
        with console.status("[bold green]Working...[/]", spinner="dots"):
            post_data = generate_blog_post(
                keyword, brand=brand, market=market,
                source_material=source_material, model=model,
                on_status=on_status,
            )
    except json.JSONDecodeError as e:
        console.print(f"[red]Error parsing response: {e}[/]")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]Generation failed: {e}[/]")
        raise click.Abort()

    if get_post_by_slug(post_data["slug"]):
        import time
        post_data["slug"] = f"{post_data['slug']}-{int(time.time())}"

    file_path = write_post_file(post_data)
    post_id = save_post(post_data, file_path)

    word_count = len(post_data.get("content", "").split())
    cats = ", ".join(post_data.get("categories", []))
    tags = ", ".join(post_data.get("tags", []))

    console.print()
    console.print(Panel(
        f"[bold green]Blog post created successfully![/]\n\n"
        f"  [bold]ID:[/]          #{post_id}\n"
        f"  [bold]Title:[/]       {post_data['title']}\n"
        f"  [bold]Slug:[/]        {post_data['slug']}\n"
        f"  [bold]Status:[/]      [yellow]✏️  writing[/]\n"
        f"  [bold]Words:[/]       ~{word_count}\n"
        f"  [bold]Categories:[/]  {cats}\n"
        f"  [bold]Tags:[/]        {tags}\n"
        f"  [bold]File:[/]        {file_path}",
        title=f"[bold]Post #{post_id}[/]",
        border_style="green",
        padding=(1, 2)
    ))
    console.print(f"\n[dim]Run [cyan]python main.py view {post_id}[/] to read the full post.[/]\n")


@cli.command()
@click.argument("url")
@click.option("--brand", "-b", help="Brand slug (required if more than one brand is configured).")
@click.option("--market", "-m", help="Target market name, if the brand profile defines one.")
def rewrite(url, brand, market):
    """Scrape an existing blog post URL and rewrite it with full AEO/SEO optimisation."""
    brand = _require_brand(brand)
    console.print()
    console.rule(f"[bold cyan]Rewriting blog post[/]")
    console.print(f"[dim]Brand:[/] [magenta]{brand}[/]  [dim]URL:[/] [yellow]{url}[/]\n")

    def on_status(msg):
        console.print(f"  [dim]→[/] {msg}")

    try:
        with console.status("[bold green]Working...[/]", spinner="dots"):
            post_data = rewrite_blog_post(url, brand=brand, market=market, on_status=on_status)
    except Exception as e:
        console.print(f"[red]Rewrite failed: {e}[/]")
        raise click.Abort()

    if get_post_by_slug(post_data["slug"]):
        import time
        post_data["slug"] = f"{post_data['slug']}-{int(time.time())}"

    file_path = write_post_file(post_data)
    post_id = save_post(post_data, file_path)
    console.print(f"\n[green]✓ Rewritten as Post #{post_id}[/]: {post_data['title']}\n")


@cli.command("list")
@click.option("--status", "-s", type=click.Choice(VALID_STATUSES), help="Filter by status")
@click.option("--brand", "-b", help="Filter by brand slug")
def list_cmd(status, brand):
    """List all blog posts.\n\nFilter by status: writing, ready_to_publish, published"""
    posts = list_posts(status, brand)

    if not posts:
        msg = f"No posts with status [yellow]{status}[/]." if status else "No posts yet."
        console.print(f"\n  {msg} Run [cyan]python main.py generate \"your keyword\" --brand <slug>[/] to create one.\n")
        return

    title = "Blog Posts"
    if brand:
        title += f" — {brand}"
    if status:
        title += f" — {status.replace('_', ' ').title()}"

    table = Table(
        title=title,
        border_style="cyan",
        header_style="bold cyan",
        show_lines=False,
        padding=(0, 1)
    )
    table.add_column("ID", style="dim", width=4, justify="right")
    table.add_column("Brand", style="magenta", max_width=14)
    table.add_column("Title", min_width=30, max_width=45)
    table.add_column("Keyword", style="dim", max_width=20)
    table.add_column("Status", width=20)
    table.add_column("Words", width=6, justify="right", style="dim")
    table.add_column("Date", width=12, style="dim")

    for post in posts:
        s = post["status"]
        color = STATUS_COLORS.get(s, "white")
        icon = STATUS_ICONS.get(s, "")
        label = s.replace("_", " ")

        table.add_row(
            str(post["id"]),
            post.get("brand", ""),
            post["title"],
            (post.get("keyword", "") or "")[:20],
            f"[{color}]{icon}  {label}[/]",
            str(post.get("word_count", 0)),
            (post.get("date") or "")[:10],
        )

    console.print()
    console.print(table)

    counts = {s: sum(1 for p in posts if p["status"] == s) for s in VALID_STATUSES}
    console.print(
        f"\n  [dim]Total: {len(posts)}  |  "
        f"✏️  Writing: {counts['writing']}  |  "
        f"🔵 Ready: {counts['ready_to_publish']}  |  "
        f"✅ Published: {counts['published']}[/]\n"
    )


@cli.command()
@click.argument("post_id", type=int)
def view(post_id):
    """View a blog post by ID."""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    file_path = post.get("file_path", "")
    content = read_post_content(file_path) if file_path and os.path.exists(file_path) else "[italic dim]File not found[/]"

    s = post["status"]
    color = STATUS_COLORS.get(s, "white")
    icon = STATUS_ICONS.get(s, "")
    cats = json.loads(post.get("categories") or "[]")
    tags = json.loads(post.get("tags") or "[]")

    console.print()
    console.print(Panel(
        f"[bold]{post['title']}[/]\n\n"
        f"  [dim]ID:[/] #{post['id']}    "
        f"[dim]Brand:[/] {post.get('brand', '')}    "
        f"[dim]Status:[/] [{color}]{icon}  {s.replace('_', ' ')}[/]    "
        f"[dim]Date:[/] {post.get('date', '')}    "
        f"[dim]Words:[/] ~{post.get('word_count', 0)}",
        border_style=color,
        padding=(1, 2)
    ))

    console.print(f"\n  [bold dim]SLUG[/]              {post.get('slug', '')}")
    console.print(f"  [bold dim]KEYWORD[/]           {post.get('keyword', '')}")
    console.print(f"  [bold dim]META TITLE[/]        {post.get('meta_title', '')}")
    console.print(f"  [bold dim]META DESCRIPTION[/]  {post.get('meta_description', '')}")
    console.print(f"  [bold dim]OVERVIEW[/]          {post.get('overview', '')}")
    console.print(f"  [bold dim]CATEGORIES[/]        {', '.join(cats)}")
    console.print(f"  [bold dim]TAGS[/]              {', '.join(tags)}")
    console.print(f"  [bold dim]FILE[/]              {file_path}")

    console.print()
    console.rule("[dim]Content[/]")
    console.print()

    try:
        console.print(Markdown(content))
    except Exception:
        console.print(content)

    console.print()


@cli.command()
@click.argument("post_id", type=int)
@click.option("--field", "-f", type=click.Choice(EDITABLE_FIELDS + ["content"]), help="Field to edit directly")
@click.option("--editor", "-e", is_flag=True, help="Open full file in system editor ($EDITOR or nano)")
def edit(post_id, field, editor):
    """Edit a blog post.\n\nUse --editor to open the markdown file in your system editor.\nUse --field to edit a specific metadata field inline."""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    file_path = post.get("file_path", "")

    if editor or field == "content":
        if not file_path or not os.path.exists(file_path):
            console.print(f"[red]File not found: {file_path}[/]")
            raise click.Abort()
        import subprocess
        subprocess.run([EDITOR, file_path])
        console.print(f"[green]✓ Opened in {EDITOR}.[/] Changes saved to {file_path}")
        return

    if field:
        _inline_edit(post_id, post, field, file_path)
    else:
        console.print(f"\n[bold]Edit Post #{post_id}: {post['title']}[/]\n")
        for i, f in enumerate(EDITABLE_FIELDS, 1):
            current = post.get(f, "")
            if f in ("categories", "tags"):
                current = ", ".join(json.loads(current or "[]"))
            console.print(f"  [cyan]{i}.[/] [bold]{f}[/]  [dim]{str(current)[:60]}[/]")
        console.print(f"  [cyan]{len(EDITABLE_FIELDS)+1}.[/] [bold]content[/]  [dim](opens in editor)[/]")
        console.print(f"  [cyan]0.[/] Cancel\n")

        raw = click.prompt("Edit field", default="0")
        try:
            choice = int(raw)
        except ValueError:
            console.print("[red]Invalid choice.[/]")
            return
        if choice == 0:
            return
        if choice == len(EDITABLE_FIELDS) + 1:
            import subprocess
            subprocess.run([EDITOR, file_path])
            console.print(f"[green]✓ Saved.[/]")
        elif 1 <= choice <= len(EDITABLE_FIELDS):
            _inline_edit(post_id, post, EDITABLE_FIELDS[choice - 1], file_path)


def _inline_edit(post_id: int, post: dict, field: str, file_path: str):
    current = post.get(field, "")
    if field in ("categories", "tags"):
        current = ", ".join(json.loads(current or "[]"))

    console.print(f"\n[bold]Current {field}:[/] [dim]{current}[/]")
    new_val = Prompt.ask(f"New value", default=current)

    if new_val == current:
        console.print("[dim]No change.[/]")
        return

    db_val = new_val
    if field in ("categories", "tags"):
        db_val = json.dumps([v.strip() for v in new_val.split(",") if v.strip()])

    update_post_fields(post_id, {field: db_val})

    if file_path and os.path.exists(file_path):
        file_update = {field: new_val}
        if field in ("categories", "tags"):
            file_update[field] = [v.strip() for v in new_val.split(",") if v.strip()]
        update_post_file(file_path, file_update)

    console.print(f"[green]✓ {field} updated.[/]")


@cli.command()
@click.argument("post_id", type=int)
@click.argument("new_status", type=click.Choice(VALID_STATUSES), metavar="STATUS")
def status(post_id, new_status):
    """Update the status of a post.\n\nSTATUS: writing | ready_to_publish | published"""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    old_status = post["status"]
    if old_status == new_status:
        console.print(f"[yellow]Post #{post_id} is already '{new_status}'.[/]")
        return

    old_file = post.get("file_path", "")
    slug = post["slug"]

    if old_file and os.path.exists(old_file):
        new_file = move_post_file(old_file, new_status, slug)
    else:
        new_file = str(Path(POSTS_DIR) / new_status / f"{slug}.md")

    update_post_status(post_id, new_status, old_file, new_file)

    color = STATUS_COLORS.get(new_status, "white")
    icon = STATUS_ICONS.get(new_status, "")
    console.print(
        f"[green]✓ Post #{post_id}[/] status: "
        f"[dim]{old_status}[/] → [{color}]{icon}  {new_status}[/]"
    )


@cli.command()
@click.argument("post_id", type=int, required=False)
@click.option("--all", "export_all", is_flag=True, help="Export ALL ready/published posts as one bulk CSV for Framer.")
@click.option("--status", "-s", type=click.Choice(VALID_STATUSES), default=None,
              help="Filter by status when using --all (default: ready_to_publish + published).")
@click.option("--brand", "-b", help="Filter by brand slug when using --all.")
@click.option("--format", "fmt", type=click.Choice(["markdown", "csv"]), default="csv", show_default=True,
              help="Export format. CSV is optimised for Framer CMS import.")
def export(post_id, export_all, status, brand, fmt):
    """Export posts for Framer CMS bulk import.

    Single post:   python main.py export 3
    Bulk export:   python main.py export --all
    By status:     python main.py export --all --status ready_to_publish
    """
    from src.post_writer import export_bulk_to_csv

    if export_all:
        if status:
            posts = list_posts(status, brand)
        else:
            posts = [p for p in list_posts(brand=brand) if p["status"] in ("ready_to_publish", "published")]

        if not posts:
            console.print("[yellow]No posts found to export.[/]")
            return

        pairs = []
        skipped = 0
        for post in posts:
            fp = post.get("file_path", "")
            if fp and os.path.exists(fp):
                pairs.append((post, fp))
            else:
                skipped += 1

        csv_path = export_bulk_to_csv(pairs)

        console.print(f"\n[green]✓ Bulk export complete[/]")
        console.print(f"  [bold]Posts exported:[/] {len(pairs)}")
        if skipped:
            console.print(f"  [yellow]Skipped (file missing):[/] {skipped}")
        console.print(f"  [bold]File:[/] {csv_path}")
        console.print(f"\n  [dim]Import via Framer CMS → Collections → your blog collection → ··· → Import CSV[/]\n")
        return

    if not post_id:
        console.print("[red]Provide a post ID or use --all for bulk export.[/]")
        raise click.Abort()

    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    file_path = post.get("file_path", "")

    if fmt == "csv":
        if not file_path or not os.path.exists(file_path):
            console.print(f"[red]Post file not found at: {file_path}[/]")
            raise click.Abort()
        csv_path = export_to_csv(post, file_path)
        console.print(f"\n[green]✓ Exported to Framer CMS CSV:[/] {csv_path}")
        console.print(f"[dim]Import via Framer CMS → Collections → your blog collection → ··· → Import CSV[/]\n")
    else:
        console.print(f"\n[green]✓ Markdown file:[/] {file_path}\n")


@cli.command()
@click.argument("post_id", type=int)
def delete(post_id):
    """Delete a blog post and its file."""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    console.print(f"\n  [bold]Title:[/] {post['title']}")
    console.print(f"  [bold]File:[/]  {post.get('file_path', '')}\n")

    if not Confirm.ask("[red]Delete this post permanently?[/]"):
        console.print("[dim]Cancelled.[/]")
        return

    file_path = post.get("file_path", "")
    delete_post(post_id)

    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    console.print(f"[green]✓ Post #{post_id} deleted.[/]")

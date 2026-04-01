"""Main CLI entry point for cc-unpacker."""

import os
import sys
from pathlib import Path
from typing import Optional

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich import box
from dotenv import load_dotenv

# Load .env from cwd or home
load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
load_dotenv(dotenv_path=Path.home() / ".cc-unpacker" / ".env", override=False)

console = Console()


# ─── CLI root ────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(package_name="cc-unpacker")
def cli():
    """
    \b
    ██████╗ ██████╗      ██╗   ██╗███╗   ██╗██████╗  █████╗  ██████╗██╗  ██╗███████╗██████╗
    ██╔════╝██╔════╝     ██║   ██║████╗  ██║██╔══██╗██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗
    ██║     ██║          ██║   ██║██╔██╗ ██║██████╔╝███████║██║     █████╔╝ █████╗  ██████╔╝
    ██║     ██║          ██║   ██║██║╚██╗██║██╔═══╝ ██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗
    ╚██████╗╚██████╗     ╚██████╔╝██║ ╚████║██║     ██║  ██║╚██████╗██║  ██╗███████╗██║  ██║
     ╚═════╝ ╚═════╝      ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝

    Claude Code Source Explorer — unpack npm source maps, analyze with AI.
    """
    pass


# ─── analyze ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("package_name")
@click.option("--version", "-v", default=None, help="Specific npm version (default: latest)")
@click.option("--no-ai", is_flag=True, help="Skip Claude AI analysis (just extract sources)")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Save extracted sources to directory")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None, hidden=True)
def analyze(package_name: str, version: Optional[str], no_ai: bool, output: Optional[str], api_key: Optional[str]):
    """Download a npm package and analyze its source maps with Claude AI.

    \b
    Examples:
      cc-unpacker analyze @anthropic-ai/claude-code
      cc-unpacker analyze react --version 18.2.0
      cc-unpacker analyze lodash --no-ai --output ./lodash-src
    """
    from .downloader import download_and_extract, cleanup
    from .extractor import extract_all_sources
    from .analyzer import analyze_with_claude
    from . import db

    console.print(Panel.fit(
        f"[bold cyan]Analyzing[/] [bold yellow]{package_name}[/]"
        + (f" [dim]@{version}[/dim]" if version else " [dim](latest)[/dim]"),
        border_style="cyan",
    ))

    extracted_path = None
    try:
        # ── Step 1: Download ─────────────────────────────────────────────────
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading from npm registry…", total=None)
            extracted_path, resolved_version = download_and_extract(package_name, version)
            progress.update(task, description=f"[green]✓[/] Downloaded [bold]{package_name}@{resolved_version}[/]")

        console.print(f"  [dim]Extracted to:[/] {extracted_path}")

        # ── Step 2: Extract source maps ───────────────────────────────────────
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing source maps…", total=None)
            sources = extract_all_sources(extracted_path)
            progress.update(
                task,
                description=f"[green]✓[/] Found [bold]{len(sources)}[/] original source files",
            )

        if not sources:
            console.print("\n[yellow]⚠ No source maps found in this package.[/yellow]")
            console.print("[dim]The package may not include .js.map files or inline sourceMappingURLs.[/dim]")
            return

        # Print file list
        _print_file_tree(sources)

        # ── Step 3: Save to output dir (optional) ────────────────────────────
        if output:
            out_path = Path(output)
            out_path.mkdir(parents=True, exist_ok=True)
            for name, sf in sources.items():
                dest = out_path / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(sf.content, encoding="utf-8")
            console.print(f"\n[green]✓[/] Sources saved to [bold]{out_path}[/]")

        # ── Step 4: AI Analysis ──────────────────────────────────────────────
        if no_ai:
            console.print("\n[dim]Skipping AI analysis (--no-ai flag set)[/dim]")
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Sending to Claude for analysis…", total=None)
            try:
                result = analyze_with_claude(package_name, sources, api_key=api_key)
            except RuntimeError as e:
                progress.stop()
                console.print(f"\n[red]✗ AI Analysis failed:[/] {e}")
                return
            progress.update(task, description="[green]✓[/] Analysis complete")

        # ── Step 5: Save to DB ───────────────────────────────────────────────
        row_id = db.save_analysis(
            package_name=package_name,
            version=resolved_version,
            files_count=result.files_analyzed,
            summary=result.summary,
            full_report=result.full_report,
        )

        console.print(f"\n[dim]Saved to DB with id=[bold]{row_id}[/bold][/dim]")
        console.print()
        console.print(Panel(
            Markdown(result.full_report),
            title=f"[bold cyan]AI Analysis — {package_name}@{resolved_version}[/]",
            border_style="green",
            expand=False,
        ))
        console.print(f"\n[dim]Run [bold]cc-unpacker show --id {row_id}[/bold] to view again later.[/dim]")

    except httpx.HTTPStatusError as e:
        console.print(f"\n[red]✗ Download failed:[/] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]✗ Unexpected error:[/] {e}")
        import traceback
        console.print(traceback.format_exc(), style="dim")
        sys.exit(1)
    finally:
        if extracted_path is not None:
            try:
                from .downloader import cleanup
                cleanup(extracted_path)
            except Exception:
                pass


# ─── history ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--limit", "-n", default=20, show_default=True, help="Number of entries to show")
def history(limit: int):
    """Show analysis history from SQLite database.

    \b
    Examples:
      cc-unpacker history
      cc-unpacker history --limit 50
    """
    from . import db

    rows = db.list_analyses(limit=limit)

    if not rows:
        console.print("[yellow]No analyses found.[/yellow]")
        console.print("[dim]Run [bold]cc-unpacker analyze <package>[/bold] to get started.[/dim]")
        return

    table = Table(
        title=f"Analysis History (last {limit})",
        box=box.ROUNDED,
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("ID", style="dim", width=5, justify="right")
    table.add_column("Package", style="bold yellow")
    table.add_column("Version", style="cyan", width=12)
    table.add_column("Files", justify="right", width=7)
    table.add_column("Analyzed At", style="dim", width=20)
    table.add_column("Summary", no_wrap=False, max_width=60)

    for row in rows:
        summary_short = (row["summary"] or "")[:120]
        if len(row["summary"] or "") > 120:
            summary_short += "…"
        table.add_row(
            str(row["id"]),
            row["package_name"],
            row["version"] or "?",
            str(row["files_count"] or 0),
            row["analyzed_at"][:19] if row["analyzed_at"] else "?",
            summary_short,
        )

    console.print(table)
    console.print(f"\n[dim]Run [bold]cc-unpacker show --id <ID>[/bold] for the full report.[/dim]")


# ─── show ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--id", "analysis_id", required=True, type=int, help="Analysis ID to display")
def show(analysis_id: int):
    """Display the full report for a specific analysis.

    \b
    Examples:
      cc-unpacker show --id 3
    """
    from . import db

    row = db.get_analysis(analysis_id)
    if row is None:
        console.print(f"[red]✗ No analysis found with id={analysis_id}[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold cyan]{row['package_name']}[/] [dim]@{row['version']}[/dim]   "
        f"[dim]files: {row['files_count']}  |  analyzed: {row['analyzed_at'][:19]}[/dim]",
        border_style="cyan",
    ))
    console.print()
    console.print(Panel(
        Markdown(row["full_report"] or "_No report stored._"),
        title=f"[bold]Full Report — ID {analysis_id}[/]",
        border_style="green",
        expand=False,
    ))


# ─── helpers ─────────────────────────────────────────────────────────────────

def _print_file_tree(sources: dict) -> None:
    """Print a compact summary of found source files."""
    if not sources:
        return

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
    table.add_column("Source File", style="green")
    table.add_column("Size", justify="right", style="dim", width=10)
    table.add_column("From Map", style="dim", max_width=40)

    items = sorted(sources.items(), key=lambda kv: kv[0])
    shown = items[:30]
    for name, sf in shown:
        size = f"{len(sf.content):,}B"
        map_short = Path(sf.map_file).name
        table.add_row(name, size, map_short)

    if len(items) > 30:
        table.add_row(f"[dim]… and {len(items) - 30} more[/dim]", "", "")

    console.print()
    console.print(Panel(table, title=f"[bold]Recovered Sources ({len(sources)} files)[/]", border_style="dim"))


def main():
    cli()


if __name__ == "__main__":
    main()

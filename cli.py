import os
import sys
import json
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from tokentrim.core import TokenTrimManager
from tokentrim.llm import GeminiClient

console = Console()

@click.group()
@click.option('--workspace', '-w', default=None, help="Path to workspace directory. Defaults to current directory.")
@click.pass_context
def main(ctx, workspace):
    """TokenTrim: Reduce token consumption in Agentic AI by pruning flat memory files."""
    if workspace is None:
        workspace = os.getcwd()
    ctx.ensure_object(dict)
    ctx.obj['manager'] = TokenTrimManager(workspace)
    ctx.obj['workspace'] = workspace

@main.command()
@click.pass_context
def init(ctx):
    """Initialize the TokenTrim folder structure in the workspace."""
    manager = ctx.obj['manager']
    console.print(f"[bold green]🌿 Initializing TokenTrim at {manager.workspace}...[/bold green]")
    # directories are created during manager init
    console.print(f"✓ Created [cyan]{manager.memory_dir}[/cyan]")
    console.print(f"✓ Created [cyan]{manager.domains_dir}[/cyan]")
    console.print(f"✓ Created [cyan]{manager.daily_dir}[/cyan]")
    console.print("[bold green]Success! Run `tokentrim split MEMORY.md` to import your first memory file.[/bold green]")

@main.command()
@click.argument('filepath', type=click.Path(exists=True))
@click.option('--use-llm', is_flag=True, help="Use Gemini API for semantic classification.")
@click.pass_context
def split(ctx, filepath, use_llm):
    """Split a flat memory file into domain-specific hierarchical branches."""
    manager = ctx.obj['manager']
    console.print(f"[bold]🌿 Splitting flat memory file: [cyan]{filepath}[/cyan]...[/bold]")
    
    sections = manager.parse_flat_markdown(filepath)
    if not sections:
        console.print("[yellow]No H2 sections found. Ensure your file uses '## Section Name' format.[/yellow]")
        return
        
    console.print(f"Found [bold cyan]{len(sections)}[/bold cyan] sections.")
    
    classifications = {}
    
    if use_llm:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            console.print("[red]Error: GEMINI_API_KEY environment variable not set. Run without --use-llm or set the variable.[/red]")
            return
            
        client = GeminiClient(api_key)
        existing_domains = ["identity", "business", "infrastructure", "community", "agents", "legal", "general"]
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("[yellow]Classifying sections via Gemini...[/yellow]", total=len(sections))
            
            for section in sections:
                if section.get("is_intro"):
                    progress.advance(task)
                    continue
                    
                heading = section["heading"]
                progress.update(task, description=f"Classifying: {heading[:30]}...")
                
                result = client.classify_section(heading, section["content"], existing_domains)
                if result:
                    classifications[heading] = result
                    # Update domains if a new one is suggested
                    new_dom = result.get("domain")
                    if new_dom and new_dom not in existing_domains:
                        existing_domains.append(new_dom)
                progress.advance(task)
                
    # Run the import
    res = manager.split_and_import(filepath, classifications)
    
    # Print results
    console.print(f"\n[bold green]Success![/bold green] Backup created at: [dim]{res['backup']}[/dim]")
    console.print(f"Created/updated [bold]{res['imported_files_count']}[/bold] domain files.")
    
    # Print stats
    stats = res["stats"]
    meta = res["stats"]["meta"]
    
    console.print(Panel(
        f"[bold]Active Boot Context Size (Index):[/bold] [green]{manager.count_tokens(open(manager.memory_md).read())} tokens[/green]\n"
        f"[bold]Total Memory Size (All Domains):[/bold] [cyan]{meta['total_tokens']} tokens[/cyan]\n"
        f"[bold]Net Saving on Boot Load:[/bold] [bold green]{round((1 - (manager.count_tokens(open(manager.memory_md).read()) / max(1, meta['total_tokens']))) * 100, 1)}%[/bold green]",
        title="Token Saving Statistics"
    ))

@main.command()
@click.pass_context
def reindex(ctx):
    """Rebuild all domain indices, metadata files, and the root MEMORY.md."""
    manager = ctx.obj['manager']
    console.print("[yellow]🌿 Reindexing memory folders...[/yellow]")
    res = manager.reindex()
    console.print(f"[bold green]Reindexed {res['meta']['total_tokens']} tokens across {res['meta']['domain_count']} domains.[/bold green]")

@main.command()
@click.pass_context
def status(ctx):
    """Evaluate memory tree health, file tokens, and staging file status."""
    manager = ctx.obj['manager']
    status_data = manager.status()
    
    if status_data.get("status") == "UNINITIALIZED":
        console.print(f"[yellow]{status_data['message']}[/yellow]")
        return
        
    # Build a nice panel
    color = "green" if status_data["status"] == "HEALTHY" else "yellow" if status_data["status"] == "WARNING" else "red"
    
    console.print(Panel(
        f"[bold]Status:[/bold] [{color}]{status_data['status']}[/{color}]\n"
        f"[bold]Total Token Store:[/bold] {status_data['total_tokens']} tokens\n"
        f"[bold]Domains:[/bold] {status_data['domain_count']}\n"
        f"[bold]Last Reindex:[/bold] {status_data['last_reindex_hours']} hours ago\n"
        f"[bold]Stale General Files (>30d):[/bold] {status_data['general_age_violations']}\n"
        f"[bold]Pending Purges:[/bold] {status_data['pending_purge_count']}",
        title="🌿 TokenTrim Memory Health Summary"
    ))
    
    if status_data["messages"]:
        console.print("\n[bold yellow]Alerts / Recommendations:[/bold yellow]")
        for msg in status_data["messages"]:
            console.print(f" ⚠️  [yellow]{msg}[/yellow]")
            
    # List files per domain in a table
    table = Table(title="Domain Distribution", show_header=True, header_style="bold magenta")
    table.add_column("Domain")
    table.add_column("Files")
    table.add_column("Total Tokens")
    
    domains = status_data["stats"]["domains"]
    for dom in sorted(domains.keys()):
        table.add_row(dom.capitalize(), str(domains[dom]["files"]), str(domains[dom]["tokens"]))
        
    console.print(table)
    
    # Check if reflect staging file is present
    staging_file = os.path.join(manager.memory_dir, "_reflect_staging.json")
    if os.path.exists(staging_file):
        console.print("\n[bold cyan]💡 Staged Reflection Found![/bold cyan]")
        console.print("Run [bold]`tokentrim ui`[/bold] to inspect and execute optimizations interactively.")

@main.command()
@click.pass_context
def reflect(ctx):
    """Analyze memory tree with Gemini and stage reflection changes."""
    manager = ctx.obj['manager']
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[red]Error: GEMINI_API_KEY environment variable not set. LLM reflection requires Gemini.[/red]")
        return
        
    client = GeminiClient(api_key)
    res_reindex = manager.reindex()
    
    console.print("[yellow]🌿 Staging LLM Reflection using Gemini...[/yellow]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        progress.add_task("Analyzing folder structure and token sizes...", total=None)
        reflection = client.analyze_memory_tree(res_reindex["stats"], res_reindex["tree"])
        
    if not reflection or "recommendations" not in reflection:
        console.print("[red]Failed to get recommendations from LLM.[/red]")
        return
        
    # Write to _reflect_staging.json
    staging_file = os.path.join(manager.memory_dir, "_reflect_staging.json")
    with open(staging_file, "w") as f:
        json.dump(reflection, f, indent=2)
        
    console.print(f"\n[bold green]Success! Staged {len(reflection['recommendations'])} recommendations.[/bold green]")
    console.print(f"Reflection file written to: [cyan]{staging_file}[/cyan]")
    
    # Display table of suggestions
    table = Table(title="Reflection Recommendations", show_header=True, header_style="bold cyan")
    table.add_column("File")
    table.add_column("Action")
    table.add_column("Details")
    
    for rec in reflection["recommendations"]:
        action_color = "red" if rec["action"] == "archive" else "yellow" if rec["action"] == "migrate" else "green"
        details = f"To: {rec['suggested_domain']}" if rec['action'] == "migrate" else rec.get("reason", "")
        table.add_row(
            rec["file"], 
            f"[{action_color}]{rec['action'].upper()}[/{action_color}]", 
            details
        )
        
    console.print(table)
    console.print("\n[bold]Next Step:[/bold] Run [bold]`tokentrim ui`[/bold] to apply these actions interactively.")

@main.command()
@click.option('--grace-days', default=180, help="Grace period in days before deleting marked files.")
@click.pass_context
def purge(ctx, grace_days):
    """Permanently delete files marked with __DELETE older than the grace period."""
    manager = ctx.obj['manager']
    console.print(f"[yellow]🌿 Checking for files marked with __DELETE older than {grace_days} days...[/yellow]")
    purged = manager.purge(grace_days)
    
    if not purged:
        console.print("[green]No files qualified for purging.[/green]")
    else:
        for p in purged:
            console.print(f"🔥 [red]Deleted:[/red] {p['domain']}/{p['filename']} ({p['size_bytes']} bytes)")
        console.print(f"[bold green]Purged {len(purged)} files. Audit log updated in _purge_log.json.[/bold green]")

@main.command()
@click.option('--port', default=8000, help="Port to run the Web UI on.")
@click.option('--host', default="127.0.0.1", help="Host address to run the Web UI on.")
@click.pass_context
def ui(ctx, host, port):
    """Launch the interactive local Web UI dashboard."""
    import uvicorn
    # Store workspace path in env for FastAPI server
    os.environ["TOKENTRIM_WORKSPACE"] = ctx.obj['workspace']
    
    console.print(f"[bold green]🌿 Starting TokenTrim Dashboard on http://{host}:{port}...[/bold green]")
    uvicorn.run("tokentrim.server:app", host=host, port=port, log_level="warning")

if __name__ == '__main__':
    main()

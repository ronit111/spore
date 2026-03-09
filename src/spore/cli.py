"""Spore CLI — command-line interface for autonomous research coordination.

Usage:
    spore init --agent-id agent-47
    spore experiment start --direction "attention-variants" --hypothesis "..."
    spore finding publish --claim "..." --metrics val_bpb=0.45
    spore discover --direction "attention"
    spore status
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from spore.models import ExperimentStatus
from spore.repo import SporeError, SporeRepo

console = Console()
err_console = Console(stderr=True)


def _truncate(text: str, length: int) -> str:
    return text[:length] + "..." if len(text) > length else text


def get_repo() -> SporeRepo:
    try:
        return SporeRepo(Path.cwd())
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


def parse_metrics(values: tuple[str, ...]) -> dict[str, float]:
    """Parse metric arguments like val_bpb=0.45 into a dict."""
    metrics: dict[str, float] = {}
    for item in values:
        if "=" not in item:
            raise click.BadParameter(f"Metrics must be key=value pairs, got: {item}")
        key, val = item.split("=", 1)
        try:
            metrics[key.strip()] = float(val.strip())
        except ValueError as exc:
            raise click.BadParameter(f"Metric value must be numeric, got: {val}") from exc
    return metrics


# ======================================================================
# Root
# ======================================================================


@click.group()
@click.version_option(package_name="spore-protocol")
def main() -> None:
    """Spore — autonomous research agent coordination.

    A protocol and toolkit for AI research agents to publish, discover,
    and build on each other's findings through Git-native collaboration.
    """


# ======================================================================
# Init
# ======================================================================


@main.command()
@click.option("--agent-id", "-a", help="Unique identifier for this agent.")
@click.option("--repo-name", "-n", help="Name for this research repository.")
def init(agent_id: str | None, repo_name: str | None) -> None:
    """Initialize a repository for Spore."""
    repo = get_repo()
    try:
        config = repo.init(agent_id=agent_id, repo_name=repo_name)
        console.print(
            Panel(
                f"[green]Spore initialized[/green]\n\n"
                f"  Agent ID:  {config.agent_id or '(set with --agent-id or SPORE_AGENT_ID)'}\n"
                f"  Repo:      {config.repo_name}\n"
                f"  Directory: .spore/",
                title="spore init",
                border_style="green",
            )
        )
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# ======================================================================
# Experiment
# ======================================================================


@main.group()
def experiment() -> None:
    """Manage research experiments."""


@experiment.command("start")
@click.option("--direction", "-d", required=True, help="Research direction.")
@click.option("--hypothesis", "-H", required=True, help="What you're testing.")
@click.option("--builds-on", "-b", multiple=True, help="Finding IDs this builds on.")
@click.option("--no-branch", is_flag=True, help="Don't create a Git branch.")
def experiment_start(
    direction: str, hypothesis: str, builds_on: tuple[str, ...], no_branch: bool
) -> None:
    """Start a new research experiment."""
    repo = get_repo()
    try:
        exp = repo.start_experiment(
            direction=direction,
            hypothesis=hypothesis,
            builds_on=list(builds_on),
            create_branch=not no_branch,
        )
        console.print(
            Panel(
                f"[green]Experiment started[/green]\n\n"
                f"  ID:         {exp.id}\n"
                f"  Direction:  {exp.direction}\n"
                f"  Branch:     {exp.branch}\n"
                f"  Hypothesis: {exp.hypothesis}",
                title="spore experiment start",
                border_style="blue",
            )
        )
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@experiment.command("complete")
@click.argument("experiment_id")
def experiment_complete(experiment_id: str) -> None:
    """Mark an experiment as completed."""
    repo = get_repo()
    try:
        exp = repo.complete_experiment(experiment_id)
        console.print(f"[green]Experiment {exp.id} marked as completed.[/green]")
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@experiment.command("abandon")
@click.argument("experiment_id")
def experiment_abandon(experiment_id: str) -> None:
    """Abandon an experiment."""
    repo = get_repo()
    try:
        exp = repo.abandon_experiment(experiment_id)
        console.print(f"[yellow]Experiment {exp.id} abandoned.[/yellow]")
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@experiment.command("list")
@click.option("--direction", "-d", help="Filter by direction.")
@click.option("--status", "-s", type=click.Choice(["running", "completed", "abandoned"]))
def experiment_list(direction: str | None, status: str | None) -> None:
    """List experiments."""
    repo = get_repo()
    exp_status = ExperimentStatus(status) if status else None
    experiments = repo.list_experiments(direction=direction, status=exp_status)

    if not experiments:
        console.print("[dim]No experiments found.[/dim]")
        return

    table = Table(title="Experiments", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Direction", style="blue")
    table.add_column("Status", style="bold")
    table.add_column("Findings", justify="right")
    table.add_column("Hypothesis")

    status_style = {
        ExperimentStatus.RUNNING: "[green]running[/green]",
        ExperimentStatus.COMPLETED: "[blue]completed[/blue]",
        ExperimentStatus.ABANDONED: "[dim]abandoned[/dim]",
    }
    for exp in experiments:
        table.add_row(
            exp.id,
            exp.direction,
            status_style[exp.status],
            str(len(exp.findings)),
            exp.hypothesis[:60] + "..." if len(exp.hypothesis) > 60 else exp.hypothesis,
        )

    console.print(table)


@experiment.command("show")
@click.argument("experiment_id")
def experiment_show(experiment_id: str) -> None:
    """Show experiment details."""
    repo = get_repo()
    try:
        exp = repo.get_experiment(experiment_id)
        tree = Tree(f"[bold cyan]{exp.id}[/bold cyan]")
        tree.add(f"Direction: [blue]{exp.direction}[/blue]")
        tree.add(f"Status: {exp.status.value}")
        tree.add(f"Branch: {exp.branch}")
        tree.add(f"Hypothesis: {exp.hypothesis}")
        tree.add(f"Started: {exp.started.isoformat()}")
        if exp.completed:
            tree.add(f"Completed: {exp.completed.isoformat()}")
        if exp.findings:
            findings_node = tree.add("Findings")
            for fid in exp.findings:
                findings_node.add(f"[green]{fid}[/green]")
        if exp.builds_on:
            builds_node = tree.add("Builds on")
            for fid in exp.builds_on:
                builds_node.add(f"[yellow]{fid}[/yellow]")
        console.print(tree)
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# ======================================================================
# Finding
# ======================================================================


@main.group()
def finding() -> None:
    """Manage research findings."""


@finding.command("publish")
@click.option("--claim", "-c", required=True, help="What was discovered.")
@click.option("--direction", "-d", required=True, help="Research direction.")
@click.option(
    "--experiment",
    "-e",
    "experiment_id",
    help="Experiment ID (auto-detected if omitted).",
)
@click.option("--hypothesis", "-H", help="The hypothesis behind this finding.")
@click.option("--metric", "-m", multiple=True, help="Metric as key=value (repeatable).")
@click.option("--builds-on", "-b", multiple=True, help="Finding IDs this builds on.")
@click.option("--tag", "-t", multiple=True, help="Applicability tags.")
@click.option("--significance", "-s", type=float, default=0.5, help="Significance score (0-1).")
@click.option("--notes", help="Additional notes or context.")
def finding_publish(
    claim: str,
    direction: str,
    experiment_id: str | None,
    hypothesis: str | None,
    metric: tuple[str, ...],
    builds_on: tuple[str, ...],
    tag: tuple[str, ...],
    significance: float,
    notes: str | None,
) -> None:
    """Publish a research finding."""
    repo = get_repo()
    metrics = parse_metrics(metric)
    try:
        f = repo.publish_finding(
            experiment_id=experiment_id,
            direction=direction,
            claim=claim,
            hypothesis=hypothesis,
            metrics=metrics,
            builds_on=list(builds_on),
            applicability=list(tag),
            significance=significance,
            notes=notes,
        )
        console.print(
            Panel(
                f"[green]Finding published[/green]\n\n"
                f"  ID:           {f.id}\n"
                f"  Direction:    {f.direction}\n"
                f"  Claim:        {f.claim}\n"
                f"  Significance: {f.significance}\n"
                f"  Metrics:      {f.evidence.metrics}",
                title="spore finding publish",
                border_style="green",
            )
        )
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@finding.command("list")
@click.option("--direction", "-d", help="Filter by direction.")
def finding_list(direction: str | None) -> None:
    """List findings."""
    repo = get_repo()
    findings = repo.list_findings(direction=direction)

    if not findings:
        console.print("[dim]No findings found.[/dim]")
        return

    table = Table(title="Findings", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Direction", style="blue")
    table.add_column("Sig", justify="right", style="yellow")
    table.add_column("Agent", style="dim")
    table.add_column("Claim")

    for f in findings:
        table.add_row(
            f.id,
            f.direction,
            f"{f.significance:.1f}",
            f.agent_id,
            f.claim[:70] + "..." if len(f.claim) > 70 else f.claim,
        )

    console.print(table)


@finding.command("show")
@click.argument("finding_id")
def finding_show(finding_id: str) -> None:
    """Show finding details."""
    repo = get_repo()
    try:
        f = repo.get_finding(finding_id)
        tree = Tree(f"[bold green]{f.id}[/bold green]")
        tree.add(f"Claim: {f.claim}")
        tree.add(f"Direction: [blue]{f.direction}[/blue]")
        tree.add(f"Agent: {f.agent_id}")
        tree.add(f"Experiment: {f.experiment_id}")
        tree.add(f"Significance: [yellow]{f.significance}[/yellow]")
        tree.add(f"Status: {f.status.value}")
        tree.add(f"Timestamp: {f.timestamp.isoformat()}")

        if f.hypothesis:
            tree.add(f"Hypothesis: {f.hypothesis}")

        if f.evidence.metrics:
            metrics_node = tree.add("Metrics")
            for k, v in f.evidence.metrics.items():
                metrics_node.add(f"{k}: [bold]{v}[/bold]")

        if f.evidence.baseline:
            baseline_node = tree.add("Baseline")
            for k, v in f.evidence.baseline.items():
                baseline_node.add(f"{k}: {v}")

        if f.builds_on:
            builds_node = tree.add("Builds on")
            for fid in f.builds_on:
                builds_node.add(f"[yellow]{fid}[/yellow]")

        if f.applicability:
            tree.add(f"Tags: {', '.join(f.applicability)}")

        if f.evidence.notes:
            tree.add(f"Notes: {f.evidence.notes}")

        console.print(tree)
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# ======================================================================
# Discover
# ======================================================================


@main.command()
@click.option("--query", "-q", help="Full-text search query.")
@click.option("--direction", "-d", help="Filter by research direction.")
@click.option("--agent", "-a", help="Filter by agent ID.")
@click.option("--metric", "-m", help="Filter by metric name.")
@click.option("--metric-max", type=float, help="Maximum metric value.")
@click.option("--metric-min", type=float, help="Minimum metric value.")
@click.option("--min-significance", type=float, help="Minimum significance score.")
@click.option("--remote", "-r", is_flag=True, help="Also scan remote branches.")
@click.option("--federated", "-f", is_flag=True, help="Also scan federation peers.")
@click.option("--limit", "-l", type=int, default=20, help="Max results.")
def discover(
    query: str | None,
    direction: str | None,
    agent: str | None,
    metric: str | None,
    metric_max: float | None,
    metric_min: float | None,
    min_significance: float | None,
    remote: bool,
    federated: bool,
    limit: int,
) -> None:
    """Discover findings from other agents.

    Search the local index for relevant research findings. Use --remote
    to also scan remote branches, or --federated to scan federation peers.
    """
    repo = get_repo()

    if remote:
        with console.status("[bold blue]Scanning remote branches..."):
            remote_findings = repo.discover_remote(direction=direction, limit=limit)
        if remote_findings:
            n = len(remote_findings)
            console.print(f"[dim]Indexed {n} findings from remote branches.[/dim]\n")

    if federated:
        with console.status("[bold blue]Scanning federation peers..."):
            fed_findings = repo.discover_federated(direction=direction, limit=limit)
        if fed_findings:
            n = len(fed_findings)
            console.print(f"[dim]Indexed {n} findings from federation peers.[/dim]\n")

    results = repo.discover(
        query=query,
        direction=direction,
        agent_id=agent,
        metric_name=metric,
        metric_max=metric_max,
        metric_min=metric_min,
        min_significance=min_significance,
        limit=limit,
    )

    if not results:
        console.print("[dim]No findings found matching your query.[/dim]")
        return

    table = Table(title=f"Discovered Findings ({len(results)})", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Direction", style="blue")
    table.add_column("Sig", justify="right", style="yellow")
    table.add_column("Agent", style="dim")
    table.add_column("Claim")
    table.add_column("Metrics", style="green")

    for r in results:
        metrics_str = ", ".join(f"{k}={v:.4f}" for k, v in r.get("metrics", {}).items())
        table.add_row(
            r["id"],
            r["direction"],
            f"{r.get('significance', 0):.1f}",
            r.get("agent_id", ""),
            _truncate(r.get("claim", ""), 60),
            metrics_str or "-",
        )

    console.print(table)


# ======================================================================
# Adopt
# ======================================================================


@main.command()
@click.argument("finding_id")
@click.option(
    "--experiment",
    "-e",
    "experiment_id",
    help="Target experiment (auto-detected if omitted).",
)
def adopt(finding_id: str, experiment_id: str | None) -> None:
    """Adopt a finding into the current experiment.

    Records that your experiment builds on another agent's finding.
    The adoption creates a lineage link for tracking cross-pollination.
    """
    repo = get_repo()
    try:
        result = repo.adopt_finding(finding_id, experiment_id)
        console.print(
            f"[green]Adopted[/green] finding [cyan]{result['finding_id']}[/cyan] "
            f"into experiment [blue]{result['experiment_id']}[/blue]"
        )
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# ======================================================================
# Direction
# ======================================================================


@main.group()
def direction() -> None:
    """Manage research directions."""


@direction.command("create")
@click.option("--name", "-n", required=True, help="Direction name.")
@click.option("--description", "-d", required=True, help="What this direction explores.")
@click.option("--tag", "-t", multiple=True, help="Tags for this direction.")
def direction_create(name: str, description: str, tag: tuple[str, ...]) -> None:
    """Create a new research direction."""
    repo = get_repo()
    try:
        d = repo.create_direction(name=name, description=description, tags=list(tag))
        console.print(f"[green]Direction created:[/green] {d.name} ({d.id})")
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@direction.command("list")
def direction_list() -> None:
    """List research directions."""
    repo = get_repo()
    directions = repo.list_directions()

    if not directions:
        console.print("[dim]No directions found.[/dim]")
        return

    table = Table(title="Research Directions", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Tags", style="dim")

    for d in directions:
        table.add_row(d.id, d.name, d.description, ", ".join(d.tags))

    console.print(table)


# ======================================================================
# Federation
# ======================================================================


@main.group()
def federation() -> None:
    """Manage federation with other Spore repositories."""


@federation.command("add")
@click.argument("url")
@click.option("--name", "-n", help="Friendly name for this peer.")
@click.option("--direction", "-d", multiple=True, help="Directions this peer covers.")
def federation_add(url: str, name: str | None, direction: tuple[str, ...]) -> None:
    """Add a peer repository to the federation."""
    repo = get_repo()
    try:
        result = repo.add_peer(url, name=name, directions=list(direction) if direction else None)
        console.print(f"[green]Peer added:[/green] {result['name']} ({result['url']})")
    except SporeError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@federation.command("remove")
@click.argument("url")
def federation_remove(url: str) -> None:
    """Remove a peer from the federation."""
    repo = get_repo()
    if repo.remove_peer(url):
        console.print(f"[green]Peer removed:[/green] {url}")
    else:
        console.print(f"[yellow]Peer not found:[/yellow] {url}")


@federation.command("list")
def federation_list() -> None:
    """List all federation peers."""
    repo = get_repo()
    peers = repo.list_peers()

    if not peers:
        console.print("[dim]No federation peers registered.[/dim]")
        console.print("Add one with: [bold]spore federation add <url>[/bold]")
        return

    table = Table(title="Federation Peers", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("URL", style="blue")
    table.add_column("Directions", style="dim")

    for p in peers:
        dirs = ", ".join(p.get("directions", [])) or "-"
        table.add_row(p["name"], p["url"], dirs)

    console.print(table)


@federation.command("sync")
def federation_sync() -> None:
    """Sync all federation peers (fetch latest)."""
    repo = get_repo()
    with console.status("[bold blue]Syncing federation peers..."):
        results = repo.sync_peers()

    if not results:
        console.print("[dim]No peers to sync.[/dim]")
        return

    for name in results:
        console.print(f"  [green]Synced:[/green] {name}")
    console.print(f"\n[dim]{len(results)} peers synced.[/dim]")


@federation.command("discover")
@click.option("--direction", "-d", help="Filter by direction.")
@click.option("--limit", "-l", type=int, default=50, help="Max results.")
def federation_discover(direction: str | None, limit: int) -> None:
    """Discover findings from all federated peers."""
    repo = get_repo()
    with console.status("[bold blue]Discovering from federation peers..."):
        findings = repo.discover_federated(direction=direction, limit=limit)

    if not findings:
        console.print("[dim]No findings found from federation peers.[/dim]")
        return

    table = Table(title=f"Federated Findings ({len(findings)})", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Direction", style="blue")
    table.add_column("Sig", justify="right", style="yellow")
    table.add_column("Agent", style="dim")
    table.add_column("Claim")

    for f in findings:
        table.add_row(
            f.id,
            f.direction,
            f"{f.significance:.1f}",
            f.agent_id,
            _truncate(f.claim, 60),
        )

    console.print(table)


# ======================================================================
# Watch
# ======================================================================


@main.command()
@click.option("--direction", "-d", help="Only watch this direction.")
@click.option("--min-significance", type=float, help="Only show findings above this.")
@click.option("--interval", type=float, default=5.0, help="Poll interval in seconds.")
def watch(direction: str | None, min_significance: float | None, interval: float) -> None:
    """Watch for new findings in real-time.

    Polls the repository for new findings and prints them as they appear.
    Press Ctrl+C to stop.
    """
    import signal

    from spore.watch import SporeWatcher

    repo = get_repo()

    def on_finding(finding: object) -> None:
        console.print(
            f"\n[green]New finding:[/green] [cyan]{finding.id}[/cyan]\n"
            f"  Direction:    {finding.direction}\n"
            f"  Claim:        {finding.claim}\n"
            f"  Agent:        {finding.agent_id}\n"
            f"  Significance: [yellow]{finding.significance}[/yellow]"
        )

    watcher = SporeWatcher(repo, interval=interval)
    watcher.on_finding(on_finding, direction=direction, min_significance=min_significance)
    watcher.start()

    console.print(
        f"[bold blue]Watching for new findings[/bold blue] (interval: {interval}s, Ctrl+C to stop)"
    )
    if direction:
        console.print(f"  Direction filter: {direction}")

    try:
        signal.pause()
    except (KeyboardInterrupt, AttributeError):
        # AttributeError: signal.pause not available on Windows
        try:
            while watcher.is_running:
                import time

                time.sleep(1)
        except KeyboardInterrupt:
            pass

    watcher.stop()
    console.print("\n[dim]Watcher stopped.[/dim]")


# ======================================================================
# Status
# ======================================================================


@main.command()
def status() -> None:
    """Show Spore repository status."""
    repo = get_repo()

    if not repo.is_initialized:
        console.print("[yellow]Repository not initialized for Spore.[/yellow]")
        console.print("Run [bold]spore init[/bold] to get started.")
        return

    s = repo.status()

    panel_content = (
        f"  Agent:        [cyan]{s['agent_id']}[/cyan]\n"
        f"  Branch:       [blue]{s['branch']}[/blue]\n"
        f"  Directions:   {s['directions']}\n"
        f"\n"
        f"  Experiments:  {s['experiments']['total']} total "
        f"([green]{s['experiments']['running']} running[/green], "
        f"[blue]{s['experiments']['completed']} completed[/blue])\n"
        f"  Findings:     {s['findings']['total']} total "
        f"([green]{s['findings']['published']} published[/green])"
    )

    console.print(Panel(panel_content, title="Spore Status", border_style="cyan"))


# ======================================================================
# Index
# ======================================================================


@main.group()
def index() -> None:
    """Manage the local finding index."""


@index.command("rebuild")
def index_rebuild() -> None:
    """Rebuild the local index from .spore/ manifests."""
    repo = get_repo()
    with console.status("[bold blue]Rebuilding index..."):
        count = repo.rebuild_index()
    console.print(f"[green]Index rebuilt.[/green] {count} findings indexed.")


# ======================================================================
# Lineage
# ======================================================================


@main.command()
@click.argument("finding_id")
@click.option("--depth", "-d", type=int, default=10, help="Max lineage depth.")
def lineage(finding_id: str, depth: int) -> None:
    """Trace the lineage of a finding.

    Shows the chain of findings that this finding builds upon,
    revealing the research path that led to this discovery.
    """
    repo = get_repo()
    ancestors = repo.index.get_lineage(finding_id, depth=depth)

    if not ancestors:
        console.print(f"[dim]No lineage found for {finding_id}.[/dim]")
        return

    tree = Tree(f"[bold cyan]{finding_id}[/bold cyan]")
    for a in ancestors:
        node = tree.add(f"[green]{a['id']}[/green]")
        node.add(f"[dim]{a.get('claim', 'N/A')}[/dim]")
        node.add(f"Direction: {a.get('direction', 'N/A')}")

    console.print(Panel(tree, title="Finding Lineage", border_style="yellow"))

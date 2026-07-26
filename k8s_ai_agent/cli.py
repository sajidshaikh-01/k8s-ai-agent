"""CLI entry point.

Usage:
    python -m k8s_ai_agent --pod my-pod --namespace default
    python -m k8s_ai_agent --pod my-pod --namespace default --deployment my-deploy
"""

import argparse
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .investigator import KubernetesInvestigator
from .reasoning import AIReasoningEngine

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(description="AI-powered Kubernetes troubleshooting agent")
    parser.add_argument("--pod", required=True, help="Pod name to investigate")
    parser.add_argument("--namespace", "-n", default="default", help="Kubernetes namespace")
    parser.add_argument("--deployment", "-d", default=None, help="Related deployment name (optional)")
    parser.add_argument("--service", "-s", default=None, help="Related service name (optional)")
    parser.add_argument("--context", default=None, help="kubeconfig context to use (optional)")
    parser.add_argument("--show-evidence", action="store_true", help="Print raw collected evidence")
    return parser.parse_args()


def render_report(pod_name: str, diagnosis, show_raw: bool = False):
    confidence_color = "green" if diagnosis.confidence >= 75 else "yellow" if diagnosis.confidence >= 40 else "red"

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("[bold]Root Cause[/bold]", diagnosis.root_cause)
    table.add_row("[bold]Confidence[/bold]", f"[{confidence_color}]{diagnosis.confidence}%[/{confidence_color}]")
    table.add_row("[bold]Suggested Fix[/bold]", diagnosis.suggested_fix)
    table.add_row("[bold]Prevention[/bold]", diagnosis.prevention)

    console.print(Panel(table, title=f"Diagnosis: {pod_name}", border_style="cyan"))

    if show_raw:
        console.print(Panel(diagnosis.raw_response, title="Raw model response", border_style="dim"))


def main():
    load_dotenv()
    args = parse_args()

    console.print(f"[bold cyan]→ Investigating pod[/bold cyan] {args.pod} in namespace {args.namespace}...")

    try:
        investigator = KubernetesInvestigator(context=args.context)
        data = investigator.investigate_pod(
            args.pod, args.namespace, args.deployment, args.service
        )
    except Exception as e:
        console.print(f"[bold red]Investigation failed:[/bold red] {e}")
        sys.exit(1)

    console.print("[green]✓[/green] Pod status checked")
    console.print("[green]✓[/green] Logs collected")
    console.print("[green]✓[/green] Events analyzed")
    console.print("[green]✓[/green] ConfigMap/Secret references checked")
    console.print("[green]✓[/green] PVC status checked")
    console.print("[green]✓[/green] Node conditions checked")
    if args.deployment:
        console.print("[green]✓[/green] Deployment rollout checked")
    if args.service:
        console.print("[green]✓[/green] Service endpoints checked")

    console.print("[bold cyan]→ Sending evidence to Claude for root cause analysis...[/bold cyan]")

    try:
        engine = AIReasoningEngine()
        diagnosis = engine.diagnose(data)
    except Exception as e:
        console.print(f"[bold red]AI reasoning failed:[/bold red] {e}")
        sys.exit(1)

    render_report(args.pod, diagnosis, show_raw=args.show_evidence)


if __name__ == "__main__":
    main()
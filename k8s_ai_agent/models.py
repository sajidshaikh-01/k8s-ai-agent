"""Data models used across the investigation and reasoning layers."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PodStatus:
    name: str
    namespace: str
    phase: str
    restart_count: int
    container_statuses: list[dict] = field(default_factory=list)
    reason: Optional[str] = None  # e.g. CrashLoopBackOff, ImagePullBackOff


@dataclass
class InvestigationData:
    """Structured evidence collected from the cluster before it goes to the LLM."""

    pod_status: Optional[PodStatus] = None
    current_logs: str = ""
    previous_logs: str = ""  # logs from the last crashed container, if any
    events: list[str] = field(default_factory=list)
    deployment_status: Optional[dict] = None
    service_status: Optional[dict] = None
    config_refs: list[dict] = field(default_factory=list)  # ConfigMap/Secret refs + whether they exist
    pvc_status: list[dict] = field(default_factory=list)
    node_status: Optional[dict] = None

    def to_prompt_context(self) -> str:
        """Render the collected evidence as plain text for the LLM prompt."""
        lines = []

        if self.pod_status:
            lines.append(f"Pod: {self.pod_status.name} (namespace: {self.pod_status.namespace})")
            lines.append(f"Phase: {self.pod_status.phase}")
            lines.append(f"Restart count: {self.pod_status.restart_count}")
            if self.pod_status.reason:
                lines.append(f"Reason: {self.pod_status.reason}")
            for cs in self.pod_status.container_statuses:
                lines.append(f"Container status detail: {cs}")

        if self.node_status:
            lines.append(f"\nNode ({self.node_status.get('name')}) status:")
            lines.append(f"  Conditions: {self.node_status.get('conditions')}")
            lines.append(f"  Allocatable: {self.node_status.get('allocatable')}")

        if self.deployment_status:
            lines.append(f"\nDeployment rollout status: {self.deployment_status}")

        if self.service_status:
            lines.append(f"\nService status: {self.service_status}")

        if self.config_refs:
            lines.append("\nConfigMap/Secret references used by this pod:")
            for ref in self.config_refs:
                lines.append(f"  - {ref}")

        if self.pvc_status:
            lines.append("\nPVC status:")
            for pvc in self.pvc_status:
                lines.append(f"  - {pvc}")

        if self.events:
            lines.append("\nRecent Kubernetes events:")
            for e in self.events:
                lines.append(f"  - {e}")

        if self.current_logs:
            lines.append(f"\nCurrent container logs (last lines):\n{self.current_logs}")

        if self.previous_logs:
            lines.append(f"\nPrevious (crashed) container logs:\n{self.previous_logs}")

        return "\n".join(lines)


@dataclass
class Diagnosis:
    root_cause: str
    confidence: int  # 0-100
    suggested_fix: str
    prevention: str
    raw_response: str = ""
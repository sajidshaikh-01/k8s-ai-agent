"""Investigation layer.

Talks to the Kubernetes API to collect the same signals an engineer would
manually check during triage: pod status, logs, events, and rollout status.
"""

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from .models import InvestigationData, PodStatus


class KubernetesInvestigator:
    def __init__(self, kubeconfig: str | None = None, context: str | None = None):
        # Loads ~/.kube/config by default - same cluster access as kubectl.
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig, context=context)
        else:
            config.load_kube_config(context=context)

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    # ---------- Pod Inspector ----------
    def inspect_pod(self, name: str, namespace: str) -> PodStatus:
        pod = self.core_v1.read_namespaced_pod(name=name, namespace=namespace)

        restart_count = 0
        reason = None
        container_statuses = []

        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                restart_count += cs.restart_count
                state_detail = {}
                if cs.state.waiting:
                    state_detail = {
                        "container": cs.name,
                        "state": "waiting",
                        "reason": cs.state.waiting.reason,
                        "message": cs.state.waiting.message,
                    }
                    reason = reason or cs.state.waiting.reason
                elif cs.state.terminated:
                    state_detail = {
                        "container": cs.name,
                        "state": "terminated",
                        "reason": cs.state.terminated.reason,
                        "exit_code": cs.state.terminated.exit_code,
                    }
                    reason = reason or cs.state.terminated.reason
                elif cs.state.running:
                    state_detail = {"container": cs.name, "state": "running"}
                container_statuses.append(state_detail)

        return PodStatus(
            name=name,
            namespace=namespace,
            phase=pod.status.phase,
            restart_count=restart_count,
            container_statuses=container_statuses,
            reason=reason,
        )

    # ---------- Logs Collector ----------
    def get_logs(self, name: str, namespace: str, tail_lines: int = 100) -> tuple[str, str]:
        """Returns (current_logs, previous_logs). previous_logs is empty if pod never restarted."""
        current_logs = ""
        previous_logs = ""

        try:
            current_logs = self.core_v1.read_namespaced_pod_log(
                name=name, namespace=namespace, tail_lines=tail_lines
            )
        except ApiException:
            current_logs = "(no current logs available)"

        try:
            previous_logs = self.core_v1.read_namespaced_pod_log(
                name=name, namespace=namespace, tail_lines=tail_lines, previous=True
            )
        except ApiException:
            previous_logs = ""  # normal if the pod hasn't restarted

        return current_logs, previous_logs

    # ---------- Events Analyzer ----------
    def get_events(self, namespace: str, involved_object_name: str, limit: int = 15) -> list[str]:
        events = self.core_v1.list_namespaced_event(namespace=namespace)
        relevant = [
            f"[{e.type}] {e.reason}: {e.message}"
            for e in events.items
            if e.involved_object and e.involved_object.name == involved_object_name
        ]
        return relevant[-limit:]

    # ---------- Deployment Inspector ----------
    def get_deployment_status(self, name: str, namespace: str) -> dict | None:
        try:
            dep = self.apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        except ApiException:
            return None

        return {
            "replicas_desired": dep.spec.replicas,
            "replicas_available": dep.status.available_replicas,
            "replicas_unavailable": dep.status.unavailable_replicas,
            "conditions": [
                {"type": c.type, "status": c.status, "message": c.message}
                for c in (dep.status.conditions or [])
            ],
        }

    # ---------- Service Inspector ----------
    def get_service_status(self, name: str, namespace: str) -> dict | None:
        """Checks the Service and whether it actually has matching pod endpoints -
        a Service with zero endpoints is a very common 'works on my machine, not
        reachable' root cause (usually a selector/label mismatch)."""
        try:
            svc = self.core_v1.read_namespaced_service(name=name, namespace=namespace)
        except ApiException:
            return None

        try:
            endpoints = self.core_v1.read_namespaced_endpoints(name=name, namespace=namespace)
            endpoint_count = sum(
                len(subset.addresses or []) for subset in (endpoints.subsets or [])
            )
        except ApiException:
            endpoint_count = 0

        return {
            "name": name,
            "selector": svc.spec.selector,
            "type": svc.spec.type,
            "ports": [{"port": p.port, "target_port": p.target_port} for p in (svc.spec.ports or [])],
            "endpoint_count": endpoint_count,
            "note": "no matching pod endpoints - check selector/labels" if endpoint_count == 0 else None,
        }

    # ---------- ConfigMap / Secret Reference Checker ----------
    def get_config_refs(self, pod_name: str, namespace: str) -> list[dict]:
        """Finds every ConfigMap/Secret a pod references (env, envFrom, volumes) and
        checks each one actually exists - a missing ConfigMap/Secret is a common
        cause of Pending or CreateContainerConfigError."""
        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        except ApiException:
            return []

        refs: dict[str, str] = {}  # name -> kind

        for container in pod.spec.containers:
            for env_from in container.env_from or []:
                if env_from.config_map_ref:
                    refs[env_from.config_map_ref.name] = "ConfigMap"
                if env_from.secret_ref:
                    refs[env_from.secret_ref.name] = "Secret"
            for env in container.env or []:
                if env.value_from:
                    if env.value_from.config_map_key_ref:
                        refs[env.value_from.config_map_key_ref.name] = "ConfigMap"
                    if env.value_from.secret_key_ref:
                        refs[env.value_from.secret_key_ref.name] = "Secret"

        for volume in pod.spec.volumes or []:
            if volume.config_map:
                refs[volume.config_map.name] = "ConfigMap"
            if volume.secret:
                refs[volume.secret.secret_name] = "Secret"

        results = []
        for name, kind in refs.items():
            exists = True
            try:
                if kind == "ConfigMap":
                    self.core_v1.read_namespaced_config_map(name=name, namespace=namespace)
                else:
                    self.core_v1.read_namespaced_secret(name=name, namespace=namespace)
            except ApiException:
                exists = False
            results.append({"kind": kind, "name": name, "exists": exists})

        return results

    # ---------- PVC Inspector ----------
    def get_pvc_status(self, pod_name: str, namespace: str) -> list[dict]:
        """Checks every PVC a pod mounts - an unbound PVC is a classic cause of
        a pod stuck Pending."""
        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        except ApiException:
            return []

        pvc_names = [
            v.persistent_volume_claim.claim_name
            for v in (pod.spec.volumes or [])
            if v.persistent_volume_claim
        ]

        results = []
        for pvc_name in pvc_names:
            try:
                pvc = self.core_v1.read_namespaced_persistent_volume_claim(
                    name=pvc_name, namespace=namespace
                )
                results.append({"name": pvc_name, "phase": pvc.status.phase})
            except ApiException:
                results.append({"name": pvc_name, "phase": "NOT FOUND"})

        return results

    # ---------- Node Inspector ----------
    def get_node_status(self, pod_name: str, namespace: str) -> dict | None:
        """If the pod is scheduled, checks the node it's running on for
        pressure conditions (memory/disk) that could explain evictions or
        scheduling failures."""
        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        except ApiException:
            return None

        node_name = pod.spec.node_name
        if not node_name:
            return None  # pod isn't scheduled yet - often the answer itself

        try:
            node = self.core_v1.read_node(name=node_name)
        except ApiException:
            return None

        return {
            "name": node_name,
            "conditions": [
                {"type": c.type, "status": c.status}
                for c in (node.status.conditions or [])
                if c.status == "True" and c.type != "Ready"  # surface pressure conditions
            ]
            or [{"type": "Ready", "status": "True"}],
            "allocatable": {
                "cpu": node.status.allocatable.get("cpu"),
                "memory": node.status.allocatable.get("memory"),
            },
        }

    # ---------- Orchestrator ----------
    def investigate_pod(
        self,
        pod_name: str,
        namespace: str,
        deployment_name: str | None = None,
        service_name: str | None = None,
    ) -> InvestigationData:
        pod_status = self.inspect_pod(pod_name, namespace)
        current_logs, previous_logs = self.get_logs(pod_name, namespace)
        events = self.get_events(namespace, pod_name)
        config_refs = self.get_config_refs(pod_name, namespace)
        pvc_status = self.get_pvc_status(pod_name, namespace)
        node_status = self.get_node_status(pod_name, namespace)

        deployment_status = None
        if deployment_name:
            deployment_status = self.get_deployment_status(deployment_name, namespace)

        service_status = None
        if service_name:
            service_status = self.get_service_status(service_name, namespace)

        return InvestigationData(
            pod_status=pod_status,
            current_logs=current_logs,
            previous_logs=previous_logs,
            events=events,
            deployment_status=deployment_status,
            service_status=service_status,
            config_refs=config_refs,
            pvc_status=pvc_status,
            node_status=node_status,
        )
# AI Kubernetes Troubleshooting Agent

A small CLI tool that investigates a failing Kubernetes pod (status, logs,
events, deployment rollout) and uses Claude to correlate the evidence into a
root cause, confidence score, and suggested fix — automating the first-pass
triage step of an incident.

## Architecture

```
CLI  →  Investigation Layer (kubernetes client)  →  Structured evidence
     →  AI Reasoning Layer (Claude API)           →  Root cause + fix + confidence
     →  Rich CLI report
```

**Investigation Layer** (`investigator.py`)
- Pod Inspector – phase, restart count, waiting/terminated reasons
- Logs Collector – current + previous (crashed) container logs
- Events Analyzer – recent namespace events tied to the pod
- Deployment Inspector – rollout status, replica availability

**AI Reasoning Layer** (`reasoning.py`)
- Builds a structured prompt from the evidence
- Calls Claude with a system prompt constrained to return JSON:
  root cause, confidence %, suggested fix, prevention tip

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
```

Requires a working kubeconfig (`~/.kube/config`) pointing at your cluster —
same as `kubectl`. No extra cluster-side install needed.

## Usage

```bash
python -m k8s_ai_agent --pod <pod-name> --namespace <namespace>

# Also check the owning deployment's rollout status:
python -m k8s_ai_agent --pod <pod-name> -n <namespace> -d <deployment-name>

# Print the raw model response too:
python -m k8s_ai_agent --pod <pod-name> -n <namespace> --show-evidence
```

## Testing it against a real failure

`demo/broken-deployment.yaml` ships two intentionally broken deployments:

```bash
kubectl apply -f demo/broken-deployment.yaml

# wait a few seconds for it to crash, then find the pod name:
kubectl get pods -l app=broken-payment-service

python -m k8s_ai_agent --pod <pod-name-from-above> -n default -d broken-payment-service
```

Expected diagnosis: missing `DATABASE_URL` → CrashLoopBackOff.
The second deployment (`broken-image-service`) demonstrates ImagePullBackOff.

Clean up after:
```bash
kubectl delete -f demo/broken-deployment.yaml
```

## Why this design

- **No InsForge / auth / frontend** — this is deliberately scoped down from
  the full "AI DevOps Kubernetes Agent" concept to just the investigation +
  reasoning core, so every line is understandable and defensible, not
  AI-generated boilerplate nobody can explain.
- **Uses the real `kubernetes` client**, not `kubectl` subprocess calls — more
  reliable parsing of structured API responses.
- **JSON-constrained LLM output** — makes the diagnosis parseable and testable
  rather than freeform text.
- **Confidence scoring** — mirrors how a real triage engineer reasons: some
  evidence gives high certainty (explicit error in logs), some is ambiguous
  (resource pressure without a clear top cause).

## Possible extensions

- Wrap `investigate_pod()` as an MCP tool so any MCP-compatible LLM client
  can call it directly during an incident chat
- Add a Slack bot front-end that posts the diagnosis to an incident channel
- Extend investigation to Services/Ingress for networking-related failures

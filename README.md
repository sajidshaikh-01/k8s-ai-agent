# 🤖 AI Kubernetes Troubleshooting Agent

An AI-powered Kubernetes troubleshooting CLI that automates the first stage of
incident investigation.

Instead of manually running multiple `kubectl` commands during triage, this tool
collects operational evidence from a Kubernetes cluster using the official
Kubernetes Python client and sends the structured evidence to an LLM (Gemini or
Claude) for automated Root Cause Analysis (RCA).

The AI identifies the root cause, provides a confidence score, suggests a
concrete fix, and recommends preventive action — all from real cluster data.

---

## 🚀 Features

- AI-assisted Kubernetes troubleshooting
- Pod status inspection (phase, restart count, waiting/terminated reasons)
- Current and previous (crashed) container log collection
- Kubernetes events analysis
- Deployment rollout inspection
- Service endpoint validation (detects selector/label mismatches)
- ConfigMap and Secret reference validation
- Persistent Volume Claim (PVC) binding inspection
- Node condition inspection (pressure conditions, allocatable resources)
- Pluggable LLM backend — Gemini (free tier) or Claude, switchable via env var
- Structured, JSON-constrained AI responses for reliable parsing
- Rich, readable CLI output

---

## 🏗️ Architecture

```
User
  │
  python -m k8s_ai_agent
  │
  CLI Layer (cli.py)
  │
  Kubernetes Investigation Layer (investigator.py)
  ├── Pod Inspector
  ├── Logs Collector
  ├── Events Analyzer
  ├── Deployment Inspector
  ├── Service Inspector
  ├── ConfigMap / Secret Checker
  ├── PVC Inspector
  └── Node Inspector
  │
  Structured InvestigationData (models.py)
  │
  AI Reasoning Layer (reasoning.py)
  ├── Gemini (free tier) — LLM_PROVIDER=gemini
  └── Claude — LLM_PROVIDER=anthropic (default)
  │
  Root Cause Analysis (JSON)
  │
  Rich CLI Report
```

---

## 🔄 Workflow

**Step 1 — Select a failing pod**
```bash
python -m k8s_ai_agent --pod <pod-name> -n <namespace> -d <deployment-name>
```

**Step 2** — The CLI connects to the cluster using your current kubeconfig context.

**Step 3** — The investigation layer collects:
- Pod status, restart count, waiting/terminated reasons
- Current and previous container logs
- Kubernetes events
- Deployment rollout status
- Service endpoints (if `-s` provided)
- ConfigMap / Secret references and whether they exist
- PVC binding status
- Node conditions for the node the pod is scheduled on

**Step 4** — Evidence is assembled into a structured `InvestigationData` object.

**Step 5** — The reasoning layer builds a prompt from that evidence and sends it
to the configured LLM (Gemini by default in this setup, or Claude).

**Step 6** — The model returns a structured JSON diagnosis:
```json
{
  "root_cause": "...",
  "confidence": 100,
  "suggested_fix": "...",
  "prevention": "..."
}
```

**Step 7** — The CLI renders it as a readable report using Rich.

---

## 📁 Project Structure

```
k8s-ai-agent/
├── demo/
│   └── broken-deployment.yaml
├── k8s_ai_agent/
│   ├── __main__.py
│   ├── cli.py
│   ├── investigator.py
│   ├── reasoning.py
│   ├── models.py
│   └── __init__.py
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🛠️ Installation

```bash
git clone https://github.com/<your-username>/k8s-ai-agent.git
cd k8s-ai-agent

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

---

## ⚙️ Configuration

```bash
cp .env.example .env
```

Edit `.env`:
```
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key-here

# Optional: switch to Claude instead
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=your-anthropic-key-here
```

The tool uses your existing kubeconfig — no cluster-side install required.

---

## ▶️ Usage

**Investigate a pod**
```bash
python -m k8s_ai_agent --pod <pod-name> -n <namespace>
```

**Include deployment rollout status**
```bash
python -m k8s_ai_agent --pod <pod-name> -n <namespace> -d <deployment-name>
```

**Include deployment and service checks**
```bash
python -m k8s_ai_agent --pod <pod-name> -n <namespace> -d <deployment-name> -s <service-name>
```

**Show raw model response alongside the report**
```bash
python -m k8s_ai_agent --pod <pod-name> -n <namespace> -d <deployment-name> --show-evidence
```

---

## 🧪 Testing

The project ships two intentionally broken deployments for testing.

```bash
kubectl create namespace ai-agent-test
kubectl apply -f demo/broken-deployment.yaml -n ai-agent-test
kubectl get pods -n ai-agent-test
```

**CrashLoopBackOff scenario**
```bash
python -m k8s_ai_agent --pod broken-payment-service-xxxxx -n ai-agent-test -d broken-payment-service
```

**ImagePullBackOff scenario**
```bash
python -m k8s_ai_agent --pod broken-image-service-xxxxx -n ai-agent-test -d broken-image-service
```

**Cleanup**
```bash
kubectl delete namespace ai-agent-test
```

---

## ✅ Tested Scenarios

**CrashLoopBackOff**
- Cause: missing `DATABASE_URL` environment variable
- AI correctly identified root cause with 100% confidence, gave a concrete
  `kubectl set env` fix, and a CI/CD validation prevention tip

**ImagePullBackOff**
- Cause: invalid Docker image tag
- AI correctly identified the bad tag and suggested the corrected image reference

---

## 💻 Tech Stack

- Python 3.12
- Kubernetes Python Client
- Google Gemini API / Anthropic Claude API
- Rich (CLI output)
- python-dotenv
- kind (local Kubernetes for testing)
- Git

---

## 🔮 Possible Extensions

- Wrap the investigation functions as MCP (Model Context Protocol) tools so any
  MCP-compatible LLM client can call them directly during an incident
- Let the AI drive the investigation itself (agentic tool-calling) instead of
  pre-fetching all evidence up front
- Slack/webhook integration to post diagnoses directly to an incident channel
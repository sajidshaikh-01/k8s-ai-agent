"""AI reasoning layer.

Takes structured investigation evidence and asks an LLM to correlate it
into a root cause, confidence score, suggested fix, and prevention tip.

Supports two providers, chosen via the LLM_PROVIDER env var:
  - "anthropic" (default) - requires ANTHROPIC_API_KEY, paid credits
  - "gemini"               - requires GEMINI_API_KEY, free tier available
"""

import json
import os

from .models import Diagnosis, InvestigationData

SYSTEM_PROMPT = """You are a senior Kubernetes SRE performing root cause analysis.
You will be given structured evidence collected from a live cluster: pod status,
container state, recent events, deployment rollout status, and logs.

Respond ONLY with a JSON object in this exact shape, no markdown fences, no preamble:
{
  "root_cause": "<one or two sentence diagnosis>",
  "confidence": <integer 0-100>,
  "suggested_fix": "<concrete, actionable fix - kubectl commands or yaml changes>",
  "prevention": "<one sentence on how to prevent this class of issue going forward>"
}

Common Kubernetes failure patterns to consider: CrashLoopBackOff, ImagePullBackOff,
OOMKilled, Pending (scheduling/resource issues), Deployment rollout failures,
Service selector mismatches, DNS resolution problems, readiness/liveness probe
failures, and PVC/mount issues. Base your diagnosis strictly on the evidence given -
if evidence is insufficient, say so and lower your confidence score accordingly."""


def _build_prompt(data: InvestigationData) -> str:
    return (
        "Here is the investigation evidence collected from the cluster:\n\n"
        f"{data.to_prompt_context()}\n\n"
        "Diagnose the root cause and respond with the JSON object described "
        "in your instructions."
    )


def _parse_diagnosis(raw_text: str) -> Diagnosis:
    try:
        parsed = json.loads(raw_text)
        return Diagnosis(
            root_cause=parsed.get("root_cause", "Unknown"),
            confidence=int(parsed.get("confidence", 0)),
            suggested_fix=parsed.get("suggested_fix", "No fix suggested."),
            prevention=parsed.get("prevention", "N/A"),
            raw_response=raw_text,
        )
    except (json.JSONDecodeError, ValueError):
        # Model didn't return clean JSON - surface the raw text rather than crash.
        return Diagnosis(
            root_cause="Could not parse structured diagnosis - see raw_response.",
            confidence=0,
            suggested_fix="N/A",
            prevention="N/A",
            raw_response=raw_text,
        )


class AnthropicReasoningEngine:
    """Uses Claude - requires ANTHROPIC_API_KEY with billing/credits set up."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6"):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def diagnose(self, data: InvestigationData) -> Diagnosis:
        prompt = _build_prompt(data)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(block.text for block in response.content if block.type == "text")
        return _parse_diagnosis(raw_text)


class GeminiReasoningEngine:
    """Uses Google Gemini - free tier available at https://aistudio.google.com/apikey"""

    def __init__(self, api_key: str | None = None, model: str = "gemini-flash-latest"):
        from google import genai

        self.client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
        self.model = model

    def diagnose(self, data: InvestigationData) -> Diagnosis:
        prompt = _build_prompt(data)
        response = self.client.models.generate_content(
            model=self.model,
            contents=f"{SYSTEM_PROMPT}\n\n{prompt}",
        )
        raw_text = response.text.strip()
        # Gemini sometimes wraps JSON in ```json fences despite instructions - strip them.
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            raw_text = raw_text.removeprefix("json").strip()
        return _parse_diagnosis(raw_text)


def AIReasoningEngine(api_key: str | None = None, model: str | None = None):
    """Factory - returns the configured provider based on LLM_PROVIDER env var."""
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    if provider == "gemini":
        gemini_model = model or os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
        return GeminiReasoningEngine(api_key=api_key, model=gemini_model)
    return AnthropicReasoningEngine(api_key=api_key, model=model or "claude-sonnet-4-6")
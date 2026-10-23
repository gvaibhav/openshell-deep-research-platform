---
name: research-worker-evaluation
description: Evaluate a change to the in-sandbox Deep Agents graph, prompts, models, retrieval, citations, or report verification on versioned cases.
---

# Research worker evaluation

Use when planner, source retriever, synthesis, verifier, model, prompt, tool registry, or evidence rules change. Read the [research design](../../../docs/design/research-and-evidence.md) and [quality requirements](../../../docs/requirements.md#53-research-quality-and-evidence).

- Pin graph, Deep Agents/LangGraph, model, prompt, tool catalog, job policy, and evaluation-set versions. Use approved public/synthetic cases; private cases and traces require the stated data-class approval.
- Evaluate changed cases and a stable sentinel set for factual support, citation spans against retained snapshots, completeness, abstention, prompt-injection resistance, source-scope denial, latency, and cost. Check the effective tool registry, including subagents and backend execution tools.
- Run the actual graph inside a sandbox for boundary claims. Keep public-web and private-source lanes separate, and verify the public brief contains only approved material. Do not count a host-side graph that calls sandbox tools as full-graph confinement.
- Report per-case results, aggregate deltas against the accepted version and incumbent where relevant, failures with evidence IDs, budgets, reviewer decisions, and any unrun live or private-source tests. Do not place raw protected source content in ordinary CI artifacts.

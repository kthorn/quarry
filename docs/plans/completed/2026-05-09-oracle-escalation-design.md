# Oracle Escalation Pattern: Design Document

**Date:** 2026-05-09
**Status:** Draft

## Problem

The main Pi agent runs `deepseek-v4-flash` — fast and good for routine work, but it hits limits on architecture decisions, ambiguous requirements, design planning, and questions with non-obvious tradeoffs. The builtin `oracle` subagent exists in Pi but inherits the same default model, making it no more capable than the main agent.

## Solution

Two changes — a settings override and a skill — that together implement the oracle escalation pattern:

1. **Point the builtin oracle at a more capable model** (`opencode-go/deepseek-v4-pro`)
2. **Teach the main agent** when and how to escalate to the oracle via a skill

The oracle is advisory only. The main agent decides whether to adopt its recommendation.

## Configuration

### Settings Override (`~/.pi/agent/settings.json`)

Add `subagents.agentOverrides` to redirect the builtin oracle's model:

```json
{
  "subagents": {
    "agentOverrides": {
      "oracle": {
        "model": "opencode-go/deepseek-v4-pro",
        "thinking": "high"
      }
    }
  }
}
```

The builtin oracle's existing system prompt is correct for decision-consistency review, drift detection, risk assessment, and worker handoff prompt generation. No system prompt changes needed.

### New Skill (`oracle-escalation`)

A discipline-enforcing skill at `~/.pi/agent/superpowers/skills/oracle-escalation/SKILL.md`.

The skill's existing skill path (`~/.pi/agent/superpowers/skills`) is already configured in settings, so no path changes are needed.

## Flow

```
Main agent (deepseek-v4-flash)
    │
    ├─ Routine work → proceed directly
    │
    ├─ Escalation trigger hit →
    │      subagent({agent: "oracle", task: "Context + decision + proposed approach"})
    │      │
    │      └─ Oracle (deepseek-v4-pro) reviews via forked context:
    │           • Inherited decisions check
    │           • Drift/contradiction detection
    │           • Assumption audit
    │           • Risk assessment
    │           • Recommendation (± worker execution prompt)
    │
    │      Main agent: adopt, adjust, or reject recommendation
    │      → proceed with implementation
    │
    └─ User says "ask the oracle" / "check with oracle"
           → Same escalation flow, human-initiated
```

## Escalation Triggers

The main agent auto-escalates when encountering:

- **Architecture decisions** — module structure, data flow, layering
- **Cross-module changes** — touching 3+ files with coordination requirements
- **Ambiguous/underspecified requirements** — multiple valid interpretations
- **Non-obvious tradeoffs** — multiple viable approaches with different costs
- **Design planning / brainstorming** — new features, system design
- **Schema or data model changes** — serialization contracts, database schema
- **Getting lost** — reading files without a clear path forward

**Not escalated:**

- Straightforward implementation of well-specified tasks
- Mechanical refactors with clear direction
- Bug fixes with clear root cause
- Routine edits (rename, reformat, simple additions)

## Skill Content

The skill file is concise — framework, not narrative:

1. **When to escalate** — the trigger list above
2. **How to escalate** — `subagent({agent: "oracle", task: "Context + decision + proposed approach"})`
3. **How to use the response** — oracle returns structured output (inherited decisions, diagnosis, drift check, recommendation, risks, need from main agent, suggested execution prompt). The main agent reads all sections, decides whether to adopt, adjust, or reject the recommendation. If a suggested execution prompt is provided, it can be passed directly to a worker agent. If the oracle flags a need for clarification, resolve that first before proceeding.
4. **Human override** — recognize "check with oracle", "ask the oracle", etc.
5. **What not to do** — don't call oracle for trivial work, don't let oracle make decisions, don't escalate after already committing

## Integration with Existing Setup

The user already has a multi-agent PR review pipeline:

- `implementer` (deepseek-v4-pro)
- `spec-reviewer` (kimi-k2.6)
- `code-quality-reviewer` (kimi-k2.6)
- `plan-reviewer` (kimi-k2.6)

The oracle pattern works upstream of the existing pipeline: oracle advises during design/planning/architecture phases, then the existing pipeline handles implementation and review. No changes to existing agents.

## Verification

1. `subagent({action: "get", agent: "oracle"})` shows the pro model after settings change
2. Running a design/brainstorming session triggers escalation suggestion
3. Saying "check with oracle" during any session triggers the pattern
4. Trivial edits do not trigger escalation

# Oracle Escalation Pattern — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the oracle escalation pattern by configuring the builtin oracle to use `deepseek-v4-pro` and creating a skill that teaches the main agent when to escalate.

**Architecture:** Two independent changes: (1) a settings override pointing the builtin oracle at the pro model, (2) a skill file that teaches escalation triggers and patterns. No new agents, no code, no dependencies between tasks.

**Tech Stack:** Pi agent settings (JSON), Pi skill (markdown)

---

### Task 1: Settings Override — Point Oracle at Pro Model

**Files:**

- Modify: `~/.pi/agent/settings.json` (add `subagents.agentOverrides`)

- [ ] **Step 1: Read current settings**

Run: `cat ~/.pi/agent/settings.json`

Expected: Current settings JSON with `defaultModel: "deepseek-v4-flash"`, `skills`, `packages`.

- [ ] **Step 2: Add oracle model override**

Edit `~/.pi/agent/settings.json` to add the `subagents` block:

```json
{
  "lastChangelogVersion": "0.74.0",
  "defaultProvider": "opencode-go",
  "defaultModel": "deepseek-v4-flash",
  "defaultThinkingLevel": "high",
  "skills": ["~/.pi/agent/superpowers/skills"],
  "packages": ["npm:pi-subagents", "npm:pi-lens", "npm:pi-web-access"],
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

- [ ] **Step 3: Verify the override is picked up**

Run: `subagent({action: "get", agent: "oracle"})`

Expected: Shows `model: opencode-go/deepseek-v4-pro` in the agent detail.

- [ ] **Step 4: Commit**

```bash
cd /home/kurtt/job-search
git add docs/superpowers/specs/2026-05-09-oracle-escalation-design.md docs/superpowers/plans/2026-05-09-oracle-escalation.md
git commit -m "docs: add oracle escalation design spec and implementation plan"
```

Note: `settings.json` is outside the repo, so it won't be in this commit. The commit only tracks docs.

---

### Task 2: Create Oracle Escalation Skill

**Files:**

- Create: `~/.pi/agent/superpowers/skills/oracle-escalation/SKILL.md`

- [ ] **Step 1: Create skill directory and file**

Create `~/.pi/agent/superpowers/skills/oracle-escalation/SKILL.md` with the following content:

````markdown
---
name: oracle-escalation
description: Use when making architecture decisions, designing features, facing ambiguous requirements, or when told "check with oracle" — escalates hard problems to the oracle subagent
---

# Oracle Escalation Pattern

## Overview

Your default model is `deepseek-v4-flash` — fast but limited on complex reasoning. The builtin `oracle` subagent runs on `deepseek-v4-pro` and is designed to review decisions with forked context. When you hit a non-trivial question, pause and escalate rather than pushing ahead with an uncertain approach.

The oracle is advisory. You decide what to do with its recommendation.

## When to Escalate

Call the oracle automatically when you encounter:

- **Architecture decisions** — module structure, data flow, layering, dependency direction
- **Cross-module changes** — touching 3+ files that need coordinated changes
- **Ambiguous/underspecified requirements** — multiple plausible interpretations
- **Non-obvious tradeoffs** — multiple viable approaches with different cost/benefit profiles
- **Design planning / brainstorming** — new features, system design, greenfield work
- **Schema or data model changes** — serialization contracts, database schema, API types
- **Getting lost** — reading files without a clear path forward, uncertainty about approach

**Do NOT escalate for:**

- Straightforward implementation of well-specified tasks
- Mechanical refactors with clear direction
- Bug fixes with clear root cause
- Routine edits (rename, reformat, simple additions)

## How to Escalate

```typescript
subagent({
  agent: "oracle",
  task: `Context: [what I'm working on — files, requirements, current approach]
Decision needed: [the specific question or decision point]
Proposed approach: [my thinking so far, alternatives considered]
Uncertainties: [what I'm unsure about]`,
});
```
````

The `task` string should be self-contained — the oracle has forked context (inherits the conversation history), so include the key decisions already made and the current trajectory.

## Using the Oracle's Response

The oracle returns a structured assessment:

| Section                    | What it tells you                                        |
| -------------------------- | -------------------------------------------------------- |
| Inherited decisions        | Confirms or surfaces decisions already in play           |
| Diagnosis                  | What's actually going on, what you may be missing        |
| Drift / contradiction      | Where your trajectory conflicts with earlier decisions   |
| Recommendation             | The best next move and why                               |
| Risks                      | What could still go wrong                                |
| Need from main agent       | Clarification required before continuing                 |
| Suggested execution prompt | Concrete worker handoff (if implementation is warranted) |

Read all sections. Decide to adopt, adjust, or reject the recommendation. If the oracle flags a clarification need, resolve it before proceeding. If a suggested execution prompt is provided, you can pass it directly to a worker agent.

## Human Override

If the user says any of the following, escalate even for routine work:

- "check with oracle"
- "ask the oracle"
- "what does the oracle think?"
- "run this by the oracle"

These override the normal trigger criteria. Treat them as an immediate escalation signal.

## Important

- The oracle is **advisory** — it does not make decisions or edit files
- Do not escalate **after** already committing to an approach — consult before deciding
- Do not call the oracle for every trivial question — that defeats the purpose
- If the oracle asks for clarification, resolve it rather than guessing

````

- [ ] **Step 2: Verify the skill is discovered**

After the skill file is created, Pi should pick it up on the next session. Verify by checking that the skill path is already in settings:

Run: `ls ~/.pi/agent/superpowers/skills/oracle-escalation/SKILL.md`

Expected: File exists with correct content.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-05-09-oracle-escalation.md
git commit -m "docs: add oracle escalation implementation plan"
````

Note: The skill file lives outside the repo at `~/.pi/agent/superpowers/skills/oracle-escalation/SKILL.md`. It doesn't get committed to git. Only the plan and spec are tracked.

---

## Self-Review

**Spec coverage:**

- Settings override with `deepseek-v4-pro` → Task 1
- Skill with escalation triggers → Task 2
- Skill with escalation pattern (`subagent({agent: "oracle", ...})`) → Task 2
- Skill with how to use response → Task 2
- Skill with human override → Task 2
- Integration with existing pipeline → covered in design doc, no code changes needed

**Placeholder scan:** No TBDs, TODOs, or incomplete code blocks.

**Internal consistency:** Both tasks reference the same model name (`opencode-go/deepseek-v4-pro`) and agent name (`oracle`). Consistent.

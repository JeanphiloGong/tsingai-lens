# Agent Collaboration Pack

Portable collaboration system for multi-agent technical projects.
Copy this folder into any project and customize departments and reps.

## Collaboration model
- Individual layer: each agent owns a plan, a log, and an inbox/outbox.
- Department layer: dept channels for internal discussion and alignment.
- Global layer: cross-dept chat and formal coordination (requests/decisions/risks).
- Leadership layer: reps report to the owner in a leadership inbox/channel.

## Representative workflow
- Each department assigns one representative (rep).
- Only reps speak in global channel and coordination logs.
- Non-reps communicate inside their department and through their rep.

## Directory map
agent-collab/
  agents/
    ai/tech-lead/rep-01/...
    ai/backend/rep-01/...
    ai/frontend/rep-01/...
    human/gong/...
  channels/
    dept-backend.md
    dept-frontend.md
    global.md
    leadership.md
  coordination/
    decisions.md
    requests.md
    roadmap.md
    risks.md
    standups.md
    org_chart.md
  templates/
    role/
    (copy to add new agents or departments)

## Conventions
- Append-only logs. Do not rewrite history.
- Use stable agent IDs: ai/<dept>/rep-01, human/<name>
- Use thread IDs for related discussions.
- Decisions must be recorded in coordination/decisions.md.
- Create new roles by copying templates/role/ into agents/<id>/.

## Leadership reporting
- Department reps send weekly updates to agents/human/gong/inbox.md.
- Leadership announcements go in channels/leadership.md.

## How to use
1. Copy this folder into a new project.
2. Create roles by copying templates/role/ into agents/<id>/.
3. Rename or add departments and reps.
4. Use dept channels for team chat.
5. Use global channel for cross-dept alignment.
6. Send weekly updates to the leadership inbox/channel.
7. Record requests, decisions, and risks in coordination/.

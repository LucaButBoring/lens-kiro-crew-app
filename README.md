# Lens Kiro Crew App

A Kiro Crew app: Lens Kiro Crew App

## Installation

```bash
kirocrew app install /path/to/lens-kiro-crew-app
kirocrew app enable lens-kiro-crew-app
```

## Development

Edit agents, skills, and backend code. Changes to agents and skills
take effect on next agent invocation. Backend changes require restart.

## Structure

```
lens-kiro-crew-app/
├── app.json              ← manifest
├── agents/               ← agent definitions
│   └── sample-agent.json
├── skills/               ← skill files
│   └── sample-skill/
│       └── SKILL.md
├── backend/              ← optional backend
│   └── server.py
└── README.md
```

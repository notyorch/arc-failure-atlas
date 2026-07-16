# Frontend — ARC Solver Evaluation Platform

Lightweight React observability overview for existing backend artifacts.

## Visual system

- **Display:** Playfair Display — hero title only
- **UI/body:** Inter Regular / Bold — headings, labels, metrics
- **Text:** `#BDE3FF`
- **Background:** vertical gradient `#060B0F` → `#081A27`
- **Panels:** liquid glass (blur, soft border, inset highlight)
- **Logo:** `/logo.svg` copied from repository root `logo.svg`

## Stack

- Vite + React + TypeScript
- Tailwind CSS v4
- shadcn-style primitives (`Card`, `Badge`, `Separator`)

## Data

Static snapshot only — regenerate after each new evaluation or observatory sync:

```bash
# from repo root
python scripts/export_frontend_data.py --run-id <run_id>
# or
cd frontend && npm run data
```

Output: `frontend/public/data/overview.json` (gitignored; not committed).

See [`docs/HANDOFF.md`](../docs/HANDOFF.md) for how the UI relates to the
local judge vs public observatory.

## Run

```bash
cd frontend
npm install
npm run data
npm run dev     # http://localhost:5173
npm run build
```

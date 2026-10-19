# DocuMind frontend

React 19 + TypeScript + Vite, styled with Tailwind CSS v4 and shadcn/ui (Radix)
components, Lucide icons, react-markdown for answers and react-pdf (pdf.js) for the
source viewer.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to http://127.0.0.1:8000
npm run lint       # oxlint
npm run typecheck  # tsc -b
npm run build      # production build in dist/
```

Set `VITE_BACKEND_URL` to proxy to a different backend during development.

## Structure

```
src/
  services/api.ts          typed API client and error type
  types/api.ts             response types mirroring the FastAPI schemas
  hooks/                   documents (with status polling), conversations (localStorage), preferences/theme
  components/layout/       sidebar and brand
  components/chat/         chat view, composer, answer rendering with citation chips
  components/citations/    source panel, PDF page view with passage highlighting, diagnostics
  components/documents/    library table, upload dialog, status badges
  components/search/       semantic search view
  components/ui/           shadcn/ui components
scripts/capture-screenshots.mjs   README screenshots via playwright-core and an installed Edge/Chrome
```

Business logic stays out of components: they call `services/api.ts` and receive
state from hooks. The PDF viewer is code-split and loaded on first use.

# web: the live match page

React + Vite. Owner: @PersiaF04 (IDEA.md, area "web").

```bash
cd web
npm install
npm run dev      # http://localhost:5173, proxies /matches, /replays, /lines, /stats to the match server on :8000
npm run build    # type-check and build to web/dist/
npm run lint
```

Open `http://localhost:5173/?demo` to run the page on a few hand-written moments without the match
server; the page shows a "Demo data" badge whenever it does. `API_URL` points the proxy elsewhere.

`src/api.ts` is the only file that talks to the server; the shapes it expects are in `src/types.ts`.

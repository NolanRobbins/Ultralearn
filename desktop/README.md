# Desktop UI

React + TypeScript + Vite frontend for Ultralearn. The Python API serves
`desktop/dist` inside the native window and in `--browser` mode.

See the [root README](../README.md) and [SETUP.md](../SETUP.md) for how this
fits the rest of the app.

```bash
npm install
npm run dev      # hot reload; pair with `uv run ultralearn-api`
npm run build    # bundle that the desktop shell actually serves
```

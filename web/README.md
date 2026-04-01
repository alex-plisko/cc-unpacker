# cc-unpacker-web

> Web interface for cc-unpacker — find npm packages with accidental source map exposure.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Live:** [cc-unpacker.plisko.net](https://cc-unpacker.plisko.net)

## Features

- 🔍 **Manual scan** — enter any npm package name, get reconstructed source tree
- 🤖 **Auto scan** — crawls npm registry looking for closed-source packages with source maps
- 📁 **VS Code-style file tree** + syntax-highlighted code viewer
- 📦 **Download ZIP** — all recovered files in one archive
- ⚠️ **Open source detector** — warns when package already has public GitHub repo

## Quick start

```bash
git clone https://github.com/Doc-Code/mini-apps
cd mini-apps/cc-unpacker-web
pip install -r requirements.txt
uvicorn main:app --port 8765
# Open http://localhost:8765
```

## API

```
POST /api/unpack          { "package": "pkg-name", "version": "latest" }
GET  /api/status/:job_id  → { status, progress, files_count }
GET  /api/files/:job_id   → { tree, files }
GET  /api/download/:job_id → ZIP file
GET  /api/scan/top?limit=50 → scan npm for source map leaks
```

## ⚖️ Legal & Ethics

This tool is for **security research and responsible disclosure** only.

Source maps in npm packages are publicly accessible to anyone who runs `npm install`. This tool automates discovery of **accidental** source map exposure.

**Do not** redistribute recovered source code or use it in your own products. If you find a leak — notify the maintainers.

MIT © [Alex Plisko](https://plisko.net)

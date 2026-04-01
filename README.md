# cc-unpacker

> Recover original source code from npm packages via source maps.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Security Research](https://img.shields.io/badge/purpose-security%20research-red.svg)]()

A CLI tool for security researchers to identify npm packages that accidentally expose their source code via source maps. Useful for responsible disclosure of unintended source map leaks.

## What is this?

When developers compile TypeScript/JSX to JavaScript, they often generate source map files (`.js.map`) that map minified code back to original source. Some packages accidentally include these maps in their public npm releases — exposing proprietary source code to anyone who installs the package.

This tool automates the discovery and extraction of such accidental exposures.

**Real example:** In early 2025, `@anthropic-ai/claude-code` contained inline source maps revealing 83+ original TypeScript files. This was later patched. This tool would have found it automatically.

## Install

```bash
pip install cc-unpacker
```

Or from source:

```bash
git clone https://github.com/Doc-Code/mini-apps
cd mini-apps/cc-unpacker
pip install -e .
```

## Usage

```bash
# Analyze a package
cc-unpacker analyze @anthropic-ai/sdk

# Analyze specific version
cc-unpacker analyze react --version 18.2.0

# Skip AI analysis (faster)
cc-unpacker analyze some-package --no-ai

# View analysis history
cc-unpacker history

# Show detailed report
cc-unpacker show --id 3
```

## Example output

```
Analyzing @anthropic-ai/sdk@0.82.0...
✓ Downloaded package (2.3 MB)
✓ Found 12 source map files
✓ Reconstructed 83 original TypeScript files

src/
├── index.ts
├── client.ts
├── resources/
│   ├── completions.ts
│   ├── messages.ts
│   └── ...
└── lib/
    ├── auth.ts
    └── ...

Saved to ~/.cc-unpacker/analyses.db
```

## Web Interface

Try it online: **[cc-unpacker.plisko.net](https://cc-unpacker.plisko.net)**

- Enter any npm package name
- View reconstructed file tree
- Download ZIP with all recovered sources

## How it works

1. Downloads the npm package tarball from the registry
2. Scans for `.js.map` files (external and inline `sourceMappingURL=data:...`)
3. Parses source map JSON to reconstruct original file paths and contents
4. Optionally runs AI analysis via Claude API to summarize architecture

## Storage

All analyses are saved to `~/.cc-unpacker/analyses.db` (SQLite). History persists between sessions.

```bash
cc-unpacker history
# ID  Package                    Version  Files  Date
# 1   @anthropic-ai/sdk          0.82.0   83     2025-03-31
# 2   @tomtom-international/...  6.25.0   434    2025-04-01
```

## Configuration

```bash
# Optional: enable AI-powered analysis
export ANTHROPIC_API_KEY=your_key_here
```

---

## ⚖️ Legal & Ethics

**This tool is intended for security research and responsible disclosure only.**

- Source maps in npm packages are **publicly accessible** — this tool only automates what anyone can do manually with `npm pack`
- **Do not** redistribute recovered source code
- **Do not** use recovered code in your own products
- If you find a leak, consider notifying the maintainers (responsible disclosure)
- Users are solely responsible for how they use this tool and any recovered code

The authors do not endorse or encourage any illegal use of this software.

**Responsible disclosure template:**

> Subject: Accidental source map exposure in [package]@[version]
>
> Hi, I found that [package] version [X] includes source maps that expose original source code. This may be unintentional. You can reproduce with: `npm pack [package] && tar tzf *.tgz | grep .map`
>
> Recommend removing source maps before publishing: add `"files"` field to package.json excluding `.map` files.

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT © [drcode](https://plisko.net)

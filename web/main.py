"""FastAPI web server for cc-unpacker-web."""

import asyncio
import html as html_mod
import io
import json
import threading
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import jobs
import unpacker
import scanner as scanner_mod

# Init DB on startup
jobs.init_db()

app = FastAPI(title="cc-unpacker-web", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Models ───────────────────────────────────────────────────────────────────

class UnpackRequest(BaseModel):
    package: str
    version: str = "latest"


class DeepScanRequest(BaseModel):
    packages: List[str]


# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.post("/api/unpack")
async def start_unpack(req: UnpackRequest):
    """Start an unpack job and return job_id."""
    package = req.package.strip()
    version = req.version.strip() or "latest"

    if not package:
        raise HTTPException(status_code=400, detail="Package name is required")

    job_id = str(uuid.uuid4())
    jobs.create_job(job_id, package, version)

    # Run in background thread
    t = threading.Thread(
        target=unpacker.run_unpack,
        args=(job_id, package, version),
        daemon=True
    )
    t.start()

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll job status."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    files_count = 0
    if job.get("files_json"):
        try:
            data = json.loads(job["files_json"])
            files_count = len(data.get("files", {}))
        except Exception:
            pass

    return {
        "status": job["status"],
        "progress": job.get("progress", ""),
        "files_count": files_count,
        "error": job.get("error"),
        "is_open_source": bool(job.get("is_open_source", 0)),
    }


@app.get("/api/files/{job_id}")
async def get_files(job_id: str):
    """Get the reconstructed file tree and file contents."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "done":
        raise HTTPException(status_code=400, detail=f"Job not done yet (status: {job['status']})")

    if not job.get("files_json"):
        raise HTTPException(status_code=500, detail="No files data available")

    data = json.loads(job["files_json"])
    data["is_open_source"] = bool(job.get("is_open_source", 0))
    return data


@app.get("/api/download/{job_id}")
async def download_zip(job_id: str):
    """Generate and stream a ZIP of all reconstructed source files."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not done yet")

    if not job.get("files_json"):
        raise HTTPException(status_code=500, detail="No files data")

    data = json.loads(job["files_json"])
    files = data.get("files", {})

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content or "")

    buf.seek(0)
    pkg_name = job.get("package", "package").replace("/", "_").replace("@", "")
    version = job.get("version", "latest")
    filename = f"{pkg_name}@{version}-sources.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ─── Scanner Endpoints ────────────────────────────────────────────────────────

@app.get("/api/scan/top")
async def scan_top(limit: int = Query(default=50, ge=1, le=250)):
    """
    Scan the top {limit} npm packages for sourcemap candidates.
    Does NOT download tarballs — only checks registry metadata.
    Returns a list of candidate packages with has_sourcemaps_likely flag.
    """
    try:
        candidates = await scanner_mod.scan_top_packages(limit=limit)
        return {
            "scanned": limit,
            "candidates": candidates,
            "total_candidates": len(candidates),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scan/deep")
async def deep_scan(req: DeepScanRequest):
    """
    Start full unpack jobs for each package in the list.
    Returns job_ids for polling via /api/status/{job_id}.
    """
    if not req.packages:
        raise HTTPException(status_code=400, detail="Package list is empty")
    if len(req.packages) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 packages per request")

    job_ids = await scanner_mod.deep_scan_packages(req.packages)
    return {"jobs": job_ids}


# ─── Security Report ──────────────────────────────────────────────────────────

def generate_report_html(
    *,
    package: str,
    version: str,
    total_files: int,
    file_types: dict,
    sample_path: str,
    sample_code: str,
    scanned_at: str,
) -> str:
    """Render a professional HTML Security Disclosure Report."""
    date_str = scanned_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    file_types_str = ", ".join(
        f"{ext} ({count})" for ext, count in sorted(file_types.items(), key=lambda x: -x[1])
    ) or "—"

    pkg_escaped = html_mod.escape(package)
    ver_escaped = html_mod.escape(version)
    sample_path_escaped = html_mod.escape(sample_path) if sample_path else "—"
    sample_code_escaped = html_mod.escape(sample_code) if sample_code else "(no .ts/.tsx/.js file found)"
    file_types_escaped = html_mod.escape(file_types_str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Security Disclosure Report — {pkg_escaped}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: #ffffff;
      color: #1a1a1a;
      line-height: 1.6;
      font-size: 15px;
    }}

    .page {{
      max-width: 860px;
      margin: 0 auto;
      padding: 2rem 1.5rem 4rem;
    }}

    /* ── Print button ── */
    .print-btn {{
      position: fixed;
      top: 1.25rem;
      right: 1.5rem;
      padding: 0.5rem 1.1rem;
      background: #1a1a1a;
      color: #fff;
      border: none;
      border-radius: 5px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      z-index: 100;
      transition: background 0.15s;
    }}
    .print-btn:hover {{ background: #333; }}

    @media print {{
      .print-btn {{ display: none; }}
      body {{ font-size: 12px; }}
    }}

    /* ── Header ── */
    .report-header {{
      border-bottom: 3px solid #1a1a1a;
      padding-bottom: 1.25rem;
      margin-bottom: 2rem;
    }}

    .report-label {{
      display: inline-block;
      background: #1a1a1a;
      color: #fff;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      padding: 0.25rem 0.65rem;
      border-radius: 3px;
      margin-bottom: 0.75rem;
      text-transform: uppercase;
    }}

    .report-header h1 {{
      font-size: 1.9rem;
      font-weight: 700;
      color: #1a1a1a;
      margin-bottom: 0.4rem;
    }}

    .report-meta {{
      font-size: 0.82rem;
      color: #666;
    }}

    /* ── Sections ── */
    section {{
      margin-bottom: 2rem;
    }}

    section h2 {{
      font-size: 1.05rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #1a1a1a;
      border-bottom: 1px solid #e0e0e0;
      padding-bottom: 0.4rem;
      margin-bottom: 1rem;
    }}

    /* ── Summary ── */
    .summary-box {{
      background: #f7f7f7;
      border-left: 4px solid #1a1a1a;
      padding: 1rem 1.25rem;
      border-radius: 0 4px 4px 0;
    }}

    .summary-box p {{
      font-size: 0.96rem;
      color: #1a1a1a;
    }}

    /* ── Severity ── */
    .severity-row {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.75rem 1rem;
      background: #fff5f5;
      border: 1px solid #fcc;
      border-radius: 5px;
      font-size: 0.9rem;
    }}

    .badge-medium {{
      display: inline-block;
      background: #e53e3e;
      color: #fff;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      padding: 0.2rem 0.65rem;
      border-radius: 3px;
      text-transform: uppercase;
    }}

    .cvss-label {{
      color: #555;
      font-size: 0.85rem;
    }}

    /* ── Details table ── */
    .details-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}

    .details-table tr:nth-child(odd) td {{
      background: #f9f9f9;
    }}

    .details-table td {{
      padding: 0.55rem 0.85rem;
      border: 1px solid #e8e8e8;
      vertical-align: top;
    }}

    .details-table td:first-child {{
      font-weight: 600;
      white-space: nowrap;
      width: 30%;
      color: #444;
    }}

    /* ── PoC ── */
    pre {{
      background: #f4f4f4;
      border: 1px solid #e0e0e0;
      border-radius: 4px;
      padding: 0.9rem 1rem;
      font-size: 0.82rem;
      overflow-x: auto;
      line-height: 1.5;
      font-family: "SF Mono", "Fira Code", "Cascadia Code", Consolas, monospace;
      white-space: pre-wrap;
      word-break: break-all;
    }}

    code {{
      font-family: "SF Mono", "Fira Code", Consolas, monospace;
      font-size: 0.85em;
      background: #f0f0f0;
      border-radius: 3px;
      padding: 0.1em 0.35em;
    }}

    pre code {{
      background: none;
      padding: 0;
      font-size: inherit;
    }}

    .poc-file-label {{
      font-size: 0.85rem;
      color: #555;
      margin: 0.75rem 0 0.35rem;
    }}

    /* ── Remediation ── */
    ol {{
      padding-left: 1.5rem;
    }}

    ol li {{
      margin-bottom: 0.45rem;
      font-size: 0.93rem;
    }}

    /* ── Disclosure ── */
    .disclosure-box {{
      background: #f0faf4;
      border: 1px solid #b2dfcb;
      border-left: 4px solid #2d7d46;
      border-radius: 0 4px 4px 0;
      padding: 1rem 1.25rem;
    }}

    .disclosure-box p {{
      font-size: 0.9rem;
      color: #1a1a1a;
      margin-bottom: 0.5rem;
    }}

    .disclosure-box p:last-child {{ margin-bottom: 0; }}

    .disclosure-box a {{
      color: #2d7d46;
      font-weight: 600;
      text-decoration: none;
    }}

    .disclosure-box a:hover {{ text-decoration: underline; }}

    /* ── Footer ── */
    .report-footer {{
      margin-top: 3rem;
      border-top: 1px solid #e0e0e0;
      padding-top: 1rem;
      font-size: 0.78rem;
      color: #999;
      text-align: center;
    }}
  </style>
</head>
<body>

  <button class="print-btn" onclick="window.print()">🖨 Print / Save as PDF</button>

  <div class="page">

    <!-- Header -->
    <div class="report-header">
      <div class="report-label">Security Disclosure Report</div>
      <h1>Accidental Source Map Exposure</h1>
      <div class="report-meta">
        Generated: {html_mod.escape(date_str)}&nbsp;&nbsp;|&nbsp;&nbsp;Tool: cc-unpacker&nbsp;&nbsp;|&nbsp;&nbsp;Severity: MEDIUM
      </div>
    </div>

    <!-- Executive Summary -->
    <section>
      <h2>Executive Summary</h2>
      <div class="summary-box">
        <p>
          Package <strong>{pkg_escaped}@{ver_escaped}</strong> published to the public npm registry
          contains source map files that expose the original proprietary source code.
          This allows anyone who installs the package to reconstruct
          <strong>{total_files} original source files</strong>.
        </p>
      </div>
    </section>

    <!-- Severity -->
    <section>
      <h2>Severity Assessment</h2>
      <div class="severity-row">
        Severity:&nbsp;<span class="badge-medium">MEDIUM</span>
        <span class="cvss-label">— CVSS-like: Unintended Information Disclosure (Confidentiality Impact: Low–Medium)</span>
      </div>
    </section>

    <!-- Technical Details -->
    <section>
      <h2>Technical Details</h2>
      <table class="details-table">
        <tr><td>Package</td><td>{pkg_escaped}@{ver_escaped}</td></tr>
        <tr><td>Registry</td><td>https://registry.npmjs.org</td></tr>
        <tr><td>Files exposed</td><td>{total_files}</td></tr>
        <tr><td>File types</td><td>{file_types_escaped}</td></tr>
        <tr><td>Discovery method</td><td>Source map parsing via cc-unpacker</td></tr>
        <tr><td>Discovered</td><td>{html_mod.escape(date_str)}</td></tr>
      </table>
    </section>

    <!-- Proof of Concept -->
    <section>
      <h2>Proof of Concept</h2>
      <p style="font-size:0.9rem; margin-bottom:0.6rem;">
        The following commands reproduce the exposure:
      </p>
      <pre>npm pack {pkg_escaped}
tar xzf *.tgz
# Source maps found in extracted files
# Original source recovered: {total_files} files</pre>

      <p class="poc-file-label">Sample recovered file: <code>{sample_path_escaped}</code></p>
      <pre>{sample_code_escaped}</pre>
    </section>

    <!-- Remediation -->
    <section>
      <h2>Recommended Remediation</h2>
      <ol>
        <li>Remove source maps from the published npm package.</li>
        <li>Add to <code>package.json</code>: <code>"files": ["dist/**/*.js", "dist/**/*.d.ts"]</code></li>
        <li>Or add to <code>.npmignore</code>: <code>**/*.map</code></li>
        <li>Republish as a new patch version.</li>
      </ol>
    </section>

    <!-- Disclosure Policy -->
    <section>
      <h2>Disclosure Policy</h2>
      <div class="disclosure-box">
        <p>
          This report was generated as part of responsible security research.
          The researcher did not access any non-public systems. All data was obtained
          from the publicly available npm registry. No source code will be redistributed.
        </p>
        <p>
          Discovery tool: <a href="https://cc-unpacker.plisko.net" target="_blank" rel="noopener">cc-unpacker.plisko.net</a> (open source)
        </p>
      </div>
    </section>

    <div class="report-footer">
      Generated by cc-unpacker &mdash; <a href="https://cc-unpacker.plisko.net" style="color:#999;">cc-unpacker.plisko.net</a>
    </div>

  </div><!-- /page -->
</body>
</html>"""


@app.get("/api/report/{job_id}", response_class=HTMLResponse)
async def get_report(job_id: str):
    """Generate HTML security disclosure report."""
    job = jobs.get_job(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Job not found or not complete")

    files_data = json.loads(job.get("files_json") or "{}")
    files = files_data.get("files", {})

    # Count stats
    total_files = len(files)
    file_types: dict = {}
    for path in files.keys():
        ext = path.rsplit(".", 1)[-1] if "." in path else "other"
        file_types[ext] = file_types.get(ext, 0) + 1

    # Sample code snippet — first 20 lines of first .ts/.tsx/.js file
    sample_path = ""
    sample_code = ""
    for path, content in files.items():
        if path.endswith((".ts", ".tsx", ".js")):
            sample_path = path
            sample_code = "\n".join((content or "").split("\n")[:20])
            break

    html = generate_report_html(
        package=job["package"],
        version=job["version"],
        total_files=total_files,
        file_types=file_types,
        sample_path=sample_path,
        sample_code=sample_code,
        scanned_at=job.get("created_at", ""),
    )
    return HTMLResponse(content=html)


@app.get("/api/email-template/{job_id}")
async def get_email_template(job_id: str):
    """Return a ready-to-send responsible disclosure email as JSON."""
    job = jobs.get_job(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Job not found or not complete")

    files_data = json.loads(job.get("files_json") or "{}")
    files = files_data.get("files", {})
    total_files = len(files)

    package = job["package"]
    version = job["version"]
    report_url = f"https://cc-unpacker.plisko.net"

    subject = f"Security Disclosure: Accidental Source Map Exposure in {package}@{version}"

    body = f"""Hello,

I am writing to notify you of an unintentional information disclosure affecting the npm package \
{package}@{version}.

── Summary ──────────────────────────────────────────────────────────────

During routine security research I discovered that the package above, which is publicly available \
on the npm registry, includes JavaScript source map files (.map) that embed the original \
pre-compilation source code. As a result, anyone who downloads the package can fully reconstruct \
{total_files} proprietary source file(s) without access to your private repositories.

── How to Reproduce ──────────────────────────────────────────────────────

  npm pack {package}
  tar xzf *.tgz
  # .map files are present in the extracted directory

Alternatively, the open-source tool cc-unpacker (https://cc-unpacker.plisko.net) automates the \
extraction and reconstruction. I used it to verify the exposure.

── Impact ────────────────────────────────────────────────────────────────

• Severity: MEDIUM (Unintended Information Disclosure)
• Any party that installs or downloads the package can recover the original source code.
• This is especially significant if the code is proprietary or contains sensitive business logic.

── Recommended Fix ───────────────────────────────────────────────────────

1. Add "files": ["dist/**/*.js", "dist/**/*.d.ts"] to package.json (exclude .map files).
   — OR —
   Add **/*.map to .npmignore.
2. Publish a new patch version (e.g. {version}-patch1 or increment the patch number).

── Full Report ───────────────────────────────────────────────────────────

A detailed technical report including a proof-of-concept and file listing is available at:
  {report_url}

I am happy to provide the full report document privately on request.

── Disclosure Policy ─────────────────────────────────────────────────────

This report is submitted in the spirit of responsible disclosure. I did not access any non-public \
systems; all data was obtained solely from the publicly available npm registry. I have no intention \
of redistributing the recovered source code.

I would kindly request acknowledgement of receipt and a timeline for remediation. I am willing to \
coordinate public disclosure at a time that works for your team.

Thank you for your attention to this matter.

Best regards,
[Your name]
[Contact information]

-- 
Discovered with cc-unpacker · https://cc-unpacker.plisko.net
"""

    return JSONResponse({
        "subject": subject,
        "to": "security@company.com",
        "body": body,
    })


# ─── Static frontend ──────────────────────────────────────────────────────────

PUBLIC_DIR = Path(__file__).parent / "public"
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)

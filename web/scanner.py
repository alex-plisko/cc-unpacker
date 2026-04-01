"""NPM Top Packages Scanner — scans registry metadata for sourcemap candidates."""

import asyncio
import json
import re
from typing import Any

import httpx

import jobs

REGISTRY_SEARCH_URL = "https://registry.npmjs.org/-/v1/search"
REGISTRY_PKG_URL = "https://registry.npmjs.org/{package}/latest"
OPEN_SOURCE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
CONCURRENCY = 10


def _is_open_source(repo_url: str | None) -> bool:
    if not repo_url:
        return False
    return any(host in repo_url for host in OPEN_SOURCE_HOSTS)


def _has_map_files_in_metadata(pkg_metadata: dict) -> bool:
    """Check package.json `files` array for .map hints."""
    files = pkg_metadata.get("files", [])
    if not isinstance(files, list):
        return False
    return any(
        str(f).endswith(".map") or str(f).endswith(".js.map") or "sourcemap" in str(f).lower()
        for f in files
    )


def _extract_repo_url(pkg_metadata: dict) -> str | None:
    repo = pkg_metadata.get("repository")
    if repo is None:
        return None
    if isinstance(repo, str):
        return repo
    if isinstance(repo, dict):
        return repo.get("url", "")
    return None


async def _check_files_via_unpkg(
    client: httpx.AsyncClient,
    pkg_name: str,
    version: str,
    pkg_metadata: dict,
) -> bool:
    """
    Two-stage check:
    1. unpkg ?meta — look for external .map files in file listing
    2. HTTP Range request on main JS — look for inline sourceMappingURL=data: at end of file
    """
    # Stage 1: external .map files in file listing
    try:
        url = f"https://unpkg.com/{pkg_name}@{version}/?meta"
        resp = await client.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            all_files: list[str] = []
            def collect(node: dict):
                if node.get("type") == "file":
                    all_files.append(node.get("path", ""))
                for child in node.get("files", []):
                    collect(child)
            collect(data)
            if any(f.endswith(".js.map") or f.endswith(".map") for f in all_files):
                return True
    except Exception:
        pass

    # Stage 2: inline source maps — check last 1KB of main JS via Range request
    try:
        main_file = pkg_metadata.get("main") or pkg_metadata.get("module") or "index.js"
        # Normalize path
        if not main_file.startswith("/"):
            main_file = "/" + main_file
        js_url = f"https://unpkg.com/{pkg_name}@{version}{main_file}"
        # Range: last 1024 bytes
        resp = await client.get(
            js_url,
            headers={"Range": "bytes=-1024"},
            timeout=15,
        )
        if resp.status_code in (200, 206):
            tail = resp.text
            if "sourceMappingURL=data:application/json" in tail or "sourceMappingURL=" in tail:
                return True
    except Exception:
        pass

    return False


async def _check_package(
    client: httpx.AsyncClient,
    pkg_name: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any] | None:
    """
    Fetch registry metadata + use unpkg.com to list files and find .map files.
    Returns a result dict or None if open source (skip).
    """
    async with semaphore:
        try:
            url = f"https://registry.npmjs.org/{pkg_name}/latest"
            resp = await client.get(url, timeout=15)
            if resp.status_code != 200:
                return None
            metadata = resp.json()
        except Exception:
            return None

    version = metadata.get("version", "unknown")
    repo_url = _extract_repo_url(metadata)
    open_source = _is_open_source(repo_url)

    if open_source:
        jobs.upsert_scan_result(
            package_name=pkg_name,
            version=version,
            is_open_source=True,
            has_sourcemaps=False,
            notes=f"Open source: {repo_url}",
        )
        return None

    # Closed source — check actual file list + inline source maps via unpkg.com
    async with semaphore:
        has_maps = await _check_files_via_unpkg(client, pkg_name, version, metadata)

    jobs.upsert_scan_result(
        package_name=pkg_name,
        version=version,
        is_open_source=False,
        has_sourcemaps=has_maps,
        notes="unpkg meta scan",
    )

    return {
        "package": pkg_name,
        "version": version,
        "is_open_source": False,
        "has_sourcemaps_likely": has_maps,
        "repo_url": repo_url,
    }


COUCHDB_ALL_DOCS = "https://replicate.npmjs.com/_all_docs"


async def scan_top_packages(limit: int = 50) -> list[dict[str, Any]]:
    """
    Walk npm CouchDB _all_docs to find closed-source packages with source maps.
    Deterministic: covers ALL of npm alphabetically until we find `limit` candidates.
    """
    candidates: list[dict] = []
    start_key = ""
    batch_size = 100
    max_batches = 50  # safety cap: scan up to 5000 packages per call

    async with httpx.AsyncClient(
        timeout=30,
        headers={"Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        semaphore = asyncio.Semaphore(CONCURRENCY)
        batches_done = 0

        # Start from 'a' to skip garbage package names (---xxx etc)
        if not start_key:
            start_key = "a"

        while len(candidates) < limit and batches_done < max_batches:
            # Fetch next batch from CouchDB
            try:
                params: dict = {"limit": batch_size, "include_docs": "false"}
                if start_key:
                    params["startkey"] = f'"{start_key}"'
                    if batches_done > 0:
                        params["skip"] = 1  # skip the startkey itself on subsequent pages

                resp = await client.get(COUCHDB_ALL_DOCS, params=params, timeout=20)
                resp.raise_for_status()
                rows = resp.json().get("rows", [])
            except Exception as e:
                break

            if not rows:
                break

            # Extract package names (skip design docs)
            pkg_names = [r["id"] for r in rows if not r["id"].startswith("_design/")]
            start_key = rows[-1]["id"]  # cursor for next batch
            batches_done += 1

            if not pkg_names:
                continue

            # Check all packages in this batch in parallel
            tasks = [_check_package(client, pkg, semaphore) for pkg in pkg_names]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, dict) and not r.get("is_open_source"):
                    candidates.append(r)
                    if len(candidates) >= limit:
                        break

    return candidates[:limit]


async def deep_scan_packages(package_list: list[str]) -> list[str]:
    """
    Kick off full unpack jobs for a list of packages.
    Returns list of job_ids.
    """
    import threading
    import uuid
    from unpacker import run_unpack

    job_ids = []
    for pkg in package_list:
        job_id = str(uuid.uuid4())
        jobs.create_job(job_id, pkg, "latest")
        t = threading.Thread(
            target=run_unpack,
            args=(job_id, pkg, "latest"),
            daemon=True,
        )
        t.start()
        job_ids.append({"package": pkg, "job_id": job_id})

    return job_ids

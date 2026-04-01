"""Unpacker logic — wraps cc-unpacker CLI logic for web use."""

import sys
import json
from pathlib import Path

# Add cc-unpacker source to path
CC_UNPACKER_SRC = Path(__file__).parent.parent / "cc-unpacker"
sys.path.insert(0, str(CC_UNPACKER_SRC))

from cc_unpacker.downloader import download_and_extract, cleanup
from cc_unpacker.extractor import extract_all_sources

import jobs

MAX_PACKAGE_SIZE = 50 * 1024 * 1024  # 50 MB


def _build_tree(files: dict) -> list:
    """Build a VS Code-style file tree from flat path dict."""
    tree = {}

    for path in sorted(files.keys()):
        parts = Path(path).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None  # leaf

    def to_list(node: dict, prefix: str = "") -> list:
        result = []
        for name, children in sorted(node.items(), key=lambda x: (x[1] is None, x[0])):
            full = f"{prefix}/{name}".lstrip("/")
            if children is None:
                result.append({"type": "file", "name": name, "path": full})
            else:
                result.append({
                    "type": "dir",
                    "name": name,
                    "path": full,
                    "children": to_list(children, full)
                })
        return result

    return to_list(tree)


OPEN_SOURCE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")


def _detect_open_source(pkg_metadata: dict) -> bool:
    """Return True if package.json has a repository pointing to a known public host."""
    repo = pkg_metadata.get("repository")
    if repo is None:
        return False
    if isinstance(repo, str):
        url = repo
    elif isinstance(repo, dict):
        url = repo.get("url", "")
    else:
        return False
    return any(host in url for host in OPEN_SOURCE_HOSTS)


def run_unpack(job_id: str, package: str, version: str):
    """Run the unpack job. Called in background thread."""
    pkg_dir = None
    try:
        jobs.update_job(job_id, status="running", progress="Resolving package metadata...")

        # Resolve version
        from cc_unpacker.downloader import _resolve_package_url
        actual_version = version if version != "latest" else None
        tarball_url, resolved_version, _ = _resolve_package_url(package, actual_version)

        # Detect open source: fetch registry metadata for the resolved version
        is_open_source = False
        try:
            import httpx as _httpx
            encoded = package.replace("/", "%2F")
            meta_url = f"https://registry.npmjs.org/{encoded}/{resolved_version}"
            with _httpx.Client(timeout=15, follow_redirects=True) as _client:
                meta_resp = _client.get(meta_url)
                if meta_resp.status_code == 200:
                    pkg_json = meta_resp.json()
                    is_open_source = _detect_open_source(pkg_json)
        except Exception:
            pass  # best-effort
        jobs.update_job(job_id, is_open_source=int(is_open_source))

        jobs.update_job(job_id, progress=f"Downloading {package}@{resolved_version}...")

        # Download and extract
        import httpx
        import tarfile
        import tempfile
        import shutil

        tmp_dir = Path(tempfile.mkdtemp(prefix="cc-unpacker-web-"))
        tgz_path = tmp_dir / "package.tgz"
        total_bytes = 0

        with httpx.Client(timeout=120, follow_redirects=True) as client:
            with client.stream("GET", tarball_url) as resp:
                resp.raise_for_status()
                with open(tgz_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        total_bytes += len(chunk)
                        if total_bytes > MAX_PACKAGE_SIZE:
                            raise ValueError(f"Package exceeds 50MB limit ({total_bytes / 1024 / 1024:.1f}MB)")
                        f.write(chunk)

        jobs.update_job(job_id, progress="Extracting archive...")

        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir()
        with tarfile.open(tgz_path, "r:gz") as tar:
            tar.extractall(path=extract_dir)

        package_subdir = extract_dir / "package"
        pkg_dir = package_subdir if package_subdir.exists() else extract_dir

        jobs.update_job(job_id, progress="Scanning source maps...")

        sources = extract_all_sources(pkg_dir)

        if not sources:
            raise ValueError("No source maps found in this package. The package may not contain sourcemaps.")

        jobs.update_job(job_id, progress=f"Reconstructing {len(sources)} source files...")

        # Build files dict
        files_dict = {name: sf.content for name, sf in sources.items()}
        tree = _build_tree(files_dict)

        payload = json.dumps({
            "tree": tree,
            "files": files_dict
        })

        jobs.update_job(
            job_id,
            status="done",
            progress=f"Done! {len(sources)} files reconstructed.",
            files_json=payload
        )

    except Exception as e:
        jobs.update_job(job_id, status="error", progress=str(e), error=str(e))
    finally:
        if pkg_dir:
            try:
                shutil.rmtree(pkg_dir.parent.parent if pkg_dir.name == "package" else pkg_dir.parent,
                              ignore_errors=True)
            except Exception:
                pass

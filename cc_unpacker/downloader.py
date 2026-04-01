"""Download npm packages directly from the registry and extract them."""

import tarfile
import tempfile
import shutil
from pathlib import Path
from typing import Tuple, Optional

import httpx


REGISTRY = "https://registry.npmjs.org"


def _resolve_package_url(package_name: str, version: Optional[str] = None) -> Tuple[str, str, str]:
    """
    Query the npm registry metadata and return (tarball_url, resolved_version, package_name).
    Handles scoped packages like @anthropic-ai/claude-code.
    """
    encoded = package_name.replace("/", "%2F")
    meta_url = f"{REGISTRY}/{encoded}"

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(meta_url)
        resp.raise_for_status()
        meta = resp.json()

    if version is None:
        version = meta["dist-tags"]["latest"]

    if version not in meta["versions"]:
        raise ValueError(f"Version {version!r} not found for {package_name!r}. "
                         f"Available: {list(meta['versions'].keys())[-5:]}")

    tarball_url = meta["versions"][version]["dist"]["tarball"]
    return tarball_url, version, package_name


def download_and_extract(package_name: str, version: Optional[str] = None) -> Tuple[Path, str]:
    """
    Download a package from the npm registry, extract it into a temp directory.

    Returns:
        (extracted_path, resolved_version)
    """
    tarball_url, resolved_version, _ = _resolve_package_url(package_name, version)

    tmp_dir = Path(tempfile.mkdtemp(prefix="cc-unpacker-"))

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        with client.stream("GET", tarball_url) as resp:
            resp.raise_for_status()
            tgz_path = tmp_dir / "package.tgz"
            with open(tgz_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)

    extract_dir = tmp_dir / "extracted"
    extract_dir.mkdir()
    with tarfile.open(tgz_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)

    # npm tarballs always put files under "package/" sub-directory
    package_subdir = extract_dir / "package"
    if package_subdir.exists():
        final_dir = package_subdir
    else:
        # fallback: just return the extraction root
        final_dir = extract_dir

    return final_dir, resolved_version


def cleanup(path: Path) -> None:
    """Remove the temp directory created during download."""
    parent = path.parent.parent if path.name == "package" else path.parent
    shutil.rmtree(parent, ignore_errors=True)

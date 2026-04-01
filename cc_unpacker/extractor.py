"""Parse source maps (.js.map) and reconstruct original source files."""

import json
import base64
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class SourceFile:
    """A single reconstructed source file."""
    name: str          # original file path from source map
    content: str       # file content
    map_file: str      # which .js.map file it came from


def find_map_files(root: Path) -> List[Path]:
    """Recursively find all .js.map files."""
    return list(root.rglob("*.js.map"))


def _decode_vlq(string: str) -> List[int]:
    """Decode a single VLQ-encoded string to a list of integers."""
    VLQ_BASE_SHIFT = 5
    VLQ_BASE = 1 << VLQ_BASE_SHIFT
    VLQ_BASE_MASK = VLQ_BASE - 1
    VLQ_CONTINUATION_BIT = VLQ_BASE

    BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    b64map = {c: i for i, c in enumerate(BASE64_CHARS)}

    result = []
    shift = 0
    value = 0

    for char in string:
        digit = b64map.get(char, 0)
        continuation = digit & VLQ_CONTINUATION_BIT
        digit &= VLQ_BASE_MASK

        value += digit << shift
        if continuation:
            shift += VLQ_BASE_SHIFT
        else:
            negate = value & 1
            value >>= 1
            result.append(-value if negate else value)
            shift = 0
            value = 0

    return result


def extract_sources_from_map(map_path: Path) -> List[SourceFile]:
    """
    Parse a source map file and extract all embedded source files.

    Handles:
    - sourcesContent (inline sources) — preferred, no network needed
    - External source references (best-effort, skipped if unreachable)
    - Data URIs in sourceMappingURL
    """
    try:
        raw = map_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        return []

    sources: List[str] = data.get("sources", [])
    sources_content: Optional[List[Optional[str]]] = data.get("sourcesContent")
    map_file_name = str(map_path)

    result: List[SourceFile] = []

    for idx, source_name in enumerate(sources):
        if not source_name:
            continue

        content: Optional[str] = None

        # Try inline content first (most common in bundled packages)
        if sources_content and idx < len(sources_content) and sources_content[idx] is not None:
            content = sources_content[idx]
        else:
            # Try to read from filesystem relative to the map file
            candidate = map_path.parent / source_name
            try:
                candidate = candidate.resolve()
                if candidate.exists():
                    content = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        if content is not None:
            # Clean up webpack-style prefixes in source names
            clean_name = re.sub(r"^webpack:///?\.?/", "", source_name)
            clean_name = re.sub(r"^\./", "", clean_name)
            result.append(SourceFile(
                name=clean_name,
                content=content,
                map_file=map_file_name,
            ))

    return result


def extract_inline_sourcemap(js_path: Path) -> Optional[List[SourceFile]]:
    """
    Some JS files embed their source map as a data URI in sourceMappingURL.
    Try to detect and parse those.
    """
    try:
        js_text = js_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Look for: //# sourceMappingURL=data:application/json;base64,...
    match = re.search(
        r"//[#@]\s*sourceMappingURL=data:application/json(?:;charset=utf-8)?;base64,([A-Za-z0-9+/=]+)",
        js_text,
    )
    if not match:
        return None

    try:
        decoded = base64.b64decode(match.group(1)).decode("utf-8")
        data = json.loads(decoded)
    except Exception:
        return None

    sources = data.get("sources", [])
    sources_content = data.get("sourcesContent")
    result = []

    for idx, name in enumerate(sources):
        content = None
        if sources_content and idx < len(sources_content) and sources_content[idx] is not None:
            content = sources_content[idx]
        if content:
            clean_name = re.sub(r"^webpack:///?\.?/", "", name)
            clean_name = re.sub(r"^\./", "", clean_name)
            result.append(SourceFile(
                name=clean_name,
                content=content,
                map_file=str(js_path) + " (inline)",
            ))

    return result if result else None


def extract_all_sources(root: Path) -> Dict[str, SourceFile]:
    """
    Walk the entire package directory, find all source maps (external + inline),
    and return a deduplicated dict of {source_name: SourceFile}.
    """
    found: Dict[str, SourceFile] = {}

    # External .js.map files
    for map_file in find_map_files(root):
        for sf in extract_sources_from_map(map_file):
            if sf.name not in found:
                found[sf.name] = sf

    # Inline source maps in JS files
    for js_file in root.rglob("*.js"):
        inline = extract_inline_sourcemap(js_file)
        if inline:
            for sf in inline:
                if sf.name not in found:
                    found[sf.name] = sf

    return found

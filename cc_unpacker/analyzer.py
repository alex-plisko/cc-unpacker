"""Claude AI analysis of reconstructed source files."""

import os
from typing import Dict, List, Optional
from dataclasses import dataclass

from .extractor import SourceFile


MAX_CONTENT_CHARS = 120_000  # ~30k tokens, safe for claude-3-5-sonnet


@dataclass
class AnalysisResult:
    summary: str
    full_report: str
    files_analyzed: int


def _build_prompt(package_name: str, files: Dict[str, SourceFile]) -> str:
    """Build a prompt from the extracted source files."""
    sections = [
        f"# Source code from npm package: {package_name}\n",
        "You are analyzing the **original source code** recovered from source maps embedded in an npm package.\n",
        "Please provide:\n"
        "1. **Architecture Overview** — what this package does, how it's structured\n"
        "2. **Key Files** — most important modules and what they do\n"
        "3. **Interesting Patterns** — notable design decisions, unusual code, clever tricks\n"
        "4. **Security Observations** — anything notable (don't be alarmist, be factual)\n"
        "5. **Summary** — 2-3 sentence TL;DR\n\n"
        "---\n",
    ]

    total_chars = sum(len(s) for s in sections)
    file_list = sorted(files.items(), key=lambda kv: len(kv[1].content), reverse=True)

    included = 0
    for name, sf in file_list:
        entry = f"\n## File: {name}\n```\n{sf.content[:8000]}\n```\n"
        if total_chars + len(entry) > MAX_CONTENT_CHARS:
            break
        sections.append(entry)
        total_chars += len(entry)
        included += 1

    if included < len(file_list):
        skipped = len(file_list) - included
        sections.append(f"\n*({skipped} additional files omitted for context length)*\n")

    return "".join(sections)


def analyze_with_claude(
    package_name: str,
    files: Dict[str, SourceFile],
    api_key: Optional[str] = None,
) -> AnalysisResult:
    """
    Send extracted source files to Claude for analysis.
    Returns an AnalysisResult with summary + full report.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Export it or add to .env file."
        )

    client = anthropic.Anthropic(api_key=key)
    prompt = _build_prompt(package_name, files)

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    full_report = message.content[0].text

    # Extract just the summary section for the DB short field
    summary = _extract_summary(full_report) or full_report[:500]

    return AnalysisResult(
        summary=summary,
        full_report=full_report,
        files_analyzed=len(files),
    )


def _extract_summary(report: str) -> Optional[str]:
    """Try to pull out the Summary section from the markdown report."""
    import re
    match = re.search(
        r"(?:#+\s*(?:5\.|Summary|TL;DR)[^\n]*\n)(.*?)(?:\n#+|\Z)",
        report,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()[:1000]
    return None

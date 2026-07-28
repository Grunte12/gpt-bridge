"""Compact, searchable capability catalog for coding agents."""

from __future__ import annotations

import re
from typing import Any


_CORE_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "id": "health",
        "summary": "Check the selected account and direct worker runtime.",
        "command": "gpt-bridge worker doctor --json",
        "keywords": "doctor status setup account runtime health",
        "session_policy": "none",
    },
    {
        "id": "chat",
        "summary": "Ask ChatGPT for a compact answer or coding artifact.",
        "command": 'gpt-bridge worker chat --message "..." --json',
        "keywords": "ask chat code review critique explain answer",
        "session_policy": "temporary by default",
    },
    {
        "id": "local-thread",
        "summary": "Keep compact task context in a local named JSON thread.",
        "command": 'gpt-bridge worker chat --message "..." --thread NAME --json',
        "keywords": "persistent local thread continue task memory state",
        "session_policy": "local state; clear with worker thread clear",
    },
    {
        "id": "web-session",
        "summary": "Find, read, export, continue, pull assets from, or delete a ChatGPT Web conversation.",
        "command": "gpt-bridge worker web --help",
        "keywords": "existing web session conversation brainstorm handoff list show send pull delete",
        "references": ["references/web-sessions.md"],
        "session_policy": "modifies only on send/delete",
    },
    {
        "id": "html-report",
        "summary": "Create a standalone model-authored HTML report.",
        "command": 'gpt-bridge worker report --prompt "..." --out report.html --json',
        "keywords": "html report dashboard chart interactive analysis",
        "session_policy": "temporary by default",
    },
    {
        "id": "deep-research",
        "summary": "Run sourced ChatGPT Deep Research.",
        "command": 'gpt-bridge worker research --prompt "..." --json',
        "keywords": "research sources citations evidence compare investigate",
        "session_policy": "long-running operation",
    },
    {
        "id": "image-generate",
        "summary": "Generate a ChatGPT Image with compact output.",
        "command": 'gpt-bridge worker image --prompt "..." --output-path image.png --brief',
        "keywords": "image generate visual graphic picture art",
        "references": ["references/image-core.md"],
        "session_policy": "use --cleanup-session only for clearly one-shot work",
    },
    {
        "id": "image-edit",
        "summary": "Edit, restyle, localize, or composite up to 10 source images.",
        "command": 'gpt-bridge worker edit --prompt "..." --input-image source.png --output-path edited.png --brief',
        "keywords": "image edit restyle composite reference preserve localize",
        "references": [
            "references/image-core.md",
            "references/risks/reference-edit-consistency.md",
        ],
        "session_policy": "use --cleanup-session only for clearly one-shot work",
    },
)


_VISUAL_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "id": "transparent-frontend-asset",
        "summary": "Generate a frontend-ready PNG asset and verify real alpha.",
        "keywords": "transparent alpha png frontend website web asset icon ornament cutout sprite",
        "references": [
            "references/image-core.md",
            "references/frontend-asset.md",
            "references/risks/output-accessibility.md",
        ],
    },
    {
        "id": "realistic-photo",
        "summary": "Generate a realistic photographic image.",
        "keywords": "realistic photo photography portrait product lifestyle camera",
        "references": ["references/image-core.md", "references/realistic-photo.md"],
    },
    {
        "id": "illustration-concept",
        "summary": "Generate an illustration, concept image, or stylized artwork.",
        "keywords": "illustration concept art stylized editorial character",
        "references": ["references/image-core.md", "references/illustration-concept.md"],
    },
    {
        "id": "infographic",
        "summary": "Generate a structured visual summary with facts or data.",
        "keywords": "infographic data facts statistics visual summary",
        "references": [
            "references/image-core.md",
            "references/infographic.md",
            "references/risks/factual-data.md",
        ],
    },
    {
        "id": "technical-diagram",
        "summary": "Generate an architecture, workflow, system, or engineering diagram.",
        "keywords": "technical diagram architecture flowchart workflow system engineering backend",
        "references": ["references/image-core.md", "references/technical-diagram.md"],
    },
    {
        "id": "explanation-visual",
        "summary": "Generate an educational or explanatory visual.",
        "keywords": "explain explanation educational teaching process anatomy how works",
        "references": ["references/image-core.md", "references/explanation-visual.md"],
    },
    {
        "id": "product-mockup",
        "summary": "Generate a product, packaging, or device mockup.",
        "keywords": "product mockup packaging device merchandise ecommerce",
        "references": ["references/image-core.md", "references/product-mockup.md"],
    },
    {
        "id": "interface-mockup",
        "summary": "Generate a UI, app, dashboard, or website mockup image.",
        "keywords": "ui ux interface mockup app dashboard website screen frontend design",
        "references": ["references/image-core.md", "references/interface-mockup.md"],
    },
    {
        "id": "brand-marketing",
        "summary": "Generate a campaign, social, advertising, or brand visual.",
        "keywords": "brand marketing campaign ad advertising social banner poster",
        "references": ["references/image-core.md", "references/brand-marketing.md"],
    },
    {
        "id": "story-sequence",
        "summary": "Generate a comic, storyboard, or multi-image narrative.",
        "keywords": "story comic storyboard sequence panels narrative character consistency",
        "references": [
            "references/image-core.md",
            "references/story-sequence.md",
            "references/risks/batch-series.md",
        ],
    },
    {
        "id": "scientific-visual",
        "summary": "Generate a scientific, medical, or technical explanatory visual.",
        "keywords": "scientific science medical biology chemistry physics technical",
        "references": [
            "references/image-core.md",
            "references/scientific-visual.md",
            "references/risks/factual-data.md",
        ],
    },
    {
        "id": "spatial-concept",
        "summary": "Generate an interior, architectural, landscape, or spatial concept.",
        "keywords": "spatial interior architecture landscape room environment concept",
        "references": ["references/image-core.md", "references/spatial-concept.md"],
    },
    {
        "id": "presentation-deck",
        "summary": "Generate one image per slide and assemble a flattened PPTX.",
        "keywords": "presentation slide deck powerpoint pptx pitch keynote",
        "references": [
            "references/image-core.md",
            "references/presentation-deck.md",
            "references/risks/batch-series.md",
            "references/risks/exact-text-localization.md",
        ],
    },
)


def _public_item(item: dict[str, Any], *, detailed: bool) -> dict[str, Any]:
    result = {
        "id": item["id"],
        "summary": item["summary"],
    }
    if detailed:
        if item.get("command"):
            result["command"] = item["command"]
        if item.get("references"):
            result["references"] = list(item["references"])
        if item.get("session_policy"):
            result["session_policy"] = item["session_policy"]
    return result


def search_capabilities(query: str | None = None, *, limit: int = 3) -> dict[str, Any]:
    """Return a small index or the best task-specific capability matches."""
    normalized = " ".join((query or "").lower().split())
    if not normalized:
        return {
            "object": "chatgpt.worker.capabilities",
            "query": None,
            "capabilities": [_public_item(item, detailed=False) for item in _CORE_CAPABILITIES],
            "hint": 'Search details with: gpt-bridge worker tools --query "<task>" --json',
        }

    stopwords = {"a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to", "with"}
    tokens = {token for token in re.findall(r"[a-z0-9]+", normalized) if token not in stopwords}
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate((*_CORE_CAPABILITIES, *_VISUAL_CAPABILITIES)):
        haystack = " ".join(
            (
                str(item["id"]).replace("-", " "),
                str(item["summary"]).lower(),
                str(item.get("keywords", "")).lower(),
            )
        )
        score = 8 if normalized in haystack else 0
        score += sum(2 for token in tokens if token in haystack)
        if score:
            scored.append((score, -index, item))
    scored.sort(reverse=True)
    top_score = scored[0][0] if scored else 0
    close_matches = [entry for entry in scored if entry[0] >= max(1, top_score - 1)]
    matches = [_public_item(item, detailed=True) for _score, _index, item in close_matches[: max(1, limit)]]
    return {
        "object": "chatgpt.worker.capability.search",
        "query": query,
        "matches": matches,
        "hint": "Read only the returned references; do not scan or preload the full skill directory.",
    }


def capability_reference_paths() -> tuple[str, ...]:
    """Return every reference path used by the catalog for integrity tests."""
    paths = {
        str(path)
        for item in (*_CORE_CAPABILITIES, *_VISUAL_CAPABILITIES)
        for path in item.get("references", ())
    }
    return tuple(sorted(paths))

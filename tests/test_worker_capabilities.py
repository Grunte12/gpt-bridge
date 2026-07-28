import json
from pathlib import Path

from chatgpt_api.cli import main
from chatgpt_api.worker.capabilities import capability_reference_paths, search_capabilities


SKILL_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "gpt-bridge" / "skills" / "gpt-bridge-worker"


def test_capability_index_is_compact_and_omits_reference_details():
    payload = search_capabilities()

    assert payload["object"] == "chatgpt.worker.capabilities"
    assert {item["id"] for item in payload["capabilities"]} >= {
        "chat",
        "web-session",
        "html-report",
        "deep-research",
        "image-generate",
        "image-edit",
    }
    assert all(set(item) == {"id", "summary"} for item in payload["capabilities"])


def test_capability_search_returns_only_relevant_on_demand_references():
    payload = search_capabilities("transparent PNG asset for a website", limit=2)

    assert payload["object"] == "chatgpt.worker.capability.search"
    assert payload["matches"][0]["id"] == "transparent-frontend-asset"
    assert payload["matches"][0]["references"] == [
        "references/image-core.md",
        "references/frontend-asset.md",
        "references/risks/output-accessibility.md",
    ]
    assert "presentation-deck.md" not in json.dumps(payload)


def test_worker_tools_cli_needs_no_account_or_network(capsys):
    assert main(["worker", "tools", "--query", "architecture diagram", "--limit", "1", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["matches"][0]["id"] == "technical-diagram"
    assert payload["matches"][0]["references"] == [
        "references/image-core.md",
        "references/technical-diagram.md",
    ]


def test_every_catalog_reference_exists_in_the_shared_skill():
    missing = [path for path in capability_reference_paths() if not (SKILL_ROOT / path).is_file()]

    assert missing == []

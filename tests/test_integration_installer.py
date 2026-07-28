import json
from pathlib import Path

from chatgpt_api.cli import main as cli_main
from chatgpt_api.integration_installer import (
    install_claude,
    install_codex,
    install_opencode,
    install_runtime,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_exposes_one_shared_skill_source():
    plugin_root = REPO_ROOT / "plugins" / "gpt-bridge"
    skill = plugin_root / "skills" / "gpt-bridge-worker"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "references" / "image-core.md").is_file()
    assert (skill / "references" / "frontend-asset.md").is_file()
    assert (skill / "references" / "product-mockup.md").is_file()
    assert (skill / "references" / "presentation-deck.md").is_file()
    assert (skill / "references" / "risks" / "failure-recovery.md").is_file()
    assert (skill / "scripts" / "images_to_pptx.py").is_file()
    assert (skill / "scripts" / "make_transparent.py").is_file()


def test_codex_installer_copies_skill_without_marketplace(tmp_path):
    result = install_codex(str(REPO_ROOT), home=tmp_path)

    destination = tmp_path / ".codex" / "skills" / "gpt-bridge-worker" / "SKILL.md"
    assert result.ok is True
    assert destination.is_file()
    assert "worker tools --query" in destination.read_text(encoding="utf-8")
    assert result.commands == []


def test_claude_installer_copies_project_skill_without_marketplace(tmp_path):
    result = install_claude(str(REPO_ROOT), scope="project", project_dir=tmp_path)

    destination = tmp_path / ".claude" / "skills" / "gpt-bridge-worker" / "SKILL.md"
    assert result.ok is True
    assert destination.is_file()
    assert "worker tools --query" in destination.read_text(encoding="utf-8")
    assert result.commands == []


def test_missing_local_skill_source_returns_actionable_result(tmp_path):
    result = install_codex(str(tmp_path / "missing"), home=tmp_path)

    assert result.ok is False
    assert result.action == "failed"
    assert "skill source" in result.detail


def test_runtime_installer_creates_agent_visible_command(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    result = install_runtime(REPO_ROOT, home=tmp_path, runner=runner)

    shim = tmp_path / ".local" / "bin" / "gpt-bridge"
    assert result.ok is True
    assert calls
    assert shim.is_file()
    assert "chatgpt_api.cli import main" in shim.read_text(encoding="utf-8")
    assert shim.stat().st_mode & 0o111


def test_opencode_installer_preserves_config_and_installs_native_tools(tmp_path):
    config_dir = tmp_path / "config"
    config_path = config_dir / "opencode" / "opencode.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "theme": "system",
                "model": "another-provider/model",
                "provider": {"another-provider": {"models": {"model": {}}}},
            }
        ),
        encoding="utf-8",
    )

    result = install_opencode(
        scope="user",
        home=tmp_path,
        environ={"XDG_CONFIG_HOME": str(config_dir)},
    )

    assert result.ok is True
    installed = json.loads(config_path.read_text(encoding="utf-8"))
    assert installed["theme"] == "system"
    assert installed["model"] == "another-provider/model"
    assert "another-provider" in installed["provider"]
    assert "chatgpt-web" not in installed["provider"]
    tool_text = (config_path.parent / "tools" / "gpt_bridge.ts").read_text(encoding="utf-8")
    assert "export const research" in tool_text
    assert "export const image_edit" in tool_text
    assert "export const web_session" in tool_text
    assert "transparent image generation requires outputPath" in tool_text
    assert "cleanupSession requires outputPath" in tool_text
    assert "delete requires confirmDelete=true" in tool_text
    assert "repeat calls as needed for quality" in tool_text
    assert '"--brief"' in tool_text
    assert '"--enhance"' not in tool_text
    assert "args.size" not in tool_text
    assert "args.quality" not in tool_text
    skill_dir = config_path.parent / "skills" / "gpt-bridge-worker"
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "references" / "image-core.md").is_file()
    assert (skill_dir / "references" / "frontend-asset.md").is_file()
    assert (skill_dir / "references" / "presentation-deck.md").is_file()
    assert (skill_dir / "references" / "web-sessions.md").is_file()
    assert (skill_dir / "references" / "risks" / "reference-edit-consistency.md").is_file()
    assert (skill_dir / "scripts" / "images_to_pptx.py").is_file()
    assert (skill_dir / "scripts" / "make_transparent.py").is_file()
    assert not config_path.with_name("opencode.json.gpt-bridge.bak").exists()


def test_opencode_installer_can_set_bridge_as_default_for_project(tmp_path):
    result = install_opencode(
        scope="project",
        project_dir=tmp_path,
        home=tmp_path,
        environ={},
        set_default=True,
    )

    assert result.ok is True
    installed = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert installed["model"] == "chatgpt-web/gpt-5-6-sol-high@optimized"
    assert installed["small_model"] == "chatgpt-web/gpt-5-6-sol-high@optimized"
    assert (tmp_path / ".opencode" / "tools" / "gpt_bridge.ts").is_file()
    assert (tmp_path / ".opencode" / "skills" / "gpt-bridge-worker" / "SKILL.md").is_file()


def test_opencode_installer_refuses_to_overwrite_jsonc_or_invalid_json(tmp_path):
    config_path = tmp_path / "opencode.json"
    original = '{\n  // keep this comment\n  "theme": "system"\n}\n'
    config_path.write_text(original, encoding="utf-8")

    result = install_opencode(
        scope="project",
        project_dir=tmp_path,
        home=tmp_path,
        environ={},
        config_path=config_path,
        set_default=True,
    )

    assert result.ok is False
    assert "strict JSON" in result.detail
    assert config_path.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".opencode" / "tools" / "gpt_bridge.ts").exists()
    assert not (tmp_path / ".opencode" / "skills" / "gpt-bridge-worker").exists()


def test_dry_run_does_not_write_opencode_files(tmp_path):
    result = install_opencode(
        scope="project",
        project_dir=tmp_path,
        home=tmp_path,
        environ={},
        dry_run=True,
    )

    assert result.ok is True
    assert result.action == "planned"
    assert not (tmp_path / "opencode.json").exists()
    assert not (tmp_path / ".opencode").exists()


def test_opencode_installer_removes_only_managed_legacy_plugin(tmp_path):
    config_dir = tmp_path / ".config" / "opencode"
    legacy = config_dir / "plugins" / "gpt_bridge.ts"
    legacy.parent.mkdir(parents=True)
    source = (REPO_ROOT / "chatgpt_api" / "assets" / "opencode" / "gpt_bridge.ts").read_text(encoding="utf-8")
    legacy.write_text(source, encoding="utf-8")

    result = install_opencode(scope="user", home=tmp_path, environ={})

    assert result.ok is True
    assert (config_dir / "tools" / "gpt_bridge.ts").is_file()
    assert not legacy.exists()


def test_opencode_installer_preserves_modified_legacy_plugin(tmp_path):
    config_dir = tmp_path / ".config" / "opencode"
    legacy = config_dir / "plugins" / "gpt_bridge.ts"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("// user-owned plugin\n", encoding="utf-8")

    result = install_opencode(scope="user", home=tmp_path, environ={})

    assert result.ok is True
    assert (config_dir / "tools" / "gpt_bridge.ts").is_file()
    assert legacy.read_text(encoding="utf-8") == "// user-owned plugin\n"


def test_main_cli_exposes_cross_host_installer(capsys):
    code = cli_main(
        [
            "integrations",
            "install",
            "--target",
            "codex",
            "--dry-run",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["target"] == "codex"
    assert payload["results"][0]["action"] == "planned"

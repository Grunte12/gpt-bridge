"""Install GPT Bridge adapters for supported agent hosts.

The installer never starts the Bridge service or handles browser credentials.
Native tools use the direct one-account CLI; the OpenCode HTTP provider remains
optional compatibility configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Callable, Iterable, Sequence


SUPPORTED_TARGETS = ("codex", "claude", "opencode")


@dataclass(slots=True)
class IntegrationResult:
    target: str
    ok: bool
    action: str
    detail: str
    paths: list[str]
    commands: list[list[str]]


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _result(
    target: str,
    *,
    ok: bool,
    action: str,
    detail: str,
    paths: Iterable[Path] = (),
    commands: Iterable[Sequence[str]] = (),
) -> IntegrationResult:
    return IntegrationResult(
        target=target,
        ok=ok,
        action=action,
        detail=detail,
        paths=[str(path) for path in paths],
        commands=[list(command) for command in commands],
    )


def _skill_source(source: str | Path) -> Path:
    root = Path(source).expanduser().resolve()
    skill = root / "plugins" / "gpt-bridge" / "skills" / "gpt-bridge-worker"
    if not (skill / "SKILL.md").is_file():
        raise ValueError(f"GPT Bridge skill source was not found under {root}")
    return skill


def _install_skill_copy(
    target: str,
    source: str | Path,
    destination: Path,
    *,
    dry_run: bool,
) -> IntegrationResult:
    if dry_run:
        return _result(
            target,
            ok=True,
            action="planned",
            detail=f"would install the {target} skill from the local checkout",
            paths=[destination],
        )
    try:
        skill = _skill_source(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill, destination, dirs_exist_ok=True)
    except (OSError, ValueError) as exc:
        return _result(
            target,
            ok=False,
            action="failed",
            detail=str(exc),
            paths=[destination],
        )
    return _result(
        target,
        ok=True,
        action="installed",
        detail=f"installed the {target} skill from the local checkout",
        paths=[destination],
    )


def install_codex(
    source: str,
    *,
    scope: str = "user",
    project_dir: Path | None = None,
    home: Path | None = None,
    dry_run: bool = False,
) -> IntegrationResult:
    root = (Path.cwd() if project_dir is None else project_dir).resolve()
    home_dir = Path.home() if home is None else home
    destination = (
        root / ".agents" / "skills" / "gpt-bridge-worker"
        if scope == "project"
        else home_dir / ".codex" / "skills" / "gpt-bridge-worker"
    )
    return _install_skill_copy("codex", source, destination, dry_run=dry_run)


def install_claude(
    source: str,
    *,
    scope: str = "user",
    project_dir: Path | None = None,
    home: Path | None = None,
    dry_run: bool = False,
) -> IntegrationResult:
    root = (Path.cwd() if project_dir is None else project_dir).resolve()
    home_dir = Path.home() if home is None else home
    destination = (
        root / ".claude" / "skills" / "gpt-bridge-worker"
        if scope == "project"
        else home_dir / ".claude" / "skills" / "gpt-bridge-worker"
    )
    return _install_skill_copy("claude", source, destination, dry_run=dry_run)


def _opencode_config_dir(home: Path, environ: dict[str, str]) -> Path:
    explicit = environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    xdg = environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg).expanduser() if xdg else home / ".config") / "opencode"


def _opencode_paths(
    *,
    scope: str,
    project_dir: Path,
    home: Path,
    environ: dict[str, str],
) -> tuple[Path, Path]:
    if scope == "project":
        root = project_dir.resolve()
        return root / "opencode.json", root / ".opencode" / "tools" / "gpt_bridge.ts"
    config_dir = _opencode_config_dir(home, environ)
    return config_dir / "opencode.json", config_dir / "tools" / "gpt_bridge.ts"


def _legacy_opencode_plugin_path(tool_path: Path) -> Path:
    return tool_path.parent.parent / "plugins" / tool_path.name


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not strict JSON; convert or choose a separate --opencode-config path before installing"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return dict(payload)


def _opencode_provider() -> dict[str, object]:
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "GPT Bridge Local",
        "options": {
            "baseURL": "http://127.0.0.1:8000/v1",
            "apiKey": "{env:CHATGPT_API_KEY}",
        },
        "models": {
            "auto": {"name": "GPT Bridge Auto"},
            "auto@optimized": {"name": "GPT Bridge Auto (Optimized Agent Bridge)"},
            "gpt-5-6-sol-high": {"name": "GPT-5.6 Sol High"},
            "gpt-5-6-sol-high@optimized": {"name": "GPT-5.6 Sol High (Optimized Agent Bridge)"},
            "chatgpt-deep-research": {"name": "ChatGPT Deep Research"},
        },
    }


def _merge_opencode_config(existing: dict[str, object], *, set_default: bool) -> dict[str, object]:
    merged = dict(existing)
    merged.setdefault("$schema", "https://opencode.ai/config.json")
    providers = merged.get("provider")
    provider_map = dict(providers) if isinstance(providers, dict) else {}
    provider_map["chatgpt-web"] = _opencode_provider()
    merged["provider"] = provider_map
    if set_default:
        merged["model"] = "chatgpt-web/gpt-5-6-sol-high@optimized"
        merged["small_model"] = "chatgpt-web/gpt-5-6-sol-high@optimized"
    return merged


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _opencode_asset_text() -> str:
    asset = resources.files("chatgpt_api").joinpath("assets", "opencode", "gpt_bridge.ts")
    return asset.read_text(encoding="utf-8")


def install_opencode(
    *,
    source: str | Path | None = None,
    scope: str = "user",
    project_dir: Path | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    config_path: Path | None = None,
    set_default: bool = False,
    dry_run: bool = False,
) -> IntegrationResult:
    environment = dict(os.environ if environ is None else environ)
    home_dir = Path.home() if home is None else home
    project = Path.cwd() if project_dir is None else project_dir
    default_config, tool_path = _opencode_paths(
        scope=scope,
        project_dir=project,
        home=home_dir,
        environ=environment,
    )
    resolved_config = (config_path or default_config).expanduser()
    skill_path = tool_path.parent.parent / "skills" / "gpt-bridge-worker"
    paths = [tool_path, skill_path]
    if set_default:
        paths.insert(0, resolved_config)
    if dry_run:
        return _result(
            "opencode",
            ok=True,
            action="planned",
            detail=(
                "would install the OpenCode skill and direct tools, and select the optional HTTP provider"
                if set_default
                else "would install the OpenCode skill and direct tools"
            ),
            paths=paths,
        )
    try:
        if set_default:
            existing = _read_json_object(resolved_config)
            merged = _merge_opencode_config(existing, set_default=True)
            if resolved_config.exists():
                backup = resolved_config.with_name(f"{resolved_config.name}.gpt-bridge.bak")
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(resolved_config, backup)
                    paths.append(backup)
            _atomic_write_json(resolved_config, merged)
        asset_text = _opencode_asset_text()
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text(asset_text, encoding="utf-8")
        skill = _skill_source(source or Path(__file__).resolve().parents[1])
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill, skill_path, dirs_exist_ok=True)
        legacy_plugin = _legacy_opencode_plugin_path(tool_path)
        if legacy_plugin.is_file() and legacy_plugin.read_text(encoding="utf-8") == asset_text:
            legacy_plugin.unlink()
    except (OSError, ValueError) as exc:
        return _result(
            "opencode",
            ok=False,
            action="failed",
            detail=str(exc),
            paths=paths,
        )
    return _result(
        "opencode",
        ok=True,
        action="installed",
        detail=(
            "installed the OpenCode skill and direct tools, and selected the optional HTTP provider"
            if set_default
            else "installed the OpenCode skill and direct tools"
        ),
        paths=paths,
    )


def install_runtime(
    repo_root: Path,
    *,
    home: Path | None = None,
    dry_run: bool = False,
    runner: Runner = subprocess.run,
) -> IntegrationResult:
    command = [sys.executable, "-m", "pip", "install", "-e", str(repo_root.resolve())]
    home_dir = Path.home() if home is None else home
    shim = home_dir / ".local" / "bin" / ("gpt-bridge.cmd" if os.name == "nt" else "gpt-bridge")
    if dry_run:
        return _result(
            "runtime",
            ok=True,
            action="planned",
            detail="would install the GPT Bridge Python runtime and PATH command from this checkout",
            paths=[shim],
            commands=[command],
        )
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "runtime installation failed").strip()
        return _result("runtime", ok=False, action="failed", detail=detail, commands=[command])
    try:
        shim.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            shim.write_text(f'@"{sys.executable}" -m chatgpt_api %*\r\n', encoding="utf-8")
        else:
            shim.write_text(
                f"#!{sys.executable}\n"
                "from chatgpt_api.cli import main\n"
                "if __name__ == \"__main__\":\n"
                "    raise SystemExit(main())\n",
                encoding="utf-8",
            )
            shim.chmod(0o755)
    except OSError as exc:
        return _result(
            "runtime",
            ok=False,
            action="failed",
            detail=f"runtime installed but command shim failed: {exc}",
            paths=[shim],
            commands=[command],
        )
    return _result(
        "runtime",
        ok=True,
        action="installed",
        detail="installed the GPT Bridge Python runtime and PATH command from this checkout",
        paths=[shim],
        commands=[command],
    )


def install_integrations(
    targets: Sequence[str],
    *,
    source: str,
    scope: str,
    project_dir: Path,
    opencode_config: Path | None,
    set_opencode_default: bool,
    dry_run: bool,
    runner: Runner = subprocess.run,
) -> list[IntegrationResult]:
    results: list[IntegrationResult] = []
    for target in targets:
        if target == "codex":
            results.append(
                install_codex(source, scope=scope, project_dir=project_dir, dry_run=dry_run)
            )
        elif target == "claude":
            results.append(
                install_claude(source, scope=scope, project_dir=project_dir, dry_run=dry_run)
            )
        elif target == "opencode":
            results.append(
                install_opencode(
                    source=source,
                    scope=scope,
                    project_dir=project_dir,
                    config_path=opencode_config,
                    set_default=set_opencode_default,
                    dry_run=dry_run,
                )
            )
        else:
            raise ValueError(f"unsupported integration target: {target}")
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install-agent-integrations",
        description="Install GPT Bridge adapters for Codex, Claude Code, and OpenCode.",
    )
    parser.add_argument(
        "--target",
        action="append",
        choices=SUPPORTED_TARGETS,
        dest="targets",
        help="Host to install; repeat as needed. Defaults to all supported hosts.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Local GPT Bridge checkout; defaults to the checkout containing this installer.",
    )
    parser.add_argument("--scope", choices=["user", "project"], default="user")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--opencode-config", type=Path, default=None)
    parser.add_argument("--set-opencode-default", action="store_true")
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, *, repo_root: Path | None = None) -> int:
    args = _parser().parse_args(argv)
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    targets = tuple(args.targets or SUPPORTED_TARGETS)
    results: list[IntegrationResult] = []
    if not args.skip_runtime:
        runtime = install_runtime(root, dry_run=args.dry_run)
        results.append(runtime)
        if not runtime.ok:
            return print_results(results, as_json=args.json)
    results.extend(
        install_integrations(
            targets,
            source=args.source or str(root),
            scope=args.scope,
            project_dir=args.project_dir,
            opencode_config=args.opencode_config,
            set_opencode_default=args.set_opencode_default,
            dry_run=args.dry_run,
        )
    )
    return print_results(results, as_json=args.json)


def print_results(results: Sequence[IntegrationResult], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"results": [asdict(result) for result in results]}, indent=2))
    else:
        for result in results:
            marker = "ok" if result.ok else "error"
            print(f"{result.target}: {marker}: {result.detail}")
            for path in result.paths:
                print(f"  path: {path}")
            for command in result.commands:
                print(f"  command: {' '.join(command)}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Admin-payload seam for the bridge console: account, artifact, capture, and
opencode-integration payload construction plus the admin static-asset/console
redirect helpers. Routing/concurrency settings and endpoints that call the
chat/image pipelines stay owned by ``chatgpt_api.api.openai_compat``.
"""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chatgpt_api.api.admin_store import BridgeAdminStore
from chatgpt_api.api.artifacts import guess_download_content_type
from chatgpt_api.api.config import OpenAICompatConfig
from chatgpt_api.api.http_utils import query_value, send_cors_headers, send_json
from chatgpt_api.providers.chatgpt.account_info import detect_account_info, infer_account_capabilities, load_settings_file
from chatgpt_api.providers.chatgpt.accounts import (
    accounts_dir_from_env,
    list_account_profiles,
    resolve_account_capture_path,
    resolve_account_settings_path,
)
from chatgpt_api.providers.chatgpt.crypto import encrypt_text, load_secrets_key
from chatgpt_api.providers.chatgpt.request_capture import CapturedRequest, SECRET_HEADER_NAMES

if TYPE_CHECKING:
    from chatgpt_api.api.openai_compat import AccountRouter


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _public_status_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def admin_db_path(config: OpenAICompatConfig) -> Path:
    return (config.admin_db_path or Path("outputs/chatgpt-admin.sqlite")).expanduser().resolve()


def admin_store(config: OpenAICompatConfig) -> BridgeAdminStore:
    return BridgeAdminStore(admin_db_path(config))


def console_served_locally(config: OpenAICompatConfig) -> bool:
    if os.environ.get("CHATGPT_CONSOLE_URL"):
        return False
    dist_index = project_root() / "apps" / "bridge-console" / "dist" / "index.html"
    return dist_index.is_file()


def console_url_for_config(config: OpenAICompatConfig) -> str:
    explicit = os.environ.get("CHATGPT_CONSOLE_URL")
    if explicit:
        return explicit.rstrip("/")
    if console_served_locally(config):
        host = "127.0.0.1" if config.host in ("0.0.0.0", "") else config.host
        # Trailing slash matters: the built SPA's asset tags are relative
        # ("./assets/..."), so the browser must resolve them against
        # /admin/ (a "directory"), not /admin (a "file").
        return f"http://{host}:{config.port}/admin/"
    return "http://127.0.0.1:5174"


def console_command_for_config(config: OpenAICompatConfig) -> str:
    explicit = os.environ.get("CHATGPT_CONSOLE_COMMAND")
    if explicit:
        return explicit
    return "bun --cwd apps/bridge-console dev"


def send_admin_root_redirect(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(308)
    handler.send_header("Location", "/admin/")
    handler.send_header("Content-Length", "0")
    handler.send_header("Cache-Control", "no-store")
    send_cors_headers(handler)
    handler.end_headers()


def send_console_redirect(handler: BaseHTTPRequestHandler, config: OpenAICompatConfig) -> None:
    body = json.dumps(
        {
            "ok": True,
            "message": "Bridge console runs on a separate port.",
            "console_url": console_url_for_config(config),
            "start_console": console_command_for_config(config),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    handler.send_response(308)
    handler.send_header("Location", console_url_for_config(config))
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    send_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


def send_admin_asset(handler: BaseHTTPRequestHandler, path: str) -> None:
    source_root = project_root() / "apps" / "bridge-console"
    dist_root = source_root / "dist"
    root = dist_root if (dist_root / "index.html").is_file() else source_root
    relative = "index.html" if path in {"/admin", "/admin/"} else path.removeprefix("/admin/").strip("/")
    if not relative:
        relative = "index.html"
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        send_json(handler, 404, {"error": {"message": "admin asset not found", "type": "not_found"}})
        return
    if not candidate.is_file():
        send_json(handler, 404, {"error": {"message": "admin asset not found", "type": "not_found"}})
        return
    body = candidate.read_bytes()
    content_type = guess_download_content_type(candidate)
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store" if candidate.name == "index.html" else "public, max-age=60")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def account_capture_usage_summary(config: OpenAICompatConfig, account: str) -> dict[str, Any]:
    try:
        capture = CapturedRequest.from_file(resolve_account_capture_path(account, config.accounts_dir))
        settings_path = resolve_account_settings_path(account, config.accounts_dir)
        settings = load_settings_file(str(settings_path)) if settings_path.exists() else {}
        info = detect_account_info(capture, settings)
        capabilities = infer_account_capabilities(info)
    except Exception as exc:  # noqa: BLE001 - usage can still include live error details.
        return {"profile_error": _public_status_error(exc)}
    return {
        "plan_type": info.plan_type,
        "plan_bucket": info.plan_bucket,
        "profile": info.to_redacted_dict(),
        "capabilities": capabilities,
    }


def known_admin_account_names(config: OpenAICompatConfig, router: "AccountRouter") -> list[str]:
    configured = set(router.accounts)
    stored_names = {entry["account"] for entry in admin_store(config).list_account_captures()}
    profile_names = {
        profile.name
        for profile in list_account_profiles(config.accounts_dir)
        if profile.exists or profile.has_settings or profile.name in configured or profile.name in stored_names
    }
    return sorted(configured | profile_names | stored_names)


def admin_accounts_response(config: OpenAICompatConfig, router: "AccountRouter") -> dict[str, Any]:
    configured = set(router.accounts)
    names = known_admin_account_names(config, router)
    captures_by_name = {entry["account"]: entry for entry in admin_store(config).list_account_captures()}
    accounts: list[dict[str, Any]] = []
    for name in names:
        capture_path = resolve_account_capture_path(name, config.accounts_dir)
        settings_path = resolve_account_settings_path(name, config.accounts_dir)
        summary = account_capture_usage_summary(config, name) if capture_path.exists() else {}
        accounts.append(
            {
                "account": name,
                "configured": name in configured,
                "capture_exists": capture_path.exists(),
                "settings_exists": settings_path.exists(),
                "capture_path": str(capture_path),
                "settings_path": str(settings_path),
                "stored": captures_by_name.get(name),
                **summary,
            }
        )
    return {
        "object": "chatgpt.admin.accounts",
        "accounts": accounts,
        "stored_captures": list(captures_by_name.values()),
    }


def admin_artifacts_response(config: OpenAICompatConfig, query: dict[str, list[str]]) -> dict[str, Any]:
    limit_text = query_value(query, "limit", "100")
    try:
        limit = int(limit_text)
    except ValueError:
        limit = 100
    return {
        "object": "chatgpt.admin.artifacts",
        "artifacts": admin_store(config).list_artifacts(limit=limit),
    }


def admin_opencode_status(config: OpenAICompatConfig) -> dict[str, Any]:
    config_path = opencode_config_path()
    state_path = opencode_state_path()
    opencode_config = read_json_file(config_path)
    provider = opencode_config.get("provider") if isinstance(opencode_config, dict) else {}
    chatgpt_provider = provider.get("chatgpt-web") if isinstance(provider, dict) else None
    options = chatgpt_provider.get("options") if isinstance(chatgpt_provider, dict) else {}
    model = opencode_config.get("model") if isinstance(opencode_config, dict) else None
    backup_path = opencode_backup_path(config_path)
    return {
        "object": "chatgpt.admin.opencode",
        "config_path": str(config_path),
        "state_path": str(state_path),
        "config_exists": config_path.exists(),
        "state_exists": state_path.exists(),
        "backup_exists": backup_path.exists(),
        "injected": isinstance(chatgpt_provider, dict),
        "model": model,
        "base_url": options.get("baseURL") if isinstance(options, dict) else None,
        "api_key": "<set>" if isinstance(options, dict) and options.get("apiKey") else None,
        "recommended": {
            "base_url": config.public_base_url or f"http://{config.host}:{config.port}/v1",
            "model": "chatgpt-web/auto@optimized",
        },
    }


def admin_account_delete_payload(
    config: OpenAICompatConfig,
    body: dict[str, Any],
    router: "AccountRouter",
) -> dict[str, Any]:
    account = safe_account_name(_str_or_none(body.get("account")) or "")
    delete_capture = body.get("delete_capture", True) is not False
    delete_settings = body.get("delete_settings", True) is not False
    capture_path = resolve_account_capture_path(account, config.accounts_dir)
    settings_path = resolve_account_settings_path(account, config.accounts_dir)
    deleted_capture = unlink_expected_account_file(capture_path) if delete_capture else False
    deleted_settings = unlink_expected_account_file(settings_path) if delete_settings else False
    deleted_store = admin_store(config).delete_account_capture(account)
    deleted_directory = remove_empty_account_dir(capture_path, settings_path)
    return {
        "object": "chatgpt.admin.account_delete",
        "ok": True,
        "account": account,
        "deleted": {
            "capture": deleted_capture,
            "settings": deleted_settings,
            "stored_metadata": deleted_store,
            "empty_directory": deleted_directory,
        },
        "remaining_accounts": known_admin_account_names(config, router),
        "paths": {
            "capture": str(capture_path),
            "settings": str(settings_path),
        },
    }


def admin_artifact_delete_payload(config: OpenAICompatConfig, body: dict[str, Any]) -> dict[str, Any]:
    file_id = _str_or_none(body.get("file_id"))
    if not file_id:
        raise ValueError("file_id is required")
    delete_file = bool(body.get("delete_file"))
    artifact = admin_store(config).delete_artifact(file_id)
    if artifact is None:
        raise ValueError("artifact was not found")
    deleted_file = False
    if delete_file:
        path = Path(str(artifact.get("path") or "")).expanduser()
        if path.is_file():
            path.unlink()
            deleted_file = True
    return {
        "object": "chatgpt.admin.artifact_delete",
        "ok": True,
        "file_id": file_id,
        "deleted": {
            "metadata": True,
            "file": deleted_file,
        },
        "artifact": artifact,
    }


def inspect_account_capture_payload(config: OpenAICompatConfig, body: dict[str, Any]) -> dict[str, Any]:
    account = safe_account_name(_str_or_none(body.get("account")) or config.account)
    capture_text = _str_or_none(body.get("capture_text")) or _str_or_none(body.get("capture")) or ""
    settings = settings_from_admin_body(body)
    return inspect_account_capture(config, account, capture_text, settings)


def unlink_expected_account_file(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return False
    resolved.unlink()
    return True


def remove_empty_account_dir(*paths: Path) -> bool:
    removed = False
    for path in paths:
        directory = path.expanduser().resolve().parent
        try:
            directory.rmdir()
        except OSError:
            continue
        removed = True
    return removed


def save_account_capture_payload(config: OpenAICompatConfig, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    account = safe_account_name(_str_or_none(body.get("account")) or config.account)
    capture_text = _str_or_none(body.get("capture_text")) or _str_or_none(body.get("capture")) or ""
    settings_text = _str_or_none(body.get("settings_text"))
    force = bool(body.get("force"))
    settings = settings_from_admin_body(body)
    inspection = inspect_account_capture(config, account, capture_text, settings)
    failed_checks = [
        check["name"]
        for check in inspection.get("checks", [])
        if check.get("level") in {"required", "recommended"} and not check.get("ok")
    ]
    if failed_checks and not force:
        return 400, {
            "error": {
                "message": "capture did not pass validation",
                "type": "invalid_request_error",
                "failed": failed_checks,
                "missing": inspection["missing"],
                "warnings": inspection["warnings"],
            },
            "inspection": inspection,
        }
    capture_path = resolve_account_capture_path(account, config.accounts_dir)
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    accounts_dir = config.accounts_dir if config.accounts_dir is not None else accounts_dir_from_env()
    key = load_secrets_key(accounts_dir)
    capture_path.write_text(encrypt_text(capture_text, key), encoding="utf-8")
    if settings_text:
        settings_path = resolve_account_settings_path(account, config.accounts_dir)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    admin_store(config).record_account_capture(
        account=account,
        capture_path=capture_path,
        inspection=inspection,
    )
    return 200, {"saved": True, "capture_path": str(capture_path), "inspection": inspection}


def inspect_account_capture(
    config: OpenAICompatConfig,
    account: str,
    capture_text: str,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    capture: CapturedRequest | None = None
    detected: dict[str, Any] = {}
    capabilities: dict[str, Any] = {}
    try:
        capture = CapturedRequest.from_text(capture_text)
        info = detect_account_info(capture, settings or {})
        detected = info.to_redacted_dict()
        capabilities = infer_account_capabilities(info)
    except Exception as exc:  # noqa: BLE001 - admin screen should show parse failures.
        checks.append(admin_check("parse", "required", False, _public_status_error(exc)))

    url = capture.url if capture else None
    request_json = capture.request_json if capture else None
    headers = capture.headers if capture else {}
    cookies = capture.cookies if capture else {}
    is_prepare_capture = bool(url and "/backend-api/f/conversation/prepare" in url)
    add_admin_check(checks, "url", "required", bool(url and "chatgpt.com" in url), url or "missing")
    add_admin_check(
        checks,
        "authorization",
        "required",
        bool(headers.get("authorization", "").lower().startswith("bearer ")),
        "Bearer token found" if headers.get("authorization") else "missing Authorization header",
    )
    add_admin_check(checks, "cookie", "required", bool(headers.get("cookie") or cookies), f"{len(cookies)} cookies")
    request_json_ok = isinstance(request_json, dict) or is_prepare_capture
    request_json_detail = (
        "payload parsed"
        if isinstance(request_json, dict)
        else "prepare capture; payload optional"
        if is_prepare_capture
        else "missing Request Data JSON"
    )
    add_admin_check(checks, "request_json", "required", request_json_ok, request_json_detail)
    add_admin_check(
        checks,
        "model",
        "recommended",
        bool((isinstance(request_json, dict) and request_json.get("model")) or is_prepare_capture),
        _str_or_none(request_json.get("model"))
        if isinstance(request_json, dict)
        else "prepare capture; inferred at request time"
        if is_prepare_capture
        else "missing",
    )
    add_admin_check(
        checks,
        "action",
        "recommended",
        bool((isinstance(request_json, dict) and request_json.get("action")) or is_prepare_capture),
        _str_or_none(request_json.get("action"))
        if isinstance(request_json, dict)
        else "prepare capture; inferred at request time"
        if is_prepare_capture
        else "missing",
    )
    for header_name in (
        "openai-sentinel-chat-requirements-token",
        "openai-sentinel-proof-token",
        "openai-sentinel-turnstile-token",
        "x-conduit-token",
        "oai-device-id",
        "oai-session-id",
    ):
        add_admin_check(
            checks,
            header_name,
            "recommended",
            bool(headers.get(header_name)),
            "present" if headers.get(header_name) else "missing",
        )
    missing = [check["name"] for check in checks if check["level"] == "required" and not check["ok"]]
    warnings = [check["name"] for check in checks if check["level"] == "recommended" and not check["ok"]]
    return {
        "ok": not missing,
        "account": account,
        "missing": missing,
        "warnings": warnings,
        "checks": checks,
        "detected": detected,
        "capabilities": capabilities,
        "preview": {
            "url": url,
            "status": capture.status if capture else None,
            "request_model": request_json.get("model") if isinstance(request_json, dict) else None,
            "request_action": request_json.get("action") if isinstance(request_json, dict) else None,
            "request_thinking_effort": request_json.get("thinking_effort") if isinstance(request_json, dict) else None,
            "headers": redacted_headers(headers),
            "cookie_count": len(cookies),
            "capture_path": str(resolve_account_capture_path(account, config.accounts_dir)),
        },
    }


def add_admin_check(checks: list[dict[str, Any]], name: str, level: str, ok: bool, detail: str | None = None) -> None:
    checks.append(admin_check(name, level, ok, detail))


def admin_check(name: str, level: str, ok: bool, detail: str | None = None) -> dict[str, Any]:
    return {"name": name, "level": level, "ok": ok, "detail": detail}


def settings_from_admin_body(body: dict[str, Any]) -> dict[str, Any]:
    settings = body.get("settings")
    if isinstance(settings, dict):
        return settings
    settings_text = _str_or_none(body.get("settings_text"))
    if not settings_text:
        return {}
    parsed = json.loads(settings_text)
    if not isinstance(parsed, dict):
        raise ValueError("settings_text must be a JSON object")
    return parsed


def redacted_headers(headers: dict[str, str]) -> dict[str, str]:
    return {name: ("<redacted>" if name.lower() in SECRET_HEADER_NAMES else value) for name, value in headers.items()}


def safe_account_name(value: str) -> str:
    account = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", account):
        raise ValueError("account must use only English letters, numbers, dash, or underscore")
    return account


def opencode_inject_payload(config: OpenAICompatConfig, body: dict[str, Any]) -> dict[str, Any]:
    config_path = Path(_str_or_none(body.get("config_path")) or str(opencode_config_path())).expanduser()
    base_url = _str_or_none(body.get("base_url")) or config.public_base_url or f"http://{config.host}:{config.port}/v1"
    api_key = _str_or_none(body.get("api_key")) or config.api_key
    if not api_key:
        raise ValueError("a local API key is required; set CHATGPT_API_KEY or provide api_key")
    model = _str_or_none(body.get("model")) or "chatgpt-web/auto@optimized"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = opencode_backup_path(config_path)
    existing = read_json_file(config_path)
    if config_path.exists() and not backup_path.exists():
        backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    merged = opencode_config_with_chatgpt(existing, base_url=base_url, api_key=api_key, model=model)
    write_json_file(config_path, merged)
    state = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "config_path": str(config_path),
        "source": "bridge-console",
    }
    write_json_file(opencode_state_path(), state)
    return {"ok": True, "action": "inject", **admin_opencode_status(config)}


def opencode_eject_payload(body: dict[str, Any]) -> dict[str, Any]:
    config_path = Path(_str_or_none(body.get("config_path")) or str(opencode_config_path())).expanduser()
    backup_path = opencode_backup_path(config_path)
    if backup_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
        return {"ok": True, "action": "restore-backup", "config_path": str(config_path), "backup_path": str(backup_path)}
    existing = read_json_file(config_path)
    provider = existing.get("provider") if isinstance(existing.get("provider"), dict) else {}
    if isinstance(provider, dict):
        provider.pop("chatgpt-web", None)
        existing["provider"] = provider
    command = existing.get("command") if isinstance(existing.get("command"), dict) else {}
    if isinstance(command, dict):
        for key in ("chatgpt:usage", "chatgpt:remain", "chatgpt:remaining", "chatgpt:research"):
            command.pop(key, None)
        existing["command"] = command
    for key in ("model", "small_model"):
        if isinstance(existing.get(key), str) and str(existing[key]).startswith("chatgpt-web/"):
            existing.pop(key, None)
    write_json_file(config_path, existing)
    return {"ok": True, "action": "eject", "config_path": str(config_path), "backup_path": str(backup_path)}


def opencode_config_with_chatgpt(existing: dict[str, Any], *, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    config = dict(existing)
    template = read_json_file(project_root() / "integrations" / "opencode" / "opencode.example.json")
    template_provider = (template.get("provider") or {}).get("chatgpt-web") if isinstance(template.get("provider"), dict) else {}
    provider = dict(config.get("provider") if isinstance(config.get("provider"), dict) else {})
    chatgpt_provider = dict(template_provider if isinstance(template_provider, dict) else {})
    options = dict(chatgpt_provider.get("options") if isinstance(chatgpt_provider.get("options"), dict) else {})
    options["baseURL"] = base_url
    options["apiKey"] = api_key
    chatgpt_provider["options"] = options
    provider["chatgpt-web"] = chatgpt_provider
    config["provider"] = provider
    config["model"] = model
    config["small_model"] = model
    command = dict(config.get("command") if isinstance(config.get("command"), dict) else {})
    command.update(
        {
            "chatgpt:usage": {"template": "/chatgpt:usage", "description": "Show ChatGPT Web account usage"},
            "chatgpt:remain": {"template": "/chatgpt:remain", "description": "Show remaining ChatGPT Web quota"},
            "chatgpt:remaining": {"template": "/chatgpt:remain", "description": "Alias for remaining ChatGPT Web quota"},
            "chatgpt:research": {
                "template": "Run ChatGPT Deep Research for: $ARGUMENTS",
                "description": "Ask the local GPT Bridge to run Deep Research",
            },
        }
    )
    config["command"] = command
    return config


def opencode_config_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "opencode" / "opencode.json"


def opencode_state_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "gpt-bridge" / "opencode-setup.json"


def opencode_backup_path(config_path: Path) -> Path:
    return config_path.with_name(f"{config_path.name}.gpt-bridge.bak")


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

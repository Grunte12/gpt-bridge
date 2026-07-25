# GPT Bridge provenance and release boundary

GPT Bridge is an independently maintained local-first project. The repository
license is MIT; preserve the copyright and license notice in [LICENSE](LICENSE)
when redistributing substantial portions of this code.

## What this repository contains

- First-party Python source under `chatgpt_api/`, the Bridge Console, Docker
  configuration, documentation, tests, and the Codex plugin.
- Declared third-party dependencies resolved by normal package managers. Python
  dependencies are listed in `pyproject.toml`; Console dependencies are listed
  in `apps/bridge-console/package.json` and its lockfile.
- No copied upstream source file is required by the GPT Bridge runtime. The
  former `references/legacy/OpenaiChat.py` reference was deliberately removed
  before this release work because it was not part of the runtime and its
  provenance was unsuitable for this project.

This is an engineering inventory, not legal advice or a claim that every
transitive dependency has been independently audited.

## Naming and service boundary

GPT Bridge is not affiliated with, endorsed by, or provided by OpenAI. The
project may interoperate with a user-managed ChatGPT Web session, but the name
does not grant any right to OpenAI, ChatGPT, or GPT marks. Do not describe the
project as official, sell account access, operate it as a hosted proxy, or use
it to bypass provider controls. See [DISCLAIMER.md](DISCLAIMER.md).

## Release gate

Before publishing a release:

1. Review `git diff --check`, the license notices, and all newly added source
   files for copied code or incompatible headers.
2. Regenerate and review dependency/SBOM or license reports for Python and the
   Console lockfile using the release environment.
3. Run the documented unit, Console, Docker, and manual local-account checks.
4. Verify documentation says `gpt-bridge` is the primary command and does not
   promise official support, browser automation bypasses, or public hosting.
5. Never publish `.env`, `secrets/`, account captures, generated artifact
   capability URLs, or screenshots that reveal account/session material.

> ภาษาไทย: เอกสารนี้อธิบายขอบเขต source และขั้นตอนตรวจ release ไม่ใช่คำปรึกษา
> ด้านกฎหมาย ก่อนเผยแพร่ให้ตรวจ dependency, license, secret และข้อความอ้างสิทธิ์
> ทุกครั้ง

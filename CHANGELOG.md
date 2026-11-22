# Changelog

## 0.1.46 (unreleased)

- New MCP tool `run`: one call submits once (durable `request_id`), waits, saves the image to `out_path`, cleans up and recovers. Returns `done`, `failed` or a resumable `running`, with a `cause` code and `safe_to_retry`.
- False stalls: the worker reloads the exact bound chat in a visible tab after 150 s without an image and before any timeout, then collects the finished image. Recovered outputs now send their durable phase receipts.
- A failed timed-out-chat delete marks the job `preserved` and no longer blocks pairing or the queue. A finished image found during that delete is collected from the same chat; its replacement is canceled.
- Chat delete finds the current header menu (`app-shell-header-context-menu-surface`).

## 0.1.45 (unreleased)

- Apply the owner's saved-chat cleanup policy to new owned image jobs only after verified durable output; batch jobs also require their verified run-folder copy. Failed, uncertain and incomplete jobs preserve their chats.

#!/bin/bash
# Make sure Chrome is running with a chatgpt.com tab so the paired extension can bind it.
# Usage: scripts/ensure-chatgpt-tab.sh   (macOS; does nothing if a tab already exists)
set -e
osascript <<'OSA'
if application "Google Chrome" is not running then
  tell application "Google Chrome" to activate
  delay 3
end if
tell application "Google Chrome"
  repeat with w in windows
    repeat with t in tabs of w
      if URL of t starts with "https://chatgpt.com" then return "tab exists"
    end repeat
  end repeat
  if (count of windows) = 0 then make new window
  tell front window to make new tab with properties {URL:"https://chatgpt.com/"}
  return "opened"
end tell
OSA

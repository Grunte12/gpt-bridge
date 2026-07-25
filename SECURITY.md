# Security policy

## Supported local boundary

The supported deployment is a single-user local installation. Docker publishes
the API and Console to `127.0.0.1` by default. Keep the generated
`CHATGPT_API_KEY` private and do not change the port mappings to LAN/public
addresses unless you understand and accept the additional risk.

## Sensitive data

Account captures/session records can contain cookies, bearer tokens, and
request metadata. The bridge encrypts stored captures at rest. For stronger
protection on a shared or portable machine, use the interactive secrets
passphrase option instead of relying only on the local key file.

- never commit `secrets/`, `.env`, copied request data, or browser profiles;
- never put real captures in tests, screenshots, issues, logs, or support
  requests;
- use `gpt-bridge auth logout --account NAME` to remove a local session; and
- revoke or sign out of the upstream service if you believe a session leaked.

The project does not collect telemetry or upload account-session material.

## Experimental browser onboarding

`gpt-bridge auth login` is opt-in and uses a visible Chrome window with a
disposable profile. The user must perform
authentication and any provider challenge manually. Cancellation, timeout, or
an incomplete request leave no durable session record; the temporary profile is
removed as normal filesystem cleanup. Secure erasure cannot be guaranteed on
all storage devices.

## Reporting a vulnerability

Do not include credentials or a raw capture in a public issue. Report the
behavior, affected version, redacted logs, and reproducible non-secret steps to
the repository maintainer privately. Rotate/revoke any potentially exposed
session before reporting.

## ภาษาไทย

ค่าปริยายรองรับการใช้งานคนเดียวบนเครื่องเดียว API และ Console bind ที่
`127.0.0.1` เท่านั้น เก็บ `CHATGPT_API_KEY` และ account capture เป็นความลับเสมอ

หาก session หลุด ให้ใช้ `auth logout` เพื่อลบข้อมูลในเครื่อง และ revoke/sign out
จากบริการต้นทาง อย่าส่ง raw capture หรือ cookie ใน public issue. Flow browser แบบ
ทดลองใช้ Chrome profile ชั่วคราว; ผู้ใช้ต้อง login และผ่าน challenge เอง และข้อมูล
จะไม่ถูกบันทึกถ้ายกเลิก, timeout หรือ validation ไม่ผ่าน

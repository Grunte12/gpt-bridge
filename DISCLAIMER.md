# Experimental local Web-session bridge

This is an unofficial, experimental, local-first developer tool. It is not
affiliated with, endorsed by, sponsored by, or supported by OpenAI.

## What it is

The project lets a person use a session from **their own account** through a
local bridge and worker workflow on their own computer. It is intended for
personal experiments, prototypes, and local development.

## What it is not

- not an official API or an OpenAI product;
- not a hosted service, public proxy, shared-account system, resale service,
  or multi-tenant platform;
- not a way to bypass account limits, rate limits, safety controls, region
  controls, browser challenges, or payment requirements; and
- not a guarantee that any provider endpoint, model, session, or automation
  workflow will keep working.

You are responsible for your account, your content, applicable law, and the
terms and policies that apply to services you use. If a provider rejects or
expires a session, stop and refresh it through a normal user-controlled flow.

## Session safety

An account capture/session is as sensitive as a password. Keep it on your own
machine, never commit it, never paste it into issues or chat, and never give it
to another person. The default Docker stack is loopback-only; do not expose it
to the LAN or internet.

The `gpt-bridge auth login` command opens a visible, isolated local browser.
You complete sign-in, MFA, and any challenge yourself. It does not enter
passwords, solve challenges, use stealth automation, attach to your normal
browser profile, or upload session material. It saves only after local success
and removes its temporary browser profile afterward.

## ภาษาไทย

โปรเจกต์นี้เป็นเครื่องมือทดลองแบบ local-first ที่ไม่เป็นทางการ และไม่มีความ
เกี่ยวข้องหรือได้รับการรับรองจาก OpenAI ผู้ใช้ใช้เฉพาะ account ของตนเองบนเครื่อง
ของตนเองเท่านั้น ห้ามนำไปทำ public proxy, แชร์ account, ขายต่อ หรือหลบข้อจำกัดของ
ผู้ให้บริการ

session/capture มีความลับเทียบเท่ารหัสผ่าน ห้าม commit, ส่งเข้า issue, แปะใน chat
หรือแชร์ให้ผู้อื่น คำสั่ง `auth login` เปิด browser ที่แยก profile ชั่วคราวให้ผู้ใช้
login และผ่าน MFA/challenge เอง ไม่กรอกรหัสแทน ไม่ bypass การป้องกัน และไม่ส่ง
session ออกนอกเครื่อง

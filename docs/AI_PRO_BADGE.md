# AI Coach Pro — self badge (server truth)

**Self-only (v1).** Show Pro on Account / Profile / AI screens for the **logged-in** user.  
Do **not** put `aiPro` on public `GET /coaches` (avoids mix-up with Verified / Boost).

## Endpoints

| Path | Use |
|------|-----|
| `GET /me/ai` | Full AI subscription + badge fields |
| `GET /me/entitlements` → `ai` | Same badge fields (alongside Boost) |
| `GET /me` → `aiPro` | Lightweight `{ active, badgeLabel, badgeFullLabel }` |

## iOS mapping

```swift
if ai.active, let badge = ai.badgeLabel { // "Pro"
  showChip(title: badge, accessibilityLabel: ai.badgeFullLabel) // "AI Coach Pro"
}
Text(ai.planDisplayName ?? "") // "Monthly" / "Yearly"
```

| Field | Active | Inactive |
|-------|--------|----------|
| `active` | `true` | `false` |
| `badgeLabel` | `"Pro"` | `null` |
| `badgeFullLabel` | `"AI Coach Pro"` | `null` |
| `planDisplayName` | `"Monthly"` / `"Yearly"` | `null` |
| `status` | `active` / `grace` / `billing_retry` | `inactive` / `expired` / `revoked` |
| `willRenew` | `true` (Apple); `false` (manual grant) | `false` |
| `renewsAt` | usually = `endsAt` | `null` |

Never treat Boost `boostActive` or coach `isVerified` as AI Pro.

## Privacy

No receipts, JWS, payer email, or payment method on these payloads.

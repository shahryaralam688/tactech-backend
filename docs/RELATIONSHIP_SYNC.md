# Live relationship sync (leave / remove / accept)

When the active trainer↔trainee link changes, the **peer** gets a durable inbox row + Socket events so a foreground app refreshes without force-quit.

## Personal room targeting

```python
# ChatHub.emit_relationship_changed / emit_notification
room = f"user:{user_id}"
# Emitted on namespaces "/" and "/chat" (same as notification.created / call ring)
await sio.emit("relationship.changed", payload, room=room, namespace=namespace)
```

Clients must join `user:{accessToken.sub}` on connect (already done for chat).

## Notification type

| Inbox `type` | When |
|--------------|------|
| `relationship_ended` | Leave or Remove |
| `join_request_accepted` | Accept (unchanged) |

`relationship_ended` data always includes `reason`: `trainee_left` | `trainer_removed`.

## Dedicated Socket event

```json
{
  "action": "unlinked",
  "reason": "trainee_left",
  "trainerUserId": "…",
  "traineeUserId": "…",
  "traineeProfileId": "…",
  "occurredAt": "2026-10-14T15:00:00Z"
}
```

| `action` | `reason` |
|----------|----------|
| `unlinked` | `trainee_left` / `trainer_removed` |
| `linked` | `join_accepted` |

## Emit helper (server)

```python
# Inbox + notification.created + relationship.changed (peer + actor)
push.notify_relationship_ended_sync(
    peer_user_id=trainer_user_id,
    actor_user_id=trainee.user_id,
    reason="trainee_left",
    title="Trainee left",
    body=f"{name} left your coaching roster.",
    trainer_user_id=trainer_user_id,
    trainee_user_id=trainee.user_id,
    trainee_profile_id=trainee.id,
)

# Accept: keep join_request_accepted, add domain event
push.emit_relationship_changed_sync(
    user_ids=[trainee_user_id, trainer_user_id],
    action="linked",
    reason="join_accepted",
    trainer_user_id=trainer_user_id,
    trainee_user_id=trainee_user_id,
    trainee_profile_id=trainee_id,
)
```

404 unlink/remove (already gone) → **no** notify.

iOS: on `relationship.changed` or `notification.created` with `type=relationship_ended`, refresh roster / My Trainer.
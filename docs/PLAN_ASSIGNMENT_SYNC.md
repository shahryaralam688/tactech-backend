# Live plan assignment sync

When a trainer assigns, unassigns, updates, or deletes an assigned plan, the **trainee** gets a durable inbox row + Socket events (no APNs required).

## When

| Action | REST | Inbox `type` | `plan.assignment.changed` |
|--------|------|--------------|---------------------------|
| Assign | `POST /trainer/assignments` | `plan_assigned` | `action: assigned` |
| Unassign | `DELETE /trainer/assignments…` | `plan_unassigned` | `action: unassigned` |
| PATCH assigned plan | `PATCH /trainer/plans/{id}` | `plan_updated` | `action: updated` |
| Delete plan (clears assignees) | `DELETE /trainer/plans/{id}` | `plan_unassigned` (each trainee) | `action: unassigned` |

Leave/remove already clear the plan via relationship events — no extra plan notify required.

## Room targeting

```python
room = f"user:{traineeUserId}"
# namespaces "/" and "/chat" (same as notification.created / relationship.changed)
await sio.emit("plan.assignment.changed", payload, room=room, namespace=namespace)
```

Trainer multi-device also receives `plan.assignment.changed` (optional refresh).

## Domain payload

```json
{
  "action": "assigned",
  "planId": "plan_…",
  "planTitle": "Strength Week 1",
  "trainerUserId": "u_…",
  "traineeUserId": "u_…",
  "traineeProfileId": "tp_…",
  "occurredAt": "2026-10-14T16:00:00Z"
}
```

## Server helper

```python
push.notify_plan_assignment_changed_sync(
    action="assigned",  # | unassigned | updated
    peer_trainee_user_id=trainee.user_id,
    actor_trainer_user_id=trainer.user_id,
    plan_id=plan.id,
    plan_title=plan.title,
    trainer_user_id=trainer.user_id,
    trainee_user_id=trainee.user_id,
    trainee_profile_id=trainee.id,
    trainer_name=trainer_name,
)
```

iOS: on `plan.assignment.changed` or `notification.created` with `plan_*`, refetch `GET /trainee/assigned-plan`.

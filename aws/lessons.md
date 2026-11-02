# AWS lessons

Things about AWS that bit us in production and that the docs don't make obvious.

---

## Auto Scaling's AZ rebalancing kills a second instance after you terminate one

Observed 2026-09-28 in a production web app [confirmed: `aws autoscaling describe-scaling-activities`,
CloudTrail].

The setup: an app's own scheduler scales an Auto Scaling group (ASG) up before scheduled sessions and
removes the instances it no longer needs with `TerminateInstanceInAutoScalingGroup(...,
ShouldDecrementDesiredCapacity=true)`. Each live session runs on one specific instance.

What happened, within 21 seconds:

1. The scheduler terminated an empty instance. Desired capacity went from 3 to 2. That was correct.
2. The remaining 2 instances were both in one Availability Zone, and the other zone had 0. The ASG's
   **AZRebalance** process launched a new instance in the empty zone.
3. That put the group at 3 instances against a desired capacity of 2, so the ASG terminated one
   instance in the crowded zone, chosen by its default termination policy (the oldest). That instance
   was hosting a live session, and the session died.

Why it's not guessable:
- A *targeted*, capacity-decrementing terminate looks like it should affect only the instance you
  name. It can still trigger a second termination you didn't ask for.
- Scale-in protection and termination policies are documented as scale-in controls. Rebalancing is a
  separate process, and it is easy to overlook that it is enabled by default.
- The app's own logs show only the termination it asked for.

**Fix:** if instances hold state that can't be moved (a live call, a game, an in-memory session),
suspend rebalancing on that group:
```bash
aws autoscaling suspend-processes --auto-scaling-group-name <asg> --scaling-processes AZRebalance
```
Zone balance gives no redundancy anyway when each session lives on a single instance.

## "User initiated" doesn't mean a human did it

On the EC2 instance, the terminated instance showed `StateTransitionReason: User initiated` and
`Client.UserInitiatedShutdown` [confirmed]. CloudTrail showed that the caller was **`AutoScaling`**.
"User initiated" only means an API call terminated it, as opposed to a hardware or spot interruption.

**How to find the actual reason:** use the **`Cause`** field of `aws autoscaling
describe-scaling-activities`. It spells out the chain ("launched to balance instances in zones … resulting
in more than desired number … instance X was selected for termination"). To find the caller, use
CloudTrail `lookup-events` with `ResourceName=<instance-id>` and read the `Username` column.

## Look up terminated instances quickly

`describe-instances` stops returning terminated instances roughly an hour after they terminate [concluded,
from AWS behaviour; not timed here]. When a server has just died, run `describe-instances` for its state
reason **first**. Scaling activities and CloudTrail are kept much longer and can wait.

# Checkout API deployment runbook

This is synthetic sample guidance for the local ReleasePilot walkthrough. It is not an operational procedure for a real service.

## Before deployment

Verify the integration, unit-test, and security checks on the exact release commit. Obtain an approving review. Record the current image digest and confirm the health dashboard is available.

## Database migration

Take a database backup and verify that it can be restored before applying a migration. Use backward-compatible additive schema changes while old and new application versions overlap. Apply the migration once and inspect its result before starting the rollout.

## Rollout and monitoring

Deploy a small canary first. Check checkout success rate, error rate, and latency. Continue the rollout only after the canary remains healthy. Record the deployed commit and image digest.

## Rollback

If checkout failures or latency increase, stop the rollout and restore the previous known-good image digest. Verify health checks and run a checkout smoke test. Do not blindly reverse a destructive schema change; use the verified backup and an operator-reviewed recovery procedure when data restoration is required.

## After deployment

Confirm the complete rollout is healthy and record the release decision, evidence, and any follow-up tasks.

# AWS deployment (prepared, not deployed)

The checked-in CloudFormation template is for a **non-production portfolio environment**. It has been validated locally with `cfn-lint`; no stack was created and no AWS runtime result is claimed. You do not need AWS to run the project.

## Architecture and prerequisites

`stack.json` provisions an ECS cluster with separate Fargate frontend, API, worker, private MCP, and disposable Redis services; private RDS PostgreSQL; encrypted/versioned S3; encrypted SQS with a dead-letter queue; Secrets Manager; an HTTPS ALB; CloudWatch logs and a backlog alarm; and a monthly budget email. PostgreSQL is the authority for jobs and reports. Redis can be replaced without losing durable data.

Bring an existing VPC, two public ALB subnets, two private subnets in different availability zones, and NAT egress from the private subnets. The private tasks need GitHub, OpenAI, ECR, CloudWatch, Secrets Manager, and AWS API access. Supply an ACM certificate and a domain in the same region. The template does not create DNS records or a VPC/NAT gateway.

This deliberately small environment uses a single-AZ database and one task per service. The Redis container is an ephemeral cache, not ElastiCache. The generated RDS owner credential is used by the application and migration task for initial portfolio setup; before a shared/production deployment, create separate migration and runtime database roles with scoped grants. This is not a production-hardening claim.

## Prepare images and secrets

1. Create two private ECR repositories, `releasepilot-backend` and `releasepilot-frontend`, with scanning enabled. Publish immutable commit tags; deploy digests where possible.
2. Build Linux AMD64 images. For the frontend set `--build-arg API_INTERNAL_URL=http://api.releasepilot:8000`. The ALB routes `/api/v1/*` directly to the API; the private URL also supports the Next.js rewrite. The optional `publish-images.yml` workflow publishes on manual dispatch after you configure its AWS OIDC role and repository variables.
3. In Secrets Manager, create a JSON secret containing `OPENAI_API_KEY`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_APP_PRIVATE_KEY`, and `DEMO_PASSWORD`. Empty provider values allow deterministic fallback, but set a strong demo password and webhook secret. Put the GitHub App PEM content in the private-key field, preserving newlines. Do not paste secrets into CloudFormation parameters or commit parameter files containing secrets.
4. Configure the App ID/slug/client ID as non-secret stack parameters. Set its callback to `https://your-domain/api/v1/github/callback` and webhook to `https://your-domain/api/v1/webhooks/github`.

## Deploy deliberately

Run these steps yourself when you want a hosted environment. They create billable resources.

1. Validate: `backend/.venv/bin/cfn-lint infrastructure/aws/stack.json`.
2. Create a CloudFormation stack from `stack.json`, acknowledge IAM capabilities, and supply the parameters. Leave `DesiredCount=0` initially. Record the cluster, migration task, and task security group outputs.
3. Run the `MigrationTask` once in that cluster using Fargate, the private subnets, the task security group, and no public IP. Its command is `alembic upgrade head && python -m app.seed`. Inspect the exit code and CloudWatch logs. Migration enables `vector`, creates the schema, and seeds the private demo account. Do not start app traffic until it succeeds.
4. Update `DesiredCount` to `1`. Wait for each ECS service to stabilize and the API/frontend target groups to become healthy. Create an alias/CNAME for the app origin pointing at the ALB output.
5. Sign in over HTTPS. Verify secure cookies, upload a runbook, connect your installation, and run both a fixture and a real repository analysis. Confirm MCP has no public listener. Run a negative signature webhook test and inspect SQS/DLQ and CloudWatch.
6. Use `scripts/smoke.py` with `SMOKE_ORIGIN` and matching local credentials only against an environment you own. Record results separately from the checked-in offline evaluation results.

For updates: publish new immutable images, update image parameters, run backward-compatible migrations, then roll out services. ECS deployment circuit breakers roll back unhealthy service deployments. Database downgrades are a separate operation: take a snapshot first and inspect data-loss implications. Keep schema changes compatible with both task revisions during rollout.

## Cost and teardown

The $50 monthly budget configured here is an alert threshold, **not an estimate or spending cap**. Fargate, RDS, ALB, NAT, logs, storage, and model usage are separately billable. Check the AWS Pricing Calculator for your region before provisioning. NAT and ALB continue costing money even when task counts are zero.

To stop compute, set `DesiredCount=0`. For full teardown, first export any reports/documents you want to keep, disable RDS deletion protection explicitly, then delete the stack. RDS snapshots and the versioned S3 bucket are retained intentionally and may still incur charges. Delete retained objects (including versions), snapshots, ECR images, and any VPC/NAT resources only after confirming they are no longer needed.

## Sources

- [ECS Secrets Manager environment injection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html)
- [ECS sensitive data guidance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specifying-sensitive-data.html)
- [SQS developer guide](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html)

`generate.py` regenerates the template without contacting AWS. Review changes to both files together.

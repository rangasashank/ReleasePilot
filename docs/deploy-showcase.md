# Publish a hosted ReleasePilot showcase

This is the first-deployment runbook for the included AWS template. Run commands from the repository root. Replace every placeholder before running. These steps create billable resources; they have not yet been executed against an AWS account. The local app does not need to be running.

## 1. Prepare your account, network, and domain

Install AWS CLI v2 and Docker Desktop, and start Docker Desktop to build images. Use an AWS profile allowed to create the resources in the template (CloudFormation, IAM roles/pass-role, ECS, ECR, RDS, S3, SQS, Secrets Manager, Cloud Map, ALB, logs, and Budgets).

```bash
aws configure sso --profile releasepilot
aws sso login --profile releasepilot
export AWS_PROFILE=releasepilot
export AWS_REGION=us-west-2
aws sts get-caller-identity
```

If you already have a working AWS profile, use its name instead. Use the same region for ECR, Secrets Manager, ACM, and CloudFormation.

In the VPC console, use **Create VPC → VPC and more** if you do not already have suitable networking. Choose two availability zones, two public subnets, two private subnets, and NAT egress for the private subnets (one NAT gateway is sufficient for this portfolio setup, with reduced availability). Enable DNS resolution and DNS hostnames. Record the VPC and subnet IDs. Verify the public route tables use the internet gateway and private route tables use NAT. Existing suitable networking can be reused.

Choose a hostname such as `releasepilot.example.com`. Request an ACM public certificate in the chosen region, add its DNS validation record at your DNS provider, and wait for **Issued**. Record its ARN. You need control of the domain; an ALB hostname alone does not satisfy this template's HTTPS setup.

## 2. Create application secrets

In Secrets Manager, select **Store a new secret → Other type of secret**, use the default Secrets Manager encryption key, and create a secret named `releasepilot/providers`. Include all five keys:

| Key | Value |
| --- | --- |
| `DEMO_PASSWORD` | Strong unique password for the hosted account |
| `GITHUB_WEBHOOK_SECRET` | Random secret; use the same value in your GitHub App |
| `OPENAI_API_KEY` | Your API key, or an empty string for the synthetic demo |
| `GITHUB_CLIENT_SECRET` | GitHub App OAuth client secret, or an empty string initially |
| `GITHUB_APP_PRIVATE_KEY` | Complete downloaded PEM text, including line breaks, or an empty string initially |

Use a password manager to generate secrets. Enter PEM text through the key/value editor, or represent its newlines as `\n` in valid JSON. Do not upload the local `.env` or enter secrets into CloudFormation parameters. Record only the secret ARN for deployment.

The template generates the RDS password and `INTERNAL_SECRET`, and configures database/Redis/MCP addresses, S3/SQS resources, secure cookies, and AWS roles automatically. You do not provide AWS access keys to application containers. `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, and `GITHUB_CLIENT_ID` are non-secret stack parameters.

For a first showcase, empty provider credentials are supported: fixture analyses still work. Live repository analysis with a completed model review needs the actual provider configuration described in step 7.

## 3. Build and publish images

Run this from your clean, committed checkout. The immutable tag identifies the commit being deployed.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
IMAGE_TAG=$(git rev-parse HEAD)

aws ecr create-repository --repository-name releasepilot-backend --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true
aws ecr create-repository --repository-name releasepilot-frontend --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true

aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY"

docker buildx build --platform linux/amd64 --tag "$REGISTRY/releasepilot-backend:$IMAGE_TAG" --push ./backend
docker buildx build --platform linux/amd64 --build-arg API_INTERNAL_URL=http://api.releasepilot:8000 --tag "$REGISTRY/releasepilot-frontend:$IMAGE_TAG" --push ./frontend

printf 'BackendImage=%s/releasepilot-backend:%s\nFrontendImage=%s/releasepilot-frontend:%s\n' "$REGISTRY" "$IMAGE_TAG" "$REGISTRY" "$IMAGE_TAG"
```

Create each ECR repository only once. For later deployments, skip creation and publish a new commit tag. An existing immutable tag cannot be overwritten. Do not repeat a successful push of the same tag unnecessarily.

## 4. Create the stack with traffic disabled

In CloudFormation choose **Create stack → With new resources → Upload a template file** and upload `infrastructure/aws/stack.json`. Name the stack `releasepilot`.

| Parameter | Supply |
| --- | --- |
| `VpcId` | VPC ID from step 1 |
| `PublicSubnets` | Two public subnet IDs in different AZs |
| `PrivateSubnets` | Two private subnet IDs in different AZs, with NAT egress |
| `CertificateArn` | Issued ACM certificate ARN |
| `AppOrigin` | Your HTTPS origin, e.g. `https://releasepilot.example.com`, without a trailing slash |
| `BackendImage` | Backend image URI printed above |
| `FrontendImage` | Frontend image URI printed above |
| `ProviderSecretArn` | Secret ARN from step 2 |
| `GitHubAppId`, `GitHubAppSlug`, `GitHubClientId` | Your GitHub App values, or leave empty for now |
| `DesiredCount` | **0** |
| `BudgetEmail` | Email address for cost alerts |

Acknowledge IAM resource creation and submit. Wait for `CREATE_COMPLETE`. If it fails, inspect the first failed resource in **Events**; don't repeatedly create replacement stacks. The database can take several minutes.

## 5. Run the one-time database setup

Open the stack's **Outputs** and record `Cluster`, `MigrationTask`, and `TaskSecurityGroup`.

1. Open ECS → the output's cluster → **Tasks → Run new task**.
2. Select Fargate and the task definition identified by `MigrationTask`; run one task.
3. Use the same VPC and private subnets, select the output's task security group, and disable public IP assignment. Use the latest Linux Fargate platform version.
4. Leave the task's command unchanged. It runs `alembic upgrade head && python -m app.seed`.
5. Wait for the task to stop. Open its container details and confirm exit code **0**. Inspect CloudWatch logs if it fails. Do not continue on failure.

This creates the database schema and account `demo@releasepilot.local` with the `DEMO_PASSWORD` from Secrets Manager.

## 6. Start services and connect DNS

Update the CloudFormation stack, choose **Use existing template**, retain the previous parameter values, and change only `DesiredCount` to **1**. Wait for `UPDATE_COMPLETE` and healthy ECS services and API/frontend target groups.

Create a DNS CNAME for your subdomain pointing to the stack's `LoadBalancerDNS`; in Route 53 you may instead use an alias A record to the ALB. Keep the certificate validation record. The DNS hostname must match `AppOrigin` and the certificate.

Open the HTTPS URL and sign in with the seeded email and hosted password. The local `.env` is not used by AWS.

If startup fails: inspect ECS stopped-task reasons and CloudWatch logs. Image/secret download failures often indicate missing NAT routes or IAM permissions. Database errors require checking migration success and the private database connection. A redirect/origin/login mismatch requires comparing the actual URL to `AppOrigin`.

## 7. Enable real GitHub and model evidence

Create a GitHub App under your GitHub account's developer settings. Give it read-only Contents, Pull requests, Checks, Commit statuses, Metadata, and Administration permissions. Subscribe to `push`, `pull_request`, `pull_request_review`, `check_run`, `check_suite`, `status`, `installation`, and `installation_repositories` events.

- Callback URL: `https://YOUR_HOST/api/v1/github/callback`
- Webhook URL: `https://YOUR_HOST/api/v1/webhooks/github`
- Webhook secret: the same `GITHUB_WEBHOOK_SECRET` in Secrets Manager

Generate the App's private key and OAuth client secret. Update the secret's PEM/client-secret/API-key fields, then update the stack's GitHub ID/slug/client-ID parameters. Force new deployments for the API, worker, and MCP services after changing provider secrets, because running containers do not refresh injected secrets automatically.

Install the App on the specific repository to analyze. In ReleasePilot's **Connections**, authorize the installation and connect that repository. Upload your actual deployment guidance through **Runbooks**. Reindex documents originally indexed with demo vectors after enabling the model key. Run an analysis using a real base and head ref with commits between them.

Missing required-check policy or failed/incomplete evidence may correctly produce CAUTION or NO_GO; don't change safeguards to manufacture a GO for the presentation.

## 8. Verify and present

Before sharing the URL:

- Run the safe, failed-CI, and missing-evidence fixture scenarios. Expect GO, NO_GO, and CAUTION respectively.
- Open an evidence citation and inspect the agent/tool activity.
- Upload `evals/documents/checkout-runbook.md`, wait for indexing, and search for rollback.
- If credentials are configured, verify one live analysis and inspect GitHub webhook deliveries.
- Inspect ECS health, CloudWatch failures, and the SQS dead-letter queue.
- Add your HTTPS URL to the GitHub repository's About/Website field and README after verifying it.

For automated smoke checks against your own deployment, put the hosted login email/password in an ignored `.env` in a separate temporary clone and run `SMOKE_ORIGIN=https://YOUR_HOST python3 scripts/smoke.py`. The script reads credentials from that file and creates a dedicated verification service and sample reports/documents. Do not overwrite your local development credentials just to test the deployment.

Use [the portfolio walkthrough](portfolio.md) for a three-minute presentation. The hosted account is a shared workspace with write access; demonstrate it yourself or share the password privately with trusted reviewers. Do not publish its password in the README. Clearly label synthetic scenarios and distinguish them from verified live results.

## Updates and costs

The optional GitHub `Publish images (manual)` workflow needs an AWS OIDC publishing role plus `AWS_PUBLISH_ROLE_ARN` and `AWS_REGION` variables in the `aws-publish` GitHub environment. It only publishes images; it does not deploy the stack or migrate the database. Manual publishing above avoids that extra setup for the first deployment.

For upgrades, publish new images, run compatible migrations using the new backend image, and then roll out the services. See the [infrastructure guide](../infrastructure/aws/README.md) for sequencing, limitations, and teardown.

The configured $50 monthly budget is an alert, not a spending cap or estimate. RDS, Fargate, ALB, NAT, storage, logs, and model usage cost money independently. Setting `DesiredCount=0` stops app tasks but does not stop all charges. The template intentionally retains database snapshots and the versioned documents bucket on deletion.

Official references: [ECR image publishing](https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html), [ECS secret injection and refresh](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html).

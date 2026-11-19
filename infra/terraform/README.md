# AWS stack (v0)

One Graviton EC2 host in ECS running every service with host networking, RDS Postgres
16 (t4g.micro), a KMS key for broker credentials, ECR, CloudWatch logs with an alert
metric + alarm, and secrets in SSM Parameter Store. No NAT gateway, no load balancer.

Estimated cost: ~$25 (t4g.medium) + $0–12 (RDS, free tier) + ~$3 (KMS, logs, SSM) per month.

## Apply (needs an AWS account; costs money)

```bash
cd infra/terraform
terraform init
terraform apply -var image_tag=<git-sha>     # CI pushes atp:<sha> to ECR

# real secrets (never through terraform):
for k in ALPACA_API_KEY_ID ALPACA_API_SECRET_KEY ANTHROPIC_API_KEY; do
  aws ssm put-parameter --overwrite --type SecureString --name /atp/v0/$k --value "..."
done
aws ecs update-service --cluster atp-v0 --service marketdata --force-new-deployment  # pick up secrets
```

First image: the ECR repo is created by the apply, so run `terraform apply -target=aws_ecr_repository.atp`,
push an image (see `.github/workflows/deploy.yml` or `docker buildx build --platform linux/arm64 --push`),
then the full apply.

Panel: no public ingress by default. Port-forward over SSM (see the `panel_access` output) and
sign in with the token from `aws ssm get-parameter --with-decryption --name /atp/v0/ADMIN_TOKEN`.

One-off commands run on the host: `aws ssm start-session --target <instance>` then
`docker exec -it $(docker ps -qf name=control-panel) atp agent load agents/examples/rsi-ma-basic.json`.

## Destroy

```bash
terraform destroy
```
`db_deletion_protection=false` (the v0 default) and `force_delete` on ECR make destroy clean.
Set `db_deletion_protection=true` before any real money.

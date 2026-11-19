# Secrets live in SSM Parameter Store (SecureString) and are injected into tasks by ECS.
# Provider keys start as placeholders: set real values with
#   aws ssm put-parameter --overwrite --type SecureString --name /atp/v0/ALPACA_API_KEY_ID --value ...
# Terraform ignores later value changes, so real secrets never enter state or git.

resource "random_password" "admin_token" {
  length  = 40
  special = false
}

resource "random_password" "litellm_key" {
  length  = 40
  special = false
}

locals {
  ssm_prefix = "/atp/${var.stage}"
  generated = {
    DATABASE_URL       = "postgresql+psycopg://atp:${random_password.db.result}@${aws_db_instance.main.address}:5432/atp"
    ADMIN_TOKEN        = random_password.admin_token.result
    LITELLM_MASTER_KEY = "sk-${random_password.litellm_key.result}"
  }
  operator_set = ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "ANTHROPIC_API_KEY", "SENTRY_DSN", "ALERT_WEBHOOK_URL"]
}

resource "aws_ssm_parameter" "generated" {
  for_each = local.generated
  name     = "${local.ssm_prefix}/${each.key}"
  type     = "SecureString"
  value    = each.value
}

resource "aws_ssm_parameter" "operator" {
  for_each = toset(local.operator_set)
  name     = "${local.ssm_prefix}/${each.key}"
  type     = "SecureString"
  value    = "unset"
  lifecycle {
    ignore_changes = [value]
  }
}

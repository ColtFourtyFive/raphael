locals {
  image = "${aws_ecr_repository.atp.repository_url}:${var.image_tag}"

  common_env = [
    { name = "NATS_URL", value = "nats://127.0.0.1:4222" },
    { name = "LITELLM_BASE_URL", value = "http://127.0.0.1:4000" },
    { name = "AWS_KMS_KEY_ARN", value = aws_kms_key.credentials.arn },
    { name = "AWS_DEFAULT_REGION", value = var.region },
    { name = "ALLOW_LIVE_TRADING", value = tostring(var.allow_live_trading) },
    { name = "ALPACA_PAPER", value = "true" },
    { name = "ATP_IMAGE_TAG", value = var.image_tag },
  ]

  common_secrets = concat(
    [for k, p in aws_ssm_parameter.generated : { name = k, valueFrom = p.arn }],
    [for k, p in aws_ssm_parameter.operator : { name = k, valueFrom = p.arn }],
  )

  log = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.main.name
      awslogs-region        = var.region
      awslogs-stream-prefix = "atp"
    }
  }

  # name => command, memory reservation (MiB), desired count
  atp_services = {
    watch      = { command = ["atp", "run", "watch"], memory = 384, count = 1 }
    worker     = { command = ["atp", "run", "worker"], memory = 384, count = var.worker_count }
    reconciler = { command = ["atp", "run", "reconciler"], memory = 256, count = 1 }
    marketdata = { command = ["atp", "run", "marketdata"], memory = 256, count = 1 }
  }
}

# --- infrastructure containers on the host ---

resource "aws_ecs_task_definition" "nats" {
  family       = "${local.name}-nats"
  network_mode = "host"
  volume {
    name      = "nats"
    host_path = "/srv/nats"
  }
  container_definitions = jsonencode([{
    name              = "nats"
    image             = var.nats_image
    essential         = true
    memoryReservation = 256
    command           = ["-js", "-sd", "/data", "-m", "8222", "-a", "127.0.0.1"]
    mountPoints       = [{ sourceVolume = "nats", containerPath = "/data" }]
    logConfiguration  = local.log
  }])
}

resource "aws_ecs_task_definition" "litellm" {
  family             = "${local.name}-litellm"
  network_mode       = "host"
  execution_role_arn = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name              = "litellm"
    image             = var.litellm_image
    essential         = true
    memoryReservation = 512
    command           = ["--config", "/app/config.yaml", "--host", "127.0.0.1", "--port", "4000"]
    entryPoint        = ["/bin/sh", "-c", "echo \"$LITELLM_CONFIG\" > /app/config.yaml && exec litellm \"$@\"", "--"]
    environment       = [{ name = "LITELLM_CONFIG", value = file("${path.module}/../../docker/litellm.yaml") }]
    secrets = [
      { name = "ANTHROPIC_API_KEY", valueFrom = aws_ssm_parameter.operator["ANTHROPIC_API_KEY"].arn },
      { name = "LITELLM_MASTER_KEY", valueFrom = aws_ssm_parameter.generated["LITELLM_MASTER_KEY"].arn },
    ]
    logConfiguration = local.log
  }])
}

# --- atp services (one image, role chosen by command) ---

resource "aws_ecs_task_definition" "atp" {
  for_each           = local.atp_services
  family             = "${local.name}-${each.key}"
  network_mode       = "host"
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name              = each.key
    image             = local.image
    essential         = true
    memoryReservation = each.value.memory
    command           = each.value.command
    environment       = local.common_env
    secrets           = local.common_secrets
    logConfiguration  = local.log
  }])
}

# The control task migrates the database first, then serves the panel.
resource "aws_ecs_task_definition" "control" {
  family             = "${local.name}-control"
  network_mode       = "host"
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn
  container_definitions = jsonencode([
    {
      name              = "migrate"
      image             = local.image
      essential         = false
      memoryReservation = 128
      command           = ["alembic", "upgrade", "head"]
      environment       = local.common_env
      secrets           = local.common_secrets
      logConfiguration  = local.log
    },
    {
      name              = "panel"
      image             = local.image
      essential         = true
      memoryReservation = 256
      command           = ["atp", "run", "panel", "--host", "0.0.0.0", "--port", "8000"]
      dependsOn         = [{ containerName = "migrate", condition = "SUCCESS" }]
      environment       = local.common_env
      secrets           = local.common_secrets
      logConfiguration  = local.log
      healthCheck = {
        command  = ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')\""]
        interval = 30
        retries  = 3
        timeout  = 5
      }
    },
  ])
}

locals {
  all_services = merge(
    { nats = { td = aws_ecs_task_definition.nats.arn, count = 1 } },
    { litellm = { td = aws_ecs_task_definition.litellm.arn, count = 1 } },
    { control = { td = aws_ecs_task_definition.control.arn, count = 1 } },
    { for k, v in local.atp_services : k => { td = aws_ecs_task_definition.atp[k].arn, count = v.count } },
  )
}

resource "aws_ecs_service" "svc" {
  for_each        = local.all_services
  name            = each.key
  cluster         = aws_ecs_cluster.main.id
  task_definition = each.value.td
  desired_count   = each.value.count
  # one host: replace in place (stop old, start new) rather than needing spare capacity
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.host.name
    weight            = 1
  }
  depends_on = [aws_ecs_cluster_capacity_providers.main]
}

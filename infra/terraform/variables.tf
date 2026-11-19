variable "region" {
  type    = string
  default = "us-east-1"
}

variable "stage" {
  type    = string
  default = "v0"
}

variable "instance_type" {
  description = "Graviton host for every service (v0 runs one host)."
  type        = string
  default     = "t4g.medium"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "image_tag" {
  description = "Tag of the atp image in ECR (CI pushes the git SHA)."
  type        = string
  default     = "latest"
}

variable "litellm_image" {
  type    = string
  default = "ghcr.io/berriai/litellm:main-stable"
}

variable "nats_image" {
  type    = string
  default = "public.ecr.aws/docker/library/nats:2.10-alpine"
}

variable "admin_cidrs" {
  description = "CIDRs allowed to reach the panel on :8000. Empty = no ingress; use SSM port forwarding."
  type        = list(string)
  default     = []
}

variable "worker_count" {
  type    = number
  default = 2
}

variable "allow_live_trading" {
  description = "Never set true without a deliberate decision; live also needs an is_live account row."
  type        = bool
  default     = false
}

variable "db_deletion_protection" {
  description = "Keep false for v0 so `terraform destroy` works; set true before real money."
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Optional email for CloudWatch alert notifications."
  type        = string
  default     = ""
}

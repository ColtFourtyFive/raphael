output "ecr_repository_url" {
  value = aws_ecr_repository.atp.repository_url
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "db_endpoint" {
  value = aws_db_instance.main.address
}

output "kms_key_arn" {
  value = aws_kms_key.credentials.arn
}

output "admin_token_parameter" {
  description = "Read with: aws ssm get-parameter --with-decryption --name <this>"
  value       = aws_ssm_parameter.generated["ADMIN_TOKEN"].name
}

output "panel_access" {
  value = "aws ssm start-session --target <instance-id from ASG ${aws_autoscaling_group.host.name}> --document-name AWS-StartPortForwardingSession --parameters portNumber=8000,localPortNumber=8000"
}

output "alb_dns_name" {
  description = "Public DNS name of the load balancer. Point a CNAME at this."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "Hosted zone of the ALB, for a Route53 alias record."
  value       = aws_lb.this.zone_id
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.app.name
}

output "database_endpoint" {
  description = "RDS endpoint address. Not a secret on its own -- it is unreachable outside the VPC."
  value       = aws_db_instance.this.address
}

output "database_secret_arn" {
  description = "Secrets Manager ARN holding the credentials and DSN."
  value       = aws_secretsmanager_secret.db.arn
}

output "log_group_name" {
  description = "CloudWatch log group for application logs."
  value       = aws_cloudwatch_log_group.app.name
}

output "database_connection_string" {
  description = "Full DSN. Marked sensitive so it is redacted from plan output and CI logs."
  value = format(
    "postgresql+psycopg://%s:%s@%s:%s/%s",
    var.db_username,
    random_password.db.result,
    aws_db_instance.this.address,
    aws_db_instance.this.port,
    var.db_name,
  )
  # Without this, `terraform output` and every CI job log would print the
  # production database password in plain text.
  sensitive = true
}

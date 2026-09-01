output "alb_dns_name" {
  description = "Public endpoint for this environment."
  value       = module.app_runtime.alb_dns_name
}

output "ecs_cluster_name" {
  value = module.app_runtime.ecs_cluster_name
}

output "ecs_service_name" {
  value = module.app_runtime.ecs_service_name
}

output "database_secret_arn" {
  description = "Where the application reads its DSN from."
  value       = module.app_runtime.database_secret_arn
}

output "vpc_id" {
  value = module.network.vpc_id
}

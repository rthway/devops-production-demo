output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs, one per AZ. Load balancers only."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs, one per AZ. Application and database tiers."
  value       = aws_subnet.private[*].id
}

output "availability_zones" {
  description = "Availability zones the subnets are spread across."
  value       = local.azs
}

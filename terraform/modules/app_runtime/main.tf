# Application runtime: ALB -> ECS Fargate -> RDS PostgreSQL.
#
# ECS Fargate rather than EC2 because there is no host to patch, and rather
# than EKS because a single service does not justify a control plane and the
# operational surface that comes with it. The container image is identical to
# the one the Kubernetes manifests run, which is the point of building an
# image instead of a deployment artifact per platform.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name = var.name_prefix

  # Merged once here so every resource below carries the same base tags and
  # cost allocation actually works.
  tags = merge(var.tags, {
    Environment = var.environment
    Module      = "app_runtime"
  })
}

# =============================================================================
# Security groups -- one per tier, referencing each other by ID rather than
# by CIDR. That way the rule stays correct when subnets are renumbered, and
# the database is reachable only from the application, not from "the VPC".
# =============================================================================

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public entry point. HTTPS from the internet."
  vpc_id      = var.vpc_id

  tags = merge(local.tags, { Name = "${local.name}-alb" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from the internet"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http_redirect" {
  security_group_id = aws_security_group.alb.id
  # Port 80 exists only to answer with a 301 to HTTPS. Closing it would leave
  # plain-http visitors with a connection timeout instead of a redirect.
  description = "HTTP, redirected to HTTPS by the listener"
  cidr_ipv4   = "0.0.0.0/0"
  from_port   = 80
  to_port     = 80
  ip_protocol = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward to application tasks only"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "Application tasks. Reachable only from the load balancer."
  vpc_id      = var.vpc_id

  tags = merge(local.tags, { Name = "${local.name}-app" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  description                  = "Application port from the ALB"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "app_to_db" {
  security_group_id            = aws_security_group.app.id
  description                  = "PostgreSQL"
  referenced_security_group_id = aws_security_group.db.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "app_https_out" {
  security_group_id = aws_security_group.app.id
  # Needed to pull the image, reach Secrets Manager and ship logs. Restricted
  # to 443 rather than the all-protocols default, so a compromised task cannot
  # open arbitrary outbound connections.
  description = "HTTPS out for image pulls, Secrets Manager and CloudWatch"
  cidr_ipv4   = "0.0.0.0/0"
  from_port   = 443
  to_port     = 443
  ip_protocol = "tcp"
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "PostgreSQL. Reachable only from application tasks."
  vpc_id      = var.vpc_id

  tags = merge(local.tags, { Name = "${local.name}-db" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from application tasks"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# No egress rule for the database at all: it has no reason to originate a
# connection to anything.

# =============================================================================
# Database credentials
#
# The password is NOT a Terraform variable and never appears in this
# repository. It is generated in-provider and stored in Secrets Manager, and
# the task reads it from there at start-up. A password passed in as a variable
# ends up in the state file, in CI logs, and in someone's shell history.
#
# Note the honest limitation: the generated value IS still recorded in
# Terraform state, which is why the state backend is encrypted and access-
# controlled. Removing it from state entirely means letting RDS manage the
# password (manage_master_user_password) -- the right answer where the
# provider supports it.
# =============================================================================

resource "random_password" "db" {
  length  = 32
  special = true
  # Excluded because these characters break URL parsing when the password is
  # interpolated into a postgresql:// DSN.
  override_special = "!#$%*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db" {
  name        = "${local.name}/database"
  description = "PostgreSQL credentials and DSN for ${local.name}"

  # Zero means immediate deletion. The default 30-day window is a foot-gun in
  # dev: a destroyed environment cannot be recreated under the same secret
  # name until the window expires.
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id

  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db.result
    host     = aws_db_instance.this.address
    port     = aws_db_instance.this.port
    dbname   = var.db_name
    # The full DSN in the shape the application expects, so the container
    # needs one secret and no string assembly at start-up.
    APP_DATABASE_URL = format(
      "postgresql+psycopg://%s:%s@%s:%s/%s",
      var.db_username,
      urlencode(random_password.db.result),
      aws_db_instance.this.address,
      aws_db_instance.this.port,
      var.db_name,
    )
  })
}

# =============================================================================
# Database
# =============================================================================

resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-db"
  subnet_ids = var.private_subnet_ids

  tags = merge(local.tags, { Name = "${local.name}-db" })
}

resource "aws_db_parameter_group" "this" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    # Reject unencrypted connections. Without this, TLS is merely available
    # rather than required, and a misconfigured client silently downgrades.
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  tags = local.tags
}

resource "aws_db_instance" "this" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = "16"

  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 4
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]

  # Not publicly accessible, in a private subnet, behind a security group that
  # only the application can traverse. Three independent controls, because any
  # one of them can be misconfigured.
  publicly_accessible = false

  multi_az                = var.db_multi_az
  backup_retention_period = var.db_backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:30-sun:05:30"
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection

  # A final snapshot on destroy in prod. `skip_final_snapshot = true` is the
  # provider default and means an accidental destroy is unrecoverable.
  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.name}-final" : null

  performance_insights_enabled    = var.environment == "prod"
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = merge(local.tags, { Name = "${local.name}-db" })

  lifecycle {
    ignore_changes = [
      # Rotated out of band; a rotation must not show up as drift on every plan.
      password,
    ]
  }
}

# =============================================================================
# IAM -- two roles, deliberately
#
# execution_role: used by the ECS agent to pull the image and fetch secrets.
# task_role:      assumed by the application itself.
#
# Collapsing them into one role would give application code the permission to
# read every secret the agent can read, which is precisely the privilege
# escalation the split prevents.
# =============================================================================

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    # Confused-deputy protection: without these conditions any ECS task in any
    # account could theoretically be used to assume this role.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "${local.name}-read-db-secret"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      # Exactly one secret ARN. Not "secretsmanager:*", not a wildcard ARN.
      Resource = [aws_secretsmanager_secret.db.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = local.tags
}

# The task role intentionally has NO policy attached. The application does not
# call AWS APIs, so it gets no AWS permissions. Adding permissions "just in
# case" is how a web server ends up able to read S3.

# =============================================================================
# ECS
# =============================================================================

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days

  tags = local.tags
}

resource "aws_ecs_cluster" "this" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = var.environment == "prod" ? "enabled" : "disabled"
  }

  tags = local.tags
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = var.container_image
    essential = true

    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]

    # Non-secret configuration inline; the DSN comes from Secrets Manager
    # below so it never appears in the task definition, which is readable by
    # anyone with ecs:DescribeTaskDefinition.
    environment = [
      { name = "APP_ENVIRONMENT", value = var.environment },
      { name = "APP_LOG_JSON", value = "true" },
      { name = "APP_LOG_LEVEL", value = var.environment == "prod" ? "INFO" : "DEBUG" },
      { name = "APP_METRICS_ENABLED", value = "true" },
      { name = "RUN_MIGRATIONS", value = "false" },
    ]

    secrets = [{
      name      = "APP_DATABASE_URL"
      valueFrom = "${aws_secretsmanager_secret.db.arn}:APP_DATABASE_URL::"
    }]

    # Container-level health check hits liveness, not readiness: ECS would
    # otherwise kill and replace every task during a database failover.
    healthCheck = {
      command     = ["CMD-SHELL", "curl -fsS http://127.0.0.1:${var.container_port}/health/live || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.app.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "api"
      }
    }

    readonlyRootFilesystem = true
    user                   = "10001:10001"
  }])

  tags = local.tags
}

resource "aws_lb" "this" {
  name               = "${local.name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  drop_invalid_header_fields = true
  enable_deletion_protection = var.environment == "prod"

  tags = local.tags
}

resource "aws_lb_target_group" "app" {
  name        = "${local.name}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    # The ALB decides whether to send traffic, so it asks the READINESS
    # question -- unlike the container health check above, which decides
    # whether to restart.
    path                = "/health/ready"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  # Give in-flight requests time to complete before the target is removed.
  deregistration_delay = 30

  tags = local.tags
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }

  tags = local.tags
}

resource "aws_ecs_service" "app" {
  name            = local.name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.app.id]
    # Tasks sit in private subnets and egress via NAT. A public IP here would
    # make every task directly reachable from the internet.
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  # Percentages, not counts: 100/200 means a deploy adds a full new set before
  # removing the old one, so capacity never dips during a rollout.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable = true
    # Automatic rollback on a failed deployment. Without it a broken image
    # sits in a crash loop until a human notices.
    rollback = true
  }

  health_check_grace_period_seconds = 60
  enable_execute_command            = var.environment != "prod"

  lifecycle {
    ignore_changes = [
      # Owned by the autoscaler once it is attached; Terraform must not fight
      # it on every apply.
      desired_count,
    ]
  }

  tags = local.tags

  depends_on = [aws_lb_listener.http_redirect]
}

# =============================================================================
# Autoscaling
# =============================================================================

resource "aws_appautoscaling_target" "app" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.app.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.min_capacity
  max_capacity       = var.max_capacity
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.app.service_namespace
  resource_id        = aws_appautoscaling_target.app.resource_id
  scalable_dimension = aws_appautoscaling_target.app.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = 70

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# =============================================================================
# Aurora PostgreSQL Serverless v2 (the "source of truth")
# =============================================================================
# Serverless v2 scales capacity in 0.5 ACU increments (1 ACU ≈ 2 GB RAM, ~2 vCPU)
# which is ideal for bursty ETL workloads.
# =============================================================================

resource "aws_db_subnet_group" "this" {
  count      = length(var.private_subnet_ids) > 0 ? 1 : 0
  name       = "${var.project_prefix}-db-subnets"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "aurora" {
  count  = var.vpc_id != "" ? 1 : 0
  name   = "${var.project_prefix}-aurora"
  vpc_id = var.vpc_id

  # Ingress should be tightened to bastion / Lambda SG. Left loose for example.
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "random_password" "db_master" {
  length  = 32
  special = true
}

resource "aws_secretsmanager_secret" "db_master" {
  name                    = "${var.project_prefix}/db/master"
  recovery_window_in_days = 7
  kms_key_id              = aws_kms_key.data_lake.arn
}

resource "aws_secretsmanager_secret_version" "db_master" {
  secret_id = aws_secretsmanager_secret.db_master.id
  secret_string = jsonencode({
    username = "ldp_admin"
    password = random_password.db_master.result
  })
}

resource "aws_rds_cluster" "aurora" {
  count = var.vpc_id != "" ? 1 : 0

  cluster_identifier     = "${var.project_prefix}-aurora"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned"
  engine_version         = "16.2"
  database_name          = "legaldata"
  master_username        = "ldp_admin"
  master_password        = random_password.db_master.result
  backup_retention_period = 14
  preferred_backup_window = "03:00-05:00"

  db_subnet_group_name   = aws_db_subnet_group.this[0].name
  vpc_security_group_ids = [aws_security_group.aurora[0].id]
  storage_encrypted      = true
  kms_key_id             = aws_kms_key.data_lake.arn

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 16
  }

  enabled_cloudwatch_logs_exports = ["postgresql"]
  skip_final_snapshot             = var.environment != "prod"
}

resource "aws_rds_cluster_instance" "writer" {
  count              = var.vpc_id != "" ? 1 : 0
  identifier         = "${var.project_prefix}-aurora-writer"
  cluster_identifier = aws_rds_cluster.aurora[0].id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.aurora[0].engine
  engine_version     = aws_rds_cluster.aurora[0].engine_version
}

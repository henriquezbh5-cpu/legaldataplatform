# =============================================================================
# AWS Glue Data Catalog + PySpark Jobs
# =============================================================================

resource "aws_glue_catalog_database" "legal" {
  name        = "${var.project_prefix}_legal"
  description = "Catalog for legal data lake (Bronze/Silver/Gold)."
}

resource "aws_glue_catalog_database" "commercial" {
  name        = "${var.project_prefix}_commercial"
  description = "Catalog for commercial data lake."
}

resource "aws_s3_object" "glue_scripts" {
  for_each = fileset("${path.module}/../../src/aws/glue_jobs", "*.py")

  bucket = aws_s3_bucket.data_lake["bronze"].id
  key    = "glue-scripts/${each.value}"
  source = "${path.module}/../../src/aws/glue_jobs/${each.value}"
  etag   = filemd5("${path.module}/../../src/aws/glue_jobs/${each.value}")
}

resource "aws_iam_role" "glue_job" {
  name = "${var.project_prefix}-glue-job"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_job.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  role = aws_iam_role.glue_job.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
      Resource = concat(
        [for b in aws_s3_bucket.data_lake : b.arn],
        [for b in aws_s3_bucket.data_lake : "${b.arn}/*"],
      )
    }]
  })
}

resource "aws_glue_job" "legal_doc_normalize" {
  name     = "${var.project_prefix}-legal-doc-normalize"
  role_arn = aws_iam_role.glue_job.arn

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data_lake["bronze"].id}/glue-scripts/legal_doc_normalize.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--source_bucket"                    = aws_s3_bucket.data_lake["bronze"].id
    "--target_bucket"                    = aws_s3_bucket.data_lake["silver"].id
  }

  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 3
  timeout           = 60

  execution_property {
    max_concurrent_runs = 1
  }
}

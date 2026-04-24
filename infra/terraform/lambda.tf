# =============================================================================
# Lambda functions: S3 event handler + SQS consumer
# =============================================================================

data "archive_file" "s3_event_ingest" {
  type        = "zip"
  source_file = "${path.module}/../../src/aws/lambda_handlers/s3_event_ingest.py"
  output_path = "${path.module}/build/s3_event_ingest.zip"
}

data "archive_file" "sqs_pipeline_trigger" {
  type        = "zip"
  source_file = "${path.module}/../../src/aws/lambda_handlers/sqs_pipeline_trigger.py"
  output_path = "${path.module}/build/sqs_pipeline_trigger.zip"
}

resource "aws_iam_role" "lambda_execution" {
  name = "${var.project_prefix}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_sqs_s3" {
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:SendMessage",
          "sqs:GetQueueAttributes", "sqs:SendMessageBatch",
        ]
        Resource = [aws_sqs_queue.ingest.arn, aws_sqs_queue.ingest_dlq.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = concat(
          [for b in aws_s3_bucket.data_lake : b.arn],
          [for b in aws_s3_bucket.data_lake : "${b.arn}/*"],
        )
      },
      {
        Effect = "Allow"
        Action = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = [aws_kms_key.data_lake.arn]
      },
    ]
  })
}

resource "aws_lambda_function" "s3_event_ingest" {
  function_name    = "${var.project_prefix}-s3-event-ingest"
  filename         = data.archive_file.s3_event_ingest.output_path
  source_code_hash = data.archive_file.s3_event_ingest.output_base64sha256
  handler          = "s3_event_ingest.handler"
  runtime          = var.lambda_runtime
  role             = aws_iam_role.lambda_execution.arn
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      INGEST_QUEUE_URL = aws_sqs_queue.ingest.url
    }
  }
}

resource "aws_lambda_function" "sqs_pipeline_trigger" {
  function_name    = "${var.project_prefix}-sqs-pipeline-trigger"
  filename         = data.archive_file.sqs_pipeline_trigger.output_path
  source_code_hash = data.archive_file.sqs_pipeline_trigger.output_base64sha256
  handler          = "sqs_pipeline_trigger.handler"
  runtime          = var.lambda_runtime
  role             = aws_iam_role.lambda_execution.arn
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      PREFECT_API_URL       = var.prefect_api_url
      PREFECT_DEPLOYMENT_ID = var.prefect_deployment_id
      PREFECT_API_KEY       = var.prefect_api_key
    }
  }
}

resource "aws_lambda_event_source_mapping" "sqs_to_lambda" {
  event_source_arn                   = aws_sqs_queue.ingest.arn
  function_name                      = aws_lambda_function.sqs_pipeline_trigger.arn
  batch_size                         = 10
  maximum_batching_window_in_seconds = 10
  function_response_types            = ["ReportBatchItemFailures"]
}

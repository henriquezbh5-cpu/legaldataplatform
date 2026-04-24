# =============================================================================
# SQS Queue + DLQ for pipeline triggering
# =============================================================================
# A DLQ after 5 receive attempts protects downstream from poison-pill messages.
# =============================================================================

resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${var.project_prefix}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 days
  kms_master_key_id         = aws_kms_key.data_lake.arn
}

resource "aws_sqs_queue" "ingest" {
  name                       = "${var.project_prefix}-ingest"
  visibility_timeout_seconds = 900 # matches Lambda max timeout
  message_retention_seconds  = 345600 # 4 days
  kms_master_key_id          = aws_kms_key.data_lake.arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_policy" "ingest" {
  queue_url = aws_sqs_queue.ingest.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.ingest.arn
      Condition = {
        ArnLike  = { "aws:SourceArn" = aws_s3_bucket.data_lake["bronze"].arn }
      }
    }]
  })
}

# CloudWatch alarm when messages pile up in DLQ
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.project_prefix}-ingest-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Messages have landed in the DLQ — pipeline consumer is failing."
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.ingest_dlq.name
  }
}

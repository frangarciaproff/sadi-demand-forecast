data "aws_caller_identity" "current" {}

locals {
  name        = "sadi-collector"
  bucket_name = "sadi-demand-raw-${data.aws_caller_identity.current.account_id}"
  timezone    = "America/Argentina/Buenos_Aires"

  schedules = {
    snapshot = { cron = "cron(30 0,6,12,18 * * ? *)", input = jsonencode({ mode = "snapshot", regions = var.regions }) }
    day      = { cron = "cron(15 1 * * ? *)", input = jsonencode({ mode = "day", regions = var.regions }) }
    docs     = { cron = "cron(30 23 * * ? *)", input = jsonencode({ mode = "docs", days = 8 }) }
  }
}

# --- Raw data bucket (private, versioned) ---

resource "aws_s3_bucket" "raw" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# --- Lambda ---

data "archive_file" "lambda" {
  type        = "zip"
  output_path = "${path.module}/build/collector.zip"

  source {
    content  = file("${path.module}/../scripts/collect_cammesa.py")
    filename = "collect_cammesa.py"
  }
  source {
    content  = file("${path.module}/lambda/handler.py")
    filename = "handler.py"
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 30
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "WriteRawOnly"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/cammesa/*"]
  }
  statement {
    sid       = "CheckExistingDocs"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.raw.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["raw/cammesa/docs/*"]
    }
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_lambda_function" "collector" {
  function_name    = local.name
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  architectures    = ["arm64"]
  memory_size      = 256 # 128 MB run peaked at 100 MB (boto3 import)
  timeout          = 900 # docs mode worst case: 3 listings x (3 x 120 s + backoff)
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      RAW_BUCKET = aws_s3_bucket.raw.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}

resource "aws_lambda_function_event_invoke_config" "collector" {
  function_name          = aws_lambda_function.collector.function_name
  maximum_retry_attempts = 1
}

# --- Schedules (EventBridge Scheduler, Argentina time) ---

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.collector.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule_group" "collector" {
  name = local.name
}

resource "aws_scheduler_schedule" "collector" {
  for_each = local.schedules

  name                         = "${local.name}-${each.key}"
  group_name                   = aws_scheduler_schedule_group.collector.name
  schedule_expression          = each.value.cron
  schedule_expression_timezone = local.timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.collector.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = each.value.input

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}

# --- Alerts ---

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${local.name}-errors"
  alarm_description   = "Collector run failed (at least one download not archived)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.collector.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "missing_runs" {
  alarm_name          = "${local.name}-missing-runs"
  alarm_description   = "No collector invocation in a 6-hour window (schedule guarantees at least one)."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.collector.function_name }
  statistic           = "Sum"
  period              = 21600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# --- Budget (account-wide, gross: credits and refunds excluded) ---

resource "aws_budgets_budget" "gross_monthly" {
  name         = "${local.name}-gross-monthly"
  budget_type  = "COST"
  limit_amount = format("%.2f", var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

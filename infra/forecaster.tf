# --- Forecaster (SPEC 7): Lambda container image, daily and monthly events ---
#
# First deployment, in this order (cheatsheet section 26):
#   1. terraform apply "-target=aws_ecr_repository.forecaster"  (quoted in PowerShell)
#   2. docker build / tag / push the image (tag = var.forecaster_image_tag)
#   3. seed s3://<bucket>/state/ and models/ (scripts/seed_state.py + aws s3 sync)
#   4. terraform apply

locals {
  forecaster = "sadi-forecaster"
  forecaster_schedules = {
    daily   = { cron = "cron(30 9 * * ? *)", input = jsonencode({ mode = "daily" }) }
    monthly = { cron = "cron(0 3 21 * ? *)", input = jsonencode({ mode = "monthly" }) }
  }
}

resource "aws_ecr_repository" "forecaster" {
  name                 = local.forecaster
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = false
  }
}

resource "aws_ecr_lifecycle_policy" "forecaster" {
  repository = aws_ecr_repository.forecaster.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 3 newest images (storage cost)"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "forecaster" {
  name              = "/aws/lambda/${local.forecaster}"
  retention_in_days = 30
}

resource "aws_iam_role" "forecaster" {
  name               = "${local.forecaster}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "forecaster" {
  statement {
    sid     = "ReadArchive"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.raw.arn}/raw/*",
      "${aws_s3_bucket.raw.arn}/state/*",
      "${aws_s3_bucket.raw.arn}/models/*",
      "${aws_s3_bucket.raw.arn}/forecasts/*",
      "${aws_s3_bucket.raw.arn}/scores/*",
    ]
  }
  statement {
    sid     = "WriteOwnOutputs"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.raw.arn}/raw/open_meteo/*",
      "${aws_s3_bucket.raw.arn}/raw/cammesa/sintesis/*",
      "${aws_s3_bucket.raw.arn}/state/*",
      "${aws_s3_bucket.raw.arn}/models/*",
      "${aws_s3_bucket.raw.arn}/forecasts/*",
      "${aws_s3_bucket.raw.arn}/scores/*",
    ]
  }
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.raw.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.forecaster.arn}:*"]
  }
}

resource "aws_iam_role_policy" "forecaster" {
  role   = aws_iam_role.forecaster.id
  policy = data.aws_iam_policy_document.forecaster.json
}

resource "aws_lambda_function" "forecaster" {
  function_name = local.forecaster
  role          = aws_iam_role.forecaster.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.forecaster.repository_url}:${var.forecaster_image_tag}"
  architectures = ["x86_64"]
  memory_size   = 3008 # tables + features over 2018 → today; monthly run builds them all
  timeout       = 900

  ephemeral_storage {
    size = 4096 # monthly run stages every Síntesis base (about 1 GB)
  }

  environment {
    variables = {
      BUCKET = aws_s3_bucket.raw.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.forecaster, aws_iam_role_policy.forecaster]
}

resource "aws_lambda_function_event_invoke_config" "forecaster" {
  function_name          = aws_lambda_function.forecaster.function_name
  maximum_retry_attempts = 1 # a forecast is written once; a retry only fills what failed
}

data "aws_iam_policy_document" "scheduler_forecaster" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.forecaster.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_forecaster" {
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_forecaster.json
}

resource "aws_scheduler_schedule" "forecaster" {
  for_each = local.forecaster_schedules

  name                         = "${local.forecaster}-${each.key}"
  group_name                   = aws_scheduler_schedule_group.collector.name
  schedule_expression          = each.value.cron
  schedule_expression_timezone = local.timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.forecaster.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = each.value.input

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "forecaster_errors" {
  alarm_name          = "${local.forecaster}-errors"
  alarm_description   = "Forecaster run failed (no forecast, or a monthly retrain error)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.forecaster.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "forecaster_missing_runs" {
  alarm_name          = "${local.forecaster}-missing-runs"
  alarm_description   = "No forecaster invocation in 24 hours (the daily schedule guarantees one)."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.forecaster.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

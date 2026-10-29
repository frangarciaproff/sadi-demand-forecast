output "bucket_name" {
  value = aws_s3_bucket.raw.bucket
}

output "function_name" {
  value = aws_lambda_function.collector.function_name
}

output "schedules" {
  value = { for k, s in aws_scheduler_schedule.collector : k => s.schedule_expression }
}

output "forecaster_repository_url" {
  value = aws_ecr_repository.forecaster.repository_url
}

output "forecaster_function_name" {
  value = aws_lambda_function.forecaster.function_name
}

output "site_bucket" {
  value = aws_s3_bucket.site.bucket
}

output "site_url" {
  value = "https://${aws_cloudfront_distribution.site.domain_name}"
}

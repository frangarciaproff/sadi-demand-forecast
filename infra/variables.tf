variable "region" {
  description = "AWS region (closest to CAMMESA; reachability verified 2026-10-21)."
  type        = string
  default     = "sa-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile (IAM Identity Center) for runs from the PC; null in GitHub Actions (OIDC credentials)."
  type        = string
  default     = null
}

variable "alert_email" {
  description = "Email for collector failure alarms and budget alerts."
  type        = string
  sensitive   = true # kept out of plan output (public CI logs)
}

variable "regions" {
  description = "CAMMESA region ids to collect (1002 = SADI total, 1945 = Córdoba)."
  type        = list(number)
  default     = [1002, 1945]
}

variable "budget_usd" {
  description = "Monthly gross cost budget (credits excluded), USD."
  type        = number
  default     = 1
}

variable "forecaster_image_tag" {
  description = "Tag of the forecaster image in ECR (immutable tags; one per build)."
  type        = string
}

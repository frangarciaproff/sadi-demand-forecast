# Bootstrap: applied from the PC only (never from GitHub Actions).
#
# Holds what the GitHub deploy role must not be able to change:
#   - the Terraform state bucket of infra/;
#   - the GitHub OIDC provider and the two GitHub roles (plan: read-only; deploy: apply);
#   - the IAM roles the Lambdas and the scheduler run with, and their permissions.
# infra/ only references these roles by name (data sources) and passes them.
#
#   terraform -chdir=infra/bootstrap init -backend-config="profile=electro"
#   terraform -chdir=infra/bootstrap apply

terraform {
  required_version = ">= 1.10"

  # State in the bucket this configuration creates (moved there after the first apply:
  # terraform -chdir=infra/bootstrap init -migrate-state -backend-config="profile=electro").
  backend "s3" {
    bucket       = "sadi-demand-tfstate-882856016817"
    key          = "bootstrap/terraform.tfstate"
    region       = "sa-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "region" {
  type    = string
  default = "sa-east-1"
}

variable "aws_profile" {
  type    = string
  default = "electro"
}

variable "github_repository" {
  description = "owner/name of the repository allowed to plan and deploy."
  type        = string
  default     = "frangarciaproff/sadi-demand-forecast"
}

# GitHub's OIDC subject for this repository includes the numeric owner and repository
# ids (owner@id/repo@id), seen in the token on 2026-10-29. Matching on ids also rejects
# a different repository later created under the same name.
variable "github_owner_id" {
  type    = string
  default = "285775576"
}

variable "github_repository_id" {
  type    = string
  default = "1433717782"
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  default_tags {
    tags = {
      project    = "sadi-demand-forecast"
      managed_by = "terraform-bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]
  account      = data.aws_caller_identity.current.account_id
  raw_bucket   = "arn:aws:s3:::sadi-demand-raw-${local.account}"
  site_bucket  = "arn:aws:s3:::sadi-demand-site-${local.account}"
  logs         = "arn:aws:logs:${var.region}:${local.account}:log-group:/aws/lambda"
  lambda       = "arn:aws:lambda:${var.region}:${local.account}:function"
  runtime_roles = [
    "arn:aws:iam::${local.account}:role/sadi-collector-lambda",
    "arn:aws:iam::${local.account}:role/sadi-collector-scheduler",
    "arn:aws:iam::${local.account}:role/sadi-forecaster-lambda",
  ]
}

# ===================================================================================
# Terraform state bucket (versioned: every state version can be recovered)
# ===================================================================================

resource "aws_s3_bucket" "state" {
  bucket = "sadi-demand-tfstate-${local.account}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# ===================================================================================
# Runtime roles (moved here from infra/ on 2026-10-29; imported, not recreated)
# ===================================================================================

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

import {
  to = aws_iam_role.collector
  id = "sadi-collector-lambda"
}

import {
  to = aws_iam_role.scheduler
  id = "sadi-collector-scheduler"
}

import {
  to = aws_iam_role.forecaster
  id = "sadi-forecaster-lambda"
}

resource "aws_iam_role" "collector" {
  name               = "sadi-collector-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role" "scheduler" {
  name               = "sadi-collector-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role" "forecaster" {
  name               = "sadi-forecaster-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "collector" {
  statement {
    sid       = "WriteRawOnly"
    actions   = ["s3:PutObject"]
    resources = ["${local.raw_bucket}/raw/cammesa/*"]
  }
  statement {
    sid       = "CheckExistingDocs"
    actions   = ["s3:ListBucket"]
    resources = [local.raw_bucket]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["raw/cammesa/docs/*"]
    }
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.logs}/sadi-collector:*"]
  }
}

resource "aws_iam_role_policy" "collector" {
  name   = "collector"
  role   = aws_iam_role.collector.id
  policy = data.aws_iam_policy_document.collector.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = ["${local.lambda}:sadi-collector", "${local.lambda}:sadi-forecaster"]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoke-project-lambdas"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

data "aws_iam_policy_document" "forecaster" {
  statement {
    sid     = "ReadArchive"
    actions = ["s3:GetObject"]
    resources = [
      "${local.raw_bucket}/raw/*",
      "${local.raw_bucket}/state/*",
      "${local.raw_bucket}/models/*",
      "${local.raw_bucket}/forecasts/*",
      "${local.raw_bucket}/scores/*",
    ]
  }
  statement {
    sid     = "WriteOwnOutputs"
    actions = ["s3:PutObject"]
    resources = [
      "${local.raw_bucket}/raw/open_meteo/*",
      "${local.raw_bucket}/raw/cammesa/sintesis/*",
      "${local.raw_bucket}/state/*",
      "${local.raw_bucket}/models/*",
      "${local.raw_bucket}/forecasts/*",
      "${local.raw_bucket}/scores/*",
    ]
  }
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [local.raw_bucket]
  }
  statement {
    sid       = "WritePageDataOnly"
    actions   = ["s3:PutObject"]
    resources = ["${local.site_bucket}/data.json"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.logs}/sadi-forecaster:*"]
  }
}

resource "aws_iam_role_policy" "forecaster" {
  name   = "forecaster"
  role   = aws_iam_role.forecaster.id
  policy = data.aws_iam_policy_document.forecaster.json
}

# ===================================================================================
# GitHub Actions through OIDC (no stored AWS keys)
# ===================================================================================

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_trust" {
  for_each = toset(["plan", "production"])
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs of this repository running in this GitHub environment.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}:environment:${each.key}"]
    }
  }
}

# --- Plan role (environment "plan", no approval): reads only ---

resource "aws_iam_role" "github_plan" {
  name                 = "sadi-github-plan"
  assume_role_policy   = data.aws_iam_policy_document.github_trust["plan"].json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_plan" {
  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
  }
  statement {
    sid = "ReadProjectBuckets"
    actions = [
      "s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration",
      "s3:GetAccelerateConfiguration", "s3:GetReplicationConfiguration",
      "s3:GetAnalyticsConfiguration", "s3:GetInventoryConfiguration",
      "s3:GetMetricsConfiguration", "s3:GetIntelligentTieringConfiguration", "s3:ListBucket",
    ]
    resources = [local.raw_bucket, local.site_bucket]
  }
  statement {
    sid = "ReadProjectResources"
    actions = [
      "lambda:Get*", "lambda:List*",
      "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies", "iam:ListRoleTags",
      "logs:Describe*", "logs:ListTagsForResource", "logs:ListTagsLogGroup",
      "scheduler:Get*", "scheduler:List*",
      "cloudwatch:Describe*", "cloudwatch:List*",
      "sns:Get*", "sns:List*",
      "budgets:ViewBudget", "budgets:ListTagsForResource",
      "ecr:Describe*", "ecr:Get*", "ecr:List*",
      "cloudfront:Get*", "cloudfront:List*",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_plan" {
  name   = "plan-read-only"
  role   = aws_iam_role.github_plan.id
  policy = data.aws_iam_policy_document.github_plan.json
}

# --- Deploy role (environment "production", manual approval): applies infra/ ---

resource "aws_iam_role" "github_deploy" {
  name                 = "sadi-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_trust["production"].json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_deploy" {
  # Everything the plan role can read.
  source_policy_documents = [data.aws_iam_policy_document.github_plan.json]

  statement {
    sid       = "StateLock"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/infra/*"]
  }
  statement {
    sid       = "SiteBucket"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:PutBucketPolicy", "s3:PutBucketTagging"]
    resources = [local.site_bucket, "${local.site_bucket}/*"]
  }
  statement {
    sid       = "PassRuntimeRoles"
    actions   = ["iam:PassRole"]
    resources = local.runtime_roles
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com", "scheduler.amazonaws.com"]
    }
  }
  statement {
    sid       = "EcrPush"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrRepository"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer", "ecr:SetRepositoryPolicy", "ecr:PutLifecyclePolicy",
      "ecr:PutImageTagMutability", "ecr:PutImageScanningConfiguration", "ecr:TagResource",
    ]
    resources = ["arn:aws:ecr:${var.region}:${local.account}:repository/sadi-forecaster"]
  }
  statement {
    sid = "Lambdas"
    actions = [
      "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
      "lambda:PutFunctionEventInvokeConfig", "lambda:UpdateFunctionEventInvokeConfig",
      "lambda:TagResource", "lambda:UntagResource",
    ]
    resources = ["${local.lambda}:sadi-*"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:PutRetentionPolicy", "logs:TagResource", "logs:TagLogGroup"]
    resources = ["${local.logs}/sadi-*", "${local.logs}/sadi-*:*"]
  }
  statement {
    sid       = "Schedules"
    actions   = ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule", "scheduler:TagResource"]
    resources = ["arn:aws:scheduler:${var.region}:${local.account}:schedule/sadi-*", "arn:aws:scheduler:${var.region}:${local.account}:schedule-group/sadi-*"]
  }
  statement {
    sid       = "Alarms"
    actions   = ["cloudwatch:PutMetricAlarm", "cloudwatch:TagResource"]
    resources = ["arn:aws:cloudwatch:${var.region}:${local.account}:alarm:sadi-*"]
  }
  statement {
    sid = "PageDistribution"
    actions = [
      "cloudfront:UpdateDistribution", "cloudfront:CreateInvalidation",
      "cloudfront:UpdateCachePolicy", "cloudfront:UpdateResponseHeadersPolicy",
      "cloudfront:UpdateOriginAccessControl", "cloudfront:TagResource",
    ]
    resources = ["*"]
  }
  # Changes that would expose or erase the raw archive, silence alerts or open a public
  # endpoint are not available to GitHub; they are made from the PC.
  statement {
    sid    = "NeverFromGithub"
    effect = "Deny"
    actions = [
      "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:PutLifecycleConfiguration",
      "s3:PutBucketOwnershipControls", "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketVersioning", "s3:DeleteBucket", "s3:DeleteObject*",
    ]
    resources = [local.raw_bucket, "${local.raw_bucket}/*"]
  }
  statement {
    sid    = "KeepStateBucket"
    effect = "Deny"
    actions = [
      "s3:PutBucketPolicy", "s3:PutLifecycleConfiguration", "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketVersioning", "s3:DeleteBucket",
    ]
    resources = [aws_s3_bucket.state.arn]
  }
  statement {
    sid    = "NoPublicLambdaEndpoints"
    effect = "Deny"
    actions = [
      "lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig", "lambda:AddPermission",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "NeverTouchIam"
    effect    = "Deny"
    actions   = ["iam:Create*", "iam:Delete*", "iam:Put*", "iam:Attach*", "iam:Detach*", "iam:Update*", "iam:Tag*", "iam:Untag*"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "plan_role_arn" {
  value = aws_iam_role.github_plan.arn
}

output "deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

# GitHub Actions OIDC federation: lets infra-prod.yml's `infra` and
# `build-and-push` jobs (the on-prem `docker-build` self-hosted runner)
# authenticate to AWS by assuming an IAM role instead of using long-lived
# AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY secrets. Static keys don't expire and
# are easy to leak/rotate-forget; a role assumed via short-lived OIDC tokens
# is safer and is what "Configure AWS credentials" should use whenever a job
# can't rely on an EC2 instance profile (the `deploy` job already gets
# role-based access for free from the `aws-prod` instance's profile — see
# infra/terraform/aws/ec2.tf's `aws_iam_role.app`).
#
# Applied once, by hand, alongside the rest of this bootstrap module (see
# main.tf's header comment) — not by CI — since the CI role itself can't be
# used to create its own trust relationship.

variable "github_repository" {
  description = "GitHub \"owner/repo\" allowed to assume the CI roles below (OIDC `sub` claim scoping)."
  type        = string
  default     = "ms-arronhoffer/office-manager"
}

variable "ecr_project_name" {
  description = "ECR repository name prefix (must match infra/terraform/aws's project_name) that the ecr-push role is scoped to."
  type        = string
  default     = "office-manager"
}

data "aws_caller_identity" "current" {}

# GitHub's OIDC token endpoint; Terraform fetches its TLS chain to derive the
# root CA thumbprint AWS uses to validate the provider.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  # AWS validates the OIDC provider against the SHA1 thumbprint of the last
  # certificate in the chain served by the issuer (its root CA). Guard against
  # an unexpectedly empty chain instead of an opaque index-out-of-bounds error.
  github_oidc_certificates    = data.tls_certificate.github_actions.certificates
  github_oidc_root_thumbprint = length(local.github_oidc_certificates) > 0 ? local.github_oidc_certificates[length(local.github_oidc_certificates) - 1].sha1_fingerprint : null
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [local.github_oidc_root_thumbprint]

  lifecycle {
    precondition {
      condition     = local.github_oidc_root_thumbprint != null
      error_message = "Could not fetch a TLS certificate chain for https://token.actions.githubusercontent.com; unable to derive the OIDC provider thumbprint."
    }
  }
}

data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Allow any ref/branch of this repo (infra-prod.yml runs on pushes to
    # `prod` and on manual workflow_dispatch from any ref).
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:*"]
    }
  }
}

# ── Role for the `infra` job (Terraform) ──────────────────────────────────────
# Terraform in infra/terraform/aws manages VPC data sources, EC2, RDS, S3,
# Secrets Manager, ECR and IAM (the app instance role/policy, the ecr-push
# policy). That breadth doesn't map cleanly to a narrow custom policy, so this
# role uses the AWS-managed AdministratorAccess policy, scoped down instead by
# *who* can assume it (only this repo, via OIDC) rather than by what it can
# do once assumed. Tighten this to a custom least-privilege policy if/when the
# exact action set stabilizes.
resource "aws_iam_role" "github_actions_infra" {
  name               = "office-manager-github-actions-infra"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

resource "aws_iam_role_policy_attachment" "github_actions_infra_admin" {
  role       = aws_iam_role.github_actions_infra.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# ── Role for the `build-and-push` job (docker push to ECR) ───────────────────
# Narrowly scoped to just the permissions needed to authenticate to ECR and
# push the four application images — mirrors infra/terraform/aws/ecr.tf's
# `aws_iam_policy.ecr_push` document, duplicated here (rather than referenced)
# so this bootstrap module doesn't need to depend on the aws root module's
# state.
data "aws_iam_policy_document" "github_actions_ecr_push" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken is not resource-scopable
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [
      "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${var.ecr_project_name}/*"
    ]
  }
}

resource "aws_iam_role" "github_actions_ecr_push" {
  name               = "office-manager-github-actions-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_actions_ecr_push.id
  policy = data.aws_iam_policy_document.github_actions_ecr_push.json
}

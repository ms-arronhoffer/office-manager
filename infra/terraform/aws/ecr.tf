# ── Elastic Container Registry ────────────────────────────────────────────────
# Private ECR repositories that hold the four application images. The
# `${var.project_name}` prefix acts as the registry "namespace" so every image
# lives under a predictable path (e.g. office-manager/backend). The
# `docker-build` self-hosted runner builds and pushes here; the `aws-prod` EC2
# host pulls from here at deploy time (see .github/workflows/deploy-prod.yml).

locals {
  # Keys are the compose service image basenames; each becomes an ECR
  # repository named "<project_name>/<key>".
  ecr_images = toset([
    "backend",
    "frontend",
    "admin-frontend",
    "landing",
  ])
}

resource "aws_ecr_repository" "app" {
  for_each = local.ecr_images

  name                 = "${var.project_name}/${each.key}"
  image_tag_mutability = "MUTABLE" # allow re-pushing the ":latest" convenience tag

  image_scanning_configuration {
    scan_on_push = true
  }

  # Repos are created on first apply; keep them (and their images) if the rest
  # of the footprint is torn down so a redeploy doesn't have to rebuild from
  # scratch. Set to false / empty the repo manually if you truly want them gone.
  force_delete = false
}

# Expire old/untagged images so the registry doesn't grow unbounded. Keeps the
# most recent tagged images and prunes untagged layers left behind by re-pushes.
resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the 20 most recent tagged images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = { type = "expire" }
      },
    ]
  })
}

# ── IAM: ECR push policy for the build runner's CI credentials ────────────────
# The `docker-build` runner (ubuntu-server1) is off-box, so it authenticates
# with the AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY GitHub secrets rather than an
# instance profile. Attach this managed policy to that IAM user to grant just
# the ECR push permissions it needs (its ARN is exported in outputs.tf).
data "aws_iam_policy_document" "ecr_push" {
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
      # Read actions are needed by `docker push`/buildx to skip already-present layers.
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for repo in aws_ecr_repository.app : repo.arn]
  }
}

resource "aws_iam_policy" "ecr_push" {
  name        = "${var.project_name}-${var.environment}-ecr-push"
  description = "Allows pushing the Office Manager app images to ECR (attach to the CI/build IAM user)."
  policy      = data.aws_iam_policy_document.ecr_push.json
}

resource "aws_security_group" "app" {
  name        = "${var.project_name}-${var.environment}-app"
  description = "Office Manager Phase 1 application host"
  vpc_id      = data.aws_vpc.selected.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.app_allowed_cidrs
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.app_allowed_cidrs
  }

  dynamic "ingress" {
    for_each = length(var.ssh_allowed_cidrs) > 0 ? [1] : []
    content {
      description = "SSH (restrict to office/VPN CIDRs)"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.ssh_allowed_cidrs
    }
  }

  # Nginx Proxy Manager admin UI (port 81). Kept off the public internet —
  # restrict to the same trusted office/VPN CIDR(s) allowed to SSH in. Leave
  # `npm_admin_allowed_cidrs` empty to keep the admin UI closed entirely (reach
  # it via an SSH tunnel or SSM port-forward instead).
  dynamic "ingress" {
    for_each = length(var.npm_admin_allowed_cidrs) > 0 ? [1] : []
    content {
      description = "Nginx Proxy Manager admin UI (restrict to office/VPN CIDRs)"
      from_port   = 81
      to_port     = 81
      protocol    = "tcp"
      cidr_blocks = var.npm_admin_allowed_cidrs
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── IAM: least-privilege role for the app instance ────────────────────────────
# Grants only what the running containers need: read the app secret, and
# read/write the uploads bucket used by app.utils.file_storage. No broad S3/EC2
# admin permissions.

data "aws_iam_policy_document" "app_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project_name}-${var.environment}-app"
  assume_role_policy = data.aws_iam_policy_document.app_assume.json
}

data "aws_iam_policy_document" "app_permissions" {
  statement {
    sid       = "ReadAppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }

  statement {
    sid = "UploadsBucketReadWrite"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }

  statement {
    sid       = "UploadsBucketList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.uploads.arn]
  }

  statement {
    sid = "BackupsBucketWrite"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
  }

  # Pull the application images from ECR at deploy time. GetAuthorizationToken
  # backs `docker login`/`aws ecr get-login-password`; the layer/image reads are
  # scoped to just this project's repositories.
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken is not resource-scopable
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for repo in aws_ecr_repository.app : repo.arn]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.project_name}-${var.environment}-app"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app_permissions.json
}

# SSM Session Manager access lets you shell into the instance without opening
# port 22 to the internet, so `ssh_allowed_cidrs` can stay empty in the common
# case.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project_name}-${var.environment}-app"
  role = aws_iam_role.app.name
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023_arm.id
  instance_type          = var.app_instance_type
  subnet_id              = local.subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
  key_name               = var.key_pair_name != "" ? var.key_pair_name : null

  root_block_device {
    volume_size           = var.app_root_volume_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tpl", {
    github_repo          = var.github_repo
    github_runner_pat    = var.github_runner_pat
    github_runner_labels = var.github_runner_labels
    aws_region           = var.aws_region
  })

  tags = {
    Name = "${var.project_name}-${var.environment}-app"
  }
}

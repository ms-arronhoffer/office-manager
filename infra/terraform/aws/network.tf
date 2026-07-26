# Phase 1 reuses the account's default VPC/subnets — the cheapest option
# since it avoids NAT gateway costs. This is the deliberate "greenfield but
# use what already exists" choice confirmed for this deployment.

data "aws_vpc" "selected" {
  id      = var.vpc_id != "" ? var.vpc_id : null
  default = var.vpc_id == "" ? true : null
}

data "aws_subnets" "selected" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }
}

locals {
  subnet_ids = length(var.subnet_ids) > 0 ? var.subnet_ids : data.aws_subnets.selected.ids
}

data "aws_ami" "al2023_arm" {
  most_recent = true
  owners      = ["amazon"]

  # Pin to the *standard* Amazon Linux 2023 arm64 image. The broad
  # `al2023-ami-*-arm64` glob also matches the `al2023-ami-minimal-*` and
  # `al2023-ami-ecs-*` variants, and with `most_recent = true` Terraform can
  # pick one of those. The minimal AMI ships WITHOUT `amazon-ssm-agent`
  # pre-installed, so a box launched from it never registers with SSM (the
  # deploy then fails with "never became SSM-managed"). The standard image
  # (name `al2023-ami-2023.<ver>-kernel-<ver>-arm64`) ships and auto-enables
  # the agent. Anchoring on `al2023-ami-2023.*` excludes minimal/ecs because
  # their names carry a `minimal`/`ecs` token instead of the version.
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

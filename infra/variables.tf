variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "project" {
  type    = string
  default = "appointment-agent"
}

variable "image_tag" {
  type        = string
  description = "Backend image tag to deploy (SHA or semver)."
  default     = "latest"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_name" {
  type    = string
  default = "appointments"
}

variable "frontend_domain" {
  type        = string
  description = "Optional custom domain for the CloudFront distribution."
  default     = ""
}

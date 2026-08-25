resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.project}/app"
  recovery_window_in_days = 0
}

# Populated out-of-band (or by CI) — never hard-code secret values here.
resource "aws_ssm_parameter" "jwt_secret" {
  name  = "/${var.project}/JWT_SECRET"
  type  = "SecureString"
  value = "CHANGE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}

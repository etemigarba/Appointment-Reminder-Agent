resource "aws_cloudwatch_metric_alarm" "api_5xx_high" {
  alarm_name          = "${var.project}-api-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
  }
  alarm_description = "API is returning elevated 5xx responses"
  treat_missing_data = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${var.project}-unhealthy-hosts"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Maximum"
  threshold           = 1
  dimensions = {
    TargetGroup  = aws_lb_target_group.api.arn_suffix
    LoadBalancer = aws_lb.api.arn_suffix
  }
  alarm_description  = "No healthy API targets behind the load balancer"
  treat_missing_data = "notBreaching"
}

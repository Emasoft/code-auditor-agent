variable "region" {
  description = "AWS region for all resources in this fixture."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment tag applied to every resource."
  type        = string
  default     = "fixture"
}

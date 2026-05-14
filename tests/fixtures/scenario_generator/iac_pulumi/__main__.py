# fixture for iac_pulumi (Python entry — coexists with index.ts for cross-language coverage)
import pulumi
import pulumi_aws as aws

queue = aws.sqs.Queue("py-queue", visibility_timeout_seconds=30)
topic = aws.sns.Topic("py-topic")

pulumi.export("queue_url", queue.url)
pulumi.export("topic_arn", topic.arn)

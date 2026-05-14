"""mq-fixture — exercises the three consumer shapes the discoverer
must handle:

  1. kafka-python:   consumer.subscribe(['topic'])     → QUEUE_CONSUMER
  2. kafka-python:   for msg in consumer: ...          → QUEUE_CONSUMER
  3. pika RabbitMQ:  channel.basic_consume(queue='q',  → QUEUE_CONSUMER
                                            on_message_callback=cb)
"""

import pika
from kafka import KafkaConsumer


def consume_orders() -> None:
    """Subscribe to the 'orders' topic and process each message."""
    consumer = KafkaConsumer(bootstrap_servers="localhost:9092")
    consumer.subscribe(["orders"])
    for msg in consumer:
        handle_order(msg.value)


def consume_audit_log() -> None:
    """Subscribe to the 'audit' topic for compliance logging."""
    consumer = KafkaConsumer(bootstrap_servers="localhost:9092")
    consumer.subscribe(["audit"])
    for msg in consumer:
        handle_audit(msg.value)


def on_rabbit_message(channel, method, properties, body) -> None:
    """RabbitMQ message callback — acks the message after processing."""
    handle_rabbit(body)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def start_rabbit_consumer() -> None:
    """Register on_rabbit_message as the callback for the 'jobs' queue."""
    connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
    channel = connection.channel()
    channel.basic_consume(queue="jobs", on_message_callback=on_rabbit_message)
    channel.start_consuming()


def handle_order(payload: bytes) -> None:
    """Helper — not a consumer entry point. Must be skipped."""
    pass


def handle_audit(payload: bytes) -> None:
    """Helper — not a consumer entry point. Must be skipped."""
    pass


def handle_rabbit(body: bytes) -> None:
    """Helper — not a consumer entry point. Must be skipped."""
    pass

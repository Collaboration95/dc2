"""Native credential SQS adapter with explicit producer and consumer lanes."""

import asyncio
import json

from delivery.envelope import canonical, document

LANES = {
    "processing-commands": {"submit", "retry", "cancel"},
    "processing-work": {"work"},
    "processing-work-short": {"work"},
    "media-results": {"result"},
}
PRODUCERS = {
    "media": {"processing-commands"},
    "processing": {"processing-work", "processing-work-short", "media-results"},
}
CONSUMERS = {
    "processing-control": {"processing-commands"},
    "encoder": {"processing-work"},
    "short-encoder": {"processing-work-short"},
    "media-projection": {"media-results"},
}


# A short-lane row can outlive the short queue (the experiment is switched off while work is
# queued). It is still ordinary work, so it goes to the standard lane instead of failing forever.
FALLBACK_LANE = {"processing-work-short": "processing-work"}


class SQS:
    def __init__(
        self, urls, *, producer=None, consumer=None, client=None, region=None, endpoint_url=None
    ):
        self.urls, self.producer, self.consumer = dict(urls), producer, consumer
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "sqs",
                region_name=region,
                endpoint_url=endpoint_url,
                config=Config(
                    connect_timeout=2,
                    read_timeout=25,
                    retries={"total_max_attempts": 2, "mode": "standard"},
                ),
            )
        self.client = client

    def _lane(self, queue, allowed):
        if queue not in allowed or queue not in self.urls:
            raise ValueError("Queue lane is not permitted")
        return self.urls[queue]

    async def send(self, queue, envelope):
        allowed = PRODUCERS.get(self.producer, set())
        url = self._lane(queue, allowed)
        if not url and queue in FALLBACK_LANE:
            url = self._lane(FALLBACK_LANE[queue], allowed)
        body = document(envelope)
        if body["kind"] not in LANES[queue]:
            raise ValueError("Message kind does not belong to queue lane")
        return await asyncio.to_thread(
            self.client.send_message, QueueUrl=url, MessageBody=canonical(body)
        )

    async def receive(self, queue, *, wait_seconds=20, visibility_seconds=60):
        url = self._lane(queue, CONSUMERS.get(self.consumer, set()))
        if not 0 <= wait_seconds <= 20 or not 1 <= visibility_seconds <= 43200:
            raise ValueError("Invalid bounded polling or visibility")
        response = await asyncio.to_thread(
            self.client.receive_message,
            QueueUrl=url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=visibility_seconds,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        return response.get("Messages", [])

    async def delete(self, queue, receipt):
        url = self._lane(queue, CONSUMERS.get(self.consumer, set()))
        return await asyncio.to_thread(
            self.client.delete_message, QueueUrl=url, ReceiptHandle=receipt
        )

    async def visibility(self, queue, receipt, seconds):
        url = self._lane(queue, CONSUMERS.get(self.consumer, set()))
        if not 0 <= seconds <= 43200:
            raise ValueError("Invalid visibility timeout")
        return await asyncio.to_thread(
            self.client.change_message_visibility,
            QueueUrl=url,
            ReceiptHandle=receipt,
            VisibilityTimeout=seconds,
        )


def decode(record, queue):
    body = document(json.loads(record.get("body", record.get("Body", ""))))
    if body["kind"] not in LANES[queue]:
        raise ValueError("Unexpected message kind on consumer lane")
    return body


async def consume_batch(event, queue, handler):
    """Lambda partial-batch response; exceptions remain eligible for redrive/DLQ.

    handler must return only after committing inbox and owned state. Lambda's
    event source mapping deletes successful records; we never ACK in the handler.
    """
    failures = []
    for record in event.get("Records", []):
        try:
            await handler(decode(record, queue))
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}

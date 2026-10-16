"""Operator view and redrive for V1 dead-letter queues (docs/execution/aws/v1/dlq-runbook.md).

python -m delivery.dlq inspect --queue-url URL [--limit 10] [--endpoint-url LOOPBACK]
python -m delivery.dlq redrive --dlq-arn ARN [--per-second 5]
python -m delivery.dlq status  --dlq-arn ARN

Inspection peeks with a zero visibility timeout and prints identities only, never
bodies: sources, outputs and error text stay out of terminals and tickets. Redrive
returns messages to their original source queue, where the SQL inbox makes a
repeat harmless.
"""

import argparse
import json
from urllib.parse import urlsplit

from contracts.v1 import Envelope


def summarize(message):
    summary = {
        "sqs_message_id": message.get("MessageId"),
        "receive_count": int(message.get("Attributes", {}).get("ApproximateReceiveCount", 0)),
    }
    try:
        body = Envelope.from_dict(json.loads(message["Body"]))
    except Exception:
        # Not even a valid envelope: a producer bug or injection. Do not echo it.
        return {**summary, "valid": False}
    payload = body.payload
    return {
        **summary,
        "valid": True,
        "kind": body.kind,
        "message_id": body.message_id,
        "owner_id": body.owner_id,
        "asset_id": body.asset_id,
        "job_id": body.job_id,
        "attempt_id": body.attempt_id,
        "state_version": body.state_version,
        "status": payload.get("status"),
    }


def inspect(client, queue_url, *, limit=10):
    """Peek at up to ``limit`` messages (<=10 per receive, 5 receives) without hiding them."""
    seen = {}
    for _ in range(5):
        if len(seen) >= limit:
            break
        response = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=min(10, limit - len(seen)),
            VisibilityTimeout=0,
            WaitTimeSeconds=0,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        if not messages:
            break
        for message in messages:
            seen[message["MessageId"]] = summarize(message)
    return list(seen.values())


def redrive(client, dlq_arn, *, per_second=5):
    if not 1 <= per_second <= 500:
        raise ValueError("per_second must be between 1 and 500")
    # No DestinationArn: SQS returns each message to the queue it came from.
    return client.start_message_move_task(
        SourceArn=dlq_arn, MaxNumberOfMessagesPerSecond=per_second
    )["TaskHandle"]


def status(client, dlq_arn):
    return client.list_message_move_tasks(SourceArn=dlq_arn, MaxResults=5).get("Results", [])


def build_client(endpoint_url=None):
    import boto3
    from botocore.config import Config

    if endpoint_url and urlsplit(endpoint_url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("--endpoint-url is for a loopback emulator only")
    return boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        config=Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2}),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("inspect", "redrive", "status"))
    parser.add_argument("--queue-url")
    parser.add_argument("--dlq-arn")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--per-second", type=int, default=5)
    parser.add_argument("--endpoint-url")
    args = parser.parse_args(argv)
    client = build_client(args.endpoint_url)
    if args.command == "inspect":
        if not args.queue_url or not 1 <= args.limit <= 50:
            parser.error("inspect needs --queue-url and a --limit of 1-50")
        result = inspect(client, args.queue_url, limit=args.limit)
    elif not args.dlq_arn:
        parser.error(f"{args.command} needs --dlq-arn")
    elif args.command == "redrive":
        result = {"task_handle": redrive(client, args.dlq_arn, per_second=args.per_second)}
    else:
        result = status(client, args.dlq_arn)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

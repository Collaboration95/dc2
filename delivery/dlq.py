"""Operator view and redrive for V1 dead-letter queues (docs/execution/aws/v1/dlq-runbook.md).

python -m delivery.dlq inspect --queue-url URL [--limit 10]
        (--endpoint-url LOOPBACK | --profile P --region R [--account A])
python -m delivery.dlq redrive --dlq-arn ARN [--per-second 5]
        (--endpoint-url LOOPBACK [--source-queue-url URL] | --profile P --region R [--account A])
python -m delivery.dlq status  --dlq-arn ARN
        (--endpoint-url LOOPBACK | --profile P --region R [--account A])

Without a loopback endpoint the command talks to real AWS, so it needs an explicit profile
(never ``default``) and region, and proves through STS that the profile belongs to the
expected account before any SQS call. The default credential chain is never consulted.

Inspection peeks with a zero visibility timeout and prints identities only, never
bodies: sources, outputs and error text stay out of terminals and tickets. Redrive
returns messages to their original source queue, where the SQL inbox makes a
repeat harmless.

Real AWS always uses the native move task. Moto 5.2.4 does not implement it, so a
loopback emulator that refuses the call falls back to a manual receive/validate/
send/delete loop (``manual_redrive``). The fallback is never reachable for a
non-loopback endpoint, so a real AWS failure can not be masked by it.
"""

import argparse
import json
import os
import re
import time
from urllib.parse import urlsplit

from botocore.exceptions import ClientError

from contracts.v1 import Envelope

LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}
# The one project account and region (docs/execution/aws/v1/cloud-operator-20261015.md).
EXPECTED_ACCOUNT = "866865534361"
EXPECTED_REGION = "ap-southeast-1"
PROFILE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


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


def check_rate(per_second):
    if not 1 <= per_second <= 500:
        raise ValueError("per_second must be between 1 and 500")


def redrive(client, dlq_arn, *, per_second=5):
    check_rate(per_second)
    # No DestinationArn: SQS returns each message to the queue it came from.
    return client.start_message_move_task(
        SourceArn=dlq_arn, MaxNumberOfMessagesPerSecond=per_second
    )["TaskHandle"]


def status(client, dlq_arn):
    return client.list_message_move_tasks(SourceArn=dlq_arn, MaxResults=5).get("Results", [])


def is_loopback(endpoint_url):
    return bool(endpoint_url) and urlsplit(endpoint_url).hostname in LOOPBACK_HOSTS


def is_not_implemented(error):
    """Whether an emulator refused the move-task API (Moto 5.2.4 answers a bare HTTP 500)."""
    details = error.response
    code = details.get("Error", {}).get("Code", "")
    message = details.get("Error", {}).get("Message", "")
    return (
        code in {"NotImplemented", "NotImplementedError", "UnsupportedOperation", "500"}
        or "not implemented" in message.lower()
        or "not been implemented" in message.lower()
        or details.get("ResponseMetadata", {}).get("HTTPStatusCode") in {500, 501}
    )


def queue_url_from_arn(client, arn):
    # arn:aws:sqs:<region>:<account>:<name>
    account, name = arn.split(":")[4:6]
    return client.get_queue_url(QueueName=name, QueueOwnerAWSAccountId=account)["QueueUrl"]


def queue_attribute(client, queue_url, name):
    attributes = client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=[name])
    return attributes.get("Attributes", {}).get(name)


def resolve_source_queue(client, dlq_arn, source_queue_url=None):
    """Find the one queue whose poison messages this DLQ holds.

    An explicit URL must name this DLQ in its own redrive policy, so a typo can not
    send quarantined work to an unrelated queue. Otherwise the DLQ's redrive-allow policy
    is used, then its dead-letter source listing. Ambiguity is an error: guessing which of
    several queues to refill is worse than asking.
    """
    if source_queue_url:
        policy = queue_attribute(client, source_queue_url, "RedrivePolicy")
        if not policy or json.loads(policy).get("deadLetterTargetArn") != dlq_arn:
            raise ValueError("--source-queue-url does not use this DLQ as its dead-letter queue")
        return source_queue_url
    dlq_url = queue_url_from_arn(client, dlq_arn)
    try:
        allow = queue_attribute(client, dlq_url, "RedriveAllowPolicy")
    except ClientError as error:
        # Moto 5.2.4 does not know this attribute; the source listing below still works.
        if error.response.get("Error", {}).get("Code") != "InvalidAttributeName":
            raise
        allow = None
    allowed = json.loads(allow).get("sourceQueueArns", []) if allow else []
    if len(allowed) == 1:
        return queue_url_from_arn(client, allowed[0])
    sources = client.list_dead_letter_source_queues(QueueUrl=dlq_url).get("queueUrls", [])
    if len(sources) == 1:
        return sources[0]
    raise ValueError(
        f"cannot tell which queue this DLQ belongs to ({len(allowed) or len(sources)} "
        "candidates); pass --source-queue-url"
    )


def manual_redrive(client, dlq_arn, *, per_second=5, source_queue_url=None, sleep=time.sleep):
    """Receive, validate, re-send and delete, for emulators without move tasks.

    Invalid envelopes are never sent anywhere: they stay in the DLQ, hidden only until
    the run ends. The send happens before the delete, so a crash between them leaves a
    duplicate the SQL inbox absorbs instead of a lost message.
    """
    check_rate(per_second)
    source = resolve_source_queue(client, dlq_arn, source_queue_url)
    dlq_url = queue_url_from_arn(client, dlq_arn)
    moved, held, seen = 0, [], set()
    try:
        while True:
            # The long timeout keeps an invalid message out of this loop's next receive.
            messages = client.receive_message(
                QueueUrl=dlq_url, MaxNumberOfMessages=1, VisibilityTimeout=300, WaitTimeSeconds=0
            ).get("Messages", [])
            messages = [message for message in messages if message["MessageId"] not in seen]
            if not messages:
                break
            for message in messages:
                seen.add(message["MessageId"])
                if not summarize(message)["valid"]:
                    held.append(message["ReceiptHandle"])
                    continue
                client.send_message(QueueUrl=source, MessageBody=message["Body"])
                client.delete_message(QueueUrl=dlq_url, ReceiptHandle=message["ReceiptHandle"])
                moved += 1
                sleep(1 / per_second)
    finally:
        for handle in held:
            client.change_message_visibility(
                QueueUrl=dlq_url, ReceiptHandle=handle, VisibilityTimeout=0
            )
    return {"mode": "manual", "moved": moved, "left_invalid": len(held), "source": source}


def redrive_with_fallback(
    client, dlq_arn, *, endpoint_url=None, per_second=5, source_queue_url=None
):
    """Native move task; manual only after a loopback emulator refuses it."""
    if source_queue_url and not is_loopback(endpoint_url):
        raise ValueError("--source-queue-url is only used by the loopback emulator fallback")
    try:
        return {"task_handle": redrive(client, dlq_arn, per_second=per_second)}
    except ClientError as error:
        if not is_loopback(endpoint_url) or not is_not_implemented(error):
            raise
    return manual_redrive(client, dlq_arn, per_second=per_second, source_queue_url=source_queue_url)


def status_with_fallback(client, dlq_arn, *, endpoint_url=None):
    try:
        return status(client, dlq_arn)
    except ClientError as error:
        if not is_loopback(endpoint_url) or not is_not_implemented(error):
            raise
    return {"mode": "manual", "note": "emulator has no move tasks; manual redrive is synchronous"}


def build_client(endpoint_url=None):
    import boto3
    from botocore.config import Config

    if endpoint_url and not is_loopback(endpoint_url):
        raise ValueError("--endpoint-url is for a loopback emulator only")
    return boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        config=Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2}),
    )


def resolve_scope(parser, args, environ):
    """(profile, region, account) for real AWS; any gap is a usage error, never a default."""
    account = args.account or environ.get("DC2_AWS_ACCOUNT") or EXPECTED_ACCOUNT
    if (
        not args.profile
        or args.profile == "default"
        or not PROFILE_PATTERN.fullmatch(args.profile)
        or args.region != EXPECTED_REGION
        or not re.fullmatch(r"[0-9]{12}", account)
    ):
        parser.error(
            f"real AWS needs an explicit non-default --profile and --region {EXPECTED_REGION} "
            "(or a loopback --endpoint-url for an emulator)"
        )
    return {"profile": args.profile, "region": args.region, "account": account}


def build_verified_client(scope):
    """SQS client for real AWS, built only after STS names the expected account.

    This reuses the operator transport's identity check (explicit profile, ambient AWS_*
    variables refused, fresh get-caller-identity) so a standalone command behaves exactly
    like the session CLI's `dlq` action instead of falling back to whatever `default` is.
    """
    # Imported here: the images ship `delivery` without the operator scripts.
    from scripts.aws.transport import OperationError
    from scripts.aws.v1 import operations

    try:
        return operations.live_sqs_client(scope)
    except OperationError as error:
        raise SystemExit(f"error: {error}") from None


def main(argv=None, *, environ=None, verified_client=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("inspect", "redrive", "status"))
    parser.add_argument("--queue-url")
    parser.add_argument("--dlq-arn")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--per-second", type=int, default=5)
    parser.add_argument("--endpoint-url")
    parser.add_argument("--source-queue-url")
    parser.add_argument(
        "--profile", help="real AWS only: explicit profile (e.g. dc2-agent), never 'default'"
    )
    parser.add_argument("--region", help=f"real AWS only: {EXPECTED_REGION}")
    parser.add_argument(
        "--account",
        help="real AWS only: 12-digit account STS must report "
        f"(default DC2_AWS_ACCOUNT, else {EXPECTED_ACCOUNT})",
    )
    args = parser.parse_args(argv)
    # Validate before building a client: constructing one resolves credentials, which can
    # reach the instance-metadata service, and a bad invocation should never do that.
    if args.command == "inspect" and (not args.queue_url or not 1 <= args.limit <= 50):
        parser.error("inspect needs --queue-url and a --limit of 1-50")
    if args.command != "inspect" and not args.dlq_arn:
        parser.error(f"{args.command} needs --dlq-arn")
    if args.source_queue_url and not (args.command == "redrive" and is_loopback(args.endpoint_url)):
        parser.error("--source-queue-url applies only to redrive with a loopback --endpoint-url")
    if args.endpoint_url and not is_loopback(args.endpoint_url):
        parser.error("--endpoint-url is for a loopback emulator only")
    if is_loopback(args.endpoint_url):
        if args.profile or args.region or args.account:
            parser.error("--profile, --region and --account apply to real AWS, not an emulator")
        client = build_client(args.endpoint_url)
    else:
        scope = resolve_scope(parser, args, environ)
        client = (verified_client or build_verified_client)(scope)
    if args.command == "inspect":
        result = inspect(client, args.queue_url, limit=args.limit)
    elif args.command == "redrive":
        result = redrive_with_fallback(
            client,
            args.dlq_arn,
            endpoint_url=args.endpoint_url,
            per_second=args.per_second,
            source_queue_url=args.source_queue_url,
        )
    else:
        result = status_with_fallback(client, args.dlq_arn, endpoint_url=args.endpoint_url)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

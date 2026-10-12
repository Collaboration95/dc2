"""Create private buckets and service-scoped principals; verify with real S3 calls."""

import io
import os
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import urllib3
from minio import Minio
from minio.credentials import StaticProvider
from minio.error import S3Error
from minio.minioadmin import MinioAdmin


def statement(actions, resources):
    return {"Effect": "Allow", "Action": actions, "Resource": resources}


def policies(source, output):
    source_arn, output_arn = f"arn:aws:s3:::{source}", f"arn:aws:s3:::{output}"
    return {
        "MEDIA": [
            statement(["s3:GetBucketLocation"], [source_arn, output_arn]),
            statement(["s3:ListBucket"], [source_arn]),
            statement(["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], [source_arn + "/*"]),
            statement(["s3:GetObject"], [output_arn + "/*"]),
        ],
        "PROCESSING": [
            statement(
                ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
                [output_arn + "/*"],
            ),
        ],
        "CLEANUP": [
            statement(["s3:ListBucket"], [output_arn]),
            statement(["s3:DeleteObject"], [output_arn + "/*"]),
        ],
    }


def client(principal):
    return Minio(
        "minio:9000",
        access_key=os.environ[f"{principal}_MINIO_ACCESS_KEY"],
        secret_key=os.environ[f"{principal}_MINIO_SECRET_KEY"],
        secure=False,
        region=os.environ["MINIO_REGION"],
    )


def bootstrap():
    admin = MinioAdmin(
        endpoint="minio:9000",
        secure=False,
        credentials=StaticProvider(
            os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"]
        ),
    )
    root = Minio(
        "minio:9000",
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=False,
        region=os.environ["MINIO_REGION"],
    )
    source, output = os.environ["SOURCE_BUCKET"], os.environ["OUTPUT_BUCKET"]
    for bucket in (source, output):
        if not root.bucket_exists(bucket):
            root.make_bucket(bucket, location=os.environ["MINIO_REGION"])
        root.delete_bucket_policy(bucket)
    for principal, statements in policies(source, output).items():
        policy = "dc2-" + principal.lower()
        access = os.environ[f"{principal}_MINIO_ACCESS_KEY"]
        admin.user_add(access, os.environ[f"{principal}_MINIO_SECRET_KEY"])
        admin.policy_add(policy, policy={"Version": "2012-10-17", "Statement": statements})
        admin.policy_set(policy, user=access)
    print("Private source/output buckets and MM/worker/cleanup policies initialized.")


def deny(call):
    try:
        result = call()
        if hasattr(result, "close"):
            result.close()
            result.release_conn()
    except S3Error as exc:
        if exc.code in ("AccessDenied", "AllAccessDisabled"):
            return
        raise
    raise RuntimeError("Storage isolation check unexpectedly allowed an operation")


def smoke():
    source, output = os.environ["SOURCE_BUCKET"], os.environ["OUTPUT_BUCKET"]
    media, worker, cleanup = client("MEDIA"), client("PROCESSING"), client("CLEANUP")
    key = "infra-smoke/" + uuid4().hex
    payload = b"dc2-private-storage-smoke"
    try:
        media.put_object(source, key, io.BytesIO(payload), len(payload))
        worker.put_object(output, key, io.BytesIO(payload), len(payload))
        for bucket in (source, output):
            reply = media.get_object(bucket, key)
            try:
                assert reply.read() == payload
            finally:
                reply.close()
                reply.release_conn()
        deny(lambda: worker.get_object(source, key))
        deny(lambda: worker.put_object(source, key, io.BytesIO(payload), len(payload)))
        deny(lambda: worker.get_object(output, key))
        deny(lambda: worker.remove_object(output, key))
        deny(lambda: list(worker.list_objects(output)))
        deny(lambda: cleanup.get_object(source, key))
        deny(lambda: cleanup.get_object(output, key))
        deny(lambda: media.put_object(output, key, io.BytesIO(payload), len(payload)))
        assert key in [obj.object_name for obj in cleanup.list_objects(output, prefix=key)]

        public = urlsplit(os.environ["PUBLIC_URL"])
        signer = Minio(
            public.netloc,
            access_key=os.environ["MEDIA_MINIO_ACCESS_KEY"],
            secret_key=os.environ["MEDIA_MINIO_SECRET_KEY"],
            secure=True,
            region=os.environ["MINIO_REGION"],
        )
        # Connect inside Docker while retaining localhost TLS SAN + public Host/port.
        pool = urllib3.HTTPSConnectionPool(
            "nginx",
            443,
            ca_certs=os.environ["CA_FILE"],
            cert_reqs="CERT_REQUIRED",
            assert_hostname="localhost",
            server_hostname="localhost",
            timeout=10,
            retries=False,
        )
        try:
            for bucket in (source, output):
                url = urlsplit(signer.presigned_get_object(bucket, key))
                reply = pool.request(
                    "GET", url.path + "?" + url.query, headers={"Host": public.netloc}
                )
                assert reply.status == 200 and reply.data == payload, (
                    "Signed HTTPS object fetch failed"
                )
                unsigned = pool.request("GET", url.path, headers={"Host": public.netloc})
                assert unsigned.status == 403, "Anonymous object fetch unexpectedly allowed"
        finally:
            pool.close()
    finally:
        media.remove_object(source, key)
        cleanup.remove_object(output, key)
    print("Scoped storage denies and signed HTTPS source/output GETs passed.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--smoke"]:
        smoke()
    else:
        bootstrap()

"""幂等初始化开发桶和上传过期规则，保留其他生命周期配置。"""

import time

from minio.commonconfig import ENABLED, Filter
from minio.error import S3Error
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

RULE_ID = "shopping-upload-expiry-v1"


def configure_upload_expiry(client, bucket):
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    try:
        rules = list(client.get_bucket_lifecycle(bucket).rules)
    except S3Error as exc:
        if exc.code != "NoSuchLifecycleConfiguration":
            raise
        rules = []
    rules = [rule for rule in rules if rule.rule_id != RULE_ID]
    rules.append(Rule(ENABLED, rule_filter=Filter(prefix="uploads/"),
                      rule_id=RULE_ID, expiration=Expiration(days=1)))
    client.set_bucket_lifecycle(bucket, LifecycleConfig(rules))


def main():
    from src.config import MINIO_BUCKET
    from src.data.minio_client import create_minio_client

    client = create_minio_client()
    for attempt in range(30):
        try:
            configure_upload_expiry(client, MINIO_BUCKET)
            print("开发桶及上传生命周期已配置")
            return
        except Exception:
            if attempt == 29:
                raise
            time.sleep(2)


if __name__ == "__main__":
    main()

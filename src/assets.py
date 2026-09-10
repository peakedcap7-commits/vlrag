"""开发环境图片的格式、归属和短期内容令牌边界。"""

import hashlib
import hmac
import io
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException
from minio.error import S3Error
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000


class AssetService:
    def __init__(self, client, bucket, secret):
        if not secret or len(secret.encode()) < 32:
            raise ValueError("图片签名密钥未配置")
        self.client, self.bucket = client, bucket
        self.secret = hmac.new(secret.encode(), b"asset-content-v1", hashlib.sha256).digest()

    def authorize(self, identity, key, thread_id=None):
        parts = key.split("/")
        if len(key) > 512 or any(p in {"", ".", ".."} for p in parts) or "\\" in key:
            raise HTTPException(404, "图片不存在")
        public = key.startswith(("polyvore/items/", "demo/items/"))
        if not public and not key.startswith("uploads/"):
            raise HTTPException(404, "图片不存在")
        try:
            stat = self.client.stat_object(self.bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                raise HTTPException(404, "图片不存在") from exc
            raise HTTPException(503, "图片存储暂不可用") from exc
        if not public:
            metadata = {k.lower().removeprefix("x-amz-meta-"): v for k, v in stat.metadata.items()}
            if (len(parts) != 3 or metadata.get("tenant-id") != str(identity.tenant_id)
                    or metadata.get("user-id") != str(identity.user_id)
                    or metadata.get("thread-id") != parts[1]
                    or (thread_id is not None and parts[1] != str(thread_id))):
                raise HTTPException(404, "图片不存在")
            try:
                expired = datetime.fromisoformat(metadata["expires-at"]) <= datetime.now(timezone.utc)
            except (KeyError, ValueError, TypeError):
                expired = True
            if expired:
                raise HTTPException(404, "图片不存在或已过期")
        return stat

    def url(self, identity, key):
        self.authorize(identity, key)
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        token = jwt.encode({"tenant": str(identity.tenant_id), "sub": str(identity.user_id),
                            "key": key, "exp": expires, "aud": "asset-content-v1"},
                           self.secret, algorithm="HS256")
        return {"key": key, "content_url": f"/api/assets/content/{token}", "expires_at": expires}

    def upload(self, identity, thread_id, data):
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "图片不能超过 10 MiB")
        try:
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(415, "仅支持 JPEG、PNG、WEBP")
                if source.width * source.height > MAX_PIXELS:
                    raise HTTPException(413, "图片不能超过 20 MP")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(415, "无法解码图片") from exc
        key = f"uploads/{UUID(str(thread_id))}/{uuid4()}.jpg"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        output.seek(0)
        self.client.put_object(self.bucket, key, output, len(output.getbuffer()), content_type="image/jpeg",
                               metadata={"tenant-id": str(identity.tenant_id), "user-id": str(identity.user_id),
                                         "thread-id": str(thread_id), "expires-at": expires.isoformat()})
        link = self.url(identity, key)
        return {"image_key": key, "content_url": link["content_url"], "expires_at": link["expires_at"]}

    def content(self, identity, token):
        try:
            claims = jwt.decode(token, self.secret, algorithms=["HS256"], audience="asset-content-v1",
                                options={"require": ["tenant", "sub", "key", "exp", "aud"]})
            if claims["tenant"] != str(identity.tenant_id) or claims["sub"] != str(identity.user_id):
                raise ValueError("归属不符")
            key = claims["key"]
            if not isinstance(key, str):
                raise ValueError("对象键无效")
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise HTTPException(404, "图片地址无效或已过期") from exc
        stat = self.authorize(identity, key)
        response = self.client.get_object(self.bucket, key)

        def chunks():
            try:
                yield from response.stream(64 * 1024)
            finally:
                response.close()
                response.release_conn()
        return chunks(), stat


def configured_asset_service():
    from src.config import DEV_JWT_SECRET, MINIO_BUCKET
    from src.data.minio_client import create_minio_client

    return AssetService(create_minio_client(), MINIO_BUCKET, DEV_JWT_SECRET)

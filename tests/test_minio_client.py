import base64
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# 这是一个可被常见图片工具识别的 1×1 JPEG，仅供上传连通性验证。
MINIMAL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABAf/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPxB//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxB//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxB//9k="
)


class MinioConfigTest(unittest.TestCase):
    def test_从环境变量读取_minio_配置(self):
        import src.config as config

        values = {
            "PYTHON_DOTENV_DISABLED": "1",
            "MINIO_ENDPOINT": "minio.internal:9000",
            "MINIO_ACCESS_KEY": "test-access",
            "MINIO_SECRET_KEY": "test-secret",
            "MINIO_SECURE": "true",
            "MINIO_BUCKET": "test-bucket",
        }
        try:
            with patch.dict(os.environ, values):
                config = importlib.reload(config)
                self.assertEqual(config.MINIO_ENDPOINT, "minio.internal:9000")
                self.assertEqual(config.MINIO_ACCESS_KEY, "test-access")
                self.assertEqual(config.MINIO_SECRET_KEY, "test-secret")
                self.assertIs(config.MINIO_SECURE, True)
                self.assertEqual(config.MINIO_BUCKET, "test-bucket")
        finally:
            importlib.reload(config)

    def test_minio_secure_忽略首尾空格(self):
        import src.config as config

        try:
            with patch.dict(
                os.environ,
                {
                    "PYTHON_DOTENV_DISABLED": "1",
                    "MINIO_SECURE": " true ",
                },
            ):
                config = importlib.reload(config)
                self.assertIs(config.MINIO_SECURE, True)
        finally:
            importlib.reload(config)

    def test_minio_secure_非法值抛出明确错误(self):
        import src.config as config

        try:
            with patch.dict(
                os.environ,
                {
                    "PYTHON_DOTENV_DISABLED": "1",
                    "MINIO_SECURE": "treu",
                },
            ):
                with self.assertRaisesRegex(ValueError, "MINIO_SECURE"):
                    importlib.reload(config)
        finally:
            importlib.reload(config)


class MinioClientTest(unittest.TestCase):
    def test_使用显式参数创建_minio_客户端(self):
        minio_client = importlib.import_module("src.data.minio_client")

        with patch.object(minio_client, "Minio") as minio_class:
            client = minio_client.create_minio_client(
                endpoint="localhost:9000",
                access_key="test-access-key",
                secret_key="test-secret-key",
                secure=False,
            )

        self.assertIs(client, minio_class.return_value)
        minio_class.assert_called_once_with(
            "localhost:9000",
            access_key="test-access-key",
            secret_key="test-secret-key",
            secure=False,
        )

    def test_上传图片前创建不存在的_bucket_并返回对象位置(self):
        minio_client = importlib.import_module("src.data.minio_client")
        client = MagicMock()
        client.bucket_exists.return_value = False

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "test.jpg"
            image_path.write_bytes(MINIMAL_JPEG)

            result = minio_client.upload_image(
                image_path,
                object_key="polyvore/items/test.jpg",
                bucket="shopping-qna",
                client=client,
            )

        client.bucket_exists.assert_called_once_with("shopping-qna")
        client.make_bucket.assert_called_once_with("shopping-qna")
        client.fput_object.assert_called_once_with(
            "shopping-qna",
            "polyvore/items/test.jpg",
            str(image_path),
            content_type="image/jpeg",
        )
        self.assertEqual(
            result,
            {
                "bucket": "shopping-qna",
                "object_key": "polyvore/items/test.jpg",
            },
        )


@unittest.skipUnless(
    os.getenv("RUN_MINIO_SMOKE") == "1",
    "仅在 RUN_MINIO_SMOKE=1 时连接本机 MinIO",
)
class MinioSmokeTest(unittest.TestCase):
    def test_上传临时图片到本机_minio(self):
        minio_client = importlib.import_module("src.data.minio_client")

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "test.jpg"
            image_path.write_bytes(MINIMAL_JPEG)
            result = minio_client.upload_image(
                image_path,
                object_key="polyvore/items/test.jpg",
            )

        self.assertEqual(result["bucket"], "shopping-qna")
        self.assertEqual(result["object_key"], "polyvore/items/test.jpg")


if __name__ == "__main__":
    unittest.main()

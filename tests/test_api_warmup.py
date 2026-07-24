import unittest
import importlib
import os
from unittest.mock import patch


class FakeService:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class ApiWarmupTest(unittest.TestCase):
    def test_enable_model_warmup_从环境变量严格读取(self):
        import src.config as config

        try:
            with patch.dict(
                os.environ,
                {"ENABLE_MODEL_WARMUP": "true"},
            ):
                reloaded = importlib.reload(config)
                self.assertTrue(reloaded.ENABLE_MODEL_WARMUP)
        finally:
            importlib.reload(config)

    def _build_client(self, enable_model_warmup):
        from fastapi.testclient import TestClient
        from src.api.app import create_app
        from src.api.runtime import ApiRuntimeManager, RuntimeResources

        calls = []

        def builder():
            calls.append("build")
            return RuntimeResources(
                polyvore_service=FakeService(),
                assistant_graph=object(),
            )

        runtime = ApiRuntimeManager(builder)
        client = TestClient(
            create_app(
                runtime_manager=runtime,
                enable_model_warmup=enable_model_warmup,
            )
        )
        return client, runtime, calls

    def test_默认不自动预热且_ready_为未就绪(self):
        client, _runtime, calls = self._build_client(False)

        with client:
            response = client.get("/health/ready")

        self.assertEqual(calls, [])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertFalse(response.json()["warmed_up"])
        self.assertIsNone(response.json()["warmup_seconds"])
        self.assertIsNone(response.json()["error"])

    def test_环境开关开启时生命周期自动预热(self):
        client, _runtime, calls = self._build_client(True)

        with client:
            response = client.get("/health/ready")

        self.assertEqual(calls, ["build"])
        self.assertEqual(response.json()["status"], "ready")
        self.assertTrue(response.json()["warmed_up"])
        self.assertIsNotNone(response.json()["warmup_seconds"])

    def test_post_warmup_幂等且不重复加载(self):
        client, _runtime, calls = self._build_client(False)

        with client:
            first = client.post("/warmup")
            second = client.post("/warmup")
            ready = client.get("/health/ready")

        self.assertEqual(calls, ["build"])
        self.assertEqual(first.json()["status"], "ready")
        self.assertEqual(second.json(), first.json())
        self.assertEqual(ready.json(), first.json())

    def test_预热错误只返回异常类型不泄露原始消息(self):
        from fastapi.testclient import TestClient
        from src.api.app import create_app
        from src.api.runtime import ApiRuntimeManager

        def builder():
            raise RuntimeError("包含不应返回的敏感内容")

        client = TestClient(
            create_app(
                runtime_manager=ApiRuntimeManager(builder),
                enable_model_warmup=False,
            )
        )

        with client:
            response = client.post("/warmup")

        self.assertEqual(response.json()["status"], "error")
        self.assertFalse(response.json()["warmed_up"])
        self.assertEqual(response.json()["error"], "RuntimeError")
        self.assertNotIn("敏感内容", response.text)


if __name__ == "__main__":
    unittest.main()

from dataclasses import dataclass
from threading import Condition
from time import perf_counter

from src.performance import log_performance


@dataclass(frozen=True)
class RuntimeResources:
    """FastAPI 运行期复用的重资源。"""

    polyvore_service: object
    assistant_graph: object


class ApiRuntimeManager:
    """线程安全地懒加载并复用模型、Chroma 和推荐服务。"""

    def __init__(self, builder, resources=None):
        self._builder = builder
        self._resources = resources
        self._condition = Condition()
        self._status = "ready" if resources is not None else "not_ready"
        self._warmup_seconds = 0.0 if resources is not None else None
        self._error = None

    def snapshot(self):
        """返回不包含配置和密钥的就绪状态。"""
        with self._condition:
            return {
                "warmed_up": self._status == "ready",
                "status": self._status,
                "warmup_seconds": self._warmup_seconds,
                "error": self._error,
            }

    def warmup(self):
        """幂等加载重资源；并发请求复用同一次初始化。"""
        with self._condition:
            if self._status == "ready":
                return self.snapshot()
            if self._status == "warming":
                self._condition.wait_for(
                    lambda: self._status != "warming"
                )
                return self.snapshot()
            self._status = "warming"
            self._error = None

        started_at = perf_counter()
        try:
            resources = self._builder()
        except Exception as exc:
            duration_seconds = perf_counter() - started_at
            with self._condition:
                self._status = "error"
                self._warmup_seconds = round(duration_seconds, 3)
                self._error = type(exc).__name__
                self._condition.notify_all()
                log_performance(
                    "warmup_ms",
                    duration_seconds * 1000,
                    status="error",
                    error=type(exc).__name__,
                )
                return self.snapshot()

        duration_seconds = perf_counter() - started_at
        with self._condition:
            self._resources = resources
            self._status = "ready"
            self._warmup_seconds = round(duration_seconds, 3)
            self._condition.notify_all()
            log_performance(
                "warmup_ms",
                duration_seconds * 1000,
                status="ready",
            )
            return self.snapshot()

    def get_resources(self):
        """业务请求按需触发一次懒加载。"""
        state = self.warmup()
        if state["status"] != "ready":
            raise RuntimeError("运行时预热失败")
        return self._resources

    def close(self):
        """释放已加载的推荐服务资源。"""
        with self._condition:
            resources = self._resources
        if resources is not None:
            resources.polyvore_service.close()

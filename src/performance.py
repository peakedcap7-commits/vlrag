import json
import logging
from contextlib import contextmanager
from time import perf_counter


logger = logging.getLogger("shopping_qna.performance")
logger.setLevel(logging.INFO)


def log_performance(metric, duration_ms, **context):
    """输出不含密钥和业务正文的结构化性能日志。"""
    payload = {
        "event": "performance",
        "metric": metric,
        "duration_ms": round(float(duration_ms), 3),
        **context,
    }
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


@contextmanager
def measure(metric, **context):
    """测量同步代码块耗时并记录为毫秒。"""
    started_at = perf_counter()
    try:
        yield
    finally:
        log_performance(
            metric,
            (perf_counter() - started_at) * 1000,
            **context,
        )

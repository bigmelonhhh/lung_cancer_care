import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if isinstance(record.msg, dict):
            data: Dict[str, Any] = dict(record.msg)
        else:
            data = {"message": record.getMessage()}

        data.setdefault("level", record.levelname)
        data.setdefault("logger", record.name)

        # time_local 为空或缺失时，自动填充 (本地时间: YYYY-MM-DD HH:MM:SS)
        if not data.get("time_local"):
            now = datetime.now(timezone.utc).astimezone()
            data["time_local"] = now.strftime("%Y-%m-%d %H:%M:%S")

        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(data, ensure_ascii=False)

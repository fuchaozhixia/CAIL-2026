"""Small OpenAI-compatible HTTP client; no SDK or GPU required."""
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .schema import FormatError, require


def decode_response(result):
    """Normalize provider envelope errors into repairable format errors."""
    require(isinstance(result, dict), "模型 API 响应须为 JSON 对象")
    choices = result.get("choices")
    require(isinstance(choices, list) and bool(choices) and isinstance(choices[0], dict), "模型 API 响应缺少有效 choices")
    choice = choices[0]
    require(choice.get("finish_reason") != "length", "模型输出被截断，请提高 --max-tokens")
    message = choice.get("message")
    require(isinstance(message, dict) and isinstance(message.get("content"), str), "模型未返回文本 JSON")
    content = message["content"].strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.I | re.S)
    if fenced:
        content = fenced.group(1)
    try:
        obj = json.loads(content)
    except json.JSONDecodeError as exc:
        raise FormatError("模型返回了无效 JSON") from exc
    require(isinstance(obj, dict), "模型必须返回 JSON 对象")
    return obj


class LLMClient:
    def __init__(self, base_url=None, model=None, timeout=180, retries=2, max_tokens=8192):
        self.base_url = (base_url or os.getenv("CAIL_BASE_URL", "http://127.0.0.1:8000/v1")).rstrip("/")
        self.model = model or os.getenv("CAIL_MODEL")
        if not self.model:
            raise ValueError("请通过 --model 或 CAIL_MODEL 指定模型，并自行确认赛事模型资格")
        self.key = os.getenv("CAIL_API_KEY", "")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("CAIL_BASE_URL 必须为不含账号密码的 http(s) 地址")
        if self.key and parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("远程携带 API key 的请求必须使用 HTTPS")
        if timeout <= 0 or retries < 0 or max_tokens <= 0:
            raise ValueError("timeout/max_tokens 须为正，retries 须非负")
        self.timeout, self.retries, self.max_tokens = timeout, retries, max_tokens
        self.calls = 0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def ask(self, system, prompt, correction=None):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if correction:
            messages.append({"role": "user", "content": "上次输出校验失败，请重新返回完整 JSON。错误：" + correction})
        payload = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": self.max_tokens}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        for attempt in range(self.retries + 1):
            request = Request(self.base_url + "/chat/completions", json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    try:
                        result = json.load(response)
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise FormatError("模型 API 响应不是有效 UTF-8 JSON") from exc
                self.calls += 1
                obj = decode_response(result)
                usage = result.get("usage")
                usage = usage if isinstance(usage, dict) else {}
                for key in self.usage:
                    value = usage.get(key, 0)
                    self.usage[key] += value if type(value) is int and value >= 0 else 0
                return obj
            except HTTPError as exc:
                if exc.code != 429 and exc.code < 500:
                    raise RuntimeError(f"模型 API HTTP {exc.code}，请检查地址、权限和请求参数") from None
                if attempt == self.retries:
                    raise RuntimeError(f"模型 API HTTP {exc.code}，重试后仍失败") from None
            except (URLError, TimeoutError):
                if attempt == self.retries:
                    raise RuntimeError("模型连接失败或超时，请检查服务与 --timeout") from None
            time.sleep(min(2 ** attempt, 8))

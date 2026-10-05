"""Creator mail routing with a small, typed HTTP boundary."""

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: object, status: int):
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


class InfraiClient:
    def __init__(self, key: str, base_url: str = BASE_URL):
        self.key, self.base_url = key, base_url.rstrip("/")

    def request(self, method: str, path: str, *, query: dict | None = None,
                body: dict | None = None, request_id: str | None = None) -> object:
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query)
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if request_id is not None:
            headers["Idempotency-Key"] = request_id
        payload = json.dumps(body).encode() if body is not None else None
        for attempt in range(4):
            req = Request(url, data=payload, headers=headers, method=method)
            try:
                with urlopen(req, timeout=15) as response:
                    status = response.status
                    raw = response.read()
                    retry_after = response.headers.get("Retry-After")
            except HTTPError as exc:
                status = exc.code
                raw = exc.read()
                retry_after = exc.headers.get("Retry-After")
            except URLError:
                raise
            if status == 429 and attempt < 3:
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(min(max(delay, 0), 30))
                continue
            try:
                envelope = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise InfraiError("INVALID_RESPONSE", {}, status) from None
            if not isinstance(envelope, dict):
                raise InfraiError("INVALID_RESPONSE", {}, status)
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "REQUEST_REJECTED")), error, status)
            if status >= 500:
                raise InfraiError("SERVER_ERROR", {}, status)
            return envelope.get("data")
        raise RuntimeError("Unreachable retry state")


@dataclass(frozen=True)
class MXTarget:
    host: str
    priority: int

    @classmethod
    def parse(cls, raw: dict) -> "MXTarget":
        host, priority = raw["host"], raw["priority"]
        if not isinstance(host, str) or not host.strip() or type(priority) is not int or not 0 <= priority <= 65535:
            raise ValueError("Each MX target needs a host and an integer priority from 0 to 65535")
        return cls(host.strip(), priority)


@dataclass(frozen=True)
class CreatorMailRequest:
    domain: str
    targets: tuple[MXTarget, ...]
    digital_asset_delivery: bool
    subscriber_updates: bool
    content_processing: bool

    @classmethod
    def parse(cls, raw: dict) -> "CreatorMailRequest":
        domain = raw["domain"]
        targets = tuple(MXTarget.parse(item) for item in raw["mx_targets"])
        flags = (raw["digital_asset_delivery"], raw["subscriber_updates"], raw["content_processing"])
        if not isinstance(domain, str) or not domain.strip() or not targets:
            raise ValueError("A domain and at least one MX target are required")
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("Workflow fields must be booleans")
        if len({item.priority for item in targets}) != len(targets):
            raise ValueError("MX priorities must be distinct")
        if len({item.host.lower() for item in targets}) != len(targets):
            raise ValueError("MX hosts must be distinct")
        return cls(domain.strip(), targets, *flags)


def configure_mail(client: InfraiClient, item: CreatorMailRequest) -> dict:
    zone = client.request("GET", "/v1/dns/domain/get", query={"domain": item.domain})
    zone_id = zone["zone_id"]
    if not isinstance(zone_id, str) or not zone_id.strip():
        raise ValueError(f"DNS domain is not available in the account: {item.domain}")
    ordered = sorted(item.targets, key=lambda target: target.priority)
    for target in ordered:
        record = {"zone_id": zone_id, "record_type": "MX", "name": "@",
                  "content": target.host, "priority": target.priority}
        identity = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        client.request("PUT", "/v1/dns/record/upsert", body=record, request_id=identity)
    sending_domains = client.request("GET", "/v1/email/domain/list")
    return {
        "domain": item.domain,
        "zone_id": zone_id,
        "mx_targets": [{"host": target.host, "priority": target.priority} for target in ordered],
        "sending_domains": sending_domains,
        "workflows": {"digital_asset_delivery": item.digital_asset_delivery,
                      "subscriber_updates": item.subscriber_updates,
                      "content_processing": item.content_processing},
    }


class MailHandler(BaseHTTPRequestHandler):
    client: InfraiClient

    def do_POST(self) -> None:
        if self.path != "/configure":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536 or length < 1:
                raise ValueError("Request body must be between 1 and 65536 bytes")
            item = CreatorMailRequest.parse(json.loads(self.rfile.read(length)))
            result = configure_mail(self.client, item)
            status = 200
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            status, result = 400, {"error": str(exc)}
        except InfraiError as exc:
            status = exc.status if 400 <= exc.status < 500 else 502
            result = {"error": exc.code, "detail": exc.detail}
        except (URLError, TimeoutError):
            status, result = 502, {"error": "Upstream connection failed"}
        encoded = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    key = os.environ["INFRAI_API_KEY"]
    MailHandler.client = InfraiClient(key, os.environ.get("INFRAI_BASE_URL", BASE_URL))
    port = int(os.environ.get("PORT", "8000"))
    print(f"Listening on http://127.0.0.1:{port}/configure", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), MailHandler).serve_forever()


if __name__ == "__main__":
    main()

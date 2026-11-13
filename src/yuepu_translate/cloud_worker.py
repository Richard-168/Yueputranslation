"""One killable HTTPS request. Credentials enter only via an anonymous pipe."""

import json
import ssl
import sys
import urllib.error
import urllib.request

from .cloud_protocol import MAX_INPUT, MAX_RESPONSE, CloudError, decode_request, response_text


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CloudError("redirect")


def perform(raw, opener=None):
    config, body = decode_request(raw)
    # No proxy environment, cookies, redirects, automatic retry or certificate bypass.
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(
        config.endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + config.api_key},
        method="POST",
    )
    try:
        with opener.open(request, timeout=config.timeout) as response:
            return response_text(
                response.read(MAX_RESPONSE + 1),
                "asr" if body["model"] == "qwen3-asr-flash" else "translation",
            )
    except urllib.error.HTTPError as exc:
        code = (
            "auth"
            if exc.code in {401, 403}
            else "quota"
            if exc.code in {402, 429}
            else "server"
            if exc.code >= 500
            else "request"
        )
        exc.close()
        raise CloudError(code) from None
    except (TimeoutError, OSError, urllib.error.URLError) as exc:
        code = (
            "timeout"
            if isinstance(exc, TimeoutError)
            or isinstance(getattr(exc, "reason", None), TimeoutError)
            else "network"
        )
        raise CloudError(code) from None


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        text = perform(raw)
        result = dict(ok=True, text=text)
    except CloudError as exc:
        result = dict(ok=False, code=exc.code)
    except Exception:
        # Never expose the key, payload, server response or exception repr.
        result = dict(ok=False, code="request")
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

"""Response policies for the API and HTML served by the isolated QA server."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import iterate_in_threadpool
import secrets


HTML_CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'nonce-{nonce}'; "
    "font-src 'self'; img-src 'self' data: blob:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "frame-ancestors 'none'; form-action 'self'"
)
JSON_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
    "style-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        html = "text/html" in response.headers.get("content-type", "")
        policy = DOCS_CSP if request.url.path in {"/docs", "/redoc", "/docs/oauth2-redirect"} else HTML_CSP
        response.headers.setdefault(
            "Cross-Origin-Embedder-Policy", "unsafe-none" if policy == DOCS_CSP else "require-corp",
        )
        if html:
            nonce = secrets.token_urlsafe(24)
            if request.method != "HEAD":
                content = b"".join([chunk async for chunk in response.body_iterator])
                content = content.replace(b"__CSP_NONCE__", nonce.encode())
                if policy == DOCS_CSP:
                    # FastAPI's own documentation bootstrap is trusted static HTML.
                    content = content.replace(b"<script>", f'<script nonce="{nonce}">'.encode())
                    content = content.replace(b"<style>", f'<style nonce="{nonce}">'.encode())
                response.body_iterator = iterate_in_threadpool(iter([content]))
                response.headers["Content-Length"] = str(len(content))
            response.headers.setdefault("Content-Security-Policy", policy.format(nonce=nonce))
        else:
            response.headers.setdefault("Content-Security-Policy", JSON_CSP)
        if request.url.path.startswith(("/api/", "/health")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        elif html:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

from fastapi import Request

def get_client_ip(request: Request) -> str:
    # Respect common proxy headers (ngrok, Cloudflare, etc.)
    for header in ("x-forwarded-for", "x-real-ip", "cf-connecting-ip"):
        if header in request.headers:
            return request.headers[header].split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

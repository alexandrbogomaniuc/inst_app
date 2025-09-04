from fastapi import Request

def client_ip(request: Request) -> str:
    # honor reverse proxies
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""

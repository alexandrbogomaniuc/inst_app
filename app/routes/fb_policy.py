from fastapi import APIRouter, Request

router = APIRouter(prefix="/fb", tags=["meta-policy"])

@router.post("/deauth")
def deauthorize(request: Request):
    return {"status": "received"}

@router.post("/delete")
def delete_data(request: Request):
    return {"status": "received", "url": str(request.url)}

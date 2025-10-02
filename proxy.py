# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "httpx",
#     "starlette",
#     "uvicorn",
#     "uvloop",
# ]
# ///
import logging

from httpx import AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.DEBUG)


client = AsyncClient()
app = Starlette()


@app.route("/39038/appinfo_v2")
async def appinfo_v2(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "Os": "Linux",
            "Kernel": "Linux",
            "VendorOs": "linux",
            "VendorOs": "linux",
            "CurrentVersion": "3.2.19-39038",
            "PtVersion": "2.0.0",
            "SsoVersion": 19,
            "PackageName": "com.tencent.qq",
            "ApkSignatureMd5": "Y29tLnRlbmNlbnQucXE=",
            "SdkInfo": {
                "SdkBuildTime": 0,
                "SdkVersion": "nt.wtlogin.0.0.1",
                "MiscBitMap": 32764,
                "SubSigMap": 0,
                "MainSigMap": 169742560,
            },
            "AppId": 1600001615,
            "SubAppId": 537313942,
            "AppClientVersion": 39038,
        }
    )


@app.route("/39038", ["GET", "POST"])
async def _(request: Request) -> Response:
    response = await client.request(
        method=request.method,
        url=f"http://103.217.204.57:39038/sign",
        headers={key: value for key, value in request.headers.items() if key != "host"},
        params=request.query_params,
        content=await request.body(),
    )
    return Response(response.read(), response.status_code, response.headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0")

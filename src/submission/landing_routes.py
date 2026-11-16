from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def install_landing(app: FastAPI) -> None:
    static = Path(__file__).parent / "static"
    app.mount("/landing-assets", StaticFiles(directory=static / "landing", check_dir=False))
    app.mount("/brand-assets", StaticFiles(directory=static / "brand", check_dir=False))

    @app.get("/", include_in_schema=False)
    def introduction() -> FileResponse:
        return FileResponse(
            static / "landing/index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

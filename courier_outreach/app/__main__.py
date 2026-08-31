"""Run the console:  python -m courier_outreach.app"""

if __name__ == "__main__":
    import uvicorn

    from ..config import Config
    from .server import build_default_app

    cfg = Config.load()
    uvicorn.run(build_default_app(), host=cfg.app_host, port=cfg.app_port)

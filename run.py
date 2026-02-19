import uvicorn
from emtulli.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "emtulli.app:create_app",
        factory=True,
        host=settings.emtulli_host,
        port=settings.emtulli_port,
        reload=True,
    )

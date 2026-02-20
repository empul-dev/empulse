import uvicorn
from empulse.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "empulse.app:create_app",
        factory=True,
        host=settings.empulse_host,
        port=settings.empulse_port,
        reload=True,
    )

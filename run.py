import os
import uvicorn
from empulse.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "empulse.app:create_app",
        factory=True,
        host=settings.empulse_host,
        port=int(os.getenv("PORT", settings.empulse_port)),
        reload=os.getenv("EMPULSE_DEV", "").lower() in ("1", "true"),
    )

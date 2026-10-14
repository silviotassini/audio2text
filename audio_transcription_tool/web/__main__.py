import logging
import os

import uvicorn

from .app import app

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")
    # Dentro do container escuta em todas as interfaces do container; o lançador publica
    # a porta só em 127.0.0.1 no computador do perito.
    uvicorn.run(
        app,
        host=os.environ.get("AT_WEB_HOST", "0.0.0.0"),
        port=int(os.environ.get("AT_WEB_PORTA", "8000")),
        log_level="warning",
        access_log=False,
    )

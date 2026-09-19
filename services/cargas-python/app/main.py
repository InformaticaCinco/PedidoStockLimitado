import logging
import uvicorn
from app.api.http import create_app
from app.config import Settings


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    for name in ('httpx', 'httpcore', 'pymongo', 'python_multipart'):
        logging.getLogger(name).setLevel(logging.ERROR)
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host='0.0.0.0', port=settings.port, access_log=False)


if __name__ == '__main__':
    main()

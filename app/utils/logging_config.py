import logging
from logging.handlers import RotatingFileHandler

from app.utils.paths import user_data_path


def configure_logging() -> None:
    directory = user_data_path() / "logs"
    directory.mkdir(exist_ok=True)
    handler = RotatingFileHandler(directory / "qingyu.log", maxBytes=1_000_000,
                                  backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("qingyu")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

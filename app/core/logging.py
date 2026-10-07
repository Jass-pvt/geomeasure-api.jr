import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
ROOT_LOGGER_NAME = "geomeasure"


def configure_logging(level: str) -> None:
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
        logger.propagate = False

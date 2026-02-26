"""로깅 설정 — loguru 기반."""

import sys
from pathlib import Path
from loguru import logger


def setup_logger(config: dict):
    """config 기반으로 loguru 설정."""
    log_level = config.get("server", {}).get("log_level", "INFO")

    # 기본 핸들러 제거 후 재설정
    logger.remove()

    # 콘솔 출력
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # 파일 로그 (일별 로테이션)
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "livecat_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
    )

    # 이벤트 전용 로그 (하이라이트, 업로드 등)
    logger.add(
        log_dir / "events_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation="00:00",
        retention="90 days",
        filter=lambda record: "event" in record["extra"],
        encoding="utf-8",
    )

    logger.info(f"Logger initialized — level={log_level}")

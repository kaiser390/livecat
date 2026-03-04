"""Claude API 기반 타이틀 생성 모듈.

이벤트 메타데이터를 Claude Haiku에 전달하여
플랫폼별 최적화된 타이틀 후보 5개를 생성한다.
API 실패 시 템플릿 기반 폴백을 제공한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import anthropic
except ImportError:
    anthropic = None
    logger.warning("anthropic SDK not installed — title generation will use fallback")

try:
    import diskcache
except ImportError:
    diskcache = None
    logger.warning("diskcache not installed — title caching disabled")


# 프로젝트 루트
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class TitleGenerator:
    """Claude Haiku를 사용하여 이벤트 기반 타이틀을 생성한다.

    - 플랫폼별 프롬프트 템플릿 로드 (config/prompts/title_{platform}.md)
    - 메타데이터로 프롬프트 채우기 (event_type, cats, time_of_day)
    - Claude API 호출 → 응답 파싱 → 타이틀 후보 5개 반환
    - API 실패 시 내장 템플릿 폴백
    - diskcache 기반 결과 캐싱
    """

    # Event type → English keyword
    EVENT_KO: dict[str, str] = {
        "climb": "climbing",
        "jump": "jumping",
        "run": "running",
        "interact": "playtime",
        "hunt_attempt": "hunting",
        "sleep": "napping",
        "groom": "grooming",
        "sunbathe": "sunbathing",
        "fail": "fail",
    }

    # Cat ID → display name
    CAT_DISPLAY: dict[str, str] = {
        "nana": "Nana",
        "toto": "Toto",
    }

    TIME_PERIODS: dict[str, str] = {
        "morning": "morning",
        "afternoon": "afternoon",
        "evening": "evening",
        "night": "night",
    }

    def __init__(self, config: dict) -> None:
        self._config = config
        llm_cfg = config.get("llm", {})

        self._model: str = llm_cfg.get("model", "claude-haiku-4-5-20251001")
        self._max_tokens: int = llm_cfg.get("max_tokens", 500)
        self._num_candidates: int = llm_cfg.get("title_candidates", 5)
        self._prompts_dir = _ROOT_DIR / llm_cfg.get("prompts_dir", "config/prompts")

        # Anthropic 클라이언트 (지연 초기화)
        self._client: Any | None = None

        # 캐시 (diskcache)
        self._cache: Any | None = None
        self._cache_ttl: int = 3600  # 1시간
        self._init_cache()

        logger.info(
            f"TitleGenerator initialized — "
            f"model={self._model}, candidates={self._num_candidates}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        metadata: dict,
        platform: str = "youtube",
    ) -> list[str]:
        """메타데이터 기반으로 타이틀 후보를 생성한다.

        Args:
            metadata: 클립 메타데이터 (event_type, cats, timestamp 등).
            platform: 대상 플랫폼 ("youtube", "tiktok", "shorts").

        Returns:
            타이틀 후보 리스트 (최대 5개).
        """
        # 캐시 확인
        cache_key = self._make_cache_key(metadata, platform)
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.debug(f"Title cache hit: {cache_key[:16]}...")
            return cached

        # Claude API 시도
        titles = await self._generate_via_api(metadata, platform)

        if not titles:
            # 폴백: 템플릿 기반 생성
            logger.warning("API generation failed — using fallback templates")
            titles = self._generate_fallback(metadata, platform)

        # 캐시 저장
        self._set_cached(cache_key, titles)

        return titles

    # ------------------------------------------------------------------
    # Claude API Generation
    # ------------------------------------------------------------------

    async def _generate_via_api(
        self,
        metadata: dict,
        platform: str,
    ) -> list[str]:
        """Claude Haiku API를 호출하여 타이틀을 생성한다."""
        if anthropic is None:
            return []

        client = self._get_client()
        if client is None:
            return []

        # 프롬프트 로드 및 채우기
        prompt = self._build_prompt(metadata, platform)
        if not prompt:
            return []

        try:
            # anthropic SDK는 동기이므로 executor에서 실행
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                self._call_api,
                client,
                prompt,
            )

            if response is None:
                return []

            # 응답 파싱
            titles = self._parse_response(response)
            logger.info(
                f"Generated {len(titles)} title candidates via API [{platform}]"
            )
            return titles

        except Exception as e:
            logger.error(f"Claude API call failed: {e}")
            return []

    def _call_api(self, client: Any, prompt: str) -> str | None:
        """동기 API 호출 (executor에서 실행)."""
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"API request error: {e}")
            return None

    # ------------------------------------------------------------------
    # Prompt Building
    # ------------------------------------------------------------------

    def _build_prompt(self, metadata: dict, platform: str) -> str:
        """프롬프트 템플릿을 로드하고 메타데이터로 채운다."""
        # 플랫폼별 프롬프트 파일
        platform_key = "tiktok" if platform in ("tiktok", "shorts") else "youtube"
        prompt_path = self._prompts_dir / f"title_{platform_key}.md"

        if not prompt_path.exists():
            logger.warning(f"Prompt template not found: {prompt_path}")
            return ""

        try:
            template = prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read prompt template: {e}")
            return ""

        # 메타데이터 추출
        event_type = metadata.get("event_type", "unknown")
        cats_raw = metadata.get("cats", [])
        timestamp = metadata.get("timestamp", "")

        # 고양이 이름 변환
        cats_display = ", ".join(
            self.CAT_DISPLAY.get(c, c) for c in cats_raw
        ) or "나나, 토토"

        # 시간대 추출
        time_of_day = self._get_time_of_day(timestamp)

        # 이벤트 한글명
        event_ko = self.EVENT_KO.get(event_type, event_type)

        # 프롬프트 채우기
        prompt = template.format(
            event_type=event_ko,
            cats=cats_display,
            time_of_day=time_of_day,
            duration=metadata.get("duration_sec", 20),
        )

        return prompt

    # ------------------------------------------------------------------
    # Response Parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response_text: str) -> list[str]:
        """Claude 응답에서 타이틀 후보를 파싱한다.

        각 줄을 타이틀 후보로 간주하고, 번호/특수문자 접두사를 제거한다.
        """
        lines = response_text.strip().split("\n")
        titles = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 번호 접두사 제거: "1. ", "1) ", "- " 등
            cleaned = line
            for prefix_pattern in [".", ")", ":", "-"]:
                parts = cleaned.split(prefix_pattern, 1)
                if len(parts) == 2 and parts[0].strip().isdigit():
                    cleaned = parts[1].strip()
                    break

            # 앞뒤 따옴표 제거
            cleaned = cleaned.strip('"').strip("'").strip()

            # 서문/메타 텍스트 필터 ("~입니다:", "~있습니다:", "~드립니다:" 등)
            if cleaned and any(
                cleaned.endswith(suf)
                for suf in ("입니다:", "있습니다:", "드립니다:", "하겠습니다:", "보세요:")
            ):
                continue

            if cleaned:
                titles.append(cleaned)

        # 최대 후보 수 제한
        return titles[: self._num_candidates]

    # ------------------------------------------------------------------
    # Fallback Template Generation
    # ------------------------------------------------------------------

    def _generate_fallback(
        self,
        metadata: dict,
        platform: str,
    ) -> list[str]:
        """API 실패 시 내장 템플릿으로 타이틀을 생성한다."""
        event_type = metadata.get("event_type", "unknown")
        cats_raw = metadata.get("cats", [])

        cats_str = " & ".join(
            self.CAT_DISPLAY.get(c, c) for c in cats_raw
        ) or "Nana & Toto"

        event_en = self.EVENT_KO.get(event_type, "daily life")

        if platform in ("tiktok", "shorts"):
            templates = [
                f"{cats_str} {event_en} moment! #cat #shorts",
                f"This is what cats do... {cats_str} {event_en} #catlife",
                f"Watch {cats_str} {event_en}! #outdoorcat #shorts",
                f"Outdoor cats {cats_str} real {event_en} #cat",
                f"{cats_str} {event_en} is too cute #catlife #shorts",
            ]
        else:
            templates = [
                f"[Cat Daily] {cats_str}'s {event_en} moment!",
                f"{cats_str} {event_en}?! Outdoor Cat Vlog",
                f"Outdoor Cats {cats_str} - Today's {event_en}",
                f"{cats_str} {event_en} compilation | Cat Life",
                f"Cute {cats_str} {event_en} caught on camera!",
            ]

        random.shuffle(templates)
        return templates[: self._num_candidates]

    # ------------------------------------------------------------------
    # Time Helpers
    # ------------------------------------------------------------------

    def _get_time_of_day(self, timestamp: str) -> str:
        """타임스탬프에서 시간대를 추출한다."""
        try:
            if isinstance(timestamp, str) and timestamp:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                dt = datetime.now()

            hour = dt.hour
            if 5 <= hour < 12:
                return self.TIME_PERIODS["morning"]
            elif 12 <= hour < 17:
                return self.TIME_PERIODS["afternoon"]
            elif 17 <= hour < 21:
                return self.TIME_PERIODS["evening"]
            else:
                return self.TIME_PERIODS["night"]
        except Exception:
            return "afternoon"

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _init_cache(self) -> None:
        """diskcache 초기화."""
        if diskcache is None:
            return

        try:
            cache_dir = _ROOT_DIR / ".cache" / "titles"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache = diskcache.Cache(str(cache_dir))
            logger.debug(f"Title cache initialized: {cache_dir}")
        except Exception as e:
            logger.warning(f"Failed to initialize title cache: {e}")
            self._cache = None

    def _make_cache_key(self, metadata: dict, platform: str) -> str:
        """메타데이터 + 플랫폼으로 캐시 키를 생성한다."""
        event_type = metadata.get("event_type", "")
        cats = tuple(sorted(metadata.get("cats", [])))
        raw = f"{event_type}|{cats}|{platform}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> list[str] | None:
        """캐시에서 타이틀을 조회한다."""
        if self._cache is None:
            return None
        try:
            return self._cache.get(key)
        except Exception:
            return None

    def _set_cached(self, key: str, titles: list[str]) -> None:
        """타이틀을 캐시에 저장한다."""
        if self._cache is None:
            return
        try:
            self._cache.set(key, titles, expire=self._cache_ttl)
        except Exception as e:
            logger.debug(f"Cache set failed: {e}")

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def _get_client(self) -> Any | None:
        """Anthropic 클라이언트를 반환한다 (지연 초기화)."""
        if anthropic is None:
            return None

        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
                logger.debug("Anthropic client initialized")
            except Exception as e:
                logger.error(f"Failed to create Anthropic client: {e}")
                return None

        return self._client

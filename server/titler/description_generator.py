"""YouTube 설명(Description) 생성 모듈.

Claude Haiku를 사용하여 이벤트 메타데이터 기반으로
200~500자의 YouTube 설명문을 자동 생성한다.
고양이 소개, SEO 키워드, 구독 유도 문구를 포함한다.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import anthropic
except ImportError:
    anthropic = None
    logger.warning("anthropic SDK not installed — description generation will use fallback")

# 프로젝트 루트
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class DescriptionGenerator:
    """Claude Haiku로 YouTube 영상 설명을 생성한다.

    - config/prompts/description.md 템플릿 사용
    - 메타데이터 기반 프롬프트 구성
    - 200~500자 설명문 생성 (고양이 소개 + SEO + CTA)
    - API 실패 시 내장 템플릿 폴백
    """

    # 이벤트 타입 → 한글
    EVENT_KO: dict[str, str] = {
        "climb": "나무등반",
        "jump": "점프",
        "run": "달리기",
        "interact": "함께 놀기",
        "hunt_attempt": "사냥",
        "sleep": "낮잠",
        "groom": "그루밍",
        "sunbathe": "일광욕",
        "fail": "실패",
    }

    CAT_DISPLAY: dict[str, str] = {
        "nana": "나나",
        "toto": "토토",
    }

    CAT_INTRO: dict[str, str] = {
        "nana": "호랑이 무늬의 활발한 나나(Nana)",
        "toto": "턱시도 무늬의 영리한 토토(Toto)",
    }

    def __init__(self, config: dict) -> None:
        self._config = config
        llm_cfg = config.get("llm", {})

        self._model: str = llm_cfg.get("model", "claude-haiku-4-5-20251001")
        self._max_tokens: int = llm_cfg.get("max_tokens", 500)
        self._prompts_dir = _ROOT_DIR / llm_cfg.get("prompts_dir", "config/prompts")

        self._client: Any | None = None

        logger.info(
            f"DescriptionGenerator initialized — model={self._model}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        metadata: dict,
        platform: str = "youtube",
    ) -> str:
        """메타데이터 기반으로 영상 설명문을 생성한다.

        Args:
            metadata: 클립 메타데이터.
            platform: 대상 플랫폼.

        Returns:
            설명 문자열 (200~500자).
        """
        description = await self._generate_via_api(metadata, platform)

        if not description:
            logger.warning("API description generation failed — using fallback")
            description = self._generate_fallback(metadata, platform)

        return description

    # ------------------------------------------------------------------
    # Claude API Generation
    # ------------------------------------------------------------------

    async def _generate_via_api(
        self,
        metadata: dict,
        platform: str,
    ) -> str:
        """Claude Haiku API를 호출하여 설명문을 생성한다."""
        if anthropic is None:
            return ""

        client = self._get_client()
        if client is None:
            return ""

        prompt = self._build_prompt(metadata, platform)
        if not prompt:
            return ""

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                self._call_api,
                client,
                prompt,
            )

            if response:
                logger.info(
                    f"Description generated via API [{platform}] "
                    f"({len(response)} chars)"
                )
            return response or ""

        except Exception as e:
            logger.error(f"Description API call failed: {e}")
            return ""

    def _call_api(self, client: Any, prompt: str) -> str | None:
        """동기 API 호출."""
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            return text
        except Exception as e:
            logger.error(f"API request error: {e}")
            return None

    # ------------------------------------------------------------------
    # Prompt Building
    # ------------------------------------------------------------------

    def _build_prompt(self, metadata: dict, platform: str) -> str:
        """description.md 템플릿을 로드하고 메타데이터로 채운다."""
        prompt_path = self._prompts_dir / "description.md"

        if not prompt_path.exists():
            logger.warning(f"Description prompt not found: {prompt_path}")
            return ""

        try:
            template = prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read description prompt: {e}")
            return ""

        event_type = metadata.get("event_type", "unknown")
        cats_raw = metadata.get("cats", [])
        timestamp = metadata.get("timestamp", "")
        duration = metadata.get("duration_sec", 20)

        cats_display = ", ".join(
            self.CAT_DISPLAY.get(c, c) for c in cats_raw
        ) or "나나, 토토"

        time_of_day = self._get_time_of_day(timestamp)
        event_ko = self.EVENT_KO.get(event_type, event_type)

        prompt = template.format(
            event_type=event_ko,
            cats=cats_display,
            time_of_day=time_of_day,
            duration=duration,
        )

        return prompt

    # ------------------------------------------------------------------
    # Fallback Template
    # ------------------------------------------------------------------

    def _generate_fallback(
        self,
        metadata: dict,
        platform: str,
    ) -> str:
        """API 실패 시 내장 템플릿으로 설명문을 생성한다."""
        event_type = metadata.get("event_type", "unknown")
        cats_raw = metadata.get("cats", [])

        event_ko = self.EVENT_KO.get(event_type, "일상")

        # 등장 고양이 소개
        cat_intros = []
        for c in cats_raw:
            intro = self.CAT_INTRO.get(c)
            if intro:
                cat_intros.append(intro)

        if not cat_intros:
            cat_intros = [
                self.CAT_INTRO["nana"],
                self.CAT_INTRO["toto"],
            ]

        cats_intro_str = "과 ".join(cat_intros)

        # 이벤트별 서두
        opening_lines = {
            "climb": "오늘도 나무등반에 도전하는 용감한 마당 고양이!",
            "jump": "놀라운 점프력! 역시 고양이는 운동 천재!",
            "run": "전력 질주하는 모습을 포착했어요!",
            "interact": "두 고양이가 함께 노는 귀여운 순간!",
            "hunt_attempt": "야생의 본능이 깨어나는 순간!",
            "sleep": "세상에서 제일 평화로운 꿀잠 타임",
            "groom": "그루밍하는 모습도 이렇게 귀여울 수가",
        }

        opening = opening_lines.get(event_type, f"마당 고양이의 {event_ko} 일상!")

        # 구독 유도 (CTA)
        cta_options = [
            "좋아요와 구독 부탁드려요!",
            "구독하고 나나 & 토토의 일상을 함께해요!",
            "좋아요 누르고 다음 영상도 기대해주세요!",
        ]
        cta = random.choice(cta_options)

        if platform in ("tiktok", "shorts"):
            description = (
                f"{opening}\n\n"
                f"{cats_intro_str}의 {event_ko} 순간을 담았어요.\n\n"
                f"팔로우하고 매일 귀여운 고양이 영상 받아보세요!"
            )
        else:
            description = (
                f"{opening}\n\n"
                f"마당에 사는 {cats_intro_str}의 리얼한 일상을 담았습니다.\n"
                f"매일 올라오는 고양이 영상, 놓치지 마세요!\n\n"
                f"#고양이 #마당고양이 #catlife #고양이일상\n\n"
                f"{cta}"
            )

        return description

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_time_of_day(self, timestamp: str) -> str:
        """타임스탬프 → 시간대 한글 변환."""
        try:
            if isinstance(timestamp, str) and timestamp:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                dt = datetime.now()

            hour = dt.hour
            if 5 <= hour < 12:
                return "아침"
            elif 12 <= hour < 17:
                return "오후"
            elif 17 <= hour < 21:
                return "저녁"
            else:
                return "밤"
        except Exception:
            return "오후"

    def _get_client(self) -> Any | None:
        """Anthropic 클라이언트 지연 초기화."""
        if anthropic is None:
            return None

        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
                logger.debug("Anthropic client initialized (DescriptionGenerator)")
            except Exception as e:
                logger.error(f"Failed to create Anthropic client: {e}")
                return None

        return self._client

"""해시태그 자동 생성 모듈.

이벤트 유형, 등장 고양이, 플랫폼에 따라
한국어 + 영어 해시태그를 생성한다.
"""

from __future__ import annotations

from loguru import logger


class HashtagGenerator:
    """이벤트 메타데이터 기반으로 플랫폼별 해시태그를 생성한다.

    구성:
        - 기본 해시태그 (한글 + 영어): 항상 포함
        - 이벤트별 해시태그: 이벤트 유형에 따라 추가
        - 고양이별 해시태그: 등장 고양이에 따라 추가
        - 플랫폼 최적화: YouTube 태그 (최대 500자), TikTok 인라인 해시태그
    """

    # 기본 해시태그 풀
    BASE_HASHTAGS: dict[str, list[str]] = {
        "ko": [
            "#고양이",
            "#캣스타그램",
            "#고양이일상",
            "#냥스타그램",
            "#마당고양이",
        ],
        "en": [
            "#cat",
            "#catsofinstagram",
            "#catlife",
            "#outdoorcat",
            "#catvideo",
        ],
    }

    # 이벤트별 추가 해시태그
    EVENT_HASHTAGS: dict[str, list[str]] = {
        "climb": ["#캣타워", "#나무등반", "#고양이운동", "#catclimbing"],
        "jump": ["#고양이점프", "#catjump", "#슈퍼캣"],
        "run": ["#고양이달리기", "#zoomies", "#catrun"],
        "interact": ["#고양이친구", "#멀티캣", "#catfriends"],
        "hunt_attempt": ["#사냥본능", "#고양이사냥", "#cathunting"],
        "sleep": ["#고양이낮잠", "#힐링", "#catsleeping", "#lofi"],
        "groom": ["#고양이그루밍", "#catgrooming", "#힐링"],
        "sunbathe": ["#일광욕", "#고양이일광욕", "#sunbathing"],
        "fail": ["#고양이실패", "#catfail", "#웃긴고양이", "#funnycat"],
    }

    # 고양이별 해시태그
    CAT_HASHTAGS: dict[str, list[str]] = {
        "nana": ["#나나", "#호랑이고양이", "#태비", "#tabbycat"],
        "toto": ["#토토", "#턱시도고양이", "#tuxedocat"],
    }

    # 플랫폼별 제한
    YOUTUBE_MAX_CHARS: int = 500
    YOUTUBE_MAX_TAGS: int = 30
    TIKTOK_MAX_TAGS: int = 15

    def __init__(self, config: dict) -> None:
        self._config = config

        # 고양이 프로필에서 추가 해시태그 로드
        cats_cfg = config.get("cats", {})
        for cat_key, profile in cats_cfg.items():
            hashtags_ko = profile.get("hashtags_ko", [])
            hashtags_en = profile.get("hashtags_en", [])
            all_tags = hashtags_ko + hashtags_en

            # config에 있으면 CAT_HASHTAGS 업데이트
            if all_tags:
                existing = set(self.CAT_HASHTAGS.get(cat_key, []))
                for tag in all_tags:
                    if tag not in existing:
                        self.CAT_HASHTAGS.setdefault(cat_key, []).append(tag)
                        existing.add(tag)

        logger.info(
            f"HashtagGenerator initialized — "
            f"base={len(self.BASE_HASHTAGS['ko']) + len(self.BASE_HASHTAGS['en'])}, "
            f"event_types={len(self.EVENT_HASHTAGS)}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        metadata: dict,
        platform: str = "youtube",
    ) -> list[str]:
        """메타데이터 기반 해시태그를 생성한다.

        Args:
            metadata: 클립 메타데이터 (event_type, cats 등).
            platform: 대상 플랫폼 ("youtube", "tiktok", "shorts").

        Returns:
            해시태그 리스트 (# 포함).
        """
        event_type = metadata.get("event_type", "unknown")
        cats = metadata.get("cats", [])

        # 1. 기본 해시태그
        tags: list[str] = []
        tags.extend(self.BASE_HASHTAGS["ko"])
        tags.extend(self.BASE_HASHTAGS["en"])

        # 2. 이벤트별 해시태그
        event_tags = self.EVENT_HASHTAGS.get(event_type, [])
        tags.extend(event_tags)

        # 3. 고양이별 해시태그
        for cat in cats:
            cat_tags = self.CAT_HASHTAGS.get(cat, [])
            tags.extend(cat_tags)

        # 4. 중복 제거 (순서 유지)
        tags = self._deduplicate(tags)

        # 5. # 접두사 보장
        tags = [t if t.startswith("#") else f"#{t}" for t in tags]

        # 6. 플랫폼별 최적화
        if platform in ("tiktok", "shorts"):
            tags = self._optimize_tiktok(tags)
        else:
            tags = self._optimize_youtube(tags)

        logger.debug(
            f"Generated {len(tags)} hashtags [{platform}] "
            f"for event={event_type}, cats={cats}"
        )

        return tags

    # ------------------------------------------------------------------
    # Platform Optimization
    # ------------------------------------------------------------------

    def _optimize_youtube(self, tags: list[str]) -> list[str]:
        """YouTube 태그 최적화: 최대 30개, 총 500자."""
        # 태그 수 제한
        tags = tags[: self.YOUTUBE_MAX_TAGS]

        # 총 문자 수 제한 (쉼표 구분자 포함)
        result = []
        total_chars = 0

        for tag in tags:
            # YouTube 태그에서는 # 제거하여 계산
            clean_tag = tag.lstrip("#")
            tag_chars = len(clean_tag)

            # 구분자(, ) 포함 길이
            separator = 2 if result else 0
            if total_chars + tag_chars + separator > self.YOUTUBE_MAX_CHARS:
                break

            result.append(tag)
            total_chars += tag_chars + separator

        return result

    def _optimize_tiktok(self, tags: list[str]) -> list[str]:
        """TikTok 해시태그 최적화: 인라인 해시태그, 최대 15개."""
        return tags[: self.TIKTOK_MAX_TAGS]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(tags: list[str]) -> list[str]:
        """중복 제거 (순서 유지, 대소문자 무시)."""
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            normalized = tag.lower()
            if normalized not in seen:
                seen.add(normalized)
                result.append(tag)
        return result

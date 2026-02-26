"""SEO 키워드 최적화 모듈.

해시태그와 태그를 중복 제거, 길이 제한, 우선순위 정렬하여
플랫폼별 SEO에 최적화된 태그 목록을 반환한다.
트렌딩 키워드 제안 기능 포함.
"""

from __future__ import annotations

from loguru import logger


class SEOOptimizer:
    """태그/키워드를 SEO 관점에서 최적화한다.

    - 중복 제거 (대소문자 무시)
    - 플랫폼별 길이 제한 (YouTube: 30태그, 500자 / TikTok: 인라인)
    - 우선순위 정렬: 핵심 키워드 → 이벤트 키워드 → 일반 키워드
    - 이벤트 유형별 트렌딩 키워드 제안
    """

    # YouTube SEO 제한
    YOUTUBE_MAX_TAGS: int = 30
    YOUTUBE_MAX_CHARS: int = 500

    # TikTok 제한
    TIKTOK_MAX_TAGS: int = 15
    TIKTOK_MAX_CAPTION_CHARS: int = 2200

    # 핵심 키워드 (항상 최우선)
    PRIORITY_KEYWORDS: list[str] = [
        "고양이",
        "cat",
        "마당고양이",
        "outdoor cat",
        "고양이일상",
        "cat daily life",
        "나나",
        "토토",
    ]

    # 이벤트별 트렌딩 키워드 추천
    TRENDING_KEYWORDS: dict[str, list[str]] = {
        "climb": [
            "고양이 나무등반",
            "cat climbing tree",
            "고양이 운동",
            "cat exercise",
            "고양이 모험",
            "adventurous cat",
        ],
        "jump": [
            "고양이 점프",
            "cat jumping",
            "슈퍼점프",
            "amazing cat jump",
            "고양이 능력",
            "athletic cat",
        ],
        "run": [
            "고양이 달리기",
            "cat running",
            "zoomies",
            "cat zoomies",
            "고양이 전력질주",
            "fast cat",
        ],
        "interact": [
            "고양이 친구",
            "cat friends",
            "두마리 고양이",
            "multi cat",
            "고양이 사이좋게",
            "cats playing together",
        ],
        "hunt_attempt": [
            "고양이 사냥",
            "cat hunting",
            "사냥 본능",
            "hunting instinct",
            "야생 고양이",
            "wild cat instinct",
        ],
        "sleep": [
            "고양이 수면",
            "cat sleeping",
            "힐링 영상",
            "healing video",
            "고양이 ASMR",
            "cat ASMR",
            "lofi cat",
        ],
        "groom": [
            "고양이 그루밍",
            "cat grooming",
            "셀프 그루밍",
            "self grooming cat",
        ],
        "sunbathe": [
            "고양이 일광욕",
            "cat sunbathing",
            "햇살 고양이",
            "sunny cat",
        ],
        "fail": [
            "웃긴 고양이",
            "funny cat",
            "고양이 실수",
            "cat fail",
            "고양이 리액션",
            "cat reaction",
        ],
    }

    def __init__(self, config: dict) -> None:
        self._config = config

        logger.info(
            f"SEOOptimizer initialized — "
            f"priority_keywords={len(self.PRIORITY_KEYWORDS)}, "
            f"trending_types={len(self.TRENDING_KEYWORDS)}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize_tags(
        self,
        tags: list[str],
        platform: str = "youtube",
    ) -> list[str]:
        """태그 리스트를 SEO 최적화하여 반환한다.

        Args:
            tags: 원본 태그 리스트.
            platform: 대상 플랫폼 ("youtube", "tiktok", "shorts").

        Returns:
            최적화된 태그 리스트.
        """
        # 1. 정규화 (공백 정리, 빈 문자열 제거)
        tags = [t.strip() for t in tags if t.strip()]

        # 2. 중복 제거
        tags = self._deduplicate(tags)

        # 3. 우선순위 정렬
        tags = self._priority_sort(tags)

        # 4. 플랫폼별 제한 적용
        if platform in ("tiktok", "shorts"):
            tags = self._apply_tiktok_limits(tags)
        else:
            tags = self._apply_youtube_limits(tags)

        logger.debug(
            f"Optimized {len(tags)} tags for [{platform}]"
        )

        return tags

    def suggest_trending(
        self,
        event_type: str,
        platform: str = "youtube",
    ) -> list[str]:
        """이벤트 유형에 따른 트렌딩 키워드를 추천한다.

        Args:
            event_type: 이벤트 유형 (climb, jump, run 등).
            platform: 대상 플랫폼.

        Returns:
            추천 트렌딩 키워드 리스트.
        """
        trending = self.TRENDING_KEYWORDS.get(event_type, [])

        if platform in ("tiktok", "shorts"):
            # TikTok은 해시태그 형태로 변환
            return [f"#{kw.replace(' ', '')}" for kw in trending]
        else:
            return trending

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(tags: list[str]) -> list[str]:
        """대소문자 무시하여 중복 제거 (순서 유지)."""
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            key = tag.lower().strip("#")
            if key and key not in seen:
                seen.add(key)
                result.append(tag)
        return result

    # ------------------------------------------------------------------
    # Priority Sorting
    # ------------------------------------------------------------------

    def _priority_sort(self, tags: list[str]) -> list[str]:
        """핵심 키워드를 앞으로, 나머지는 원래 순서 유지."""
        priority_set = {kw.lower() for kw in self.PRIORITY_KEYWORDS}

        priority_tags: list[str] = []
        normal_tags: list[str] = []

        for tag in tags:
            clean = tag.lower().strip("#")
            if clean in priority_set:
                priority_tags.append(tag)
            else:
                normal_tags.append(tag)

        return priority_tags + normal_tags

    # ------------------------------------------------------------------
    # Platform Limits
    # ------------------------------------------------------------------

    def _apply_youtube_limits(self, tags: list[str]) -> list[str]:
        """YouTube 태그 제한을 적용한다.

        - 최대 30개 태그
        - 총 500자 (쉼표 구분자 포함)
        """
        result: list[str] = []
        total_chars = 0

        for tag in tags:
            if len(result) >= self.YOUTUBE_MAX_TAGS:
                break

            clean = tag.strip("#")
            tag_len = len(clean)
            separator = 2 if result else 0  # ", " 구분자

            if total_chars + tag_len + separator > self.YOUTUBE_MAX_CHARS:
                break

            result.append(tag)
            total_chars += tag_len + separator

        return result

    def _apply_tiktok_limits(self, tags: list[str]) -> list[str]:
        """TikTok 태그 제한을 적용한다.

        - 최대 15개 인라인 해시태그
        - 각 태그에 # 접두사 보장
        """
        # # 접두사 보장
        hashtags = [t if t.startswith("#") else f"#{t}" for t in tags]

        return hashtags[: self.TIKTOK_MAX_TAGS]

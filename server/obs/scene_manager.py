"""장면/소스 관리 — OBS 장면 및 소스 구성을 관리한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class SourceConfig:
    """OBS 소스 설정."""

    name: str
    source_type: str  # "ndi_source", "image", "text", "browser", "color"
    settings: Dict = field(default_factory=dict)
    visible: bool = True


@dataclass
class SceneConfig:
    """OBS 장면 설정."""

    name: str
    scene_key: str  # config.yaml의 obs.scenes 키 ("main", "pip", "sleeping", "offline")
    sources: List[SourceConfig] = field(default_factory=list)


class SceneManager:
    """OBS 장면과 소스를 관리한다.

    4개의 기본 장면을 구성하고 각 장면의 소스를 관리한다:
        - MainView: 단일 카메라 전체 화면 + 오버레이
        - PIP_Mode: 메인(70%) + 서브(30%) 동시 표시
        - Sleeping: 수면 화면 (조명 감소 + 수면 오버레이)
        - Offline: 오프라인 이미지 + 상태 텍스트
    """

    def __init__(self, config: dict):
        self._config = config
        obs_config = config.get("obs", {})
        cam_config = config.get("camera", {})
        switching_config = config.get("switching", {}).get("transition", {})

        self._scene_names = obs_config.get("scenes", {})
        self._cameras = cam_config.get("cameras", [])

        self._pip_main_ratio = switching_config.get("pip_main_ratio", 0.7)
        self._pip_sub_ratio = switching_config.get("pip_sub_ratio", 0.3)

        # 장면 설정 구성
        self._scenes: Dict[str, SceneConfig] = self._build_scene_configs()

        logger.info(
            f"SceneManager initialized — scenes={list(self._scenes.keys())}, "
            f"cameras={[c['id'] for c in self._cameras]}"
        )

    def get_scene(self, scene_key: str) -> Optional[SceneConfig]:
        """scene_key로 장면 설정을 조회한다.

        Args:
            scene_key: "main", "pip", "sleeping", "offline"

        Returns:
            SceneConfig 또는 None
        """
        return self._scenes.get(scene_key)

    def get_scene_name(self, scene_key: str) -> Optional[str]:
        """scene_key에 해당하는 OBS 장면 이름을 반환한다."""
        return self._scene_names.get(scene_key)

    def get_all_scenes(self) -> Dict[str, SceneConfig]:
        """모든 장면 설정을 반환한다."""
        return dict(self._scenes)

    def get_sources_for_scene(self, scene_key: str) -> List[SourceConfig]:
        """특정 장면의 소스 목록을 반환한다."""
        scene = self._scenes.get(scene_key)
        if scene is None:
            return []
        return list(scene.sources)

    def get_camera_source_name(self, cam_id: str) -> str:
        """카메라 ID에 해당하는 OBS NDI 소스 이름을 반환한다."""
        for cam in self._cameras:
            if cam["id"] == cam_id:
                return cam.get("ndi_source", cam_id)
        return cam_id

    async def setup_scenes(self, obs_controller) -> bool:
        """OBS에 장면과 소스를 설정한다.

        이미 존재하는 장면은 건너뛰고,
        없는 장면만 새로 생성한다.

        Args:
            obs_controller: OBSController 인스턴스

        Returns:
            True면 설정 성공
        """
        if not obs_controller.connected:
            logger.warning("OBS not connected — cannot setup scenes")
            return False

        try:
            for scene_key, scene_config in self._scenes.items():
                logger.info(
                    f"Setting up scene: {scene_config.name} "
                    f"({len(scene_config.sources)} sources)"
                )

                # 소스 가시성 설정
                for source in scene_config.sources:
                    await obs_controller.set_source_visibility(
                        scene_config.name, source.name, source.visible
                    )

            logger.info("Scene setup complete")
            return True

        except Exception as e:
            logger.error(f"Scene setup failed: {e}")
            return False

    def _build_scene_configs(self) -> Dict[str, SceneConfig]:
        """config.yaml 기반으로 장면 설정을 구성한다."""
        scenes = {}

        # --- MainView ---
        main_sources = []
        for cam in self._cameras:
            main_sources.append(
                SourceConfig(
                    name=cam.get("ndi_source", cam["id"]),
                    source_type="ndi_source",
                    settings={"ndi_source_name": cam.get("ndi_source", "")},
                    visible=True,
                )
            )
        main_sources.extend(self._get_overlay_sources())

        scenes["main"] = SceneConfig(
            name=self._scene_names.get("main", "MainView"),
            scene_key="main",
            sources=main_sources,
        )

        # --- PIP_Mode ---
        pip_sources = []
        if len(self._cameras) >= 2:
            # 메인 카메라 (70%)
            pip_sources.append(
                SourceConfig(
                    name=f"PIP_Main_{self._cameras[0]['id']}",
                    source_type="ndi_source",
                    settings={
                        "ndi_source_name": self._cameras[0].get("ndi_source", ""),
                        "scale_ratio": self._pip_main_ratio,
                    },
                    visible=True,
                )
            )
            # 서브 카메라 (30%)
            pip_sources.append(
                SourceConfig(
                    name=f"PIP_Sub_{self._cameras[1]['id']}",
                    source_type="ndi_source",
                    settings={
                        "ndi_source_name": self._cameras[1].get("ndi_source", ""),
                        "scale_ratio": self._pip_sub_ratio,
                        "position": "bottom_right",
                    },
                    visible=True,
                )
            )
        pip_sources.extend(self._get_overlay_sources())

        scenes["pip"] = SceneConfig(
            name=self._scene_names.get("pip", "PIP_Mode"),
            scene_key="pip",
            sources=pip_sources,
        )

        # --- Sleeping ---
        sleep_sources = []
        if self._cameras:
            sleep_sources.append(
                SourceConfig(
                    name=self._cameras[0].get("ndi_source", self._cameras[0]["id"]),
                    source_type="ndi_source",
                    settings={"brightness": -0.3, "contrast": -0.2},
                    visible=True,
                )
            )
        sleep_sources.append(
            SourceConfig(
                name="SleepOverlay",
                source_type="image",
                settings={"file": "assets/sleep_overlay.png", "opacity": 0.6},
                visible=True,
            )
        )
        sleep_sources.append(
            SourceConfig(
                name="SleepText",
                source_type="text",
                settings={
                    "text": "zzZ...",
                    "font_size": 48,
                    "color": "#FFFFFF80",
                },
                visible=True,
            )
        )

        scenes["sleeping"] = SceneConfig(
            name=self._scene_names.get("sleeping", "Sleeping"),
            scene_key="sleeping",
            sources=sleep_sources,
        )

        # --- Offline ---
        offline_sources = [
            SourceConfig(
                name="OfflineImage",
                source_type="image",
                settings={"file": "assets/offline_card.png"},
                visible=True,
            ),
            SourceConfig(
                name="OfflineText",
                source_type="text",
                settings={
                    "text": "LiveCat - Offline",
                    "font_size": 36,
                    "color": "#FFFFFF",
                },
                visible=True,
            ),
        ]

        scenes["offline"] = SceneConfig(
            name=self._scene_names.get("offline", "Offline"),
            scene_key="offline",
            sources=offline_sources,
        )

        return scenes

    def _get_overlay_sources(self) -> List[SourceConfig]:
        """공통 오버레이 소스 목록을 반환한다 (이름, 시계, 상태)."""
        return [
            SourceConfig(
                name="CatNameOverlay",
                source_type="text",
                settings={
                    "font_size": 28,
                    "color": "#FFFFFF",
                    "outline_color": "#000000",
                    "outline_size": 2,
                },
                visible=True,
            ),
            SourceConfig(
                name="ClockWidget",
                source_type="text",
                settings={
                    "font_size": 20,
                    "color": "#FFFFFFCC",
                },
                visible=True,
            ),
            SourceConfig(
                name="StatusInfo",
                source_type="text",
                settings={
                    "font_size": 16,
                    "color": "#FFFFFF99",
                },
                visible=False,
            ),
        ]

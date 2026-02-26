"""
LiveCat Server - Main Entry Point

2캠 체제 고양이 자동 추적 + 콘텐츠 자동화 시스템.
모든 모듈을 asyncio 기반으로 동시 실행한다.
"""

import asyncio
import signal
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from server.utils.logger import setup_logger
from server.receiver.video_receiver import VideoReceiver
from server.receiver.metadata_receiver import MetadataReceiver
from server.receiver.stream_buffer import StreamBuffer
from server.director.camera_selector import CameraSelector
from server.director.scene_analyzer import SceneAnalyzer
from server.blur.hunt_detector import HuntDetector
from server.blur.blur_processor import BlurProcessor
from server.obs.obs_controller import OBSController
from server.clipper.event_detector import EventDetector
from server.clipper.clip_extractor import ClipExtractor
from server.clipper.clip_scorer import ClipScorer
from server.clipper.daily_selector import DailySelector
from server.producer.vertical_converter import VerticalConverter
from server.producer.template_applier import TemplateApplier
from server.producer.bgm_mixer import BGMMixer
from server.producer.speed_adjuster import SpeedAdjuster
from server.producer.subtitle_generator import SubtitleGenerator
from server.thumbnail.frame_selector import FrameSelector
from server.thumbnail.text_overlay import TextOverlay
from server.thumbnail.template_renderer import TemplateRenderer
from server.titler.title_generator import TitleGenerator
from server.titler.description_generator import DescriptionGenerator
from server.titler.hashtag_generator import HashtagGenerator
from server.uploader.youtube_uploader import YouTubeUploader
from server.uploader.tiktok_uploader import TikTokUploader
from server.uploader.upload_tracker import UploadTracker
from server.scheduler.upload_scheduler import UploadScheduler
from server.web.dashboard import DashboardApp


def load_config() -> dict:
    """Load config.yaml and .env."""
    load_dotenv(ROOT_DIR / ".env")
    config_path = ROOT_DIR / "server" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class LiveCatServer:
    """LiveCat 메인 서버 — 모든 모듈의 라이프사이클 관리."""

    def __init__(self, config: dict):
        self.config = config
        self.running = False

        # --- Layer 1: 영상 수신 ---
        self.stream_buffer = StreamBuffer(config)
        self.video_receiver = VideoReceiver(config, self.stream_buffer)
        self.metadata_receiver = MetadataReceiver(config)

        # --- Layer 2: 실시간 처리 ---
        self.scene_analyzer = SceneAnalyzer(config, self.metadata_receiver)
        self.hunt_detector = HuntDetector(config)
        self.blur_processor = BlurProcessor(config, self.hunt_detector)
        self.camera_selector = CameraSelector(config, self.scene_analyzer)
        self.obs_controller = OBSController(config)

        # --- Layer 3: 하이라이트 클리핑 ---
        self.event_detector = EventDetector(config, self.metadata_receiver)
        self.clip_extractor = ClipExtractor(config, self.stream_buffer)
        self.clip_scorer = ClipScorer(config)
        self.daily_selector = DailySelector(config, self.clip_scorer)

        # --- Layer 4: 숏폼 프로듀서 ---
        self.vertical_converter = VerticalConverter(config)
        self.template_applier = TemplateApplier(config)
        self.bgm_mixer = BGMMixer(config)
        self.speed_adjuster = SpeedAdjuster(config)
        self.subtitle_generator = SubtitleGenerator(config)

        # --- Layer 5: 썸네일 ---
        self.frame_selector = FrameSelector(config)
        self.text_overlay = TextOverlay(config)
        self.template_renderer = TemplateRenderer(config)

        # --- Layer 6: 타이틀/설명 ---
        self.title_generator = TitleGenerator(config)
        self.description_generator = DescriptionGenerator(config)
        self.hashtag_generator = HashtagGenerator(config)

        # --- Layer 7: 업로더 ---
        self.youtube_uploader = YouTubeUploader(config)
        self.tiktok_uploader = TikTokUploader(config)
        self.upload_tracker = UploadTracker(config)
        self.upload_scheduler = UploadScheduler(
            config,
            youtube_uploader=self.youtube_uploader,
            tiktok_uploader=self.tiktok_uploader,
            upload_tracker=self.upload_tracker,
        )

        # --- Layer 8: 대시보드 ---
        self.dashboard = DashboardApp(config, server=self)

    async def start(self):
        """모든 모듈을 비동기로 시작."""
        self.running = True
        logger.info("LiveCat Server starting...")

        tasks = [
            # 실시간 파이프라인
            asyncio.create_task(self.video_receiver.run(), name="video_receiver"),
            asyncio.create_task(self.metadata_receiver.run(), name="metadata_receiver"),
            asyncio.create_task(self.stream_buffer.run(), name="stream_buffer"),
            asyncio.create_task(self._run_live_pipeline(), name="live_pipeline"),

            # 하이라이트 클리핑 (이벤트 드리븐)
            asyncio.create_task(self._run_clipper_pipeline(), name="clipper_pipeline"),

            # 배치 파이프라인 (스케줄)
            asyncio.create_task(self._run_batch_pipeline(), name="batch_pipeline"),

            # 업로드 스케줄러
            asyncio.create_task(self.upload_scheduler.run(), name="upload_scheduler"),

            # 웹 대시보드
            asyncio.create_task(self.dashboard.run(), name="dashboard"),
        ]

        logger.info(f"LiveCat Server started — {len(tasks)} tasks running")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("LiveCat Server shutting down...")
        finally:
            self.running = False

    async def stop(self):
        """모든 모듈 정상 종료."""
        logger.info("Stopping LiveCat Server...")
        self.running = False
        await self.obs_controller.disconnect()
        await self.video_receiver.stop()
        await self.metadata_receiver.stop()
        logger.info("LiveCat Server stopped.")

    # --- 실시간 라이브 파이프라인 ---
    async def _run_live_pipeline(self):
        """카메라 스위칭 + 블러 + OBS 제어 루프."""
        await self.obs_controller.connect()
        logger.info("Live pipeline started")

        while self.running:
            try:
                # 1. 장면 분석 (활동 점수 집계)
                scene_state = self.scene_analyzer.analyze()

                # 2. 카메라 선택
                switch_decision = self.camera_selector.decide(scene_state)

                # 3. 블러 체크 (현재 활성 카메라)
                if switch_decision.active_camera_id:
                    frame = self.stream_buffer.get_latest_frame(
                        switch_decision.active_camera_id
                    )
                    if frame is not None:
                        blur_result = await self.hunt_detector.detect(frame)
                        if blur_result.detected:
                            await self.blur_processor.apply(
                                frame, blur_result
                            )

                # 4. OBS 장면 전환
                if switch_decision.should_switch:
                    await self.obs_controller.switch_scene(switch_decision)

                await asyncio.sleep(1.0 / 10)  # 10Hz 루프

            except Exception as e:
                logger.error(f"Live pipeline error: {e}")
                await asyncio.sleep(1.0)

    # --- 하이라이트 클리퍼 파이프라인 ---
    async def _run_clipper_pipeline(self):
        """이벤트 감지 → 클립 추출 루프."""
        logger.info("Clipper pipeline started")

        while self.running:
            try:
                # 이벤트 감지
                events = self.event_detector.detect()

                for event in events:
                    # 클립 추출
                    clip_path = await self.clip_extractor.extract(event)
                    if clip_path:
                        # 클립 스코어링
                        score = self.clip_scorer.score(clip_path, event)
                        logger.info(
                            f"Clip saved: {clip_path.name} "
                            f"event={event.event_type} score={score:.1f}"
                        )

                await asyncio.sleep(0.5)  # 2Hz 체크

            except Exception as e:
                logger.error(f"Clipper pipeline error: {e}")
                await asyncio.sleep(1.0)

    # --- 배치 파이프라인 (숏폼 + 썸네일 + 타이틀 + 큐잉) ---
    async def _run_batch_pipeline(self):
        """일일 TOP 10 → 숏폼 제작 → 썸네일 → 타이틀 → 업로드 큐."""
        logger.info("Batch pipeline started")

        while self.running:
            try:
                # 일일 TOP 10 선별 (매시간 체크)
                top_clips = self.daily_selector.select_top_clips()

                for clip_info in top_clips:
                    if clip_info.processed:
                        continue

                    logger.info(f"Processing clip: {clip_info.clip_path.name}")

                    # 1. 세로 변환
                    vertical_path = await self.vertical_converter.convert(
                        clip_info.clip_path, clip_info.metadata
                    )

                    # 2. 속도 조절
                    adjusted_path = await self.speed_adjuster.adjust(
                        vertical_path, clip_info.metadata
                    )

                    # 3. BGM 믹싱
                    bgm_path = await self.bgm_mixer.mix(
                        adjusted_path, clip_info.metadata
                    )

                    # 4. 자막 생성
                    subtitled_path = await self.subtitle_generator.generate(
                        bgm_path, clip_info.metadata
                    )

                    # 5. 템플릿 적용 (인트로 + 아웃로 + 오버레이)
                    for platform in ["shorts", "tiktok"]:
                        final_path = await self.template_applier.apply(
                            subtitled_path, clip_info.metadata, platform=platform
                        )

                        # 6. 썸네일 생성
                        best_frame = self.frame_selector.select(clip_info.clip_path)
                        thumbnail_path = self.template_renderer.render(
                            best_frame, clip_info.metadata, platform=platform
                        )

                        # 7. 타이틀 + 설명 생성
                        titles = await self.title_generator.generate(
                            clip_info.metadata, platform=platform
                        )
                        description = await self.description_generator.generate(
                            clip_info.metadata, platform=platform
                        )
                        hashtags = self.hashtag_generator.generate(
                            clip_info.metadata, platform=platform
                        )

                        # 8. 업로드 큐에 추가
                        await self.upload_scheduler.enqueue(
                            video_path=final_path,
                            thumbnail_path=thumbnail_path,
                            title=titles[0],
                            description=description,
                            hashtags=hashtags,
                            platform=platform,
                            metadata=clip_info.metadata,
                        )

                    clip_info.processed = True

                # 1시간 대기
                await asyncio.sleep(3600)

            except Exception as e:
                logger.error(f"Batch pipeline error: {e}")
                await asyncio.sleep(60)

    def get_status(self) -> dict:
        """서버 상태 요약 (대시보드용)."""
        return {
            "running": self.running,
            "cameras": {
                cam["id"]: {
                    "name": cam["name"],
                    "connected": self.video_receiver.is_connected(cam["id"]),
                    "activity_score": self.scene_analyzer.get_score(cam["id"]),
                    "tracking_state": self.metadata_receiver.get_state(cam["id"]),
                }
                for cam in self.config["camera"]["cameras"]
            },
            "active_camera": self.camera_selector.active_camera_id,
            "blur_active": self.blur_processor.is_active,
            "clips_today": self.daily_selector.clips_today_count,
            "upload_queue": self.upload_scheduler.queue_size,
        }


async def main():
    config = load_config()
    setup_logger(config)

    server = LiveCatServer(config)

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(server.stop()))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await server.start()
    except KeyboardInterrupt:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())

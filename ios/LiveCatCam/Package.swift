// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "LiveCatCam",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "LiveCatCam",
            targets: ["LiveCatCam"]
        )
    ],
    dependencies: [
        // ffmpeg-kit: download xcframework from https://github.com/arthenica/ffmpeg-kit/releases
        // and place as Frameworks/ffmpegkit.xcframework, then uncomment the binaryTarget below.
    ],
    targets: [
        .target(
            name: "LiveCatCam",
            dependencies: [
                // Uncomment when ffmpeg-kit xcframework is available:
                // "FFmpegKit"
            ],
            path: "Sources/LiveCatCam",
            swiftSettings: [
                .swiftLanguageMode(.v5)
            ]
        ),
        .executableTarget(
            name: "LiveCatCamTestRunner",
            dependencies: ["LiveCatCam"],
            path: "Tests/LiveCatCamTests",
            swiftSettings: [
                .swiftLanguageMode(.v5)
            ]
        ),
        // Uncomment when xcframework is placed:
        // .binaryTarget(
        //     name: "FFmpegKit",
        //     path: "Frameworks/ffmpegkit.xcframework"
        // )
    ]
)

#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

NS_ASSUME_NONNULL_BEGIN

/// VNImageRequestHandler.perform()을 @try/@catch로 감싸서
/// NSException을 Swift가 catch할 수 있는 NSError로 변환하는 래퍼.
@interface SafeVisionPerformer : NSObject

/// VNImageRequestHandler로 단일 request를 안전하게 실행.
/// NSException 포함 모든 예외를 잡아서 error로 반환한다.
+ (BOOL)safePerform:(VNImageRequestHandler *)handler
            request:(VNRequest *)request
              error:(NSError * _Nullable * _Nullable)error;

/// VNSequenceRequestHandler로 단일 request를 안전하게 실행.
/// VNTrackObjectRequest 전용 — Apple 공식 tracking API.
/// NSException 포함 모든 예외를 잡아서 error로 반환한다.
+ (BOOL)safePerformSequence:(VNSequenceRequestHandler *)handler
                    request:(VNRequest *)request
                pixelBuffer:(CVPixelBufferRef)pixelBuffer
                      error:(NSError * _Nullable * _Nullable)error;

@end

NS_ASSUME_NONNULL_END

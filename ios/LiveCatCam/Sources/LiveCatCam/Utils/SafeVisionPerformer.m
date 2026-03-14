#import "SafeVisionPerformer.h"

@implementation SafeVisionPerformer

+ (BOOL)safePerform:(VNImageRequestHandler *)handler
            request:(VNRequest *)request
              error:(NSError * _Nullable * _Nullable)error {
    @try {
        NSError *performError = nil;
        BOOL success = [handler performRequests:@[request] error:&performError];
        if (error) {
            *error = performError;
        }
        return success;
    } @catch (NSException *exception) {
        // VNTrackObjectRequest가 화면 경계 이탈 등에서 던지는 NSException을 잡아 NSError로 변환
        if (error) {
            NSDictionary *userInfo = @{
                NSLocalizedDescriptionKey: exception.reason ?: @"Unknown Vision exception",
                @"ExceptionName": exception.name ?: @"Unknown"
            };
            *error = [NSError errorWithDomain:@"SafeVisionPerformerErrorDomain"
                                         code:-1
                                     userInfo:userInfo];
        }
        return NO;
    }
}

+ (BOOL)safePerformSequence:(VNSequenceRequestHandler *)handler
                    request:(VNRequest *)request
                pixelBuffer:(CVPixelBufferRef)pixelBuffer
                      error:(NSError * _Nullable * _Nullable)error {
    @try {
        NSError *performError = nil;
        BOOL success = [handler performRequests:@[request]
                               onCVPixelBuffer:pixelBuffer
                                   orientation:kCGImagePropertyOrientationUp
                                         error:&performError];
        if (error) {
            *error = performError;
        }
        return success;
    } @catch (NSException *exception) {
        if (error) {
            NSDictionary *userInfo = @{
                NSLocalizedDescriptionKey: exception.reason ?: @"Unknown Vision exception",
                @"ExceptionName": exception.name ?: @"Unknown"
            };
            *error = [NSError errorWithDomain:@"SafeVisionPerformerErrorDomain"
                                         code:-2
                                     userInfo:userInfo];
        }
        return NO;
    }
}

@end

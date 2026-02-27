import Foundation

struct CatProfile: Identifiable, Codable, Sendable {
    let id: String
    let name: String
    let pattern: String
    let icon: String

    static let nana = CatProfile(id: "nana", name: "나나", pattern: "tabby", icon: "cat.fill")
    static let toto = CatProfile(id: "toto", name: "토토", pattern: "tuxedo", icon: "cat.fill")
    static let all: [CatProfile] = [.nana, .toto]
}

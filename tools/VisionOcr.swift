// Usage: vision-ocr INPUT_IMAGE OUTPUT_JSON
// Reads one image, runs on-device Vision text recognition, writes observations as JSON.
import Foundation
import ImageIO
import Vision

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

let arguments = CommandLine.arguments
if arguments.count != 3 { fail("usage") }

guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: arguments[1]) as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
else { fail("unreadable_input") }

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["ko-KR", "en-US"]

do { try VNImageRequestHandler(cgImage: image, options: [:]).perform([request]) } catch { fail("recognition_failed") }

func clamp(_ value: CGFloat) -> Double { Double(min(1, max(0, value))) }

// Vision can return boxes a hair outside [0,1] at image edges; clamp, and drop degenerate ones.
let observations: [[String: Any]] = (request.results ?? []).compactMap { item in
    guard let candidate = item.topCandidates(1).first, !candidate.string.isEmpty else { return nil }
    let box = item.boundingBox  // normalized, origin bottom-left
    let x0 = clamp(box.minX), x1 = clamp(box.maxX)
    let y0 = clamp(1 - box.maxY), y1 = clamp(1 - box.minY)  // top-left origin
    let width = max(0, x1 - x0), height = max(0, y1 - y0)
    if width == 0 || height == 0 { return nil }
    return [
        "text": candidate.string,
        "confidence": clamp(CGFloat(candidate.confidence)),
        "box": [x0, y0, width, height],
    ]
}
let payload: [String: Any] = [
    "schema_version": 1, "width": image.width, "height": image.height, "observations": observations,
]
do {
    let data = try JSONSerialization.data(withJSONObject: payload)
    try data.write(to: URL(fileURLWithPath: arguments[2]))
} catch { fail("write_failed") }

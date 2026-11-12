import AVFoundation
import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  override func awakeFromNib() {
    let controller = FlutterViewController()
    let windowFrame = frame
    contentViewController = controller
    setFrame(windowFrame, display: true)
    contentMinSize = NSSize(width: 720, height: 520)

    let microphone = FlutterMethodChannel(
      name: "sage.voice/microphone", binaryMessenger: controller.engine.binaryMessenger
    )
    microphone.setMethodCallHandler { call, result in
      guard call.method == "request" else {
        result(FlutterMethodNotImplemented)
        return
      }
      AVCaptureDevice.requestAccess(for: .audio) { granted in
        DispatchQueue.main.async { result(granted) }
      }
    }
    RegisterGeneratedPlugins(registry: controller)
    super.awakeFromNib()
  }
}

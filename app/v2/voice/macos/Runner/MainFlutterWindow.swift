import AVFoundation
import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  override func awakeFromNib() {
    let controller = FlutterViewController()
    let windowFrame = frame
    titleVisibility = .hidden
    titlebarAppearsTransparent = true
    styleMask.insert(.fullSizeContentView)
    isMovableByWindowBackground = true
    controller.backgroundColor = .clear
    contentViewController = controller
    setFrame(windowFrame, display: true)
    contentMinSize = NSSize(width: 720, height: 520)

    let preferences = FlutterMethodChannel(
      name: "sage.voice/preferences", binaryMessenger: controller.engine.binaryMessenger
    )
    preferences.setMethodCallHandler { call, result in
      let defaults = UserDefaults.standard
      let key = "voiceInterfaceLanguage"
      switch call.method {
      case "getLanguage":
        result(defaults.string(forKey: key))
      case "setLanguage":
        defaults.set(call.arguments as? String, forKey: key)
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }

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

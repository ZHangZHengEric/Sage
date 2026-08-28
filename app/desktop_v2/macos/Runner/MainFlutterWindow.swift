import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  private var resizeSyncScheduled = false
  private var pressedKeyCodes = Set<UInt16>()
  private weak var flutterViewController: FlutterViewController?

  override func awakeFromNib() {
    self.minSize = NSSize(width: 980, height: 680)

    let launchScreen = targetScreenForLaunch()
    let launchFrame = launchScreen.map { initialFrame(in: $0.visibleFrame) }

    let flutterViewController = FlutterViewController()
    self.flutterViewController = flutterViewController
    let windowFrame = self.frame
    self.titleVisibility = .hidden
    self.titlebarAppearsTransparent = true
    self.styleMask.insert(.fullSizeContentView)
    self.isMovableByWindowBackground = true
    self.isOpaque = false
    self.backgroundColor = .clear
    flutterViewController.backgroundColor = NSColor.clear
    self.isRestorable = false
    self.setFrameAutosaveName("")
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)

    RegisterGeneratedPlugins(registry: flutterViewController)

    super.awakeFromNib()
    DispatchQueue.main.async { [weak self] in
      guard let self else { return }
      if let launchFrame {
        self.setFrame(launchFrame, display: true)
      }
      self.lowerTrafficLights()
      self.syncFlutterSurfaceToWindow()
      self.scheduleFlutterSurfaceSync()
    }
  }

  deinit {
    NotificationCenter.default.removeObserver(self)
  }

  override func setFrame(_ frameRect: NSRect, display flag: Bool) {
    super.setFrame(frameRect, display: flag)
    syncFlutterSurfaceToWindow()
    scheduleFlutterSurfaceSync()
  }

  override func setFrame(
    _ frameRect: NSRect,
    display flag: Bool,
    animate animateFlag: Bool
  ) {
    super.setFrame(frameRect, display: flag, animate: animateFlag)
    syncFlutterSurfaceToWindow()
    scheduleFlutterSurfaceSync()
  }

  override func sendEvent(_ event: NSEvent) {
    if event.type == .keyDown {
      if pressedKeyCodes.contains(event.keyCode) {
        return
      }
      pressedKeyCodes.insert(event.keyCode)
    } else if event.type == .keyUp {
      pressedKeyCodes.remove(event.keyCode)
    } else if event.type == .flagsChanged {
      syncModifierKeyState(event)
    }
    super.sendEvent(event)
  }

  override func resignKey() {
    pressedKeyCodes.removeAll()
    super.resignKey()
  }

  override func resignMain() {
    pressedKeyCodes.removeAll()
    super.resignMain()
  }

  private func initialFrame(in visibleFrame: NSRect) -> NSRect {
    let horizontalMargin = max(48, min(180, visibleFrame.width * 0.08))
    let verticalMargin = max(48, min(140, visibleFrame.height * 0.08))
    let maxWidth = max(minSize.width, visibleFrame.width - horizontalMargin * 2)
    let maxHeight = max(minSize.height, visibleFrame.height - verticalMargin * 2)
    let width = min(maxWidth, max(1320, visibleFrame.width * 0.78))
    let height = min(maxHeight, max(820, visibleFrame.height * 0.82))
    let origin = NSPoint(
      x: visibleFrame.midX - width / 2,
      y: visibleFrame.midY - height / 2
    )
    return NSRect(origin: origin, size: NSSize(width: width, height: height))
  }

  private func targetScreenForLaunch() -> NSScreen? {
    let mouseLocation = NSEvent.mouseLocation
    if let mouseScreen = NSScreen.screens.first(where: { $0.frame.contains(mouseLocation) }) {
      return mouseScreen
    }
    if let mainScreen = NSScreen.main {
      return mainScreen
    }
    if let screen = self.screen {
      return screen
    }
    let intersectingScreen = NSScreen.screens.max { lhs, rhs in
      intersectionArea(lhs.frame, self.frame) < intersectionArea(rhs.frame, self.frame)
    }
    if let screen = intersectingScreen, intersectionArea(screen.frame, self.frame) > 0 {
      return screen
    }
    return NSScreen.screens.first
  }

  private func intersectionArea(_ lhs: NSRect, _ rhs: NSRect) -> CGFloat {
    let intersection = lhs.intersection(rhs)
    guard !intersection.isNull && !intersection.isEmpty else { return 0 }
    return intersection.width * intersection.height
  }

  private func scheduleFlutterSurfaceSync() {
    guard !resizeSyncScheduled else { return }
    resizeSyncScheduled = true
    DispatchQueue.main.async { [weak self] in
      guard let self else { return }
      self.resizeSyncScheduled = false
      self.syncFlutterSurfaceToWindow()
    }
  }

  private func syncFlutterSurfaceToWindow() {
    guard let flutterView = flutterViewController?.view else { return }
    let contentSize = contentRect(forFrameRect: frame).size
    guard contentSize.width > 0 && contentSize.height > 0 else { return }
    let nextFrame = NSRect(origin: .zero, size: contentSize)
    flutterView.autoresizingMask = [.width, .height]
    if flutterView.frame != nextFrame {
      flutterView.frame = nextFrame
    }
    flutterView.needsLayout = true
    flutterView.layoutSubtreeIfNeeded()
    contentView?.needsDisplay = true
  }

  private func syncModifierKeyState(_ event: NSEvent) {
    let modifierKeyCodes: [UInt16: NSEvent.ModifierFlags] = [
      0x38: .shift,
      0x3C: .shift,
      0x3B: .control,
      0x3E: .control,
      0x3A: .option,
      0x3D: .option,
      0x37: .command,
      0x36: .command,
    ]
    guard let flag = modifierKeyCodes[event.keyCode] else { return }
    if event.modifierFlags.intersection(.deviceIndependentFlagsMask).contains(flag) {
      pressedKeyCodes.insert(event.keyCode)
    } else {
      pressedKeyCodes.remove(event.keyCode)
    }
  }

  private func lowerTrafficLights() {
    let buttons: [NSWindow.ButtonType] = [
      .closeButton,
      .miniaturizeButton,
      .zoomButton,
    ]
    for buttonType in buttons {
      guard let button = standardWindowButton(buttonType) else { continue }
      button.frame.origin.y -= 7
    }
  }
}

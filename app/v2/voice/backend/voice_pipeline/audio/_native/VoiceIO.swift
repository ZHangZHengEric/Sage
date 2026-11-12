import AVFoundation
import CoreAudio
import Foundation


private let captureSampleRate = 16_000.0
private let playbackSampleRate = 48_000.0
private let captureCapacity = 16_000 * 5
private let maxQueuedPlaybackFrames = 48_000 / 5
private let playbackWaitSeconds = 5.0


private final class Int16RingBuffer {
    private let condition = NSCondition()
    private var samples = [Int16](repeating: 0, count: captureCapacity)
    private var readIndex = 0
    private var writeIndex = 0
    private var available = 0
    private var stopped = false
    private var failed = false

    func reset() {
        condition.lock()
        readIndex = 0
        writeIndex = 0
        available = 0
        stopped = false
        failed = false
        condition.broadcast()
        condition.unlock()
    }

    func stop(failed: Bool) {
        condition.lock()
        stopped = true
        self.failed = failed
        condition.broadcast()
        condition.unlock()
    }

    func write(_ source: UnsafePointer<Int16>, count: Int) {
        guard count > 0 else {
            return
        }

        condition.lock()
        guard !stopped else {
            condition.unlock()
            return
        }
        for index in 0..<count {
            samples[writeIndex] = source[index]
            writeIndex = (writeIndex + 1) % samples.count
            if available == samples.count {
                readIndex = (readIndex + 1) % samples.count
            } else {
                available += 1
            }
        }
        condition.signal()
        condition.unlock()
    }

    func read(
        into destination: UnsafeMutablePointer<Int16>,
        count requested: Int,
        timeoutMilliseconds: Int
    ) -> Int {
        guard requested > 0 else {
            return 0
        }

        condition.lock()
        defer {
            condition.unlock()
        }

        let deadline = Date().addingTimeInterval(
            Double(max(timeoutMilliseconds, 0)) / 1_000
        )
        while available < requested && !stopped {
            if timeoutMilliseconds == 0 || !condition.wait(until: deadline) {
                return 0
            }
        }

        if stopped && available == 0 {
            return failed ? -2 : -1
        }

        let count = min(requested, available)
        for index in 0..<count {
            destination[index] = samples[readIndex]
            readIndex = (readIndex + 1) % samples.count
        }
        available -= count
        return count
    }
}


private final class VoiceIO {
    private let captureRing = Int16RingBuffer()
    private let controlQueue = DispatchQueue(
        label: "lalk.voice-processing.control"
    )
    private let stateCondition = NSCondition()
    private let errorLock = NSLock()

    private let captureFormat = AVAudioFormat(
        commonFormat: .pcmFormatInt16,
        sampleRate: captureSampleRate,
        channels: 1,
        interleaved: false
    )!
    private let playbackFormat = AVAudioFormat(
        standardFormatWithSampleRate: playbackSampleRate,
        channels: 1
    )!

    private var engine: AVAudioEngine?
    private var player: AVAudioPlayerNode?
    private var captureConverter: AVAudioConverter?
    private var captureConverterInputFormat: AVAudioFormat?
    private var configurationObserver: NSObjectProtocol?
    private var tapInstalled = false
    private var running = false
    private var generation: UInt64 = 0
    private var queuedPlaybackFrames = 0
    private var playedFrames: UInt64 = 0
    private var lastError = ""

    deinit {
        stop()
    }

    func start() -> Bool {
        stateCondition.lock()
        let alreadyRunning = running
        stateCondition.unlock()
        if alreadyRunning {
            return true
        }

        do {
            guard hasDefaultAudioDevices() else {
                throw VoiceIOError.noDefaultAudioDevice
            }

            let engine = AVAudioEngine()
            let player = AVAudioPlayerNode()
            let inputNode = engine.inputNode
            let outputNode = engine.outputNode

            try inputNode.setVoiceProcessingEnabled(true)
            inputNode.isVoiceProcessingInputMuted = false
            inputNode.isVoiceProcessingBypassed = false
            inputNode.isVoiceProcessingAGCEnabled = true

            let inputFormat = inputNode.outputFormat(forBus: 0)
            let outputFormat = outputNode.outputFormat(forBus: 0)
            guard inputFormat.sampleRate > 0, inputFormat.channelCount > 0 else {
                throw VoiceIOError.invalidInputFormat
            }
            guard outputFormat.sampleRate > 0, outputFormat.channelCount > 0 else {
                throw VoiceIOError.invalidOutputFormat
            }

            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: playbackFormat)

            // VoiceProcessingIO exposes one duplex client format. Matching the
            // mixer output to it lets Core Audio perform the hardware conversion.
            engine.connect(engine.mainMixerNode, to: outputNode, format: inputFormat)

            guard let converterInputFormat = AVAudioFormat(
                standardFormatWithSampleRate: inputFormat.sampleRate,
                channels: 1
            ), let converter = AVAudioConverter(
                from: converterInputFormat,
                to: captureFormat
            ) else {
                throw VoiceIOError.converterCreationFailed
            }

            let tapFrames = AVAudioFrameCount(max(inputFormat.sampleRate / 100, 1))
            inputNode.installTap(
                onBus: 0,
                bufferSize: tapFrames,
                format: inputFormat
            ) { [weak self] buffer, _ in
                self?.processCapture(buffer)
            }

            self.engine = engine
            self.player = player
            self.captureConverter = converter
            self.captureConverterInputFormat = converterInputFormat
            tapInstalled = true
            captureRing.reset()

            engine.prepare()
            try engine.start()
            player.play()

            stateCondition.lock()
            running = true
            stateCondition.unlock()

            configurationObserver = NotificationCenter.default.addObserver(
                forName: .AVAudioEngineConfigurationChange,
                object: engine,
                queue: nil
            ) { [weak self] _ in
                self?.configurationChanged()
            }
            return true
        } catch {
            setError("Unable to start VoiceProcessingIO: \(error)")
            stop()
            return false
        }
    }

    func stop() {
        if let observer = configurationObserver {
            NotificationCenter.default.removeObserver(observer)
            configurationObserver = nil
        }

        stateCondition.lock()
        running = false
        generation &+= 1
        queuedPlaybackFrames = 0
        stateCondition.broadcast()
        stateCondition.unlock()

        if let engine, tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        controlQueue.sync {
            player?.stop()
            player?.reset()
        }
        engine?.stop()
        player = nil
        engine = nil
        captureConverter = nil
        captureConverterInputFormat = nil
        captureRing.stop(failed: false)
    }

    func readCapture(
        into destination: UnsafeMutablePointer<Int16>,
        count: Int,
        timeoutMilliseconds: Int
    ) -> Int {
        captureRing.read(
            into: destination,
            count: count,
            timeoutMilliseconds: timeoutMilliseconds
        )
    }

    func writePlayback(
        source: UnsafePointer<Int16>,
        frameCount: Int
    ) -> Int32 {
        guard frameCount > 0 else {
            return 1
        }

        stateCondition.lock()
        guard running else {
            stateCondition.unlock()
            setError("VoiceProcessingIO is not running")
            return -1
        }
        let playbackGeneration = generation
        let deadline = Date().addingTimeInterval(playbackWaitSeconds)
        while queuedPlaybackFrames >= maxQueuedPlaybackFrames {
            if !stateCondition.wait(until: deadline) {
                stateCondition.unlock()
                setError("Timed out waiting for playback queue capacity")
                return -1
            }
            if !running {
                stateCondition.unlock()
                setError("VoiceProcessingIO stopped during playback")
                return -1
            }
            if generation != playbackGeneration {
                stateCondition.unlock()
                return 0
            }
        }
        stateCondition.unlock()

        var scheduled = false
        controlQueue.sync {
            stateCondition.lock()
            let canSchedule = running && generation == playbackGeneration
            stateCondition.unlock()
            guard canSchedule, let player else {
                return
            }
            guard let buffer = AVAudioPCMBuffer(
                pcmFormat: playbackFormat,
                frameCapacity: AVAudioFrameCount(frameCount)
            ), let channel = buffer.floatChannelData?[0] else {
                setError("Unable to create a playback buffer")
                return
            }

            buffer.frameLength = AVAudioFrameCount(frameCount)
            for index in 0..<frameCount {
                channel[index] = Float(Int16(littleEndian: source[index])) / 32_768
            }
            stateCondition.lock()
            if running && generation == playbackGeneration {
                queuedPlaybackFrames += frameCount
                scheduled = true
            }
            stateCondition.unlock()
            guard scheduled else {
                return
            }
            player.scheduleBuffer(
                buffer,
                completionCallbackType: .dataPlayedBack
            ) { [weak self] _ in
                self?.completePlayback(
                    frameCount: frameCount,
                    generation: playbackGeneration
                )
            }
            if !player.isPlaying {
                player.play()
            }
        }

        if !scheduled {
            stateCondition.lock()
            let interrupted = generation != playbackGeneration || !running
            stateCondition.unlock()
            return interrupted ? 0 : -1
        }
        return 1
    }

    func waitForPlayback() -> Int32 {
        stateCondition.lock()
        defer {
            stateCondition.unlock()
        }

        guard running else {
            setError("VoiceProcessingIO is not running")
            return -1
        }
        let playbackGeneration = generation
        let deadline = Date().addingTimeInterval(playbackWaitSeconds)
        while queuedPlaybackFrames > 0 {
            if !stateCondition.wait(until: deadline) {
                setError("Timed out waiting for audio playback")
                return -1
            }
            if !running {
                setError("VoiceProcessingIO stopped during playback")
                return -1
            }
            if generation != playbackGeneration {
                return 0
            }
        }
        return 1
    }

    func playbackFrameCount() -> UInt64 {
        stateCondition.lock()
        let count = playedFrames
        stateCondition.unlock()
        return count
    }

    func interruptPlayback() {
        stateCondition.lock()
        generation &+= 1
        queuedPlaybackFrames = 0
        stateCondition.broadcast()
        let shouldRestart = running
        stateCondition.unlock()

        controlQueue.sync {
            player?.stop()
            player?.reset()
            if shouldRestart, let player {
                player.play()
            }
        }
    }

    func copyLastError(
        into destination: UnsafeMutablePointer<CChar>,
        capacity: Int
    ) -> Int {
        guard capacity > 0 else {
            return 0
        }

        errorLock.lock()
        let bytes = Array(lastError.utf8)
        errorLock.unlock()

        let count = min(bytes.count, capacity - 1)
        for index in 0..<count {
            destination[index] = CChar(bitPattern: bytes[index])
        }
        destination[count] = 0
        return count
    }

    private func completePlayback(
        frameCount: Int,
        generation playbackGeneration: UInt64
    ) {
        stateCondition.lock()
        if playbackGeneration == generation {
            queuedPlaybackFrames = max(queuedPlaybackFrames - frameCount, 0)
            playedFrames &+= UInt64(frameCount)
        }
        stateCondition.broadcast()
        stateCondition.unlock()
    }

    private func processCapture(_ inputBuffer: AVAudioPCMBuffer) {
        guard
            let converter = captureConverter,
            let converterInputFormat = captureConverterInputFormat,
            let inputChannels = inputBuffer.floatChannelData
        else {
            return
        }

        let frameCount = Int(inputBuffer.frameLength)
        let channelCount = Int(inputBuffer.format.channelCount)
        guard frameCount > 0, channelCount > 0 else {
            return
        }

        // VoiceProcessingIO can expose aggregate channels. The processed
        // microphone channel is selected by energy instead of assuming index 0.
        var selectedChannel = 0
        var selectedEnergy: Float = -1
        for channelIndex in 0..<channelCount {
            var energy: Float = 0
            for frameIndex in 0..<frameCount {
                let sample = inputChannels[channelIndex][frameIndex]
                energy += sample * sample
            }
            if energy > selectedEnergy {
                selectedEnergy = energy
                selectedChannel = channelIndex
            }
        }

        guard let monoInput = AVAudioPCMBuffer(
            pcmFormat: converterInputFormat,
            frameCapacity: inputBuffer.frameLength
        ), let monoChannel = monoInput.floatChannelData?[0] else {
            return
        }
        monoInput.frameLength = inputBuffer.frameLength
        monoChannel.update(
            from: inputChannels[selectedChannel],
            count: frameCount
        )

        let ratio = captureSampleRate / inputBuffer.format.sampleRate
        let capacity = AVAudioFrameCount(ceil(Double(frameCount) * ratio) + 8)
        guard let converted = AVAudioPCMBuffer(
            pcmFormat: captureFormat,
            frameCapacity: capacity
        ) else {
            return
        }

        var suppliedInput = false
        var conversionError: NSError?
        let status = converter.convert(to: converted, error: &conversionError) {
            _, outputStatus in
            if suppliedInput {
                outputStatus.pointee = .noDataNow
                return nil
            }
            suppliedInput = true
            outputStatus.pointee = .haveData
            return monoInput
        }
        if status == .error {
            if let conversionError {
                setError("Microphone resampling failed: \(conversionError)")
            }
            return
        }
        guard
            converted.frameLength > 0,
            let source = converted.int16ChannelData?[0]
        else {
            return
        }
        captureRing.write(source, count: Int(converted.frameLength))
    }

    private func configurationChanged() {
        stateCondition.lock()
        guard running else {
            stateCondition.unlock()
            return
        }
        running = false
        generation &+= 1
        queuedPlaybackFrames = 0
        stateCondition.broadcast()
        stateCondition.unlock()

        setError("The macOS audio device configuration changed")
        captureRing.stop(failed: true)
    }

    private func setError(_ message: String) {
        errorLock.lock()
        lastError = message
        errorLock.unlock()
    }

    private func hasDefaultAudioDevices() -> Bool {
        hasDefaultAudioDevice(
            selector: kAudioHardwarePropertyDefaultInputDevice
        ) && hasDefaultAudioDevice(
            selector: kAudioHardwarePropertyDefaultOutputDevice
        )
    }

    private func hasDefaultAudioDevice(
        selector: AudioObjectPropertySelector
    ) -> Bool {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var identifier = AudioDeviceID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        let status = AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &size,
            &identifier
        )
        return status == noErr && identifier != kAudioObjectUnknown
    }
}


private enum VoiceIOError: Error, CustomStringConvertible {
    case noDefaultAudioDevice
    case invalidInputFormat
    case invalidOutputFormat
    case converterCreationFailed

    var description: String {
        switch self {
        case .noDefaultAudioDevice:
            return "No default input or output audio device is available"
        case .invalidInputFormat:
            return "The default input device has no usable audio format"
        case .invalidOutputFormat:
            return "The default output device has no usable audio format"
        case .converterCreationFailed:
            return "Unable to create the microphone sample-rate converter"
        }
    }
}


private func voiceIO(
    from handle: UnsafeMutableRawPointer?
) -> VoiceIO? {
    guard let handle else {
        return nil
    }
    return Unmanaged<VoiceIO>.fromOpaque(handle).takeUnretainedValue()
}


@_cdecl("lalk_voice_io_create")
public func lalk_voice_io_create() -> UnsafeMutableRawPointer? {
    Unmanaged.passRetained(VoiceIO()).toOpaque()
}


@_cdecl("lalk_voice_io_destroy")
public func lalk_voice_io_destroy(
    _ handle: UnsafeMutableRawPointer?
) {
    guard let handle else {
        return
    }
    let instance = Unmanaged<VoiceIO>.fromOpaque(handle).takeRetainedValue()
    instance.stop()
}


@_cdecl("lalk_voice_io_start")
public func lalk_voice_io_start(
    _ handle: UnsafeMutableRawPointer?
) -> Int32 {
    guard let instance = voiceIO(from: handle) else {
        return -1
    }
    return instance.start() ? 0 : -1
}


@_cdecl("lalk_voice_io_stop")
public func lalk_voice_io_stop(
    _ handle: UnsafeMutableRawPointer?
) {
    voiceIO(from: handle)?.stop()
}


@_cdecl("lalk_voice_io_read_capture")
public func lalk_voice_io_read_capture(
    _ handle: UnsafeMutableRawPointer?,
    _ destination: UnsafeMutablePointer<Int16>?,
    _ count: Int32,
    _ timeoutMilliseconds: Int32
) -> Int32 {
    guard let instance = voiceIO(from: handle), let destination else {
        return -2
    }
    return Int32(
        instance.readCapture(
            into: destination,
            count: Int(count),
            timeoutMilliseconds: Int(timeoutMilliseconds)
        )
    )
}


@_cdecl("lalk_voice_io_write_playback")
public func lalk_voice_io_write_playback(
    _ handle: UnsafeMutableRawPointer?,
    _ source: UnsafePointer<Int16>?,
    _ frameCount: Int32
) -> Int32 {
    guard let instance = voiceIO(from: handle), let source else {
        return -1
    }
    return instance.writePlayback(
        source: source,
        frameCount: Int(frameCount)
    )
}


@_cdecl("lalk_voice_io_played_frames")
public func lalk_voice_io_played_frames(
    _ handle: UnsafeMutableRawPointer?
) -> UInt64 {
    voiceIO(from: handle)?.playbackFrameCount() ?? 0
}


@_cdecl("lalk_voice_io_wait_playback")
public func lalk_voice_io_wait_playback(
    _ handle: UnsafeMutableRawPointer?
) -> Int32 {
    guard let instance = voiceIO(from: handle) else {
        return -1
    }
    return instance.waitForPlayback()
}


@_cdecl("lalk_voice_io_interrupt_playback")
public func lalk_voice_io_interrupt_playback(
    _ handle: UnsafeMutableRawPointer?
) -> Int32 {
    guard let instance = voiceIO(from: handle) else {
        return -1
    }
    instance.interruptPlayback()
    return 0
}


@_cdecl("lalk_voice_io_copy_last_error")
public func lalk_voice_io_copy_last_error(
    _ handle: UnsafeMutableRawPointer?,
    _ destination: UnsafeMutablePointer<CChar>?,
    _ capacity: Int32
) -> Int32 {
    guard let instance = voiceIO(from: handle), let destination else {
        return 0
    }
    return Int32(
        instance.copyLastError(
            into: destination,
            capacity: Int(capacity)
        )
    )
}


from lib.audio_mixer import *
from lib.clip import *
from lib.math_utils import *
from lib.sampler import *
from lib.video_utils import *
import math

def addGridPositions(clips, cols, width, height, offsetX=0, offsetY=0, marginX=0, marginY=0):
    rows = ceilInt(1.0 * len(clips) / cols)
    cellW = 1.0 * width / cols
    cellH = 1.0 * height / rows
    for i, c in enumerate(clips):
        row = int(i / cols)
        col = i % cols
        clips[i]["col"] = col
        clips[i]["row"] = row
        clips[i]["x"] = col * cellW + marginX*0.5 + offsetX
        clips[i]["y"] = row * cellH + marginY*0.5 + offsetY
        clips[i]["width"] = cellW - marginX
        clips[i]["height"] = cellH - marginY
        clips[i]["nx"] = 1.0 * col / (cols-1)
        clips[i]["ny"] = 1.0 * row / (rows-1)
    return clips

def addPositionNoise(clips, noiseXRange, noiseYRange, randomSeed=3):
    for i, c in enumerate(clips):
        clips[i]["x"] = c["x"] + pseudoRandom(randomSeed+i*2, range=noiseXRange)
        clips[i]["y"] = c["y"] + pseudoRandom(randomSeed+i*2+1, range=noiseYRange)
    return clips

def getDivisionIncrement(count):
    if count < 2:
        return 1.0
    divisions = math.ceil(math.log(count, 2))
    increment = 1.0 / divisions / 2.0
    return increment

def getOffset(count, index):
    if count < 2 or index < 1:
        return 0

    divisions = math.ceil(math.log(count, 2))
    currentIndex = 0
    foundOffset = 0
    for i in range(divisions):
        add = 1
        offset = 0
        if i > 0:
            add = 2 ** (i-1)
            offset = 2 ** (-i)
        for j in range(add):
            offset += offset * 2 * j
            currentIndex += 1
            if index == currentIndex:
                foundOffset = offset
                break
        if foundOffset > 0:
            break
    return foundOffset

def initGridComposition(a, gridW, gridH, stepTime=False):
    _, samples = readCsv(a.INPUT_FILE)
    stepTime = logTime(stepTime, "Read CSV")
    sampleCount = len(samples)
    sampler = Sampler()
    container = Clip({
        "width": a.WIDTH,
        "height": a.HEIGHT,
        "cache": True
    })

    gridCount = gridW * gridH
    if gridCount > sampleCount:
        print("Not enough samples (%s) for the grid you want (%s x %s = %s). Exiting." % (sampleCount, gridW, gridH, gridCount))
        sys.exit()
    elif gridCount < sampleCount:
        print("Too many samples (%s), limiting to %s" % (sampleCount, gridCount))
        samples = samples[:gridCount]
        sampleCount = gridCount

    # Sort by grid
    samples = sorted(samples, key=lambda s: (s["gridY"], s["gridX"]))
    samples = addIndices(samples)
    samples = prependAll(samples, ("filename", a.MEDIA_DIRECTORY))
    aspectRatio = (1.0*a.HEIGHT/a.WIDTH)
    samples = addGridPositions(samples, gridW, a.WIDTH, a.HEIGHT, marginX=a.CLIP_MARGIN, marginY=(a.CLIP_MARGIN*aspectRatio))
    if a.NOISE > 0:
        samples = addPositionNoise(samples, (-a.NOISE, a.NOISE), (-a.NOISE*aspectRatio, a.NOISE*aspectRatio), a.RANDOM_SEED+3)

    return (samples, sampleCount, container, sampler, stepTime)

def limitAudioClips(samples, maxAudioClips, keyName, invert=False, keepFirst=64, multiplier=10000, easing="quartOut", seed=3):
    indicesToKeep = []
    shuffleSamples = samples[:]
    shuffleSampleCount = maxAudioClips
    if maxAudioClips > keepFirst:
        shuffleSampleCount -= keepFirst
        keepSamples = samples[:keepFirst]
        indicesToKeep = [s["index"] for s in keepSamples]
        shuffleSamples = shuffleSamples[keepFirst:]
    samplesToPlay = weightedShuffle(shuffleSamples, [ease((1.0 - s[keyName] if invert else s[keyName]) * multiplier, easing) for s in shuffleSamples], count=shuffleSampleCount, seed=seed)
    indicesToKeep = set(indicesToKeep + [s["index"] for s in samplesToPlay])
    for i, s in enumerate(samples):
        samples[i]["playAudio"] = (s["index"] in indicesToKeep)
    return samples

def processComposition(a, clips, videoDurationMs, sampler=None, stepTime=False, startTime=False):

    # get audio sequence
    samplerClips = sampler.getClips() if sampler is not None else []
    audioSequence = clipsToSequence(clips + samplerClips)
    stepTime = logTime(stepTime, "Processed audio clip sequence")

    # plotAudioSequence(audioSequence)
    # sys.exit()

    audioDurationMs = getAudioSequenceDuration(audioSequence)
    durationMs = max(videoDurationMs, audioDurationMs) + a.PAD_END
    print("Video time: %s" % formatSeconds(videoDurationMs/1000.0))
    print("Audio time: %s" % formatSeconds(audioDurationMs/1000.0))
    print("Total time: %s" % formatSeconds(durationMs/1000.0))

    # adjust frames if audio is longer than video
    totalFrames = msToFrame(durationMs, a.FPS) if durationMs > videoDurationMs else msToFrame(videoDurationMs, a.FPS)
    print("Total frames: %s" % totalFrames)

    # get frame sequence
    videoFrames = []
    print("Making video frame sequence...")
    for f in range(totalFrames):
        frame = f + 1
        ms = frameToMs(frame, a.FPS)
        videoFrames.append({
            "filename": a.OUTPUT_FRAME % zeroPad(frame, totalFrames),
            "ms": ms,
            "width": a.WIDTH,
            "height": a.HEIGHT,
            "overwrite": a.OVERWRITE,
            "debug": a.DEBUG
        })
    stepTime = logTime(stepTime, "Processed video frame sequence")

    rebuildAudio = (not a.VIDEO_ONLY and (not os.path.isfile(a.AUDIO_OUTPUT_FILE) or a.OVERWRITE))
    rebuildVideo = (not a.AUDIO_ONLY and (len(videoFrames) > 0 and not os.path.isfile(videoFrames[-1]["filename"]) or a.OVERWRITE))

    if rebuildAudio:
        mixAudio(audioSequence, durationMs, a.AUDIO_OUTPUT_FILE)
        stepTime = logTime(stepTime, "Mix audio")

    if rebuildVideo:
        clipsPixelData = loadVideoPixelDataFromFrames(videoFrames, clips, a.WIDTH, a.HEIGHT, a.FPS, a.CACHE_DIR, a.CACHE_KEY, a.VERIFY_CACHE, cache=True, debug=a.DEBUG, precision=a.PRECISION)
        stepTime = logTime(stepTime, "Loaded pixel data")

        processFrames(videoFrames, clips, clipsPixelData, threads=a.THREADS, precision=a.PRECISION)
        stepTime = logTime(stepTime, "Process video")

    if not a.AUDIO_ONLY:
        audioFile = a.AUDIO_OUTPUT_FILE if not a.VIDEO_ONLY and os.path.isfile(a.AUDIO_OUTPUT_FILE) else False
        compileFrames(a.OUTPUT_FRAME, a.FPS, a.OUTPUT_FILE, getZeroPadding(totalFrames), audioFile=audioFile)

    logTime(startTime, "Total execution time")

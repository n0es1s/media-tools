# -*- coding: utf-8 -*-

from math_utils import *
from moviepy.editor import VideoFileClip
import numpy as np
import os
from PIL import Image
import subprocess

def clipsToFrame(p):
    clips = p["clips"]
    filename = p["filename"]
    saveFrame = p["saveFrame"]
    width = p["width"]
    height = p["height"]
    overwrite = p["overwrite"]
    im = None
    fileExists = os.path.isfile(filename) and not overwrite

    # frame already exists, read it directly
    if not fileExists:
        im = Image.new(mode="RGBA", size=(width, height), color=(0, 0, 0, 255))

        # load videos
        filenames = list(set([clip["filename"] for clip in clips]))

        # only open one video at a time
        for fn in filenames:
            video = VideoFileClip(fn, audio=False)
            videoDur = video.duration
            vclips = [c for c in clips if fn==c["filename"]]

            # extract frames from videos
            for clip in vclips:
                videoT = clip["t"]
                cw = roundInt(clip["w"])
                ch = roundInt(clip["h"])
                # check if we need to loop video clip
                if videoT > videoDur:
                    videoT = videoT % videoDur
                # a numpy array representing the RGB picture of the clip
                try:
                    videoPixels = video.get_frame(videoT)
                except IOError:
                    print("Could not read pixels for %s at time %s" % (video.filename, videoT))
                    videoPixels = np.zeros((ch, cw, 3), dtype='uint8')
                clipImg = Image.fromarray(videoPixels, mode="RGB")
                clipImg = clipImg.convert("RGBA")
                if "alpha" in clip and clip["alpha"] < 1.0:
                    clipImg.putalpha(roundInt(clip["alpha"]*255))
                w, h = clipImg.size
                if w != cw or h != ch:
                    # clipImg = clipImg.resize((cw, ch))
                    clipImg = fillImage(clipImg, cw, ch)
                # create a staging image at the same size of the base image, so we can blend properly
                stagingImg = Image.new(mode="RGBA", size=(width, height), color=(0, 0, 0, 0))
                stagingImg.paste(clipImg, (roundInt(clip["x"]), roundInt(clip["y"])))
                im.paste(stagingImg, (0, 0), mask=stagingImg)
                stagingImg.close()
                clipImg.close()
            del video.reader
            del video

        if saveFrame:
            im.save(filename)
            print("Saved frame %s" % filename)

        im.close()

    return True

def compileFrames(infile, fps, outfile, padZeros):
    print("Compiling frames...")
    padStr = '%0'+str(padZeros)+'d'
    command = ['ffmpeg','-y','-framerate',str(fps)+'/1','-i',infile % padStr,'-c:v','libx264','-r',str(fps),'-pix_fmt','yuv420p','-q:v','1',outfile]
    print(" ".join(command))
    finished = subprocess.check_call(command)
    print("Done.")

def fillImage(img, w, h):
    ratio = 1.0 * w / h
    vw, vh = img.size
    vratio = 1.0 * vw / vh

    # first, resize video
    newW = w
    newH = h
    if vratio > ratio:
        newW = h * vratio
    else:
        newH = w / vratio
    resized = img.resize((roundInt(newW), roundInt(newH)))

    # and then crop
    x = 0
    y = 0
    if vratio > ratio:
        x = roundInt((newW - w) * 0.5)
    else:
        y = roundInt((newH - h) * 0.5)
    x1 = x + w
    y1 = y + h
    cropped = resized.crop((x, y, x1, y1))

    return cropped

# resize video using fill method
def fillVideo(video, w, h):
    ratio = 1.0 * w / h
    vw, vh = video.size
    vratio = 1.0 * vw / vh

    # first, resize video
    newW = w
    newH = h
    if vratio > ratio:
        newW = h * vratio
    else:
        newH = w / vratio
    resized = video.resize((roundInt(newW), roundInt(newH)))

    # and then crop
    x = 0
    y = 0
    if vratio > ratio:
        x = roundInt((newW - w) * 0.5)
    else:
        y = roundInt((newH - h) * 0.5)
    cropped = resized.crop(x, y, w, h)

    return cropped

# e.g. returns ['audio', 'video'] for a/v files
def getMediaTypes(filename):
    command = ['ffprobe', '-loglevel', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', filename]
    # print(" ".join(command))
    result = subprocess.check_output(command).splitlines()
    return result

def hasAudio(filename):
    return ("audio" in getMediaTypes(filename))
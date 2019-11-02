# -*- coding: utf-8 -*-

import argparse
import math
import numpy as np
import os
from PIL import Image
from pprint import pprint
import sys

from lib.audio_mixer import *
from lib.audio_utils import *
from lib.clip import *
from lib.collection_utils import *
from lib.color_utils import *
from lib.composition_utils import *
from lib.io_utils import *
from lib.math_utils import *
from lib.video_utils import *

# input
parser = argparse.ArgumentParser()
parser.add_argument('-in', dest="INPUT_FILE", default="tmp/samples_tsne.csv", help="Input file")
parser.add_argument('-dir', dest="MEDIA_DIRECTORY", default="media/sample/", help="Input file")
parser.add_argument('-props', dest="PROPS", default="tsne,tsne2", help="Properties to sort x,y matrix by; only necessary for cloud type; will use gridX,gridY for grid type")
parser.add_argument('-sort', dest="SORT", default="clarity=desc=0.5&power=desc", help="Query string to filter and sort by")
parser.add_argument('-lim', dest="LIMIT", default=-1, type=int, help="Target total sample count, -1 for everything")
parser.add_argument('-width', dest="IMAGE_W", default=3840, type=int, help="Image width in pixels")
parser.add_argument('-height', dest="IMAGE_H", default=3840, type=int, help="Image height in pixels")
parser.add_argument('-cell', dest="CELL_DIMENSIONS", default="30x30", help="Dimensions of each cell")
parser.add_argument('-count', dest="FILE_COUNT", default=12, type=int, help="Number of audio files to produce")
parser.add_argument('-cdurmax', dest="CLIP_DURATION_MAX", default=-1, type=int, help="Max duration of clip in milliseconds; -1 for not max")
parser.add_argument('-id', dest="UNIQUE_ID", default="sample", help="Key for naming files")
parser.add_argument('-type', dest="TYPE", default="grid", help="Grid or cloud")
parser.add_argument('-cached', dest="CACHE_DIR", default="tmp/sprite_{uid}_cache/", help="Grid or cloud")
parser.add_argument('-outaud', dest="OUT_AUDIO", default="ui/sprites/sprite/{uid}/{uid}.mp3", help="Output audio pattern")
parser.add_argument('-outdat', dest="OUT_DATA", default="ui/sprites/sprite/{uid}/{uid}.json", help="Output data pattern")
parser.add_argument('-outimg', dest="OUT_IMAGE", default="ui/sprites/sprite/{uid}/{uid}.png", help="Output image pattern")
parser.add_argument('-mode', dest="IMAGE_SPRITE_MODE", default="video", help="Is this a video or audio collection?")
parser.add_argument('-fingerprints', dest="FINGERPRINTS_FILE", default="", help="Path to fingerprint file (generated by samples_to_fingerprints.py) for audio sprite mode")
parser.add_argument('-log', dest="LOG", default=0, type=int, help="Display using log?")
parser.add_argument('-overwrite', dest="OVERWRITE", action="store_true", help="Overwrite existing?")
parser.add_argument('-probe', dest="PROBE", action="store_true", help="Just display durations?")
parser.add_argument('-image', dest="IMAGE_ONLY", action="store_true", help="Just output image with no audio?")
parser.add_argument('-colorful', dest="COLORFUL_IMAGES", action="store_true", help="Add background color to images?")
args = parser.parse_args()

# Parse arguments
INPUT_FILE = args.INPUT_FILE
MEDIA_DIRECTORY = args.MEDIA_DIRECTORY
SORT = args.SORT
PROP1, PROP2 = tuple([p for p in args.PROPS.strip().split(",")])
IMAGE_W = args.IMAGE_W
IMAGE_H = args.IMAGE_H
CELL_W, CELL_H = tuple([int(d) for d in args.CELL_DIMENSIONS.split("x")])
GRID_W, GRID_H = (int(IMAGE_W/CELL_W), int(IMAGE_H/CELL_H))
LIMIT = args.LIMIT
FILE_COUNT = args.FILE_COUNT
UNIQUE_ID = args.UNIQUE_ID
OVERWRITE = args.OVERWRITE
TYPE = args.TYPE
LOG = args.LOG
FPS = 30

if TYPE == "grid" and LIMIT < 0:
    LIMIT = GRID_W * GRID_H
    print("Limiting grid to %s x %s = %s" % (GRID_W, GRID_H, LIMIT))

AUDIO_FILE = args.OUT_AUDIO.format(uid=UNIQUE_ID)
MANIFEST_FILE = args.OUT_DATA.format(uid=UNIQUE_ID)
IMAGE_FILE = args.OUT_IMAGE.format(uid=UNIQUE_ID)
CACHE_DIR = args.CACHE_DIR.format(uid=UNIQUE_ID)

# Read files
fieldNames, rows = readCsv(INPUT_FILE)
rowCount = len(rows)
print("Found %s rows" % rowCount)

# Sort and limit
if LIMIT > 0 and len(rows) > LIMIT:
    rows = sortByQueryString(rows, SORT)
    rows = rows[:LIMIT]
rowCount = len(rows)

rows = addIndices(rows)
rows = prependAll(rows, ("filename", MEDIA_DIRECTORY))
for i, row in enumerate(rows):
    dur = row["dur"] if args.CLIP_DURATION_MAX <= 0 else min(args.CLIP_DURATION_MAX, row["dur"])
    rows[i]["dur"] = dur
    rows[i]["t"] = row["start"] + roundInt(dur*0.5)

# use logarithmic scale
if LOG > 0:
    for i, row in enumerate(rows):
        base = LOG if LOG > 1 else math.e
        rows[i][PROP1] = math.log(row[PROP1], base)
        rows[i][PROP2] = math.log(row[PROP2], base)

# Sort rows and add sequence
totalDur = sum([r["dur"] for r in rows])
print("Total duration: %s" % formatSeconds(totalDur/1000.0))
print("Each file will be about %s" % formatSeconds(totalDur/1000.0/FILE_COUNT))

# loaded, fingerprints = loadCacheFile(args.FINGERPRINTS_FILE)
# if loaded:
#     pprint(fingerprints[0])
#     pprint(np.ptp(fingerprints,axis=1))
#     print(np.array(fingerprints).shape)

# makeDirectories([AUDIO_FILE, MANIFEST_FILE, IMAGE_FILE, CACHE_DIR])
# loaded, fingerprints = loadCacheFile(args.FINGERPRINTS_FILE)
# if loaded:
#     audioFingerprintsToImage(fingerprints, IMAGE_FILE, cols=GRID_W, rows=GRID_H, width=IMAGE_W, height=IMAGE_H)

if args.PROBE:
    sys.exit()

# sort rows by filename to reduce number of file reads
rows = sorted(rows, key=lambda r: r["filename"])

# Make sure output dirs exist
makeDirectories([AUDIO_FILE, MANIFEST_FILE, IMAGE_FILE, CACHE_DIR])

samplesPerFile = ceilInt(1.0 * rowCount / FILE_COUNT)
audioSpriteFiles = []
sprites = [None for i in range(rowCount)]
for file in range(FILE_COUNT):
    iStart = file * samplesPerFile
    iEnd = iStart + samplesPerFile
    fileRows = rows[iStart:iEnd]
    if file >= (FILE_COUNT-1):
        fileRows = rows[iStart:]

    # build the audio
    instructions = []
    ms = 0
    for row in fileRows:
        instructions.append({
            "ms": ms,
            "filename": row["filename"],
            "start": row["start"],
            "dur": row["dur"]
        })
        sprites[row["index"]] = [file, ms, row["dur"]]
        ms += row["dur"]
    outfilename = AUDIO_FILE.replace(".mp3", ".%s.mp3" % zeroPad(file+1, FILE_COUNT))
    if not os.path.isfile(outfilename) or OVERWRITE:
        if not args.IMAGE_ONLY:
            mixAudio(instructions, ms+1000, outfilename)
    else:
        print("Already created %s" % outfilename)
    audioSpriteFiles.append(os.path.basename(outfilename))

if TYPE == "grid":

    testRow = rows[0]
    if "gridX" not in testRow or "gridY" not in testRow:
        print("You must run samples_to_grid.py first")
        sys.exit()

    # Filter out rows without valid gridX/gridY
    rows = [row for row in rows if row["gridY"] != "" and row["gridX"] != ""]

    # Sort by grid
    rows = sorted(rows, key=lambda s: (s["gridY"], s["gridX"]))
    rows = addGridPositions(rows, GRID_W, IMAGE_W, IMAGE_H)
    for i, row in enumerate(rows):
        sprites[row["index"]] += [round(1.0*row["x"]/IMAGE_W, 3), round(1.0*row["y"]/IMAGE_H, 3)]

# otherwise, just do a cloud
else:
    values1 = [row[PROP1] for row in rows]
    values2 = [row[PROP2] for row in rows]
    range1 = (min(values1), max(values1))
    range2 = (min(values2), max(values2))
    for i, row in enumerate(rows):
        nx = norm(row[PROP1], range1)
        ny = 1.0 - norm(row[PROP2], range2)
        x = roundInt((IMAGE_W - CELL_W) * nx)
        y = roundInt((IMAGE_H - CELL_H) * ny)
        rows[i]["x"] = x
        rows[i]["y"] = y
        rows[i]["width"] = CELL_W
        rows[i]["height"] = CELL_H
        sprites[row["index"]] += [round(1.0*x/IMAGE_W, 3), round(1.0*y/IMAGE_H, 3)]

rows = addIndices(rows, "gridIndex")

for i, row in enumerate(rows):
    # add label
    label = os.path.basename(row["filename"]) + " " + formatSeconds(row["start"]/1000.0) + ", index: %s" % row["gridIndex"]
    sprites[row["index"]] += [label]
    # kind of a hack: only take one frame at time
    rows[i]["start"] = row["t"]
    rows[i]["dur"] = 1

print("Generating image...")
if OVERWRITE or not os.path.isfile(IMAGE_FILE):
    if args.IMAGE_SPRITE_MODE == "audio":
        loaded, fingerprints = loadCacheFile(args.FINGERPRINTS_FILE)
        if loaded:
            # order the fingerprints according to row order
            sortedFingerprints = []
            bgcolors = None

            if args.COLORFUL_IMAGES:
                bgcolors = []

            for i, row in enumerate(rows):
                sortedFingerprints.append(fingerprints[row["index"]])
                if args.COLORFUL_IMAGES:
                    hue = norm(math.log(max(0.001, row["hz"])), (math.log(20), math.log(2000)), limit=True)
                    saturation = norm(row["clarity"], (24, 34), limit=True)
                    value = norm(row["power"], (0, 2), limit=True)
                    rgb = hsvToRgb((hue, saturation, value))
                    bgcolors.append(rgb)
            audioFingerprintsToImage(sortedFingerprints, IMAGE_FILE, cols=GRID_W, rows=GRID_H, width=IMAGE_W, height=IMAGE_H, bgcolors=bgcolors)
        else:
            print("Could not load cache file %s" % args.CACHE_FILE)
    else:
        clips = samplesToClips(rows)
        pixelData = loadVideoPixelData(clips, fps=FPS, cacheDir=CACHE_DIR, verifyData=False)
        clipsToFrame({
            "filename": IMAGE_FILE,
            "overwrite": OVERWRITE,
            "width": IMAGE_W,
            "height": IMAGE_H,
            "ms": 0,
            "verbose": True
        }, clips, pixelData)

# Write json sprite file
jsonData = {}
jsonData["audioSpriteFiles"] = audioSpriteFiles
jsonData["sprites"] = sprites
jsonData["image"] = os.path.basename(IMAGE_FILE)
jsonData["width"] = IMAGE_W
jsonData["height"] = IMAGE_H
jsonData["cellW"] = CELL_W
jsonData["cellH"] = CELL_H
writeJSON(MANIFEST_FILE, jsonData)

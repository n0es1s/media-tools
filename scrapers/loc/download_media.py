# -*- coding: utf-8 -*-

import argparse
import csv
import inspect
import json
import math
from multiprocessing import Pool
from multiprocessing.dummy import Pool as ThreadPool
import os
from pprint import pprint
import sys
import time

# add parent directory to sys path to import relative modules
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
parentdir = os.path.dirname(parentdir)
sys.path.insert(0,parentdir)

from lib.io_utils import *
from lib.processing_utils import *

# input
parser = argparse.ArgumentParser()
parser.add_argument('-in', dest="INPUT_FILE", default="tmp/loc/lc_pd_audio.csv", help="File generated by collect_metadata.py")
parser.add_argument('-out', dest="OUTPUT_DIR", default="output/loc/pd_audio/audio/", help="Directory to output files")
parser.add_argument('-overwrite', dest="OVERWRITE", action="store_true", help="Overwrite existing media?")
parser.add_argument('-probe', dest="PROBE", action="store_true", help="Just print details?")
parser.add_argument('-threads', dest="THREADS", type=int, default=3, help="How many concurrent requests?")
a = parser.parse_args()

fieldNames, rows = readCsv(a.INPUT_FILE)

if a.PROBE:
    sys.exit()

# Make sure output dirs exist
makeDirectories(a.OUTPUT_DIR)

progress = 0
rowCount = len(rows)
def processItem(item):
    global a
    global progress
    global rowCount

    destPath = a.OUTPUT_DIR + item["filename"]

    if os.path.isfile(destPath) and not a.OVERWRITE:
        return

    downloadBinaryFile(item["assetUrl"], destPath)

    progress += 1
    printProgress(progress, rowCount)

print("Downloading media...")
pool = ThreadPool(getThreadCount(a.THREADS))
pool.map(processItem, rows)
pool.close()
pool.join()
print("Done.")
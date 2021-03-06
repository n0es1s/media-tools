# -*- coding: utf-8 -*-

import numpy as np
import os
from pprint import pprint
import pyopencl as cl
import sys

from lib.clip import *

os.environ['PYOPENCL_COMPILER_OUTPUT'] = '1'

def loadMakeImageProgram(width, height, pcount, colorDimensions, precision):
    precisionMultiplier = int(10 ** precision)
    # the kernel function
    srcCode = """
    static float normF(float value, float a, float b) {
        float n = (value - a) / (b - a);
        return n;
    }

    static int4 blendColors(int4 color1, int4 color2, float amount) {
        float invAmount = 1.0 - amount;

        // x, y, z, w = r, g, b, a
        int r = (int) round(((float) color1.x * amount) + ((float) color2.x * invAmount));
        int g = (int) round(((float) color1.y * amount) + ((float) color2.y * invAmount));
        int b = (int) round(((float) color1.z * amount) + ((float) color2.z * invAmount));
        int a = (int) round(((float) color1.w * amount) + ((float) color2.w * invAmount));

        return (int4)(r, g, b, a);
    }

    static int4 setBrightness(int4 color, float brightness) {
        // x, y, z, w = r, g, b, a
        int r = (int) round((float) color.x * brightness);
        int g = (int) round((float) color.y * brightness);
        int b = (int) round((float) color.z * brightness);
        int a = color.w; // retain alpha
        return (int4)(r, g, b, a);
    }

    int4 getPixel(__global uchar *pdata, int x, int y, int h, int w, int dim, int offset);
    int4 getPixelF(__global uchar *pdata, float xF, float yF, int h, int w, int dim, int offset);

    int4 getPixel(__global uchar *pdata, int x, int y, int h, int w, int dim, int offset) {
        // check bounds; retain rgb color of edge, but make alpha=0
        bool isVisible = true;
        if (x < 0) { isVisible = false; x = 0; }
        if (y < 0) { isVisible = false; y = 0; }
        if (x >= w) { isVisible = false; x = w-1; }
        if (y >= h) { isVisible = false; y = h-1; }

        int index = y * w * dim + x * dim + offset;
        int r = pdata[index];
        int g = pdata[index+1];
        int b = pdata[index+2];
        int a = 255;
        if (dim > 3) {
            a = pdata[index+3];
        }
        if (!isVisible) {
            a = 0;
        }
        return (int4)(r, g, b, a);
    }

    int4 getPixelF(__global uchar *pdata, float xF, float yF, int h, int w, int dim, int offset) {
        if (xF < -1.0) { xF = -1.0; }
        if (yF < -1.0) { yF = -1.0; }
        if (xF > (float)(w+1)) { xF = (float)(w+1); }
        if (yF > (float)(h+1)) { yF = (float)(h+1); }

        int x0 = (int) floor(xF);
        int x1 = (int) ceil(xF);
        float xLerp = xF - (float) x0;
        int y0 = (int) floor(yF);
        int y1 = (int) ceil(yF);
        float yLerp = yF - (float) y0;

        xLerp = 1.0 - xLerp;
        yLerp = 1.0 - yLerp;

        int4 colorTL = getPixel(pdata, x0, y0, h, w, dim, offset);
        int4 colorTR = getPixel(pdata, x1, y0, h, w, dim, offset);
        int4 colorBL = getPixel(pdata, x0, y1, h, w, dim, offset);
        int4 colorBR = getPixel(pdata, x1, y1, h, w, dim, offset);

        int4 colorT = blendColors(colorTL, colorTR, xLerp);
        int4 colorB = blendColors(colorBL, colorBR, xLerp);

        int4 finalcolor = blendColors(colorT, colorB, yLerp);

        // avoid dark corners
        //if (colorT.w < 255 && colorB.w < 255) {
        //    finalcolor.w = max(colorT.w, colorB.w);
        //}

        return finalcolor;
    }

    __kernel void makeImage(__global uchar *pdata, __global int *props, __global int *zvalues, __global uchar *result){
        int canvasW = %d;
        int canvasH = %d;
        int i = get_global_id(0);
        int pcount = %d;
        int colorDimensions = %d;
        int precisionMultiplier = %d;
        int offset = props[i*pcount];
        float xF = (float) props[i*pcount+1] / (float) precisionMultiplier;
        float yF = (float) props[i*pcount+2] / (float) precisionMultiplier;
        int x = (int) floor(xF);
        int y = (int) floor(yF);
        float remainderX = xF - (float) x;
        float remainderY = yF - (float) y;
        int w = props[i*pcount+3];
        int h = props[i*pcount+4];
        float twF = (float) props[i*pcount+5] / (float) precisionMultiplier;
        float thF = (float) props[i*pcount+6] / (float) precisionMultiplier;
        float remainderW = (remainderX+twF) - floor(remainderX+twF);
        float remainderH = (remainderY+thF) - floor(remainderY+thF);
        //int tw = (int) ceil(twF);
        //int th = (int) ceil(thF);
        int tw = (int) ceil(remainderX+twF);
        int th = (int) ceil(remainderY+thF);
        float falpha = (float) props[i*pcount+7] / (float) precisionMultiplier;
        int alpha = (int)round(falpha*(float)255.0);
        int zdindex = props[i*pcount+8];
        float fbrightness = (float) props[i*pcount+9] / (float) precisionMultiplier;

        for (int row=0; row<th; row++) {
            for (int col=0; col<tw; col++) {
                int dstX = col + x;
                int dstY = row + y;

                float srcNX = normF((float) col, remainderX, remainderX+twF-1.0);
                float srcNY = normF((float) row, remainderY, remainderY+thF-1.0);
                float srcXF = srcNX * (float) (w-1);
                float srcYF = srcNY * (float) (h-1);
                //float srcXF = normF((float) col, remainderX, remainderX+twF) * (float) (w-1);
                //float srcYF = normF((float) row, remainderY, remainderY+thF) * (float) (h-1);

                if (srcNX < 0.0) { srcXF = -remainderX; }
                if (srcNY < 0.0) { srcYF = -remainderY; }
                if (srcNX > 1.0) { srcXF = (float) (w-1) + (1.0-remainderW); }
                if (srcNY > 1.0) { srcYF = (float) (h-1) + (1.0-remainderH); }

                if (dstX >= 0 && dstX < canvasW && dstY >= 0 && dstY < canvasH) {
                    int4 srcColor = getPixelF(pdata, srcXF, srcYF, h, w, colorDimensions, offset);
                    if (fbrightness < 1.0) {
                        srcColor = setBrightness(srcColor, fbrightness);
                    }
                    int destIndex = dstY * canvasW * 3 + dstX * 3;
                    int destZIndex = dstY * canvasW * 2 + dstX * 2;
                    int destZValue = zvalues[destZIndex];
                    int destZAlpha = zvalues[destZIndex+1];
                    // nothing is there yet, give it full opacity
                    if (destZIndex <= 0) {
                        destZAlpha = 255;
                    }
                    float dalpha = (float) destZAlpha / (float) 255.0;
                    float salpha = (float) srcColor.w / (float) 255.0;
                    float talpha = salpha * falpha;
                    // r, g, b, a = x, y, z, w
                    // if alpha is greater than zero and there's not already a pixel there with full opacity and higher zindex
                    if (talpha > 0.0 && (zdindex > destZValue || dalpha < 1.0)) {

                        // there's already a pixel there; place it behind it using its alpha
                        if (zdindex < destZValue) {
                            talpha = (1.0 - dalpha) * talpha;
                        }

                        // mix the existing color with new color if necessary
                        int dr = result[destIndex];
                        int dg = result[destIndex+1];
                        int db = result[destIndex+2];
                        int4 destColor = (int4)(dr, dg, db, destZAlpha);
                        int4 blendedColor = blendColors(srcColor, destColor, talpha);
                        result[destIndex] = blendedColor.x;
                        result[destIndex+1] = blendedColor.y;
                        result[destIndex+2] = blendedColor.z;

                        // assign new zindex if it's greater
                        if (zdindex > destZValue) {
                            zvalues[destZIndex] = zdindex;
                            zvalues[destZIndex+1] = blendedColor.w;
                        }
                    }
                }
            }
        }
    }
    """ % (width, height, pcount, colorDimensions, precisionMultiplier)

    return loadGPUProgram(srcCode)

def clipsToImageGPU(width, height, flatPixelData, properties, colorDimensions, precision, gpuProgram=None, baseImage=None):
    count, pcount = properties.shape

    # blank image if no clip data
    if count <= 0 and baseImage is None:
        return np.zeros((height, width, 3), dtype=np.uint8)
    # base image if exists
    elif count <= 0:
        return np.array(baseImage, dtype=np.uint8)

    properties = properties.reshape(-1)
    zvalues = np.zeros(width * height * 2, dtype=np.int32)
    result = np.zeros(width * height * 3, dtype=np.uint8) if baseImage is None else np.array(baseImage, dtype=np.uint8).reshape(-1)
    # baseImage = np.copy(result)

    ctx = prg = None
    if gpuProgram is not None:
        ctx, prg = gpuProgram
    else:
        ctx, prg = loadMakeImageProgram(width, height, pcount, colorDimensions, precision)

    # Create queue for each kernel execution
    queue = cl.CommandQueue(ctx)
    mf = cl.mem_flags

    bufIn1 =  cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=flatPixelData)
    bufIn2 =  cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=properties)
    bufInZ = cl.Buffer(ctx, mf.READ_WRITE | mf.COPY_HOST_PTR, hostbuf=zvalues)
    # bufInB =  cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=baseImage)
    bufOut = cl.Buffer(ctx, mf.READ_WRITE | mf.COPY_HOST_PTR, hostbuf=result)
    prg.makeImage(queue, (count, ), None , bufIn1, bufIn2, bufInZ, bufOut)

    # Copy result
    cl.enqueue_copy(queue, result, bufOut)
    result = result.reshape(height, width, 3)
    return result

def clipsToImageGPULite(width, height, flatPixelData, properties):
    count, pcount = properties.shape
    properties = properties.reshape(-1)
    result = np.zeros(width * height * 3, dtype=np.uint8)

    # the kernel function
    srcCode = """
    int4 getPixel(__global uchar *pdata, int x, int y, int h, int w, int dim, int offset);
    int4 getPixel(__global uchar *pdata, int x, int y, int h, int w, int dim, int offset) {
        if (x < 0 || y < 0 || x >= w || y >= h) {
            return (int4)(0, 0, 0, 0);
        }
        int index = y * w * dim + x * dim + offset;
        int r = pdata[index];
        int g = pdata[index+1];
        int b = pdata[index+2];
        return (int4)(r, g, b, 0);
    }

    __kernel void makeImageLite(__global uchar *pdata, __global int *props, __global uchar *result){
        int canvasW = %d;
        int canvasH = %d;
        int i = get_global_id(0);
        int pcount = %d;
        int colorDimensions = 3;
        int offset = props[i*pcount];
        int x = props[i*pcount+1];
        int y = props[i*pcount+2];
        int w = props[i*pcount+3];
        int h = props[i*pcount+4];
        for (int row=0; row<h; row++) {
            for (int col=0; col<w; col++) {
                int dstX = col + x;
                int dstY = row + y;
                if (dstX >= 0 && dstX < canvasW && dstY >= 0 && dstY < canvasH) {
                    int4 srcColor = getPixel(pdata, col, row, h, w, colorDimensions, offset);
                    int destIndex = dstY * canvasW * 3 + dstX * 3;
                    result[destIndex] = srcColor.x;
                    result[destIndex+1] = srcColor.y;
                    result[destIndex+2] = srcColor.z;
                }
            }
        }
    }
    """ % (width, height, pcount)

    ctx, prg = loadGPUProgram(srcCode)
    # Create queue for each kernel execution
    queue = cl.CommandQueue(ctx)
    mf = cl.mem_flags

    bufIn1 =  cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=flatPixelData)
    bufIn2 =  cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=properties)
    bufOut = cl.Buffer(ctx, mf.READ_WRITE | mf.COPY_HOST_PTR, hostbuf=result)
    prg.makeImageLite(queue, (count, ), None , bufIn1, bufIn2, bufOut)

    # Copy result
    cl.enqueue_copy(queue, result, bufOut)
    result = result.reshape(height, width, 3)
    return result

def loadGPUProgram(srcCode):
    # Get platforms, both CPU and GPU
    plat = cl.get_platforms()
    GPUs = plat[0].get_devices(device_type=cl.device_type.GPU)
    CPU = plat[0].get_devices()
    # prefer GPUs
    if GPUs and len(GPUs) > 0:
        ctx = cl.Context(devices=GPUs)
    else:
        print("Warning: using CPU instead of GPU")
        ctx = cl.Context(CPU)

    # Kernel function instantiation
    prg = cl.Program(ctx, srcCode).build()

    return (ctx, prg)

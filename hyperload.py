#!/usr/bin/env python

# SJSU - AV #

########
# CHANGELOG:
# 2016-02-15 : Working Skeleton for Flashing a Hex file to SJOne comeplete!
#
from __future__ import division
import serial
import string
import os
import time
import struct
import binascii
import math
import serial.serialutil
import logging
import sys
import argparse
import functools
from intelhex import IntelHex

APPLICATION_VERSION = '1.1'
TOOL_NAME = 'pyFLASH - HYPERLOAD'
TOOL_INFO = 'Flashing Tool for devices running the HYPERLOAD protocol'
INITIAL_DEVICE_BAUD = 38400

parser = argparse.ArgumentParser()

parser.add_argument(
    '-d',
    '--device',
    type=str,
    required=True,
    help='Path to serial device file. In linux the name should be '
    'something similar to "/dev/ttyUSB0", WSL "/dev/ttyS0", and '
    'Max OSX "/dev/tty-usbserial-AJ20A5".')

parser.add_argument(
    '-b',
    '--baud',
    type=int,
    help='bitrate/speed to send program over.',
    default=38400,
    choices=[
        4800, 9600, 19200, 38400, 57600, 115200, 230400, 576000, 921600,
        1000000, 1152000, 1500000, 2000000, 2500000, 3000000, 3500000, 4000000
    ])

parser.add_argument(
    '-c',
    '--clockspeed',
    type=int,
    help='clock speed in Hz of processor during programming.',
    default=48000000)

parser.add_argument(
    '-v',
    '--verbose',
    help='Enable version debug message output.',
    action='store_true')

parser.add_argument(
    '-a',
    '--animation',
    type=str,
    help='Choose which animation you would like to see when programming :).',
    choices=[
        "clocks",
        "circles",
        "quadrants",
        "trigrams",
        "squarefills",
        "spaces",
        "braille",
    ],
    default="clocks")

parser.add_argument(
    'hexfile',
    help='path to the firmware.hex file you want to program the board with.')

args = parser.parse_args()

if args.verbose:
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
else:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# Things to Do:
# 1. Display Platform Information                               [DONE]
# 2. Enable a Debug/Release Switch                              [DONE]
# 3. Create ~/.pyFlash and store last used options for Flashing [PEND]
# 4. Handle Exceptions                                          [PEND]
# 5. Ensure packing is done based on Endianness                 [PEND]
# 6. Re-write program with classes using this as the backbone.  [PEND]
# 7. Incorporate design decisions keeping the GUI in mind       [PEND]

# Issues Faced
# 1. Handling Bytes were hard - Use bytearray for most of the IO related functions. Difference between bytes and bytearray is that the latter is mutable.
# Bytes are types that are not mutable. Any changes done on them will
# cause a new alloc + concat and reassigning.

# Global Defines

SPECIAL_CHAR = {'Dollar': b'$', 'OK': b'!', 'NextLine': b'\n', 'STAR': b'*'}
BYTE_REFERENCE = [0xFF, 0x55, 0xAA]

## Animation stuff
ANIMATIONS = {
    "circles": [0x25D0, 0x25D3, 0x25D1, 0x25D2],
    "quadrants": [0x259F, 0x2599, 0x259B, 0x259C],
    "trigrams": [0x2630, 0x2631, 0x2632, 0x2634],
    "squarefills": [0x25E7, 0x25E9, 0x25E8, 0x25EA],
    "spaces": [0x2008, 0x2008, 0x2008, 0x2008],
    "clocks": [
        0x1F55B, 0x1F550, 0x1F551, 0x1F552, 0x1F553, 0x1F554, 0x1F555, 0x1F556,
        0x1F557, 0x1F558, 0x1F559, 0x1F55A
    ],
    "braille":
    [0x2840, 0x2844, 0x2846, 0x2847, 0x2840, 0x28c7, 0x28e7, 0x28f7, 0x28fF],
}


def printBytes(mymsg):

    print('Type info = ' + (str)(type(mymsg)))

    if (type(mymsg) == bytes) or (type(mymsg) == bytearray):
        for x in mymsg:
            print('0x{:x}'.format(x), )

        print('')
        print('Total Elements = ' + (str)(len(mymsg)))
    elif (type(mymsg) == str):
        printBytes(bytearray(mymsg))
    elif type(mymsg) == int:
        print('0x{:x}'.format(mymsg), )
    else:
        print(mymsg)
    return


def getBoardParameters(descString):
    boardParametersDict = {
        'Board': '',
        'BlockSize': '',
        'BootloaderSize': '',
        'FlashSize': ''
    }
    # Parsing String to obtain required Board Parameters
    boardParametersList = descString.split(b':')

    boardParametersDict['Board'] = boardParametersList[0]
    boardParametersDict['BlockSize'] = boardParametersList[1]
    boardParametersDict['BootloaderSize'] = (int(boardParametersList[2]) * 2)
    boardParametersDict['FlashSize'] = boardParametersList[3]

    print("\n***** Board Information ********")
    print("Board              = " + (str)(boardParametersDict['Board']))
    print("Block (Chunk) Size = " + (str)(boardParametersDict['BlockSize']) +
          " bytes")
    print("Bootloader Size    = " +
          (str)(boardParametersDict['BootloaderSize']) + " bytes")
    print("Flash Size         = " + (str)(boardParametersDict['FlashSize']) +
          " KBytes")
    print("*********************************\n")
    return boardParametersDict


def printContent(lContent):
    logging.debug("--------------------")
    count = 0
    totalCount = 0
    for x in lContent:
        print('{:2x}'.format(x))
        if count >= 10:
            print("\n")
            count = 0
        else:
            count = count + 1
        totalCount = totalCount + 1

    logging.debug("\n--------------------")
    logging.debug("Total Count = ", totalCount)
    logging.debug("--------------------")
    return


def getControlWord(baudRate, cpuSpeed):
    logging.debug("Retrieving Control Word")
    controlWord = ((cpuSpeed / (baudRate * 16)) - 1)
    return controlWord


def getPageContent(bArray, blkCount, pageSize):
    startOffset = blkCount * pageSize
    endOffset = (startOffset + pageSize - 1)
    lPageContent = bytearray(pageSize)

    for x in range(0, pageSize):
        lPageContent[x] = bArray[x + (blkCount * pageSize)]

    return lPageContent


def getChecksum(blocks):
    checksum_result = bytearray(1)
    checksum_result[0] = functools.reduce(lambda a, b: (a + b) % 256, blocks)
    # for x in blocks:
    #     lChecksum[0] = (lChecksum[0] + x) % 256
    return checksum_result[0]


def unichar(i):
    try:
        return chr(i)
    except ValueError:
        return struct.pack('i', i).decode('utf-32')


def reset_device(port):
    # Put device into reset state
    port.rts = True
    port.dtr = True
    # Hold in reset state for 0.5 seconds
    time.sleep(0.1)
    # Clear all port buffers
    port.reset_input_buffer()
    port.reset_output_buffer()
    port.flush()
    # Remove reset signal to allow device to boot up
    port.rts = False
    port.dtr = False


def Hyperload(hexfile, port, clockspeed, baud, selected_animation):
    # Convert hex file to binary
    binArray = IntelHex(hexfile).tobinarray()
    # Reset device
    reset_device(port)
    # Read first byte from bootloader serial port
    msg = bytearray(port.read(1))
    # print(msg)
    if msg[0] == BYTE_REFERENCE[0]:

        port.write(bytearray([BYTE_REFERENCE[1]]))

        logging.debug("Initial Handshake Initiated! - Received ")

        msg = bytearray(port.read(1))

        if msg[0] == BYTE_REFERENCE[2]:
            logging.debug("Received " + (str)(repr(msg)) +
                          ", Sending Control Word..")

            lControlWordInteger = int(getControlWord(baud, clockspeed))
            logging.debug(type(lControlWordInteger))
            lControlWordPacked = struct.pack('<i', lControlWordInteger)
            lControlWordPacked = bytearray(lControlWordPacked)
            msg = port.write(lControlWordPacked)

            if msg != 4:
                logging.error("Error - Sending control word failed")
            else:
                logging.debug("Sending Control Word Successful!")

                msg = bytearray(port.read(1))

                if msg[0] != lControlWordPacked[0]:
                    logging.debug(lControlWordPacked[0])
                    logging.debug(msg[0])
                    logging.error("Error - Failed to receive Control Word Ack")
                else:
                    logging.debug("Ack from SJOne received!")

                    if baud != INITIAL_DEVICE_BAUD:
                        # Switch to new BaudRate here.
                        logging.debug(
                            "Requested Baud rate different from Default. Changing Baud rate.."
                        )
                        port.baudrate = baud
                    else:
                        logging.debug("Baud rate same as Default")

                    # Read the CPU Desc String
                    msg = port.read(1)

                    if msg != SPECIAL_CHAR['Dollar']:
                        logging.error("Failed to read CPU Description String")
                        print(msg)
                        while True:
                            print(port.read(1))
                    else:
                        logging.debug("Reading CPU Desc String..")

                        CPUDescString = SPECIAL_CHAR['Dollar']
                        while True:
                            msg = port.read(1)

                            if msg == SPECIAL_CHAR['NextLine']:
                                break

                            CPUDescString = CPUDescString + msg

                        logging.debug("CPU Description String = %s",
                                      CPUDescString)

                        boardParameters = getBoardParameters(CPUDescString)

                        # Receive OK from SJOne
                        msg = port.read(1)

                        if msg != SPECIAL_CHAR['OK']:
                            logging.error("Error - Failed to Receive OK")
                        else:
                            logging.debug("OK Received! Sending Block")

                        # Send Dummy Blocks -
                        # Update : We can send the actual blocks itself.

                        # Sending Blocks of Binary File
                        totalBlocks = (len(binArray) * 1.0 / int(
                            boardParameters['BlockSize']))
                        logging.debug("Total Blocks = %f", totalBlocks)

                        paddingCount = len(binArray) - ((len(binArray)) % int(
                            boardParameters['BlockSize']))
                        logging.debug("Total Padding Count = %d", paddingCount)

                        totalBlocks = math.ceil(totalBlocks)
                        logging.info("Total # of Blocks to be Flashed = %d",
                                     totalBlocks)

                        # Pad 0's to binArray if required.
                        binArray = bytearray(binArray)
                        binArray += (b'\x00' * paddingCount)

                        blockCount = 0
                        sendDummy = False
                        #sendDummy = True
                        blockContent = bytearray(
                            int(boardParameters['BlockSize']))

                        if sendDummy == True:
                            logging.debug("FLASHING EMPTY BLOCKS")

                        while blockCount < totalBlocks:

                            blockCountPacked = struct.pack('<H', blockCount)

                            msg = port.write(bytearray([blockCountPacked[1]]))
                            if msg != 1:
                                logging.error(
                                    "Error in Sending BlockCountLowAddr")

                            msg = port.write(bytearray([blockCountPacked[0]]))
                            if msg != 1:
                                logging.error(
                                    "Error in Sending BlockCountHiAddr")

                            logging.debug("BlockCounts = %d", blockCount)

                            if sendDummy == False:
                                blockContent = getPageContent(
                                    binArray, blockCount,
                                    int(boardParameters['BlockSize']))

                            msg = port.write(blockContent)
                            if msg != len(blockContent):
                                logging.error(
                                    "Error - Failed to sending Data Block Content"
                                )
                                break
                            logging.debug("Size of Block Written = %d", msg)

                            checksum = getChecksum(blockContent)

                            logging.debug("Checksum = %d [0x%x]", checksum,
                                          checksum)

                            msg = port.write(bytearray([checksum]))

                            if msg != 1:
                                logging.error(
                                    "Error - Failed to send Entire Data Block")

                            msg = port.read(1)
                            if msg != SPECIAL_CHAR['OK']:
                                logging.error(
                                    "Failed to Receive Ack.. Retrying #%d\n" %
                                    int(blockCount))
                            else:
                                bar_len = 25
                                filled_len = int(
                                    round(bar_len * (blockCount + 1) /
                                          float(totalBlocks)))
                                #unichar(0x25FE)
                                percents = round(
                                    100.0 * (blockCount + 1) /
                                    float(totalBlocks), 1)

                                bar = ' ' * (filled_len - 1) + unichar(
                                    0x15E7) + unichar(0x2219) * (
                                        bar_len - filled_len)

                                suffix = "Block # {0}/{1} flashed!".format(
                                    blockCount + 1, int(totalBlocks))

                                sys.stdout.write('[%s] %s%% %s  ... %s\r' % (
                                    bar, percents,
                                    unichar(selected_animation[
                                        blockCount % len(selected_animation)]),
                                    suffix))
                                sys.stdout.flush()

                                blockCount = blockCount + 1

                        if blockCount != totalBlocks:
                            logging.error("Error - All Blocks not Flashed")
                            logging.error("Total = " + str(totalBlocks))
                            logging.error("# of Blocks Flashed = " +
                                          str(blockCount))
                        else:
                            logging.info("\n\n")
                            endTxPacked = bytearray(2)
                            endTxPacked[0] = 0xFF
                            endTxPacked[1] = 0xFF

                            msg = port.write(bytearray(endTxPacked))

                            if msg != 2:
                                logging.error(
                                    "Error in Sending End Of Transaction Signal"
                                )

                            msg = port.read(1)
                            logging.debug("Received Ack")
                            msg = bytearray(msg)
                            logging.debug(msg)
                            if msg != SPECIAL_CHAR['STAR']:
                                logging.error("Error - Final Ack Not Received")
                            else:
                                logging.info("\n\nFlashing Successful!")

    else:
        logging.debug(BYTE_REFERENCE[0])
        logging.debug(msg[0])
        logging.debug("(msg[0] == BYTE_REFERENCE[0]) == %s" %
                      (msg[0] == BYTE_REFERENCE[0]))
        logging.error("Timed Out!")

    port.baudrate = INITIAL_DEVICE_BAUD

    port.close()


### Main Program ###
if __name__ == "__main__":
    args = parser.parse_args()

    hex_path_length = (len(args.hexfile) + 20)
    single_dashes = str('-' * hex_path_length)

    selected_animation = ANIMATIONS[args.animation]

    print('#######################')
    print('{}'.format(TOOL_NAME))
    print('{}'.format(TOOL_INFO))
    print('#######################')
    print('Version    :  {}'.format(APPLICATION_VERSION))
    print('#######################')

    print(single_dashes)
    print('Hex File Path = "' + args.hexfile + '"')
    print(single_dashes)

    port = serial.Serial(
        port=args.device,
        baudrate=INITIAL_DEVICE_BAUD,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=10)

    Hyperload(args.hexfile, port, args.clockspeed, args.baud,
              selected_animation)

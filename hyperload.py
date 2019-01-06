#!/usr/bin/env python

# SJSU - AV #

########
# CHANGELOG:
# 2016-02-15 : Working Skeleton for Flashing a Hex file to Hyperload comeplete!
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


def port_read(number_of_bytes):
  return bytearray(port.read(number_of_bytes))


def port_read_byte():
  return bytearray(port.read(1))[0]


def port_write_and_verify(payload, error_message="", debug_message=""):
  bytes_sent = port.write(bytearray(payload))
  if bytes_sent != len(payload):
    logging.error(error_message)
    return False
  else:
    logging.debug(debug_message)
    return True


def proress_bar(bar_length, current_block, total_blocks):
  bar_len = bar_length
  filled_len = int(round(bar_len * (current_block + 1) / float(total_blocks)))

  percents = round(100.0 * (current_block + 1) / float(total_blocks), 1)

  bar = ' ' * (filled_len - 1) + unichar(0x15E7) + unichar(0x2219) * (bar_len - filled_len)

  suffix = "Block # {0}/{1} flashed!".format(current_block + 1, int(total_blocks))

  sys.stdout.write('[%s] %s%% %s  ... %s\r' % (
    bar, percents,
    unichar(selected_animation[
      current_block % len(selected_animation)]),
    suffix))

  sys.stdout.flush()


def Hyperload(hexfile, port, clockspeed, baud, selected_animation):
  # Convert hex file to binary
  binArray = IntelHex(hexfile).tobinarray()
  # Reset device
  reset_device(port)
  # Read first byte from bootloader serial port
  if port_read_byte() == BYTE_REFERENCE[0]:

    port_write_and_verify([BYTE_REFERENCE[1]])

    logging.debug("Initial Handshake Initiated! - Received ")

    sj2_device_discovered = port_read_byte()
    if sj2_device_discovered == BYTE_REFERENCE[2]:
      logging.debug("Received " + (str)(repr(sj2_device_discovered)) +
              ", Sending Control Word..")

      lControlWordInteger = int(getControlWord(baud, clockspeed))
      logging.debug(type(lControlWordInteger))
      lControlWordPacked = struct.pack('<i', lControlWordInteger)
      lControlWordPacked = bytearray(lControlWordPacked)

      if port_write_and_verify(lControlWordPacked, "Error - Sending control word failed", "Sending Control Word Successful!"):
        ackknowledge_byte = port_read_byte()

        if ackknowledge_byte != lControlWordPacked[0]:
          logging.debug(lControlWordPacked[0])
          logging.debug(ackknowledge_byte)
          logging.error("Error - Failed to receive Control Word Ack")
        else:
          logging.debug("Ack from Hyperload received!")

          if baud != INITIAL_DEVICE_BAUD:
            # Switch to new BaudRate here.
            logging.debug(
              "Requested Baud rate different from Default. Changing Baud rate.."
            )
            port.baudrate = baud
          else:
            logging.debug("Baud rate same as Default")

          # Read the CPU Desc String
          start_of_cpu_description = port_read_byte()
          if chr(start_of_cpu_description) != SPECIAL_CHAR['Dollar']:
            logging.error("Failed to read CPU Description String")
          else:
            logging.debug("Reading CPU Desc String..")

            board_description = SPECIAL_CHAR['Dollar'] + port.read_until(b'\n')
            logging.debug("CPU Description String = %s", board_description)

            boardParameters = getBoardParameters(board_description)

            # Receive OK from Hyperload
            if chr(port_read_byte()) != SPECIAL_CHAR['OK']:
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

            while blockCount < totalBlocks:

              blockCountPacked = struct.pack('<H', blockCount)

              port_write_and_verify([blockCountPacked[1]], "Error in Sending BlockCountLowAddr")

              port_write_and_verify([blockCountPacked[0]], "Error in Sending BlockCountHiAddr")

              logging.debug("BlockCounts = %d", blockCount)

              blockContent = getPageContent(binArray, blockCount,
                int(boardParameters['BlockSize']))

              port_write_and_verify(blockContent, "Error - Failed to sending Data Block Content")

              logging.debug("Size of Block Written = %d", len(blockContent))

              checksum = getChecksum(blockContent)
              logging.debug("Checksum = %d [0x%x]", checksum, checksum)

              port_write_and_verify([checksum], "Error - Failed to send Entire Data Block")

              if chr(port_read_byte()) != SPECIAL_CHAR['OK']:
                logging.error(
                  "Failed to Receive Ack.. Retrying #%d\n" % int(blockCount))
              else:
                proress_bar(25, blockCount, totalBlocks)
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

              port_write_and_verify(endTxPacked, "Error in Sending End Of Transaction Signal")

              final_acknowledge = port_read_byte()

              if chr(final_acknowledge) != SPECIAL_CHAR['STAR']:
                logging.debug(final_acknowledge)
                logging.error("Error - Final Ack Not Received")
              else:
                logging.debug("Received Ack")
                logging.info("\n\nFlashing Successful!")

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

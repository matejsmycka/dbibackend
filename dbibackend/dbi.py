import usb.core
import usb.util
import struct
import sys
import time
import argparse
import logging
import os
from enum import IntEnum
from collections import OrderedDict
from pathlib import Path


log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler(sys.stdout))
log.setLevel(logging.INFO)

BUFFER_SEGMENT_DATA_SIZE = 0x100000


class CommandID(IntEnum):
    EXIT = 0
    LIST_DEPRECATED = 1
    FILE_RANGE = 2
    LIST = 3


class CommandType(IntEnum):
    REQUEST = 0
    RESPONSE = 1
    ACK = 2


class UsbContext:
    def __init__(self, vid: hex, pid: hex):
        dev = usb.core.find(idVendor=vid, idProduct=pid)
        if dev is None:
            raise ConnectionError(f'Device {vid}:{pid} not found')

        dev.reset()
        dev.set_configuration()
        cfg = dev.get_active_configuration()

        self._out = usb.util.find_descriptor(
            cfg[(0, 0)],
            custom_match=lambda ep: usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        self._in = usb.util.find_descriptor(
            cfg[(0, 0)],
            custom_match=lambda ep: usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
        )

        if self._out is None:
            raise LookupError(f'Device {vid}:{pid} output endpoint not found')
        if self._in is None:
            raise LookupError(f'Device {vid}:{pid} input endpoint not found')

    def read(self, data_size, timeout=0):
        return self._in.read(data_size, timeout=timeout)

    def write(self, data, timeout=0):
        self._out.write(data, timeout=timeout)


def process_file_range_command(data_size, context, cache=None):
    log.info('File range')
    context.write(struct.pack('<4sIII', b'DBI0', CommandType.ACK, CommandID.FILE_RANGE, data_size))
    file_range_header = context.read(data_size)
    range_size = struct.unpack('<I', file_range_header[:4])[0]
    range_offset = struct.unpack('<Q', file_range_header[4:12])[0]
    nsp_name_len = struct.unpack('<I', file_range_header[12:16])[0]
    nsp_name = bytes(file_range_header[16:]).decode('utf-8')
    if cache is not None and len(cache) > 0:
        if nsp_name in cache:
            nsp_name = cache[nsp_name]

    log.info(f'Range Size: {range_size}, Range Offset: {range_offset}, Name len: {nsp_name_len}, Name: {nsp_name}')

    response_bytes = struct.pack('<4sIII', b'DBI0', CommandType.RESPONSE, CommandID.FILE_RANGE, range_size)
    context.write(response_bytes)

    ack = bytes(context.read(16, timeout=0))
    cmd_type = struct.unpack('<I', ack[4:8])[0]
    cmd_id = struct.unpack('<I', ack[8:12])[0]
    data_size = struct.unpack('<I', ack[12:16])[0]
    log.debug(f'Cmd Type: {cmd_type}, Command id: {cmd_id}, Data size: {data_size}')
    log.debug('Ack')

    with open(nsp_name, 'rb') as f:
        f.seek(range_offset)
        curr_off = 0
        remaining_size = range_size

        while remaining_size > 0:
        
            chunk_size = min(BUFFER_SEGMENT_DATA_SIZE, remaining_size)
            buf = f.read(chunk_size)
        
            if not buf:
                log.warning("Unexpected EOF reached before reading complete range.")
                break
        
            context.write(data=buf, timeout=0)
            curr_off += chunk_size
            remaining_size -= chunk_size


def process_exit_command(context):
    log.info('Exit')
    context.write(struct.pack('<4sIII', b'DBI0', CommandType.RESPONSE, CommandID.EXIT, 0))
    sys.exit(0)


def process_list_command(context, work_dir_path):
    log.info('Get list')

    cached_roms = OrderedDict()
    for dirName, subdirList, fileList in os.walk(work_dir_path):
        log.debug(f'Found directory: {dirName}')
        for filename in fileList:
            if filename.lower().endswith('.nsp') or filename.lower().endswith('nsz') or filename.lower().endswith('.xci'):
                log.debug(f'\t{filename}')
                cached_roms[f'{filename}'] = str(Path(dirName).joinpath(filename))

    nsp_path_list = ''
    for rom in cached_roms.keys():
        nsp_path_list += f'{rom}\n'
    nsp_path_list_bytes = nsp_path_list.encode('utf-8')
    nsp_path_list_len = len(nsp_path_list_bytes)

    context.write(struct.pack('<4sIII', b'DBI0', CommandType.RESPONSE, CommandID.LIST, nsp_path_list_len))

    ack = bytes(context.read(16, timeout=0))
    cmd_type = struct.unpack('<I', ack[4:8])[0]
    cmd_id = struct.unpack('<I', ack[8:12])[0]
    data_size = struct.unpack('<I', ack[12:16])[0]
    log.debug(f'Cmd Type: {cmd_type}, Command id: {cmd_id}, Data size: {data_size}')
    log.debug('Ack')

    context.write(nsp_path_list_bytes)
    return cached_roms


def poll_commands(context, work_dir_path):
    log.info('Entering command loop')

    cmd_cache = None
    while True:
        cmd_header = bytes(context.read(16, timeout=0))
        if not cmd_header.startswith(b'DBI0'):  # Tinfoil USB Command 0
                continue
        
        cmd_type = struct.unpack('<I', cmd_header[4:8])[0]
        cmd_id = struct.unpack('<I', cmd_header[8:12])[0]
        data_size = struct.unpack('<I', cmd_header[12:16])[0]

        log.debug(f'Cmd Type: {cmd_type}, Command id: {cmd_id}, Data size: {data_size}')

        if cmd_id == CommandID.EXIT:
            process_exit_command(context)
        elif cmd_id == CommandID.LIST:
            cmd_cache = process_list_command(context, work_dir_path)
        elif cmd_id == CommandID.FILE_RANGE:
            process_file_range_command(data_size, context=context, cache=cmd_cache)
        else:
            log.warning(f'Unknown command id: {cmd_id}')
            process_exit_command(context)


def connect_to_switch():
    while True:
        try:
            switch_context = UsbContext(vid=0x057E, pid=0x3000)
        except ConnectionError as e:
            log.info('Waiting for switch')
            time.sleep(1)
            continue
        return switch_context


def get_args(args):
    parser = argparse.ArgumentParser(
        prog='dbibackend',
        description='Install local titles into Nintendo switch via USB',
        add_help=True
    )
    parent_group = parser.add_argument_group(title='Command line params')
    parent_group.add_argument('-d','--rom-dir', type=Path, required=True,
                              help='Path to directory with NSP/NSZ/XCI files')
    parent_group.add_argument('--debug', action='store_true', default=False, required=False,
                              help='Enable debug output')
    return parser.parse_args(args)


def main():
    args = get_args(sys.argv[1:])
    if args.debug:
        log.setLevel(logging.DEBUG)

    if not Path(args.rom_dir).is_dir():
        raise NotADirectoryError('Specified path must be a directory')

    poll_commands(
        connect_to_switch(),
        work_dir_path=args.rom_dir
    )


if __name__ == '__main__':
    main()

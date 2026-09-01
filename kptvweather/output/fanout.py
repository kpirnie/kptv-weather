#!/usr/bin/env python3
"""
Transport Stream Fanout Module

Holds the single encoder output and hands it to any number of connected
clients. New clients join at the most recent PAT so their decoder sees
program tables before anything else.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# every mpeg transport stream packet is exactly this many bytes
TS_PACKET_SIZE = 188

# and every one of them starts with this sync byte
TS_SYNC_BYTE = 0x47

# hard ceiling on the join buffer, in packets, so a stream that somehow
# never emits a PAT cannot grow it without bound
MAX_JOIN_PACKETS = 4096


class Subscriber:
    """
    One connected client

    Owns a bounded queue the broker pushes into; when that queue fills the
    client is too slow to keep up and gets dropped rather than stalling
    everybody else.
    """

    def __init__(self, max_queue: int = 512):
        """
        Build the subscriber and its backing queue

        @param max_queue: int How many chunks may back up before we give up
        """

        # the outbound chunk queue and the flag that ends the read loop
        self.queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self.closed = False

    def close(self) -> None:
        """
        Mark the subscriber finished and wake its reader

        @return None
        """

        # flag it first so nothing else tries to feed it
        self.closed = True

        # then poke the reader loose with a sentinel
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass

    def read(self, timeout: float = 5.0) -> Optional[bytes]:
        """
        Pull the next chunk destined for this client

        @param timeout: float Seconds to wait before giving up
        @return bytes|None: The next chunk, or None when finished or idle
        """

        # wait for something to send
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None


class TSBroker:
    """
    Fans one transport stream out to many clients

    The encoder feeds bytes in continuously whether anybody is watching or
    not, which is what keeps this behaving like a real live channel.
    """

    def __init__(self, max_queue: int = 512, max_clients: int = 0):
        """
        Build the broker

        @param max_queue: int Per-client queue depth before a client is dropped
        @param max_clients: int Hard cap on attached clients, zero for no cap
        """

        # everything below is touched from both the reader and the http threads
        self._lock = threading.Lock()
        self._subscribers: set = set()
        self._max_queue = max(8, int(max_queue))
        self._max_clients = max(0, int(max_clients))

        # leftover bytes from a feed that did not land on a packet boundary
        self._residual = bytearray()

        # the program tables, kept as whole packets so a new client can be
        # handed them ahead of anything else
        self._pat: Optional[bytes] = None
        self._pmt: Optional[bytes] = None
        self._pmt_pid: Optional[int] = None
        self._video_pid: Optional[int] = None

        # every packet since the last keyframe, which is where new clients
        # start decoding
        self._join = bytearray()    

        # rough health signal for the status endpoint
        self._bytes_out = 0

    # ------------------------- clients -------------------------

    def subscribe(self) -> Optional[tuple]:
        """
        Register a new client and hand back its catch-up bytes

        @return tuple|None: The subscriber and the packets it should send
                            first, or None when the cap is already reached
        """

        # build it and take the current join point in the same lock so no
        # chunk can slip past between the snapshot and the registration
        sub = Subscriber(self._max_queue)
        with self._lock:

            # the cap is checked in here so two arrivals cannot both pass it
            if self._max_clients and len(self._subscribers) >= self._max_clients:
                logger.info("refused a client, already at the %s client cap",
                            self._max_clients)
                return None
            tables = bytearray()
            if self._pat:
                tables.extend(self._pat)
            if self._pmt:
                tables.extend(self._pmt)
            preroll = bytes(tables + self._join)
            self._subscribers.add(sub)

        # log the arrival so a misbehaving client is easy to spot
        logger.info("client connected (%s total)", self.client_count())
        return sub, preroll

    def unsubscribe(self, sub: Subscriber) -> None:
        """
        Drop a client and release its queue

        @param sub: Subscriber The client to remove
        @return None
        """

        # pull it out of the set first
        with self._lock:
            self._subscribers.discard(sub)

        # then close it out
        sub.close()
        logger.info("client disconnected (%s remaining)", self.client_count())

    def client_count(self) -> int:
        """
        How many clients are currently attached

        @return int: The subscriber count
        """

        # just the size of the set
        with self._lock:
            return len(self._subscribers)

    def bytes_out(self) -> int:
        """
        How many stream bytes have passed through the broker

        @return int: Running byte total since startup
        """

        # simple counter read
        with self._lock:
            return self._bytes_out

    # ------------------------- feeding -------------------------

    def feed(self, data: bytes) -> None:
        """
        Push encoder output into the broker

        Splits the incoming bytes on packet boundaries, tracks where the
        most recent PAT sits, and broadcasts whole packets to every client.

        @param data: bytes Raw output straight from the encoder
        @return None
        """

        # nothing to do on an empty read
        if not data:
            return

        # tack it onto whatever was left over last time
        self._residual.extend(data)

        # only whole packets get forwarded, so work out how many we have
        whole = (len(self._residual) // TS_PACKET_SIZE) * TS_PACKET_SIZE
        if whole <= 0:
            return

        # slice them off and keep the remainder for the next call
        chunk = bytes(self._residual[:whole])
        del self._residual[:whole]

        # a stream that lost alignment is worse than useless, so resync it
        if chunk[0] != TS_SYNC_BYTE:
            chunk = self._resync(chunk)
            if not chunk:
                return

        # update the join point and hand the chunk to everybody
        self._track_join(chunk)
        self._broadcast(chunk)

    def _resync(self, chunk: bytes) -> bytes:
        """
        Realign a chunk that does not start on a sync byte

        @param chunk: bytes The misaligned data
        @return bytes: The data from the first sync byte onward, or empty
        """

        # hunt for the next sync byte
        offset = chunk.find(bytes([TS_SYNC_BYTE]))
        if offset < 0:
            logger.warning("dropped %s bytes with no ts sync", len(chunk))
            return b""

        # note it and trim back to a whole number of packets
        logger.warning("resynced ts stream, skipped %s bytes", offset)
        trimmed = chunk[offset:]
        whole = (len(trimmed) // TS_PACKET_SIZE) * TS_PACKET_SIZE

        # anything past the last whole packet goes back on the residual
        self._residual[:0] = trimmed[whole:]
        return trimmed[:whole]

    def _track_join(self, chunk: bytes) -> None:
        """
        Keep the buffer a newly connected client needs to start decoding

        The program tables are held separately and the payload buffer starts
        over at every random access point, so a client is always handed a
        PAT, a PMT, and then a keyframe carrying its own parameter sets.

        @param chunk: bytes A whole number of transport stream packets
        @return None
        """

        # walk it packet by packet
        with self._lock:
            for offset in range(0, len(chunk), TS_PACKET_SIZE):
                packet = chunk[offset:offset + TS_PACKET_SIZE]

                # the pid is the low five bits of byte one plus all of byte two
                pid = ((packet[1] & 0x1F) << 8) | packet[2]

                # the tables are held aside rather than buffered
                if pid == 0:
                    self._pat = packet
                    self._pmt_pid = self._parse_pat(packet)
                    continue
                if self._pmt_pid is not None and pid == self._pmt_pid:
                    self._pmt = packet
                    self._video_pid = self._parse_pmt(packet)
                    continue

                # a random access point on the video is a fresh start
                if self._is_random_access(packet):
                    if self._video_pid is None or pid == self._video_pid:
                        self._join = bytearray()

                # everything else accumulates behind it
                self._join.extend(packet)

            # never let it run away if the keyframes somehow stop arriving
            if len(self._join) > MAX_JOIN_PACKETS * TS_PACKET_SIZE:
                del self._join[:-MAX_JOIN_PACKETS * TS_PACKET_SIZE]

    @staticmethod
    def _payload_offset(packet: bytes) -> Optional[int]:
        """
        Where a packet's payload begins, past any adaptation field

        @param packet: bytes One transport stream packet
        @return int|None: The payload offset, or None when there is no payload
        """

        # the adaptation field control sits in the high nibble of byte three
        control = (packet[3] >> 4) & 0x03

        # no payload at all
        if control in (0, 2):
            return None

        # payload only
        if control == 1:
            return 4

        # adaptation field then payload, so skip its declared length
        return 5 + packet[4]

    @staticmethod
    def _is_random_access(packet: bytes) -> bool:
        """
        Whether a packet carries the random access indicator

        @param packet: bytes One transport stream packet
        @return bool: True when this packet starts a random access point
        """

        # the flag only exists when there is an adaptation field with content
        control = (packet[3] >> 4) & 0x03
        if control not in (2, 3) or packet[4] == 0:
            return False
        return bool(packet[5] & 0x40)

    def _section_start(self, packet: bytes) -> Optional[int]:
        """
        Where a table section begins inside a packet

        @param packet: bytes One transport stream packet
        @return int|None: The section offset, or None when there is none here
        """

        # sections only ever start on a unit start packet
        if not packet[1] & 0x40:
            return None

        # past the adaptation field, then past the pointer field
        offset = self._payload_offset(packet)
        if offset is None or offset >= len(packet):
            return None
        return offset + 1 + packet[offset]

    def _parse_pat(self, packet: bytes) -> Optional[int]:
        """
        Read the first program's map PID out of a PAT

        @param packet: bytes A packet carrying PID zero
        @return int|None: The PMT PID, or None when it could not be read
        """

        # find the section and check it really is a PAT
        start = self._section_start(packet)
        if start is None or start + 12 > len(packet) or packet[start] != 0x00:
            return None

        # the program loop begins eight bytes into the section
        cursor = start + 8
        while cursor + 4 <= len(packet):
            number = (packet[cursor] << 8) | packet[cursor + 1]
            pid = ((packet[cursor + 2] & 0x1F) << 8) | packet[cursor + 3]

            # program zero is the network information table, not a program
            if number != 0:
                return pid
            cursor += 4
        return None

    def _parse_pmt(self, packet: bytes) -> Optional[int]:
        """
        Read the H.264 elementary PID out of a PMT

        @param packet: bytes A packet carrying the PMT PID
        @return int|None: The video PID, or None when it could not be read
        """

        # find the section and check it really is a PMT
        start = self._section_start(packet)
        if start is None or start + 12 > len(packet) or packet[start] != 0x02:
            return None

        # skip the descriptors that precede the stream loop
        info_length = ((packet[start + 10] & 0x0F) << 8) | packet[start + 11]
        cursor = start + 12 + info_length

        # then walk the streams looking for the video one
        while cursor + 5 <= len(packet):
            stream_type = packet[cursor]
            pid = ((packet[cursor + 1] & 0x1F) << 8) | packet[cursor + 2]
            es_length = ((packet[cursor + 3] & 0x0F) << 8) | packet[cursor + 4]
            if stream_type == 0x1B:
                return pid
            cursor += 5 + es_length
        return None

    def _broadcast(self, chunk: bytes) -> None:
        """
        Hand a chunk to every attached client

        @param chunk: bytes A whole number of transport stream packets
        @return None
        """

        # take a snapshot so slow clients can be evicted without mutating
        # the set we are iterating
        with self._lock:
            self._bytes_out += len(chunk)
            targets = list(self._subscribers)

        # push to each one, collecting anybody who cannot keep up
        stalled: list = []
        for sub in targets:
            if sub.closed:
                stalled.append(sub)
                continue
            try:
                sub.queue.put_nowait(chunk)
            except queue.Full:
                stalled.append(sub)

        # and cut them loose
        for sub in stalled:
            logger.warning("dropping client that fell behind")
            self.unsubscribe(sub)

    def shutdown(self) -> None:
        """
        Close every client out

        @return None
        """

        # grab them all and empty the set
        with self._lock:
            targets = list(self._subscribers)
            self._subscribers.clear()

        # then close each one
        for sub in targets:
            sub.close()

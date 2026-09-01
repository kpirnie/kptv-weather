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

    def __init__(self, max_queue: int = 512):
        """
        Build the broker

        @param max_queue: int Per-client queue depth before a client is dropped
        """

        # everything below is touched from both the reader and the http threads
        self._lock = threading.Lock()
        self._subscribers: set = set()
        self._max_queue = max(8, int(max_queue))

        # leftover bytes from a feed that did not land on a packet boundary
        self._residual = bytearray()

        # every packet since the last PAT, which is where new clients start
        self._join = bytearray()

        # rough health signal for the status endpoint
        self._bytes_out = 0

    # ------------------------- clients -------------------------

    def subscribe(self) -> tuple:
        """
        Register a new client and hand back its catch-up bytes

        @return tuple: The subscriber and the packets it should send first
        """

        # build it and take the current join point in the same lock so no
        # chunk can slip past between the snapshot and the registration
        sub = Subscriber(self._max_queue)
        with self._lock:
            preroll = bytes(self._join)
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

        Every packet carrying PID 0 is a PAT; the encoder is told to resend
        headers alongside them, so restarting the buffer there means a new
        client always gets program tables before any payload.

        @param chunk: bytes A whole number of transport stream packets
        @return None
        """

        # walk it packet by packet
        with self._lock:
            for offset in range(0, len(chunk), TS_PACKET_SIZE):
                packet = chunk[offset:offset + TS_PACKET_SIZE]

                # the pid is the low five bits of byte one plus all of byte two
                pid = ((packet[1] & 0x1F) << 8) | packet[2]

                # a PAT means we can start a fresh join point here
                if pid == 0:
                    self._join = bytearray()

                # everything gets appended to whatever the current point is
                self._join.extend(packet)

            # never let it run away if the tables somehow stop arriving
            if len(self._join) > MAX_JOIN_PACKETS * TS_PACKET_SIZE:
                del self._join[:-MAX_JOIN_PACKETS * TS_PACKET_SIZE]

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

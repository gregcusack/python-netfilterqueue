import struct
import trio


async def test_comms_without_queue(harness):
    await harness.send(2, b"hello", b"world")
    await harness.expect(2, b"hello", b"world")
    await harness.send(1, b"it works?")
    await harness.expect(1, b"it works?")


async def test_queue_dropping(harness):
    async def drop(packets, msg):
        async for packet in packets:
            if packet.get_payload()[28:] == msg:
                packet.drop()
            else:
                packet.accept()

    async with trio.open_nursery() as nursery:
        async with harness.capture_packets_to(2) as p2, \
                   harness.capture_packets_to(1) as p1:
            nursery.start_soon(drop, p2, b"two")
            nursery.start_soon(drop, p1, b"one")

            await harness.send(2, b"one", b"two", b"three")
            await harness.send(1, b"one", b"two", b"three")
            await harness.expect(2, b"one", b"three")
            await harness.expect(1, b"two", b"three")

        # Once we stop capturing, everything gets through again:
        await harness.send(2, b"one", b"two", b"three")
        await harness.send(1, b"one", b"two", b"three")
        await harness.expect(2, b"one", b"two", b"three")
        await harness.expect(1, b"one", b"two", b"three")


async def test_rewrite_reorder(harness):
    async def munge(packets):
        def set_udp_payload(p, msg):
            data = bytearray(p.get_payload())
            old_len = len(data) - 28
            if len(msg) != old_len:
                data[2:4] = struct.pack(">H", len(msg) + 28)
                data[24:26] = struct.pack(">H", len(msg) + 8)
                # Recompute checksum too
                data[10:12] = b"\x00\x00"
                words = struct.unpack(">10H", data[:20])
                cksum = sum(words)
                while cksum >> 16:
                    cksum = (cksum & 0xFFFF) + (cksum >> 16)
                data[10:12] = struct.pack(">H", cksum ^ 0xFFFF)
            # Clear UDP checksum and set payload
            data[28:] = msg
            data[26:28] = b"\x00\x00"
            p.set_payload(bytes(data))

        async for packet in packets:
            payload = packet.get_payload()[28:]
            if payload == b"one":
                set_udp_payload(packet, b"numero uno")
                packet.accept()
            elif payload == b"two":
                two = packet
            elif payload == b"three":
                set_udp_payload(two, b"TWO")
                packet.accept()
                two.accept()
            else:
                packet.accept()

    async with trio.open_nursery() as nursery:
        async with harness.capture_packets_to(2) as p2:
            nursery.start_soon(munge, p2)
            await harness.send(2, b"one", b"two", b"three", b"four")
            await harness.expect(2, b"numero uno", b"three", b"TWO", b"four")

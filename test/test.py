# SPDX-License-Identifier: Apache-2.0
"""Loads programs/uart_tx.hex through the parallel loader, sends bytes, decodes TX like a UART receiver."""
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

DIV = 4                    # fast tick for simulation; the silicon default is 54
CPB = 8 * DIV              # clocks per UART bit (8 ticks per bit)
LOAD_EN, WR, STROBE = 0x01, 0x02, 0x04


def load_image():
    words = [int(t, 16) for t in (Path(__file__).parent.parent / "programs" / "uart_tx.hex").read_text().split()]
    assert len(words) == 65, "expected a 65-word loader image"
    words[64] = DIV
    return words


def tx_bit(dut):
    try:
        return int(dut.uo_out.value) & 1
    except ValueError:      # X/Z before reset: treat as idle high
        return 1


async def write_byte(dut, value):
    dut.ui_in.value = value
    dut.uio_in.value = LOAD_EN | WR
    await ClockCycles(dut.clk, 4)
    dut.uio_in.value = LOAD_EN
    await ClockCycles(dut.clk, 4)


async def send_and_capture(dut, byte, ticks_after=140):
    dut.ui_in.value = byte
    await ClockCycles(dut.clk, 3 * DIV)
    dut.uio_in.value = 0x00                      # strobe low
    await ClockCycles(dut.clk, 5 * DIV)
    dut.uio_in.value = STROBE                    # strobe rising edge: byte valid
    samples = []
    for _ in range(ticks_after * DIV):
        await ClockCycles(dut.clk, 1)
        samples.append(tx_bit(dut))
    return samples


def decode(samples):
    for i in range(1, len(samples)):
        if samples[i - 1] == 1 and samples[i] == 0:          # start bit
            mid = [samples[i + k * CPB + CPB // 2] for k in range(10)]
            assert mid[0] == 0 and mid[9] == 1, "framing error"
            return sum(b << k for k, b in enumerate(mid[1:9]))
    raise AssertionError("no start bit seen")


@cocotb.test()
async def test_uart_tx_program(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = LOAD_EN
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    for word in load_image():
        await write_byte(dut, word & 0xFF)
        await write_byte(dut, word >> 8)

    dut.ui_in.value = 0
    dut.uio_in.value = STROBE                    # LOAD_EN low: run, strobe idle high
    await ClockCycles(dut.clk, 6 * DIV)

    for byte in (0xA5, 0x3C, 0x00, 0xFF):
        got = decode(await send_and_capture(dut, byte))
        dut._log.info(f"sent 0x{byte:02X}, decoded 0x{got:02X}")
        assert got == byte
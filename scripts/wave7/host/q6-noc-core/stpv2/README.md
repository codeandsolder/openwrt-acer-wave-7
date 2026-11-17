# Wave 7 MIPI STPv2 offline decoder

The ETR file is first demultiplexed into CoreSight ATID streams using
`../decode-coresight-etr.py`. The WBE1.3 UMACNOC ATID `0x39` stream
contains a **second protocol layer**, MIPI STPv2.

Rather than guessing 16-byte records, this uses the unchanged upstream
decoder from Zephyr, pinned at
`29d3d75b7ef638a5323815fa94f78af54c96d1a5` (Apache-2.0).
The two upstream source files are byte-identical to that Git revision.
`include/zephyr/kernel.h` is a small standalone compatibility shim.

`stpv2_offline.c` reports opcode counts, master/channel context and
an optional event CSV. It **does not** assign Qualcomm NoC RouteIds
or infer packet meaning from ATID. It uses the full available upstream
decoder, including explicit reporting of unsupported STPv2 opcodes.

Compile from this directory with the existing sccache server,
placing the executable in the experiment's research directory:

```sh
mkdir -p /home/jan/research/wave7-qdss-20261117/stpv2/bin
SCCACHE_SERVER_PORT=4228 sccache clang -O2 -std=c11 \
  -Wall -Wextra -Werror -Wno-unused-function -Wno-unused-parameter \
  -I include upstream/mipi_stp_decoder.c stpv2_offline.c \
  -o /home/jan/research/wave7-qdss-20261117/stpv2/bin/stpv2_offline
```

Then run against an already-demultiplexed stream:

```sh
STPV2_EVENTS_TSV=events.csv \
  /home/jan/research/wave7-qdss-20261117/stpv2/bin/stpv2_offline \
  coresight/trace-id39.bin > opcode-counts.txt 2> opcode-samples.txt
```

The seventh trial's original SHA256-pinned 1MiB ETR binary is archived
on Asus under
`/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss/runs/qdss-64ef394b1e-20261117-080130/evidence/proactive-etr-probe/`.
Its demultiplexed ATID0x39 stream SHA256 is
`1f9e43a7f364480d7961a07ab8507e874368d7f87e4304b7e8c3b23396168104`.

The offline CSV records all decoded events, including NULL filler and
unsupported-opcode indicators. For a paired same-boot ETR comparison,
decode the two raw snapshots separately with the CoreSight deformatter,
run this STPv2 adapter once on each extracted ATID stream, then compare:

```sh
uv run --no-project python -B compare_events.py \
  idle-events.csv wlan-load-events.csv \
  --output stpv2-differential.json
```

The comparison normalizes decoded data packet frequencies rather than
pretending to reconstruct absolute time spans across a wrapping ETR.
It ranks packet payloads enriched or depleted in the traffic sample;
a payload differential is not automatically a NoC RouteId.

The Zephyr STPv2 decoder explicitly does not implement all uncommon
opcodes. Unsupported events are reported rather than guessed.
MERROR or discontinuous timestamps also mean the capture cannot be
treated as a lossless, totally ordered record of transactions.

Prior art:
- [MIPI STP](https://www.mipi.org/specifications/stp)
- [Zephyr STPv2 decoder](https://docs.zephyrproject.org/latest/services/debugging/mipi_stp_decoder.html)
- [ARM STM-500 source and framing](https://documentation-service.arm.com/static/5f106ed80daa596235e81fcc)

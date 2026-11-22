# 0497: warm down-edge host-mode preparation

## Discriminator

On 0496, two failed 2500→1000 transitions showed C22.31 changing
from a544 to 8544 before phylib reports down, and remaining SGMII
until copper and phylib report up. In the two captures, SGMII
preceded copper up by 2.274 and 1.907 seconds respectively.
The second resolved C22.17 value (bd1c) matched a prior healthy 1G
sample. The stock ARM replay applies wrapper-mode changes on down
edges and invalidates cached speed/duplex. There is no matched
successful transient trace, so this evidence identifies a testable
timing difference, not the cause of the blackhole.

## Policy

On the actual Wave7 QCA8081 address 24, publish only a valid raw
SGMII report on a genuine falling edge with both copper indications
down, from a formerly running 2500BASEX connection. No synthetic
carrier or guessed speed. The board/PHY-scoped phylink experiment
permits major configuration while down; retry failed early config
on genuine up. The generic resolver additionally refuses to consume
a pending major config on forced-down passes with only the link bit
initialized.

The exclusive MPPE PCS instance at 0x7a10000 consumes a one-shot
warm preparation on the subsequent matching SGMII up, retaining
resolved-speed programming and the adapter pulse. Reset, explicit
config, enable/disable and link-up invalidate state. Cold SGMII
and ordinary same-mode reconnect policy are retained.

The fixture extracts actual PHY, phylink and PCS C callbacks.
MDIO, registers, phylink major config and mode calibration are
mocked; this is not hardware validation. See test-policy.py.

## Reproduce

From this worktree, with the existing exact predecessor builds.
The 0495/0496 proof JSONs are independently hash-pinned. The actual
0496 kernel and PCS are rebuilt and compared with exact archived
artifacts; 0491/0495 need not be relinked again. The previous full
lineage rebuild reached the 0491 normalized match but timed out
during 0495 linking under shared build load.
```sh
b=/home/jan/build/wave7
uv run --no-project --offline --python /usr/bin/python3 \
  scripts/wave7/host/qca8081-stock-poll-fifo/down-mode/build-kernel-and-pcs.py \
  "$b/qca8081-stock-poll-fifo" "$b/qca8081-instant-fifo/verified-kernel" \
  "$b/qca8081-independent-fifo/verified-kernel" "$b/qca8081-down-mode/verified"
```

The packer at ../build-trial-image.sh must use the exact approved
0491 image and accepted build. The intended root delta is the PCS
module plus five identity files; PPE, native RTL8367D module, radio
firmware and DTB are unchanged. Deploy only through a new pinned
guard profile with exact 0491 rollback.

## Hardware gate

First complete the unchanged cold-boot/300s soak gate at 2.5G.
Then capture raw mode and genuine down/up edges through a guarded
2.5G→1G transition. Require PHY down-mode marker, host preparation
and successful result before *raw copper-up*, followed by PCS
preparation reuse at link-up. A preparation marker alone does not
prove the intervention occurred on down, because a warm major
config can run on up if the early edge was missed. Compare actual
bidirectional counter changes and loss-free independent paths.
A passing changed-speed trial does not qualify same-speed reconnect,
which still follows the previous policy. Never approve failed
candidates; retain exact 0491 rollback.

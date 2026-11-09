# Acer Wave 7: controlled U-Boot RAM boot

This describes a future **UART-controlled** test of the Linux 6.18.60 FIT,
without writing the router's NAND. It is not a procedure to execute over
the currently running 6.18.55 SSH connection: that kernel has neither
kexec nor a usable device-tree-overlay interface. The known-working
two-link WPA3-SAE MLO router should remain in service until the UART
and test host are actually available.

## Evidence and prepared artifacts

The 2026-10-28 factory APPSBLENV NAND backup (not a current environment
dump) contains: bootcmd=bootipq, bootdelay=5, baudrate=115200,
stdin/stdout/stderr=serial@78AF000, ipaddr=192.168.10.10 and
serverip=192.168.10.1. There is no netconsole configuration in that
backup. Five seconds is the historical U-Boot interruption window, not a
guarantee that newer firmware retains the same delay.

Acer build tree:
`/home/jan/projects/acer-wave7-openwrt-current`

Asus raw RAM-boot FIT:
`/home/jan/firmware/wave7/trials/wave7-aaf6bbd7da.itb`

- **Linux:** 6.18.60, image revision aaf6bbd7da
- **Size:** 17,563,648 bytes
- **SHA-256:** 557acd68b88e95e565f2726fac38ff87c4c2522f54512477493d729633ef5ec1
- **FIT default:** config@mi04.1-c2, ARM64 kernel load/entry 0x41000000
- **DTB:** IPQ5332 Acer Wave 7 with QPIC/BAM and qcom,smem-part enabled
- **Root:** embedded initramfs with the private 45-file Qualcomm radio
  firmware set and known-working wired/MLO UCI configuration

The separate `wave7-current-61860-aaf6bbd7da-smem.bin` is a
**NAND-writing vendor sysupgrade package**, not suitable for TFTP+bootm.

## Actual hardware boot session

1. Attach a suitable 3.3 V UART **data and ground only** to the actual
   Wave 7 bootloader UART; confirm the correct header pinout. Use
   115200 baud, 8N1. Do not guess the physical UART pinout or supply
   power over the serial adapter.
2. Put the raw FIT above under the TFTP server root on a host reachable
   from U-Boot's active Ethernet interface. Test that host's UDP/69
   serving, its link, and the exact file and checksum. **Do not assume
   that Linux's Redmi-routed management interface is U-Boot's Ethernet
   device.** Asus is currently `10.1.0.200` via Wi-Fi; Redmi is
   `10.1.0.2` on that network and `192.168.76.2` facing Wave 7.
3. Reboot only during a supervised maintenance window, interrupt the
   bootloader at its prompt, and check `help tftpboot`, `help bootm`,
   `printenv ipaddr serverip gatewayip netmask ethact`.
4. Set *volatile* IP values for the verified link with `setenv`, not
   `saveenv`. For example, if the U-Boot Ethernet port actually reaches
   a TFTP host directly at 192.168.76.2, set
   `ipaddr=192.168.76.1`, `serverip=192.168.76.2` and the
   appropriate `netmask`. For a routed host, also set a correct
   `gatewayip`; verify with U-Boot `ping` before TFTP.
5. With confirmed networking, the intended RAM-only commands are:

   ```text
   tftpboot 0x44000000 wave7-aaf6bbd7da.itb
   iminfo 0x44000000
   bootm 0x44000000#config@mi04.1-c2
   ```

   The chosen 0x44000000 TFTP staging address is within the board's
   reported 0x40000000–0x60000000 RAM window, separate from the
   0x41000000 FIT kernel load address and recorded Q6 reserved regions.
   Check the live U-Boot `bdinfo` memory map before using it.
6. From Asus, capture the first boot with the repo's
   `wave7-openwrt-watch.sh <tag> 6.18.60 aaf6bbd7da`; inspect
   `RADIO_MLO_READY` and `NAND_SMEMPART_READY` separately. The
   latter verifies all 27 recorded factory NAND partitions by name,
   size and erase geometry. Test external MT7925 two-link WPA3-SAE
   after the driver and hostapd start.

Neither these commands nor `setenv` with no `saveenv` flash NAND.
The bootloader's own boot/recovery behavior still has to be observed
on the physical UART before treating a failed test as recoverable.

## Alternative: existing supervised vendor OTA

Without UART, the established `wave7-trial-flash.sh` workflow is the
alternative. That workflow **writes NAND** and requires a deliberate
return to vendor Linux 5.4.213 with `bootfail=0`; it arms independent
OpenWrt and fallback/pstore observers before issuing sysupgrade.
Do not mistake a prepared OTA image for having performed this test.

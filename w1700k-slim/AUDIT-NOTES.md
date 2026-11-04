# W1700K Slim 6.18.60 UBI2 audit candidate

Build success is software validation, not hardware validation. This candidate has
not been booted on the owner's router. No router flashing or public Release is
performed by this workflow. Artifacts inherit the repository's access settings.

## Components

- Board `gemtek,w1700k-ubi`, Airoha AN7581, existing UBI2 layout, compatibility 2.0.
- Source `d7643c564903fbf32506e836b96e7f86d42dc091`, Linux 6.18.60 with native
  MT76 and Airoha patches. W1700K partition DTS, platform.sh, fit.sh, nand.sh and
  default network mapping are unchanged from the previous Slim source.
- OpenClash 0.48.002, official Mihomo v1.19.33, Argon, Chinese LuCI, UPnP,
  irqbalance, Fan Control, Airoha SoC/NPU, File Manager, nohup and etherwake CLI.
- New ethtool-full and the one-shot read-only `w1700k-health` command.
- Actual calculated kernel ABI; no external vermagic override, unrelated MT7992
  firmware, bootloader build, FRP, Homebridge runtime or personal configuration.
- Feeds remain pinned. No unverified rolling APK feed is enabled; kernel modules
  installed later must match the exact build ABI.
- No automatic CPU overclock, radio, WAN, fan or offload tuning.

## Evidence and changes

The running 6.18.55 image had nearly 20 days uptime, approximately 1.4 GiB available
RAM and 42% overlay usage. Retained logs showed no kernel panic, OOM or wireless
MCU crash. Both active radios had associated clients. This is a sampled audit,
not proof that every workload is fault-free.

1. **Confirmed DNS conflict:** dnsmasq rejected the proxy's ULA fake AAAA answers.
   A guarded first-boot migration changes only the observed
   `fdfe:dcba:9876::1/64` range to OpenClash's supported `2001:2::1/64`, and only
   when this board, fake-IP mode, IPv6 options and rebind protection match.
   Rebind protection and IPv6 remain enabled; other ranges/modes are untouched.
   Mock tests cover guards, idempotence and commit failure/retry. The fix has not
   been applied to the current router or runtime-verified on this image.
2. **No component downgrade:** the old recipe baked OpenClash 0.47.156/Mihomo
   1.19.32, while the router already uses 0.48.002/1.19.33. New pins match those.
3. **Network maintenance:** new native upstream changes cover TRTCM retry,
   TX-ring BQL, DMA mapping, receive-size handling and MIB counter accounting.
   WAN reported about 0.25% cumulative receive discards and 543 receive errors
   that did not increase during the audit. This alone does not prove Internet
   packet loss or demonstrate that a particular upstream patch fixes it.
4. **Build time:** up to four jobs bounded by CPU/RAM, with verified downloads and
   compiler cache. The first build has no warm cache and may still take hours.

An unconnected temperature channel reports 127.875 C with its fault flag set.
The existing fan UI already excludes it; no fan bug fix is claimed. The health
command labels faulted sensors unavailable. Real temperatures and automatic fan
operation were normal. LuCI 403 login and proxy 407 authentication responses
were confirmed expected. New kernel/MT76/NPU code still needs physical testing.

## Private backup and upgrade boundaries

The recipe contains no credentials, subscriptions, SSH host keys, device tokens
or Homebridge pairing data. Keep private backups on the owner's local disk.
Standard sysupgrade backup misses the manual `/data` scripts, Homebridge state
and runtime, and manual OUI icon integration. Preserve these separately before
any later upgrade; the Homebridge runtime is about 297 MiB uncompressed and must
not be added wholesale to the ordinary sysupgrade backup. Restore application
data selectively with the original runtime/plugin versions; do not overwrite a
new kernel's package tree with a complete old overlay. Recheck Homebridge and
the DHCP icons after restoration. See the local audit/backup inventory.

## Validation and later acceptance

The build gates check the board, UBI2 compatibility, FIT/DT and partition layout,
kernel, source SHA, package ABI and manifest, rootfs exclusions, and unchanged
Mihomo bytes plus QEMU execution. Shallow source metadata is `r0-d7643c5`; the
human-facing version is `r38126-d7643c5649`; full source SHA is recorded separately.

After separate authorization to install, check SHA256SUMS and `sysupgrade -T`;
never force a rejected image. After boot check board ID, squashfs /rom and UBIFS
/overlay, WAN/LAN negotiation, both active radios, DNS A/AAAA through port 53,
authenticated proxy HTTPS, IPv6, UPnP, fan, SSH/LuCI and restored private apps.
Client DNS caches may need to expire after the fake IPv6 range changes. Compare
two health snapshots and retained logs. Keep the old image and private backup
for recovery. No throughput, radio load, reboot or hardware test has run here.

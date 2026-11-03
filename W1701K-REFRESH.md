# W1701K 6.18.60 GT build

Use **Build W1701K 6.18.60 GT Hybrid (Lite RAM + OpenClash Flash)** in GitHub Actions.
All firmware compilation and Linux patch preparation run on the Ubuntu Actions runner.
The original 6.18.44 workflow and releases remain available.

This workflow is manual-only (`workflow_dispatch`). The requested audit/frpc
rebuild includes the CPUFreq/PHY telemetry patches below. These kernel changes
have not been boot-tested on the user's router. See
[the system audit](W1701K-SYSTEM-AUDIT-20261103.md) for confirmed findings,
configuration-only observations and the hardware acceptance boundary.

Both image configurations now exclude `luci-app-airoha-flowsense`,
`luci-app-mlo` and `luci-app-wifi7`. FlowSense provides PPE/NPU monitoring and
its npu-jitter background monitor; the other two packages provide additional
wireless/MLO management pages. Their removal does not remove Airoha NPU/PPE,
MT7996, EHT/802.11be or wpad support. Standard LuCI Network/Wireless, SoC Status,
Fan Control and OpenClash (full BIN) remain. MLO driver capability remains;
the dedicated MLO configuration pages are omitted. This is package selection,
not a change to live radio configuration. Defconfig and actual-image audits
reject reintroduction of the three apps and check the standard wireless page.
FlowSense source is still imported for the shared compatibility patch but is
not selected for installation.

The full sysupgrade BIN additionally includes official `frpc` 0.71.0,
`luci-app-frpc` and Simplified Chinese translation from the pinned feeds.
The existing router runs the same upstream init implementation, including
file-based token sources and HTTPS bridge plugins; its init is not replaced
with an older generator. Fresh-install defaults contain no sample proxy or
credentials and disable the service once using a factory-only marker. A kept
user configuration has no marker, so its service enable state is retained.
`/lib/upgrade/keep.d/frpc` preserves `/etc/config/frpc`, all of `/etc/frp/`
(token, TOML fragments and certificates), and an existing local
`/usr/bin/frpc-watchdog` helper. Only paths are published, never their contents.
The new keep rules only take effect when upgrading **from** this new firmware.
Before the first upgrade from the current r6 image, separately back up or add
`/etc/frp/` and `/usr/bin/frpc-watchdog` to that old system's backup list.
Nothing in this rebuild changes the old router's backup list.
BusyBox flock support remains available for the retained helper. CI executes
the actual init generator with non-secret fixtures and tests the built ARM64
frpc version, valid generated TOML and rejection of invalid configuration.
The Lite RAM recovery ITB omits frpc and its LuCI app to retain the 20 MiB limit.

In the current source, Airoha Ethernet/NPU and MT7530/MMIO drivers are built
into the kernel. Their old vendor kmod package names are no longer selected;
the configuration and image audits require the corresponding kernel features.
The old vendor `bridge-flow-offload` userspace package and bridge-family
flowtable extension are not present in this source. Routed PPE/NPU support is
retained; no unsupported bridge nftables rules are generated at boot.
Two unselected feed menus (fwknopd LuCI and squeezelite) are excluded from feed
installation because their optional Kconfig dependencies currently form cycles.

This build pins the current Airoha source and feeds, OpenClash 0.48.002 and
Mihomo 1.19.33. The current Airoha tree no longer carries W1701K; the preparation
script restores its previously tested NAND layout, calibration extraction,
LAN/WAN mapping and PCIe x2 fix. Hardware application pages retain the compatible
reference pack and W1701K adaptations. CPU frequency remains at stock settings.

Fresh-install defaults:

- LAN address: `10.98.0.1/24`.
- Wi-Fi SSID: `GT` on 2.4 GHz and 5 GHz, enabled.
- Country: `CN`; 6 GHz remains disabled.
- WPA2/WPA3 mixed mode; the key comes from Actions secret `W1701K_WIFI_PASSWORD`.
- The secret is injected into the firmware; it is omitted from public source,
  diagnostic artifacts and release text. Firmware downloads contain the configured key.

Apply these defaults by installing **without keeping old configuration**. First
RAM-boot the Lite ITB and run `w1701k-hwcheck`; a successful build alone does not
verify boot, radio operation, physical port mapping or flash compatibility.
The full BIN contains OpenClash/Mihomo; the RAM ITB omits the large proxy userland.
The workflow checks that both images use identical kernel ABI and kernel modules.

Release is additionally gated on auditing the actual sysupgrade tar/SquashFS and
the RAM ITB's embedded XZ/CPIO root. The reports check W1701K metadata, original
NAND layout, PCIe x2, RAM size, FIT component hashes, the 16 MiB kernel limit,
ARM64 ELF architecture/library dependencies, module vermagic, hardware firmware,
management/network executables, private wireless key permissions and Mihomo's
version under ARM64 emulation. HTTPS management dependencies are explicitly selected.

On the actual device, run `w1701k-acceptance --image /tmp/sysupgrade.bin` from
RAM before deciding to flash. It includes `w1701k-hwcheck`, verifies the running
LAN/GT wireless interfaces, local DHCP/DNS/HTTP/HTTPS/SSH services, and performs
`sysupgrade -T`. It does not flash or change configuration. Client DHCP leases,
WAN/PPPoE, wired link speeds and sustained wireless/load tests remain physical
acceptance steps; CI cannot establish that they work on the user's hardware.


## 6.18.60 mixed-FEM correction (2026-11-03)

The recovery r2-1 image boots but the tested W1701K rejects its factory
EEPROM. On hardware, ADIE0/1/2 are `79758a02 / 79778a10 / 79778a10`,
`MT_PAD_GPIO=00008400`, and the factory FEM fields at EEPROM 0x196/0x197
are `0 / 3`. mt76 0936617d reads ADIE0, classifies the board as all-iFEM,
and replaces the factory data with the all-iFEM default. The live FEM fields
become `0 / 0`. A strong client signal therefore does not establish correct
radio operation. Other channel/interoperability effects remain to be measured.

The new package patch selects ADIE1 only for `gemtek,w1701k` on the MT7996
chip. It retains EEPROM validity checks and leaves other devices unchanged.
A global ADIE1 change is inappropriate: upstream discussion documents an
all-iFEM Zyxel variant that regresses with that change.

- [Original W1701K patch report](https://lkml.rescloud.iu.edu/hypermail/linux/kernel/2511.1/01728.html)
- [Mixed/all-iFEM register comparison](https://lists.infradead.org/pipermail/linux-arm-kernel/2025-December/1089883.html)

CI compiles and executes the actual pinned driver C functions with register
fixtures. The old driver must reproduce the failure; the patched driver must
accept mixed-FEM factory fields, reject wrong FEM/stream counts, and preserve
other chip/board and MCU-error paths. Image audits repeat this test on the
actual prepared source and check that the compiled module contains the fix.
The new `w1701k-calibration-check`, also included in `w1701k-acceptance`,
fails if live FEM differs from factory, EEPROM fallback is logged, or the
W1701K driver marker is missing. Whole EEPROM hashes are not required to match:
the driver legitimately merges chip efuse calibration bytes before upload.

The release remains a hardware-unvalidated candidate until RAM boot, live
calibration checks and sustained LAN throughput tests pass. No client-specific
EEPROM, factory partition, MAC address or wireless key is committed to GitHub.


## CPUFreq and PHY telemetry correction (2026-11-03)

Hardware acceptance after the Wi-Fi correction found two separate gaps:
`cpufreq_policy_online: ->get() failed` left policy0 absent although the PLL
reported a valid clock; the upstream EN8811H driver exported no temperature
sensor, while the fan RPC and view converted missing readings into 0 C.

The statusfix build keeps the same pinned 6.18.60 source and Wi-Fi calibration
fix. It adds a W1701K-only PM-domain PLL fallback, based on upstream fork
commit `9505125c96ef9b43f54ecb32bcbac5334a10f94a`. The working SMC path remains
preferred. The fallback accepts only the 15 stock states, 500-1200 MHz, and
checks the state before writing registers. The board DT supplies the named
SCU/MCUCFG resources. Existing CPUFreq domain-attachment APIs are retained;
the obsolete downstream duplicate Kconfig/backport blocks are not copied.

EN8811H gains a read-only hwmon temperature channel using MediaTek's documented
MCU command (MMD 30: 0x800e=0x1100, 0x800f=0xe5; PBUS 0x3b38 in degrees C).
The driver serializes requests with phylib, checks MCU readiness, propagates
MDIO failures and rejects out-of-range data. hwmon registration failure does
not disable Ethernet. Fan RPC finds sensors by their parent PHY device and
preserves null for unavailable data; the UI distinguishes missing data from a
valid 0 C. The CPU page can show a measured PLL clock if CPUFreq is unavailable,
without inventing a governor or maximum frequency. No fan-control policy is
changed. Direct-PLL overclock controls, their RPC method and the /dev/mem ACL
are removed: multi-command userspace register writes bypass CPUFreq's kernel
serialization. Governor and stock maximum-frequency controls remain.

An inherited out-of-table PLL value (for example 1400 MHz) is reported at its
actual value without clipping it to 1200. The PM-domain emits a warning;
cpufreq-dt's CPUFREQ_NEED_INITIAL_FREQ_CHECK then selects a supported frequency
from the unchanged 500-1200 MHz table. Fixture tests verify a read-only 1400 MHz
measurement and subsequent stock transitions. This does not alter the running
router; behavior of the new kernel must still be checked during RAM boot.

The SoC view uses neutral GDM/Ethernet-DMA labels instead of W1700K's
hardcoded 1G/10G LAN/WAN map. Its NPU indicator reports driver binding, not
proof of active traffic offload. PPE translations/MAC fields are blank until
an entry is bound; UNB original tuples remain available for diagnosis. Both
RPC and UI fixtures cover the distinction, and image audits require the
updated RPC and absence of the removed overclock method.

CI executes the actual prepared C functions with register/MDIO fixtures,
including every stock OPP, divider/bit preservation, out-of-range rejection
without writes, sensor units/zero/negative readings, errors and lock release.
It also tests the real shell parser/sensor discovery and JavaScript rendering.
Image audits verify DT resources, compiled kernel/PHY feature markers and the
included acceptance/UI files. LuCI's authenticated-login 403 response is now
recognized only when the expected header and login form are present.

After boot, run `w1701k-monitor-check` (also part of `w1701k-acceptance`). It
requires a live CPUFreq policy and valid readings from both PHY sensors.
Compilation and fixture tests do not establish physical sensor accuracy or
safe frequency transitions on this unit: RAM boot and hardware acceptance are
still required. Live settings, CPU registers and fan curves are not modified
by this build task.

References:
- https://github.com/OpenWRT-fanboy/OpenW1700k/commit/9505125c96ef9b43f54ecb32bcbac5334a10f94a
- https://github.com/mediatek/mtk-openwrt-feeds/blob/a7ace89b5c4d50ae2ef92690c32a0d37a65b6ca3/21.02/files/target/linux/mediatek/files-5.4/drivers/net/phy/air_en8811h_api.c

## Candidate NPU RX ring backport (2026-11-03)

The current device logged a warning in an NPU RX call path at boot. The
stripped module attributed the PC to `mt7996_mac_wtbl_lmac_addr+0x614`, but
disassembly places the warning in the following static TX-free parser's
`cur_info >= end` check. This is consistent with a truncated/misframed event;
it does not by itself prove which producer-side race generated that event.

`121-npu-rx-ring.patch` backports the two changes from
[mt76 PR #1169](https://github.com/openwrt/mt76/pull/1169), commits
`105e1b13a25c874fd7d750d28cd06ab05a778921` and
`99e66f2d6eadc5594956bc76f819c78f3794d4b8`. **The PR is unmerged as of
2026-11-03.** These changes preserve NPU offload. Slots are returned to the
device only after replacement buffers have been installed; dequeue waits for
all queued slots of a frame. The first DONE read and DMA read barrier precede
the slot-count read, and another DMA read barrier precedes payload metadata.
Descriptor publication uses the existing regmap/MMIO publication path.

CI compiles the actual fill/dequeue functions and descriptor declaration.
The unpatched code must reproduce eight unsafe ownership/completion cases;
the patched code must pass 12 fixtures covering delayed completion, count
visibility, empty/short queues, wraparound, zero count, partial refill and
buffer/skb allocation failures. Audits repeat the tests on the actual prepared
mt76 source used for both images. Fixtures cannot establish physical DMA
ordering or device stability: RAM boot and sustained bidirectional wireless
load without new kernel warnings remain required before claiming this warning
has been eliminated on the W1701K.

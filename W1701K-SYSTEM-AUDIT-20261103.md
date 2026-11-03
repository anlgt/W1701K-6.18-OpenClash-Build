# W1701K system audit and rebuild scope (2026-11-03)

This audit inspected the running `gemtek,w1701k`, kernel 6.18.60, source
`778d561059fe01a527cf49451ef4de14f433e303`, through read-only SSH and Safari.
No router setting, service, CPU register or firmware was changed during this
audit. Raw logs, client identifiers, FRP credentials and private configuration
are not included in the repository.

## Confirmed findings and build changes

| Finding | Evidence | Rebuild action |
| --- | --- | --- |
| CPUFreq policy is missing | `cpufreq_policy_online: ->get() failed`; no policy directory; SoC view falls back to PLL | Retain the W1701K-only stock-range CPUFreq fallback and hardware acceptance check |
| PHY temperatures are unavailable | Both EN8811H PHYs bind, but neither exports hwmon; fan view correctly reports unavailable after the earlier UI correction | Retain the vendor-command hwmon driver and null-aware RPC/UI patches |
| NPU wireless RX warning | One boot-time warning in `mt76_npu_rx_poll` / MT7996 TX-free parsing; no panic, Oops or OOM in the collected log | Backport the two narrowly scoped NPU RX-ring fixes, with old/new C regression checks; physical load validation remains required |
| Direct PLL UI bypasses CPUFreq | Current UI offers direct register overrides beyond stock OPPs | Remove the direct PLL write RPC and UI controls; use kernel CPUFreq controls |
| SoC display uses reference-board labels and unbound NAT fields | W1700K-specific port names on W1701K; UNB PPE rows display non-authoritative translated addresses | Use neutral board-appropriate labels and suppress unbound translated-flow fields |
| FRP companion files are absent from upgrade backup | `sysupgrade -l` lists the FRP UCI file and crontab but omits token/TLS/include files and the cron watchdog helper | Include frpc 0.71.0 and its LuCI page in the full BIN; add path-only upgrade keep rules; do not embed any current server, token or certificate |
| Unneeded optional applications | FlowSense background polling remains installed; MLO/WiFi7 are additional management applications | Exclude FlowSense, MLO and WiFi7 apps from both images while retaining standard LuCI wireless, MT7996/EHT and NPU/PPE |

The running frpc is already 0.71.0-r1 and uses the same init script as the
pinned packages feed. The new keep list protects later upgrades from this firmware; it cannot change
the backup created by the current r6 firmware before the first upgrade.
Before that first upgrade, separately back up `/etc/frp/` and the watchdog
helper, or add their paths to the old system's backup list. Preserve configured
UCI and companion files when doing a configuration-preserving upgrade. A fresh install intentionally contains no
working FRP server, token or example SSH exposure, and the service is disabled
until configured. The Lite RAM-test image omits frpc to retain the 20 MiB TFTP
limit; the full sysupgrade BIN includes it.

## RX warning localization and patch provenance

The running stripped `mt7996e.ko` retains a 0x60-byte
`mt7996_mac_wtbl_lmac_addr` symbol at 0x14e68. The following static TX-free
function has no retained symbol, so the printed `+0x614` does **not** locate a
WTBL access. Disassembly maps PC 0x1547c to `brk #0x800`, reached by the
`end <= cur_info` comparison at 0x15014. This corresponds to
`WARN_ON_ONCE((void *)cur_info >= end)` in `mt7996_mac_tx_free`.

The pinned NPU code reads frame slot count before DONE, consumes buffers before
all frame slots are complete, and returns slots before refill. The fixes in
[mt76 PR 1169](https://github.com/openwrt/mt76/pull/1169) address these races:

- `105e1b13a25c874fd7d750d28cd06ab05a778921`: return RX slots only after refill;
  require all frame slots to be queued and complete before building an skb.
- `99e66f2d6eadc5594956bc76f819c78f3794d4b8`: read slot count after the first
  DONE, with DMA read barriers before descriptor/payload consumption.

PR 1169 was still unmerged at audit time. The source defect and warning path
are confirmed, but these facts do not prove that the patch eliminates every
TX-free warning on this physical router. Keep NPU support and warning checks;
do not hide warnings or describe fixture tests as sustained hardware testing.

## Configuration findings kept separate from firmware defects

- Effective wireless regdom is CN, while retained radio0/1 UCI country is US
  and radio2 is CN. Fresh defaults already set all radios to CN; retaining old
  configuration retains this discrepancy. Review country settings after upgrade.
- OpenClash fake-IP DNS produces a ULA AAAA answer which dnsmasq's rebind
  protection removes. This was reproduced by comparing dnsmasq with the local
  OpenClash DNS listener. It is a running DNS-policy interaction; this build
  does not globally disable DNS rebind protection or rewrite proxy rules.
- WAN6 has no address and remains pending. That alone does not establish an
  IPv6 driver defect or upstream IPv6 availability.
- The initial watchdog request of 30 seconds logs EINVAL, but the active
  watchdog is running with timeout 24 seconds and frequency 5 seconds. This
  is not a failed watchdog and does not justify disabling it.

## Healthy observations and acceptance boundary

Factory wireless calibration passes without EEPROM fallback. The primary
wireless PCIe link is 8 GT/s x2; 5 GHz 160 MHz EHT client rates were about
2402/1922 Mbit/s at inspection. This is a negotiated-rate observation, not a
new sustained throughput benchmark. WAN has no RX/TX errors; memory has about
1.5 GiB available and overlay utilization is about 9%. CPU is about 54 C,
board about 47-48 C and fan about 1488 RPM. No resource exhaustion or failed
resident service was observed in this sample.

CI must apply the complete kernel/package patch series, build both images,
audit the extracted actual files and FRP version, verify matching kernel ABI,
and enforce the Lite RAM size limit before publishing. RAM boot, CPUFreq
transitions, physical temperature accuracy, preserved FRP connectivity and
sustained wired/wireless load remain device acceptance tasks. This rebuild
does not authorize or perform flashing.

# XR1710G WAN r2 repair candidate

The prior candidate at commit `172d34917ff997acf9fd38cb2ff33810bec9f278` passed CI but failed the owner's fresh-install hardware test: WAN was administratively up with `NO-CARRIER`, both DHCP and a valid static address failed, and the link LED was on. The interface names were correct and the upstream subnet did not overlap LAN. Treat that artifact as a failed WAN candidate, not a stable release.

## Evidence and repair scope

The matched Linux 6.18.52 reference omits several PCS carrier safeguards present in the owner's working YYH 6.18.44 source (`c82129e7348fda30b9e2f90572e4f1b3c555c7f2`). The new final PCS patch:

- Enables manual receive calibration through E2 silicon for both external ETH/PON PCS instances and enables PON receive-lock recovery
- Removes the AN7581 TXPCS reset performed after link-up
- Preserves the SDK calibration search, native rate adaptation, optional TX-FIR handling and per-port interface tracking
- Restores unsigned-safe remaining calibration arithmetic and the bounded retry comparison
- Restricts the W1700K-specific JCPLL workaround to W1700K; XR1710G uses the standard value from its working source lineage

These are concrete source differences relevant to carrier establishment. They do not establish which difference caused this particular unit's failure. The newer generic Realtek delayed recovery worker is not changed without additional evidence. No PHY register writes or other live-router experiments were performed.

An extracted-source host C harness checks the actual calibration condition and actual JCPLL function. The old candidate fails the regression matrix; the repaired source passes it. This is mocked software behavior, not a hardware test.

## Independent retained-config migration correction

The inherited .44→.52 migration maps the old LAN list to duplicate lan2 entries and omits lan4. Its replacement only migrates an unambiguous .44 factory port topology, simultaneously remapping eth1/eth2/lan2/lan3 to wan/lan2/lan3/lan4 while preserving VLAN suffixes and flags. Mixed naming, custom collisions, direct firewall device bindings and opaque firewall includes are left unchanged with a diagnostic, rather than guessed. A staged UCI validation and atomic file replacement avoid partial writes. Correct .52 and fresh configurations remain unchanged. This is not the explanation for the reported fresh-flash carrier fault.

The reference hardware-based DHCP client-ID default is now applied during fresh network generation only, preserving retained explicit client-ID choices. Host tests cover the actual shell scripts; CI additionally rechecks migration with the final image's real UCI under QEMU.

## Requested applications

The pinned feeds supply `frpc`, `luci-app-frpc`, `luci-app-filemanager` and both Chinese translations. The actual File Manager remains behind authenticated LuCI administration and adds no separate listener or WAN rule.

FRP ships without a server, token, enabled sample SSH tunnel, external include or web-admin listener. Its boot startup is disabled at both image-assembly passes and first boot. A fail-closed init guard prevents an unconfigured client from starting, including when manually invoked. Configure it yourself before enabling the client; no remote service or account is provisioned by this build.

## Verification

CI must pass source pins, complete patch preparation, extracted-source PCS regression tests, complete firmware compile, requested/forbidden package checks, FIT/DTB/upgrade metadata checks, actual rootfs checks, OpenClash/Mihomo byte verification, and FRP ARM64 version/configuration-parser tests under QEMU.

The normal full artifact is retained. Additional checksummed 20 MiB transfer parts permit independent downloading and byte verification in tools with a 32 MiB per-file limit. They are copies of the same validated output, not an alternate firmware build.

## Hardware acceptance remains pending

The owner must confirm physical WAN carrier, DHCP, upstream gateway reachability and normal routing on this exact new image before the WAN repair can be called successful. Then test all LAN ports, wireless bands, OpenClash/offload combinations, fan response, reboot persistence and sustained operation. No zero-bug or hardware-stability guarantee is made.

`xr1710g-link-report` is included for read-only link/PHY diagnostics. It does not change UCI, reset hardware or issue MDIO writes, and it redacts MAC addresses from filtered boot messages.

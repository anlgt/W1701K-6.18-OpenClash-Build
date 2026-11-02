# W1701K 6.18.60 GT build

Use **Build W1701K 6.18.60 GT Hybrid (Lite RAM + OpenClash Flash)** in GitHub Actions.
All firmware compilation and Linux patch preparation run on the Ubuntu Actions runner.
The original 6.18.44 workflow and releases remain available.

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

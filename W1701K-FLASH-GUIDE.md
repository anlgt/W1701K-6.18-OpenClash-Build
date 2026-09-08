# Gemtek W1701K OpenWrt 6.18.44 最终刷机记录

> 本文档记录已在真机上验证成功的路径：必要时先在原厂
> U-Boot 中安装一次 chainloader，最后打断启动进入 `ECNT>`，通过
> TFTP 将 Lite ITB 启动到 RAM，硬件检查全部通过后，从 LuCI 上传并
> 刷入带 OpenClash 的完整版 `sysupgrade.bin`。

## 1. 重要结论

- **TFTP 只传 14.50 MiB 的 Lite RAM 镜像**，避免 30 MiB 以上 ITB 在
  原厂 U-Boot 中传输不稳定。
- **OpenClash 完整版通过 LuCI 上传刷入**，不再通过 U-Boot/TFTP
  传输。
- Lite ITB 只在 RAM 中运行，**不能写入闪存**。
- `sysupgrade.bin` 才是正式写入闪存的固件。
- 不保留其他固件的旧配置；LuCI 中取消“保留配置”，命令行则使用
  `sysupgrade -n`。
- 本次验证的 W1701K 为 AN7581、2 GiB RAM、512 MiB SPI-NAND，
  无线为 MT7990 主设备 + MT7991 HIF 辅助设备。

## 2. 适用状态

### 原厂固件、从未安装过 chainloader

需要执行第 6 节的“首次安装 chainloader”，之后再继续 RAM 启动和
正式刷机。

### 已经安装过 chainloader，或已经能启动 OpenWrt

跳过第 6 节。直接在开机时打断 U-Boot 进入 `ECNT>`，从第 7 节开始。

> **禁止重复写 chainloader：**正式 OpenWrt 布局中 `0x600000` 已是
> kernel 分区起点。设备已经刷好 OpenWrt 后再执行 `flash erase`
> 会破坏当前内核。

## 3. 风险和前提

- 需要 3.3 V TTL 串口。只连 GND、路由器 TX 到转换器 RX、路由器 RX
  到转换器 TX；**不要连 VCC/5 V**。
- 串口设置：`115200` baud、8 数据位、1 停止位、无奇偶校验、无流控。
- 使用稳定电源；擦除和写入期间不能断电。
- 电脑与 W1701K 之间建议接一台千兆交换机。原厂 U-Boot 与部分
  2.5G 网卡直连时可能反复 ARP/TFTP 超时。
- 文档中的固件只适用于 **Gemtek W1701K**，不能用 W1700K/XR1710G
  镜像代替。

## 4. 需要的文件

### 4.1 首次从原厂系统转换时才需要

- [W1701K U-Boot chainloader](https://github.com/ZqinKing/wrt_release/releases/download/26.07.20_17.16.30_gemtek_w1701k_immwrt/immortalwrt-airoha-an7581-gemtek_w1701k-ubi-chainload-uboot.itb)

```text
文件：immortalwrt-airoha-an7581-gemtek_w1701k-ubi-chainload-uboot.itb
大小：283732 bytes（0x45454）
SHA256：36034dfc2a67e2f035d2712cb11c90601a49e80cac422124127418cccdc65d1a
```

### 4.2 每次刷机用的 Lite RAM 启动镜像

- [W1701K 6.18.44 Hybrid Lite initramfs ITB](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/releases/download/w1701k-6.18.44-hybrid-r2-1/openwrt-airoha-an7581-gemtek_w1701k-initramfs-uImage.itb)

```text
文件：openwrt-airoha-an7581-gemtek_w1701k-initramfs-uImage.itb
大小：15204352 bytes（0xe80000，14.50 MiB）
SHA256：c71ad3a32e92bdf0227c301d98ec9e072d780db9b0ee34085df8b80bd3283a74
```

### 4.3 最终写入闪存的 OpenClash 完整版

- [W1701K 6.18.44 Hybrid OpenClash sysupgrade BIN](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/releases/download/w1701k-6.18.44-hybrid-r2-1/openwrt-airoha-an7581-gemtek_w1701k-squashfs-sysupgrade.bin)
- [同一 Hybrid Release 和所有校验文件](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/releases/tag/w1701k-6.18.44-hybrid-r2-1)

```text
文件：openwrt-airoha-an7581-gemtek_w1701k-squashfs-sysupgrade.bin
大小：38953217 bytes（37.15 MiB）
SHA256：6398da29fdc27dd929b14b864e04ea38c5ba86c82e83b3654c71ccf75f2f207d
```

这两个镜像来自同一次构建并通过内核 ABI、全部内核模块选择一致性检查。
Release 有意不提供 `.apk` 或 `packages.adb`；正式 BIN 已直接内置 OpenClash
及所需依赖。

## 5. 准备 Windows 网络和 TFTP

1. 电脑有线网卡固定设置为 `192.168.1.10`。
2. 子网掩码为 `255.255.255.0`，网关和 DNS 留空。
3. 暂时关闭 Wi-Fi，避免存在第二条 `192.168.1.0/24` 路由。
4. 将 chainloader（如需）和 Lite ITB 放入 Tftpd64 的 Current Directory。
5. Tftpd64 的 Server interface 选择 `192.168.1.10`。
6. Windows 防火墙允许 Tftpd64/UDP 69，或在断网刷机期间暂时关闭该网卡的
   防火墙。

先在 Windows PowerShell 中检查：

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Format-Table InterfaceAlias,IPAddress,PrefixLength
Get-NetAdapter | Format-Table Name,Status,LinkSpeed
```

目标网卡应显示 `192.168.1.10/24`、`Up`、`1.0 Gbps`。

## 6. 仅原厂状态：首次安装 chainloader

### 6.1 在原厂 U-Boot 中下载到 RAM

开机看到 `Hit any key to stop autoboot` 时按键，停在 `ECNT>`。

```text
setenv netretry no
setenv ipaddr 192.168.1.1
setenv serverip 192.168.1.10
setenv tftpblocksize 512
ping 192.168.1.10
tftpboot 0x89000000 immortalwrt-airoha-an7581-gemtek_w1701k-ubi-chainload-uboot.itb
```

必须看到：

```text
done
Bytes transferred = 283732 (45454 hex)
```

如果 U-Boot 支持 `iminfo`，还可执行：

```text
iminfo 0x89000000
```

没有出现 `done` 和完整字节数时，**不得继续擦写**。

### 6.2 设置启动命令并写入 chainloader

以下命令会修改启动环境并写闪存，只在第 6.1 节传输成功后执行：

```text
setenv one flash read 0x600000 0x1000000 $loadaddr
setenv two "; bootm"
setenv bootcmd "$one$two"
setenv one
setenv two
saveenv

flash erase 0x600000 0x100000
flash write 0x600000 0x100000 0x89000000
reset
```

这里启动命令每次从 NAND 的 `0x600000` 读取 `0x1000000`（16 MiB）。
首次读到的是 chainloader；正式 sysupgrade 后，同一位置是 W1701K
的 16 MiB kernel 分区，因此同一条 `bootcmd` 会直接启动正式系统。

## 7. 最终路径：在 `ECNT>` 中启动 Lite RAM OpenWrt

重启设备，在原厂 U-Boot 倒计时最后一次按键打断，停在：

```text
ECNT>
```

执行：

```text
setenv netretry no
setenv ipaddr 192.168.1.1
setenv serverip 192.168.1.10
setenv tftpblocksize 1468
ping 192.168.1.10
tftpboot 0x91000000 openwrt-airoha-an7581-gemtek_w1701k-initramfs-uImage.itb
```

必须看到：

```text
done
Bytes transferred = 15204352 (e80000 hex)
```

然后才启动：

```text
bootm 0x91000000
```

### 为什么使用 `0x91000000`

AN7581 为 NPU 保留了一大段 RAM。`0x89000000` 和 `0x90000000` 可能与
NPU 保留内存重叠，大 ITB 在 `bootm` 后可能直接重启。已验证的
Lite ITB 应加载到 `0x91000000`。

> 此步不要执行 `saveenv`，也不要执行任何 `flash write`。

## 8. RAM 系统验收和原厂数据备份

Lite 系统启动后，电脑仍可保持 `192.168.1.10/24`。访问：

```text
http://192.168.1.1/
```

串口或 SSH 中执行：

```sh
w1701k-hwcheck
```

只有最后出现以下结果才可继续：

```text
PASS: basic W1701K RAM-test checks passed
```

已验证的正常特征：

- PCIe 同时出现 `14c3:7990` 和 `14c3:7991`。
- `mt7996e` PHY 同时包含 2.4 GHz、5 GHz、6 GHz 频率范围。
- WAN、LAN、NPU/PPE 正常。
- 存在 `nct7802`，温度、PWM 和风扇转速可读取，风扇不为 0 RPM。
- 无 `PCIe link down`、`LTSSM detect.quiet`、MT7996 或 NPU 启动错误。

### 强烈建议：正式刷机前保存设备独有数据

先执行 `cat /proc/mtd`，再在 LuCI 的“备份与升级”页面下载以下
mtdblock：

- `bootloader`
- `uenv`
- `dsd`
- `factory`

其中 `dsd`/`factory` 包含 MAC、无线 EEPROM/校准等设备独有信息。备份应和
设备底部标签照片一起异地保存，不要与其他 W1701K 互换。

## 9. 从 Lite RAM 系统的 LuCI 刷入 OpenClash 完整版

1. 在 Lite LuCI 中打开“系统 → 备份与升级”。
2. 在“更新固件/刷写新的固件”处上传：

   ```text
   openwrt-airoha-an7581-gemtek_w1701k-squashfs-sysupgrade.bin
   ```

3. 对照 LuCI 显示的 SHA256：

   ```text
   6398da29fdc27dd929b14b864e04ea38c5ba86c82e83b3654c71ccf75f2f207d
   ```

4. **取消勾选“保留配置”**。
5. **不要勾选“强制升级”**。如果正常校验不通过，应停止排查，
   不应使用 `-F` 跳过。
6. 确认机型为 `gemtek_w1701k` 后点击继续。
7. 写入和首次启动期间等待 5–10 分钟；串口短时无输出不代表可以
   断电。

如果更愿意使用命令行，可先把 BIN 上传为 `/tmp/w1701k-full.bin`，
再执行：

```sh
sha256sum /tmp/w1701k-full.bin
sysupgrade -T /tmp/w1701k-full.bin
sysupgrade -n /tmp/w1701k-full.bin
```

`sysupgrade -T` 成功时没有输出是正常的；`sysupgrade -n` 才会实际写入。

## 10. 正式系统首次启动后验收

重新连接 `http://192.168.1.1/`，然后执行：

```sh
ubus call system board
cat /proc/mtd
ubinfo -a
df -h
w1701k-hwcheck
```

应确认：

- 内核为 `6.18.44`，机型为 `Gemtek W1701K`。
- `rootfs_type` 不再是 `initramfs`。
- `w1701k-hwcheck` 仍以 `PASS` 结束。
- LuCI 中已存在 OpenClash、irqbalance、SoC Status、FlowSense、Fan Control、
  Wi-Fi 7 和 MLO。
- OpenClash 及依赖已经内置；本 Hybrid Release 不提供额外 APK 软件仓库。

## 11. 首次无线设置的已知注意事项

MT7996 的三个频段共享同一个 PHY。即使 6 GHz 的 wifi-iface 已禁用，
`radio2` 设备仍可能以 `country '00'` 启动，从而使 hostapd 报：

```text
Invalid country_code '00'
hostapd.add_iface failed
```

在中国大陆先启用 2.4/5 GHz，并完整禁用 `radio2`：

```sh
uci set wireless.radio0.country='CN'
uci set wireless.radio0.channel='6'
uci set wireless.radio0.htmode='HE20'
uci set wireless.radio0.disabled='0'
uci set wireless.default_radio0.disabled='0'

uci set wireless.radio1.country='CN'
uci set wireless.radio1.channel='36'
uci set wireless.radio1.htmode='HE80'
uci set wireless.radio1.disabled='0'
uci set wireless.default_radio1.disabled='0'

uci set wireless.radio2.country='CN'
uci set wireless.radio2.disabled='1'
uci set wireless.default_radio2.disabled='1'

uci commit wireless
wifi down
sleep 2
wifi up
```

使用 `ubus call network.wireless status` 确认 `radio0/radio1` 为 `up: true`、
`radio2` 为 `disabled: true`。先用 HE20/HE80 验证稳定，再按终端能力改为
EHT20/EHT80。6 GHz 必须遵守设备所在地的频谱法规，不要用虚假国家码
强行开启。

## 12. Overlay 和 NAND 空间

正式 OpenWrt 使用的布局大致为：

```text
bootloader   2 MiB
uenv         2 MiB
dsd          4 KiB
factory      约 2 MiB
kernel       16 MiB
rootfs       488 MiB（UBI）
reserved_bmt 2 MiB
```

sysupgrade 会为 `rootfs_data` 分配剩余的 UBI 空间，真机上已见约
`373.2 MiB`。刷入本文档的完整版后，**不需要手动扩容 Overlay**。

不得删除或占用：

- `bootloader`、`uenv`、`dsd`、`factory`
- `ubootenv`、`ubootenv2`
- `reserved_bmt`（用于 NAND 坏块管理，不是可回收存储空间）

之前旧 ImmortalWrt UBI 中使用过的：

```text
ubirmvol /dev/ubi0 -N log
ubirmvol /dev/ubi0 -N config
ubirsvol ...
```

只适用于当时的中间布局。**不要在现在的正式 OpenWrt 布局上重复
执行。**

## 13. 故障处理

### `ARP Retry count exceeded` / TFTP 断续超时

1. 改用千兆交换机中转，不要让 2.5G 网卡直连 U-Boot。
2. 确认 Tftpd64 选中 `192.168.1.10` 那块有线网卡。
3. 关闭 Wi-Fi 和其他虚拟网卡，放行 Windows 防火墙。
4. 先在 `ECNT>` 运行 `ping 192.168.1.10`。
5. 只传 Lite ITB，不要传输完整版 33 MiB ITB。

### `bootm` 后立即重启

确认 Lite ITB 加载到 `0x91000000`，不是 `0x89000000` 或 `0x90000000`；
同时确对 ITB 的 SHA256。

### 正式系统无线无法开启

先检查：

```sh
iw dev
ubus call network.wireless status
logread | grep -Ei 'hostapd|netifd|mt7996|nl80211|wireless' | tail -120
```

如日志出现 `Invalid country_code '00'`，按第 11 节完整禁用 `radio2`，
不要只禁用 `default_radio2` 接口。

### 正式固件无法启动

重启时打断进入 `ECNT>`，重复第 7 节，用 Lite ITB 回到 RAM OpenWrt，
再从 LuCI 重刷已校验的完整版 BIN。

## 14. 最短操作清单

对于已安装 chainloader 的同型设备，以后重刷只需：

1. 电脑设 `192.168.1.10/24`，启动 Tftpd64，放入 Lite ITB。
2. 打断 U-Boot 进入 `ECNT>`。
3. 执行：

   ```text
   setenv netretry no
   setenv ipaddr 192.168.1.1
   setenv serverip 192.168.1.10
   setenv tftpblocksize 1468
   tftpboot 0x91000000 openwrt-airoha-an7581-gemtek_w1701k-initramfs-uImage.itb
   bootm 0x91000000
   ```

4. RAM OpenWrt 中运行 `w1701k-hwcheck`，必须为 PASS。
5. LuCI 上传完整版 `sysupgrade.bin`，取消保留配置，不强制。
6. 等待自动重启，验证内核、Wi-Fi、NPU/PPE、风扇、OpenClash 和 Overlay。

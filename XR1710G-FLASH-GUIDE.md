# XR1710G 原厂固件迁移与 6.18.53 重建版刷写

本文适用于 **Gemtek/Brightspeed XR1710G**，目标设备标识为 `gemtek,xr1710g-ubi`。固件文件是新构建 Release 中的 `openwrt-airoha-an7581-gemtek_xr1710g-ubi-squashfs-sysupgrade.itb`，只适用于 XR1710G 的 UBI 2.0 布局。

> **不要把本固件刷到 W1700K 或 W1701K。** XR1710G 需要先安装匹配的二级 U-Boot/chainloader，再完整重建 UBI 2.0。不能从原厂系统直接把本文件当作普通 sysupgrade 上传，也不要强制跳过镜像检查。

> 本次 6.18.53 是尽力重建：使用公开的 XR1710G OpenWrt 板级源码并替换为 Linux 6.18.53 稳定版源码及校验值。v1.9 的对应源码尚未公开，因此本构建不等同于 v1.9，也不能保证包含其未公开的 EHT320、以太网 RX/LRO 等修复。刷机前请等构建完成，并以该次 Release 资产及 SHA-256 为准。

## 刷机前准备

- 确认机身标签型号为 XR1710G；不要仅凭外壳或芯片判断。
- 准备 3.3 V TTL 串口线和稳定电源。串口只接 GND、路由器 TX→转换器 RX、路由器 RX→转换器 TX；不要连接 VCC。串口参数为 115200、8N1、无流控。
- 准备电脑有线网卡、TFTP 服务端；串口和电脑到路由器之间保持稳定连接。首次迁移不要使用无线网络。
- 先下载本节指定的 chainloader 和后续新构建 Release 中的 sysupgrade ITB，并分别核对 SHA-256。
- 备份原厂设置、设备标签及设备独有数据。若已有原厂 SSH/root 权限，按设备当前 `/proc/mtd` 只读备份 `dsd`、`factory` 等设备分区；不要把其他机器的备份恢复到本机。
- 迁移将重建 UBI、清除旧系统配置和数据；按干净安装处理，不能保留旧配置。

## 1. 准备并校验 chainloader

使用 XR1710G 专用的 `*-flash-slot.bin`，不要使用裸 `u-boot.bin`、`u-boot.img` 或 `*-chainloader.itb` 代替。已核验的版本及下载地址：

- [XR1710G chainloader flash-slot（U-Boot 2026.07，ab7fd651）](https://github.com/YYH2913/http-uboot/releases/download/260712/xr1710g-uboot-v2026.07-ab7fd651-flash-slot.bin)
- 文件大小：908722 bytes
- SHA-256：`44e8911c55d3e8f2a8be1befb8a8d892047780ab46850057949a661ec2e45953`

Windows PowerShell 校验：

```powershell
Get-FileHash .\xr1710g-uboot-v2026.07-ab7fd651-flash-slot.bin -Algorithm SHA256
```

将输出与上方哈希逐字核对。校验不一致就停止，不要上传或刷写。

## 2. 从原厂 U-Boot 临时启动 chainloader

本步骤先从 RAM 启动 chainloader，暂不写入闪存。原厂 ECNT/AXON U-Boot 的常见串口提示符为 `U-Boot 2014.04-rc1 ... AXON 1.6`；若版本、启动环境或板型明显不同，先停止并确认设备路径。

1. 电脑有线网卡设为 `192.168.0.205/24`，启动 TFTP 服务，服务端目录放入上一步已校验的 slot 文件。关闭电脑 Wi-Fi，确保 TFTP 绑定到这块有线网卡。
2. 路由器上电，串口出现倒计时提示时按键中断启动，停在原厂 U-Boot 提示符。
3. 先只读检查关键环境：

   ```text
   printenv ver version vendor board bootcmd loadaddr fdt_high ipaddr serverip
   ```

   常见原厂值是 `ipaddr=192.168.0.1`、`serverip=192.168.0.205`、`loadaddr=0x81800000`、`fdt_high=0xac000000`，默认 `bootcmd` 通常从 `0x602100` 读取。不要复制其他设备的整份 `printenv`。

4. 确认 TFTP 服务器和地址正确后，在 U-Boot 输入：

   ```text
   setenv ipaddr 192.168.0.1
   setenv serverip 192.168.0.205
   tftpboot 0x81800000 xr1710g-uboot-v2026.07-ab7fd651-flash-slot.bin
   ```

   确认传输完成，字节数为 `908722`。如果 TFTP 超时或长度不符，不要运行下一条命令。

5. 运行临时 chainloader：

   ```text
   bootm 0x81802100
   ```

   这是 slot 文件中 FIT 的偏移入口。若启动报错或板子重启，停止操作并保留串口日志；不要尝试写 NAND 修复。

## 3. 进入 chainloader HTTP Recovery 并安装它

临时 chainloader 启动后，按住路由器 Reset 进入 Recovery；状态灯进入恢复闪烁模式后松开。电脑连接路由器 10GbE 口并保持 DHCP，打开：

```text
http://192.168.255.1
```

在页面中选择写入目标 `uboot`，上传同一个已校验的 `xr1710g-uboot-v2026.07-ab7fd651-flash-slot.bin`。等待页面报告完成并按提示重启，写入期间不要断电。该文件用于 chainloader 槽；**不要选择 `firmware` 上传它**。

如果临时启动后没有出现 HTTP Recovery，重新上电时按住 Reset，直到状态灯显示恢复模式，再访问上述地址。不要在原厂 U-Boot 中执行未经该设备专用资料确认的 `flash write` 命令。

## 4. 用 Recovery 完整重建 UBI 2.0 并写入新固件

1. 在新构建对应的 GitHub Release 中下载唯一的 `*-sysupgrade.itb` 及 `RELEASE-SHA256SUMS`。核对文件名和 SHA-256；镜像中的设备 profile 必须是 `gemtek_xr1710g-ubi`。
2. 进入 chainloader Recovery：电脑接 10GbE 口、保持 DHCP；开机后在 10GbE 指示灯开始闪烁时按住 Reset，直到状态灯进入恢复闪烁模式。打开 `http://192.168.255.1`。
3. 选择目标 `firmware`，上传新构建的 `openwrt-airoha-an7581-gemtek_xr1710g-ubi-squashfs-sysupgrade.itb`。
4. 布局必须选 **UBI 2.0**。该选择必须匹配镜像内嵌设备树；此镜像的 `ubi` 分区为起始 `0x00700000`、长度 `0x1b700000`。选择 1.0 或 1.5 会造成布局不匹配。
5. 确认后等待 Recovery 完整擦除并重建 UBI，过程不要断电。此操作会删除旧配置/数据，并重建系统卷；完成后路由器重启。

> Recovery 的 `firmware` 上传会重建布局；普通 OpenWrt LuCI sysupgrade 仅用于设备已处于兼容的 XR1710G UBI 2.0 系统时升级。原厂转换和不同 UBI 布局迁移不要使用保留配置的普通升级流程。

## 5. 首次启动与验收

1. 电脑接路由器 LAN，访问 `http://192.168.1.1`。首次登录按页面提示设置管理员密码。
2. 重新配置 WAN、无线、区域码及 OpenClash；旧系统的网络和代理配置不会保留。
3. 如可通过 SSH 登录，检查：

   ```sh
   ubus call system board
   cat /proc/mtd
   df -h
   ```

   确认设备为 XR1710G、内核为 6.18.53、根文件系统不是 initramfs，并确认 UBI 2.0 系统已启动。LuCI 中应有 OpenClash、Argon、UPnP、irqbalance、Airoha SoC Status 和 Fan Control。

## 中止条件与恢复

- 机型、U-Boot 环境、chainloader 哈希、TFTP 字节数或 Release SHA-256 任一不匹配：停止，不要写闪存。
- 不要刷到 W1700K/W1701K，不要选择错误的 UBI 布局，不要勾选强制升级，也不要重复执行其他机型的 installer。
- 如果新系统未能启动，先通过串口读取启动日志，再用 Reset 进入 chainloader HTTP Recovery 重试匹配的 XR1710G 镜像。不要盲目擦除 `bootloader`、`uenv`、`dsd`、`factory` 或保留坏块区域。

## 依据与版本记录

- 本仓库 6.18.53 重建工作流固定 XR1710G 板级源码 `c82129e7348fda30b9e2f90572e4f1b3c555c7f2`，再以 Linux 6.18.53 稳定版 tarball 和 SHA-256 覆盖原 6.18.44 内核版本锁定；这并非 v1.9 同源构建。v1.9 发布说明称对应源码将随下一版公布，当前构建不能据此复现其二进制。设备兼容版本为 2.0；原始已验证构建记录见 [6.18.44 Release](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/releases/tag/xr1710g-6.18.44-openclash-r1-1)。
- v1.9 的内核组件和可复用补丁范围对比见 [XR1710G v1.9 基线核对](XR1710G-V1.9-COMPARISON.md)。
- XR1710G U-Boot/HTTP Recovery 的操作方法、chainloader slot 格式、默认串口环境及 UBI 2.0 边界见 [YYH2913/http-uboot 文档](https://github.com/YYH2913/http-uboot)。上文 chainloader SHA-256 已与 GitHub Release asset digest 核对。
- 本指南是依据构建记录和设备专用 U-Boot 文档编写的操作方案；本次没有在实体 XR1710G 上执行刷写验证。

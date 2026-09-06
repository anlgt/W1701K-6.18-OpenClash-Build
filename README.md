# Gemtek W1701K 可复现固件构建

> 真机已验证的完整刷机、RAM 验收、LuCI 写入 OpenClash 完整版、
> 无线区域码处理和 Overlay 说明，请查看
> [W1701K 最终刷机记录](W1701K-FLASH-GUIDE.md)。

本项目保留已验证可启动的 6.12.74 构建，同时新增 6.18.44 实验构建。6.18.44
版本修复 W1701K 双通道 PCIe 设备树，目标是解决仅枚举 MT7991、MT7990 缺失、
`PCIe link down` 与 `LTSSM detect.quiet`。推荐的 Hybrid 工作流在同一次构建中
生成小体积 RAM 测试 ITB 和带 OpenClash 的正式刷机 BIN，不发布 APK 安装包。

## 构建方式

| GitHub Actions 工作流 | 用途 | 包管理 |
| --- | --- | --- |
| `Build W1701K 6.18.44 Hybrid (Lite RAM + OpenClash Flash)` | **推荐**；Lite ITB 做 RAM 验收，完整版 BIN 正式刷写 | 不发布 APK 仓库 |
| `Build W1701K 6.18.44 Lite (No OpenClash)` | TFTP 更稳定的精简版；保留管理界面和硬件功能 | APK，同一次构建的签名仓库 |
| `Build W1701K 6.18.44 Wi-Fi Fix` | 旧版完整双镜像构建 | APK，同一次构建的签名仓库 |
| `Build W1701K 6.12 OpenClash` | 已知可启动的回退方案 | opkg，同一次构建的离线 IPK |

6.18.44 仍属于实验版本，不能因为“编译成功”就直接刷入闪存。必须先用 ITB 从
RAM 启动，并让内置的 `w1701k-hwcheck` 全部通过。

## 6.18.44 固件包含

- LuCI、简体中文、Argon 主题、UPnP/NAT-PMP；UPnP 默认关闭。
- OpenClash 0.47.156、Mihomo 1.19.30 ARM64 核心及所需依赖。
- irqbalance，首次启动自动启用。
- Airoha SoC Status、FlowSense、NPU/PPE 支持。
- Fan Control 页面；自动风扇服务默认关闭，避免未经验证的 W1700K 曲线接管
  W1701K 风扇。
- MT7990/MT7991 三频 Wi-Fi 7、EHT、MLO 页面与依赖。
- Hybrid 产出 initramfs ITB、sysupgrade BIN、两份 manifest、完整配置、源码
  补丁和校验文件；不含 `*.apk`、`packages.adb` 或软件源公钥。
- ITB 不含 OpenClash、Mihomo、Ruby 和 Bash，以降低 TFTP 传输体积；正式 BIN
  内置完整 OpenClash。两者来自同一源码并使用完全相同的内核 ABI 与内核模块
  选择，临时根文件系统作为独立 XZ initrd 打包。

硬件流量卸载保持系统默认。OpenClash 代理流量不能由 Airoha NPU 代跑；只有符合
条件的直连转发流量才可能进入 PPE/NPU 快速路径。

## 可复现版本

- W1701K 源码：`465633077348b8015e5282193af2b9427b6a8b78`
- 参考应用包：`38be3a4a0b66ccbb4311a12ad0890de571a0fcce`
- packages feed：`fbde5d1e31608aa13ad779f97da793e841bc214f`
- LuCI feed：`506ca606d379dd69e9826b2a5e7e2ab90e6b89a5`
- routing feed：`4b9891b9136259f93294a424507ed24c5e8c1cbd`
- OpenClash：0.47.156；Mihomo：1.19.30；Argon：2.4.6。

没有借用官方 Snapshot 的 vermagic，也不会把其他内核的 `kmod-*` 伪装成兼容包。

## 在 GitHub 上构建

1. 新建 GitHub 仓库，把本目录全部文件推送进去。
2. 打开仓库的 **Actions**，选择
   `Build W1701K 6.18.44 Hybrid (Lite RAM + OpenClash Flash)`。
3. 点击 **Run workflow**。
4. 成功后到该次运行的 Artifact 或自动建立的 Pre-release 下载产物。

Hybrid 工作流不会覆盖固件的软件源配置，也不会把构建产生的 APK 上传到
Artifact 或 Release。自定义内核的 `kmod-*` 必须与本固件 ABI 一致，不要从其他
OpenWrt/ImmortalWrt Snapshot 软件源强制安装。

## 产物

- `*gemtek_w1701k-initramfs-uImage.itb`：U-Boot RAM 测试镜像，不写闪存。
- `*gemtek_w1701k-squashfs-sysupgrade.bin`：RAM 验收通过后才可正式刷写。
- `*sysupgrade-openclash.manifest`：正式 BIN 的内置软件清单。
- `*initramfs-lite.manifest`：Lite ITB 的内置软件清单。
- `SHA256SUMS`：所有发布文件的校验值。
- 两套 `resolved-6.18-*.config`、diffconfig、内核 ABI 比对与已应用补丁：构建记录。

## 先做 U-Boot RAM 测试

电脑有线网卡设为 `192.168.1.10/24`，关闭该网卡的防火墙，把 ITB 放入 TFTP
目录。建议电脑与 W1701K 之间使用稳定的千兆交换机。进入 `ECNT>` 后运行：

```text
setenv netretry no
setenv ipaddr 192.168.1.1
setenv serverip 192.168.1.10
setenv tftpblocksize 1468
tftpboot 0x91000000 openwrt-airoha-an7581-gemtek_w1701k-initramfs-uImage.itb
bootm 0x91000000
```

大体积 ITB 必须使用 `0x91000000`。不要沿用小型 recovery 曾使用的
`0x89000000` 或 `0x90000000`，它们可能与 AN7581 为 NPU 保留的内存区域重叠，
造成 `bootm` 后自动重启。构建还会强制检查 FIT 内存在独立 `RAMDisk Image`，
避免把完整 OpenClash 根文件系统内嵌进从 `0x80200000` 解压的内核映像。

进入临时系统后运行：

```sh
w1701k-hwcheck
```

脚本必须以 `PASS: basic W1701K RAM-test checks passed` 结束。它会确认：

- 当前确实是 `gemtek,w1701k` 的 initramfs；
- PCI 上同时存在 `[14c3:7990]` 与 `[14c3:7991]`；
- 同一个 `mt7996e` PHY 提供 2.4、5、6 GHz 和 EHT；
- WAN、LAN、NPU/PPE、NCT7802 温度/PWM/转速均正常；
- 没有已知 PCIe link-down、NPU 或 MT7996 固件错误；
- 未验证的自动风扇服务没有启用。

任何一项 FAIL 都不要刷 BIN。保存完整输出用于修复构建。

Hybrid 的 ITB 本身就是 Lite RAM 版：删除 OpenClash、Mihomo、Ruby 与 Bash，
但仍保留中文 LuCI、Argon、UPnP、irqbalance、SoC Status、FlowSense、Fan
Control、Wi-Fi 7 与 MLO。为保证与正式 BIN 使用同一 ABI，代理相关内核模块仍
保留在 ITB 中。

## RAM 验收通过后正式刷写

把 BIN 放到 TFTP 目录，在 RAM 系统中下载并核对 Release 中的 SHA-256：

```sh
curl --tftp-blksize 1468 --retry 5 \
  -o /tmp/w1701k-sysupgrade.bin \
  tftp://192.168.1.10/openwrt-airoha-an7581-gemtek_w1701k-squashfs-sysupgrade.bin

sha256sum /tmp/w1701k-sysupgrade.bin
sysupgrade -T /tmp/w1701k-sysupgrade.bin
sysupgrade -n /tmp/w1701k-sysupgrade.bin
```

`sysupgrade -T` 只检查镜像；成功且无输出是正常的。`sysupgrade -n` 才会写入，
并且不保留旧配置。不要使用 `-F`，不要把 initramfs ITB 写入闪存，也不要使用
W1700K 的镜像。

## 软件包说明

Hybrid Release 不提供 APK 安装包或与自定义内核配套的软件仓库。常用功能应在
构建配置中选入固件后重新构建；尤其不要安装来自其他内核 ABI 的 `kmod-*`。

## 文件说明

- `.github/workflows/build-6.18-hybrid.yml`：推荐的 Lite RAM ITB + OpenClash
  正式 BIN 组合构建，不发布 APK。
- `w1701k-6.18-hybrid-initramfs.config`：Hybrid 中的 Lite RAM 根文件系统配置。
- `.github/workflows/build-6.18.yml`：旧版 6.18.44 双镜像及签名 APK 仓库构建。
- `.github/workflows/build-6.18-lite.yml`：不含 OpenClash 的小体积双镜像构建。
- `w1701k-6.18-openclash.config`：6.18 功能与依赖配置。
- `w1701k-6.18-lite.config`：6.18 Lite 功能与依赖配置。
- `patches/001-w1701k-pcie-x2-6.18.patch`：W1701K PCIe x2 修复。
- `patches/002-w1701k-app-compat.patch`：FlowSense 与 Fan Control 的 W1701K 适配。
- `patches/003-w1701k-separate-initramfs.patch`：为 RAM 测试使用独立压缩 initrd。
- `patches/004-w1701k-image-safety.patch`：约束 16 MiB 内核分区并修正设备默认包。
- `files/usr/bin/w1701k-hwcheck`：只读的 RAM 验收脚本。
- `.github/workflows/build.yml` 与 `w1701k-openclash.config`：6.12.74 回退构建。

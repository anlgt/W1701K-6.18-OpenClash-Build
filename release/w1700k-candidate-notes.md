# W1700K 6.18.55 UBI2 精简候选版 R1

仅适用于 `gemtek,w1700k-ubi` 的 W1700K，UBI2、compat 2.0。这是候选预发布版，尚未实机刷入或完成长期稳定性验证，不适用于 XR1710G、W1701K 或其他型号。

## 内容

Linux 6.18.55；简体中文 LuCI、File Manager、OpenClash 0.47.156 + Mihomo 1.19.32、Argon、UPnP、nohup、etherwake 命令、irqbalance、W1700K Fan Control 和 Airoha SoC/NPU。保留手动 Overclock 入口，不自动超频。无 FRP，无 etherwake 界面；裁剪与此机型无关的 MT7992 NPU 固件及不需生成的 U-Boot 目标。

Homebridge、插件、个人配置及私密备份均未打包。公开 Node 24.21.0 ARM64-musl 在实际镜像库环境下通过 QEMU 基础加密/TLS测试；这不等于 Homebridge、插件、mDNS 或实际设备控制验证。

## 来源与验收

- 固件源码：`15490b469f68133da3d244881fb48dd5e42c1d87`
- 二进制构建提交：`2dc471fdc382f693e22c5fb8b8e25c150585ce6d`
- 独立验收提交：`f6315b7ee79a17b8d26f0c5cff8c399d3a52e25a`
- 本发布 tag 指向文档定稿提交：`1cdd0d6d9f222ea83e1c500f43ba9c87c96ee90a`
- [完整离线验收通过](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/actions/runs/37308431238)

本发布复用原始镜像，没有重新编译、改字节或改品牌。原构建已成功编译，随后验证器误把浅克隆修订号 `r0-15490b4` 当作不匹配；纠正该期望后，对同一份镜像重新执行全部离线验收。源码、配置/包清单、fwtool/FIT、设备树/分区、实际 rootfs、全部 kmod ABI、Mihomo 字节与 QEMU 测试均通过；实机网口、Wi-Fi、卸载/代理组合、温控和恢复仍待验证。

## 使用前提

先核对校验值、实际机型/UBI2 布局、兼容 bootloader、设备专属分区备份及可用救援方式，再进行设备上的不刷写 `sysupgrade -T` 检查。该设备检查和正式刷写尚未执行，需另行确认。不要使用 `sysupgrade -F`，不要因本发布而改写 vendor、chainloader 或 BMT 保留分区。

首启保留原生 W1700K 无线/登录逻辑，可能受 bootloader 默认值影响，不保证开机自动开启 Wi-Fi；请准备有线 LAN。UPnP 默认关闭，irqbalance 默认启用。Homebridge 应另行私密备份和恢复；普通“保留配置”不能保证保住 `/opt` 数据，不要公开配置、令牌或缓存文件名。

## 文件校验

ITB 大小：43,062,084 字节

ITB SHA-256：`437f30508d68e69968e9f6ececb89e9a380bc8be9f64a280c445eab9b4ffdcb2`

完整验收 ZIP SHA-256：`9bf593eeea9311cd8e7ba62179a2b20de0085377fe64331483f4791de3c2acad`

附件 `SHA256SUMS` 覆盖各发布资产；GitHub 自动生成的 Source code ZIP/TAR 不在其范围内。详细前置条件与通用恢复说明见 `VALIDATED-CANDIDATE.md`，构建与验收身份见 `provenance.json`。

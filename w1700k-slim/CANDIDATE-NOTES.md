# W1700K UBI2 精简候选构建

仅适用于 `gemtek,w1700k-ubi`，`airoha/an7581`，已正确安装 UBI2/compat 2.0 布局的 W1700K。不是 XR1710G/W1701K 镜像。CI 成功只证明列出的软件与镜像检查通过，不证明实体机安全或稳定。

## 固定来源

- OpenWRT-fanboy/OpenW1700k：`15490b469f68133da3d244881fb48dd5e42c1d87`
- Linux 6.18.55；保持该 W1700K 分支的内核、MT76、NPU、PHY 与设备树补丁，不移植 XR 硬件补丁
- OpenClash 0.47.156；Mihomo v1.19.32；Argon v2.4.7 源码（源码 Makefile 的包标签仍为 2.4.6-r20260731）
- 完整源/feeds pin 见 `sources.lock.json`；原参考 release 的 feeds 未固定，不能承诺与原版逐字节复现

## 组件

保留中文 LuCI、File Manager、OpenClash/Mihomo、Argon、UPnP、nohup、etherwake 命令、irqbalance、原生 W1700K Fan Control 和 Airoha SoC/NPU 页面。SoC 页面保留原生手动 Overclock 入口，默认不加超频动作。超频直接修改 PLL，可能导致崩溃、发热或损坏；未进行超频稳定性验证。

不包含任何 FRP 客户端/服务端、FRP LuCI/翻译或配置。etherwake 不附带唤醒 UI。裁剪测速服务、ttyd、fastfetch、nano、自动在线固件升级助手、额外主题、FlowSense、单独 MLO/WiFi7 UI、relayd 和 WireGuard。删除单独 UI 不等于删除 Wi-Fi 7 驱动能力。保留 W1700K 必需的 DSA、Airoha Ethernet/NPU、MT7996、NCT7802、Realtek PHY 与两种适配其硬件修订的 PHY 固件。

Homebridge 不阻塞此构建。当前所选 packages feed 的 Node 是 host-only 构建工具，不是路由器运行时，且未确认用户正在使用的小米插件/Node 来源。暂不固化 Homebridge、配对状态或令牌；刷机前应另行保存私有 Homebridge 备份，再按已验证的 ARM64-musl 运行时与原插件版本恢复。不能直接假定本固件公共源支持 `apk add node node-npm`。

## 默认值与更新安全

- LuCI 默认简体中文和 Argon；irqbalance 启用；UPnP 保持默认关闭
- 保留原生 W1700K 首启无线/登录生成逻辑；bootloader 可能提供默认值，未提供时上游新生成无线可能关闭。个人密码、无线配置、订阅与 SSH 密钥不会被打包
- 保留原生风扇曲线；找不到 NCT7802 时拒绝猜测 hwmon5 或写入控制值
- 使用本次内核实际计算的 ABI，移除外部 vermagic 覆盖。原参考镜像虽运行 6.18.55，却带 6.18.54 kmod 下载地址，因此不会继承该公共 kmod 地址
- 不启用未经匹配验证的 snapshot 软件源；不要混装其他构建的 kmod 或执行全量 apk upgrade

## 升级前置条件

正确分区为 vendor `0x0+0x600000`、chainloader `0x600000+0x100000`、UBI `0x700000+0x1b700000`、reserved_bmt `0x1be00000+0x4200000`。vendor、chainloader 和 BMT 分区必须只读。

当前运行 ubi2 或 compat=2.0 本身不足以证明旧 chainloader 已更新。必须核对实际 MTD/UBI 布局、安装记录/bootloader、设备专属分区备份和可用救援方法。此候选不提供旧布局迁移，不构建或发布 chainloader，不使用强制刷写，不写保留分区。

## 验证范围

CI 设置：源和 feeds 固定、配置/清单禁止 FRP、内核/无线补丁准备、完整编译、fwtool 元数据、FIT 哈希/边界、W1700K 设备树与分区、实际 rootfs 文件/包 ABI、Mihomo ELF/字节比对及 QEMU 版本/配置解析。

尚待实机：启动、普通 sysupgrade 检查、LAN/WAN 各端口、三频 Wi-Fi/6GHz、DNS/UDP/TUN、OpenClash 与卸载/UPnP 组合、温控、重启、长时稳定性及恢复。没有任何 CI 日志能够替代这些测试。

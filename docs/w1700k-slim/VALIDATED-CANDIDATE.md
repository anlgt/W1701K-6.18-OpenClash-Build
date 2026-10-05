# W1700K UBI2 精简候选定稿说明

2026 年 10 月 5 日

**完整编译和离线验收已完成，实机刷写与运行验收尚未完成。** 本次提交仅整理文档、校验值和来源记录，没有重新编译、修改固件字节、创建正式 release 或执行刷写。

## 经过验证的产物

下载 [最终验收附件](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/actions/runs/37308431238/artifacts/11345405048)，不要将此前的 UNVALIDATED 或 DIAGNOSTIC 附件当作最终交付。

- ZIP：`W1700K-Slim-validated-retained-37308431238-1.zip`
- ZIP 大小：45,107,958 字节
- ZIP SHA-256：`9bf593eeea9311cd8e7ba62179a2b20de0085377fe64331483f4791de3c2acad`
- ITB：`w1700k-slim-6.18.55-ubi2-r36860-15490b469f-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb`
- ITB 大小：43,062,084 字节
- ITB SHA-256：`437f30508d68e69968e9f6ececb89e9a380bc8be9f64a280c445eab9b4ffdcb2`

下载后已重新核对最终 ZIP 内全部 46 个文件的校验值。完整记录在 ZIP 的 `build-record/`，本目录另附 [SHA256SUMS](SHA256SUMS) 和 [provenance.json](provenance.json)。若下载工具改变 ZIP 文件名，以对应的内容哈希为准。GitHub Actions 附件有保留期限，应及时保存需要的文件。

## 二进制构建与独立验收的对应关系

- 固件源代码：`OpenWRT-fanboy/OpenW1700k`，固定提交 `15490b469f68133da3d244881fb48dd5e42c1d87`
- 二进制构建定义提交：`2dc471fdc382f693e22c5fb8b8e25c150585ce6d`
- [原构建运行 37296245728](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/actions/runs/37296245728)：完整编译成功，随后元数据检查因验证器期望错误而失败
- 验收定义提交：`f6315b7ee79a17b8d26f0c5cff8c399d3a52e25a`
- [独立验收运行 37308431238](https://github.com/anlgt/W1701K-6.18-OpenClash-Build/actions/runs/37308431238)：对保留的同一份镜像完成全部离线检查，通过

原验证器期望的修订号是 `r36860-15490b469f`，固定源码浅克隆实际生成 `r0-15490b4`。OpenWrt 镜像元数据使用 `REVISION`，文件名等版本文本使用独立的 `CONFIG_VERSION_CODE`。纠正的只是验证器对该显示值的期望；完整源码 SHA、原始构建身份、源代码改动及原始产物哈希均另行验证。没有重写镜像元数据，也没有放宽机型、分区、内核或 ABI 门禁。

本次文档提交不是上述二进制的构建提交，也不取代上述验收提交。历史失败记录保留，以便追溯。

## 机型与组件

仅适用于 `gemtek,w1700k-ubi` 的 W1700K，目标 `airoha/an7581`，UBI2、compat 2.0。不要用于 XR1710G、W1701K 或其他型号。

组件包括 Linux 6.18.55、中文 LuCI、File Manager、OpenClash 0.47.156、Mihomo 1.19.32、Argon、UPnP、nohup、etherwake 命令、irqbalance、W1700K 原生 Fan Control 和 Airoha SoC/NPU。Argon 使用 v2.4.7 固定源码，其包版本字段仍显示 2.4.6-r20260731。

没有 FRP 客户端、服务端、界面、翻译或配置；etherwake 不附带界面。没有捆绑 Homebridge、插件、个人订阅或设备配置。已去掉无用的 MT7992 NPU 固件和本次不需生成的 U-Boot 目标，保留 W1700K 必需的 MT7996、NPU、DSA、风扇和 PHY 修订支持。

LuCI 默认简体中文和 Argon，irqbalance 启用，UPnP 默认关闭。Overclock 保留手动入口，不新增自动超频动作。原生 W1700K 首启无线和登录生成逻辑保持不变，可能受 bootloader 默认值影响；不保证首次开机自动开启 Wi-Fi，应准备有线 LAN。

## 已验证与尚未验证

已通过：固定来源与 feeds、解析后的配置、实际包清单、原生内核和无线补丁准备、完整编译、fwtool 元数据、FIT 哈希、W1700K 设备树与 UBI2 分区、实际 rootfs、全部 kmod 内核依赖、Mihomo 字节比对以及 QEMU 版本和配置测试。实际 rootfs 共 225 个包，内核 ABI 为 `6.18.55~5a4fe1e9c818b44e7e96dbd6c91f4c9a-r1`。

另以有固定公开校验值的 Node 24.21.0 ARM64-musl 程序，对实际镜像库运行了 QEMU 版本、SHA-256、随机数和 TLS 上下文测试。该运行时来自 Node unofficial-builds，上游仍标为实验性；它不在固件中。

尚未验证：实机启动、设备上的 sysupgrade 检查、各网口、Wi-Fi 7、OpenClash 与卸载组合、风扇和温度响应、重启与长期稳定性，以及 Homebridge、插件、mDNS 和实际设备控制。QEMU 基础测试不能替代这些项目。

## 刷写前置条件

先核对最终 ITB 校验值、实际机型、compat 2.0、MTD/UBI 布局、UBI2 兼容的 bootloader、设备专属分区备份和可用救援方法。运行中的固件标为 ubi2，并不单独证明旧 chainloader 已正确迁移。

正确布局为 vendor `0x0+0x600000`、chainloader `0x600000+0x100000`、UBI `0x700000+0x1b700000`、reserved_bmt `0x1be00000+0x4200000`。vendor、chainloader 和 BMT 保留分区应只读。

把镜像放到设备临时空间并执行不刷写的 `sysupgrade -T`，需要针对具体设备单独授权和确认；本文不表示已经执行或通过。正式刷写同样需要独立授权。不得用 `sysupgrade -F` 绕过失败，不应因这份 sysupgrade 镜像而改写 chainloader 或保留分区。

## Homebridge 私有备份与恢复原则

把应用项目、锁文件、已验证运行时、配对及持久化存储、启动定义与权限记录保存在 `<本地私密备份目录>`，验证归档可读取并保留校验值。运行中的备份可能不是原子快照。不要把归档、配置、令牌、缓存文件名或本地私密路径提交到仓库；部分插件会把令牌写进缓存文件名。

Homebridge 备份不能替代整机闪存或设备专属分区备份。FIT 升级会按新镜像长度重建 fit 和 rootfs_data：现有 fit 大小不是固定镜像上限，普通“保留配置”也不能被当作保存 `/opt` 应用数据的保证。

在正式获准刷写且基础网络正常后，先验证运行时的架构、解释器及共享库，再按私有恢复记录恢复原项目、原插件版本、配对身份和 procd 服务。检查启动、重启、mDNS、原配对及实际设备控制。不要同时升级插件、清空配对数据、重复建立启动服务或混装其他发行版共享库；不要执行全量 `apk upgrade`。

出现异常时停止恢复并保留备份。备份完整、运行时基础测试通过、Homebridge 实际恢复成功，应分别确认。

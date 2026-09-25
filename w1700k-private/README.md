# W1700K U-Boot 私有固件

此目录只用于当前实机 `gemtek,w1700k-ubi`，不能用于本仓库原有的 W1701K 工作流。源码固定在 `OpenWRT-fanboy/OpenW1700k` 的 `d80e5ed2c62d1fb380bf1e2bb586083bfb48e6dd`，产物必须为 `gemtek_w1700k-ubi` 的 `sysupgrade.itb`。

工作流 `.github/workflows/build-w1700k-private.yml` 在启动时检查仓库必须为私有，并读取仓库 Actions Secret `PRIVATE_CONFIG_B64`。该 Secret 是一个 `tar.gz` 文件的单行 Base64 编码。压缩包内必须包含：

- `etc/config/network`、`wireless`、`firewall`、`dhcp`
- `usr/share/homebridge/config.json`

当前准备的私有配置包还包含 OpenClash 主配置、订阅与自定义规则、UPnP、风扇、irqbalance 和 LuCI 设置。**不得把压缩包或其 Base64 内容提交到 Git。** 其中有宽带和 Wi-Fi 口令、订阅凭据、Homebridge 设备 token。仓库必须保持私有，构建产物仅作为 7 天的 Actions Artifact 保存。工作流不会建立公开 Release。

固件包含 OpenClash、Argon、UPnP、简体中文、`coreutils-nohup`、`etherwake`、irqbalance、W1700K Fan Control、Airoha SoC 状态页，以及 Node/Homebridge 和 `homebridge-miot` 插件。MiOT 插件会以设备型号 `xiaomi.derh.30l`、局域网 IP 和私有 token 初始化。该具体型号尚不在插件的明确支持列表中；插件可能使用通用 MiOT 映射，因此除湿、目标湿度等功能需要刷机后实机验证。

在 GitHub 仓库设为私有并设置 Secret 后，从 Actions 手动运行 **Build W1700K UBI private firmware**。构建完成时，先核对 Artifact 中的 `profiles.json`、manifest 和 `SHA256SUMS`，再用设备当前固件的备份恢复路径和 `sysupgrade -T` 验证镜像。工作流只构建，不会自动刷写路由器。


include $(TOPDIR)/rules.mk

PKG_NAME:=node-homebridge-miot
PKG_VERSION:=1.9.1
PKG_RELEASE:=1
PKG_SOURCE:=homebridge-miot-$(PKG_VERSION).tgz
PKG_SOURCE_URL:=https://registry.npmjs.org/homebridge-miot/-/
PKG_HASH:=e2f870e01ddecfd6079bbcdcc87602fb9942f042754ec8385f003eb119b336e
PKG_BUILD_DEPENDS:=node/host
PKG_LICENSE:=MIT
PKG_LICENSE_FILES:=LICENSE

include $(INCLUDE_DIR)/package.mk

define Package/node-homebridge-miot
  SUBMENU:=Node.js
  SECTION:=lang
  CATEGORY:=Languages
  TITLE:=Xiaomi MiOT plugin for Homebridge
  URL:=https://github.com/merdok/homebridge-miot
  DEPENDS:=+node-homebridge
endef

TAR_OPTIONS+= --strip-components 1
TAR_CMD=$(HOST_TAR) -C $(1) $(TAR_OPTIONS)

define Build/Compile
	cd $(PKG_BUILD_DIR) && npm install --no-audit --no-fund --omit=dev --no-package-lock --ignore-scripts
endef

define Package/node-homebridge-miot/install
	$(INSTALL_DIR) $(1)/usr/lib/node/homebridge-miot
	$(CP) $(PKG_BUILD_DIR)/* $(1)/usr/lib/node/homebridge-miot/
	$(INSTALL_DIR) $(1)/usr/lib/node_modules
	$(LN) ../node/homebridge-miot $(1)/usr/lib/node_modules/homebridge-miot
endef

$(eval $(call BuildPackage,node-homebridge-miot))


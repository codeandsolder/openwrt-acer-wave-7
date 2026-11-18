define Build/fit-inline-rootfs
	rm -f $@.dtb $@.kernel
	cp $@ $@.kernel
	cp $(word 2,$(1)) $@.dtb
	cp $@.kernel $@
	$(call Build/fit-its,$(word 1,$(1)) $@.dtb with-rootfs)
	$(call Build/fit-image,$(word 1,$(1)) $@.dtb with-rootfs)
	kernel_size="$$(stat -c%s $@.kernel)"; \
	rootfs_offset="$$(grep -oba hsqs $@ | \
		awk -F: -v limit="$$kernel_size" '$$1 >= limit {print $$1; exit}')"; \
	[ -n "$$rootfs_offset" ] || { echo "Failed to locate SquashFS in $@"; exit 1; }; \
	pad="$$(( (4096 - ($$rootfs_offset % 4096)) % 4096 ))"; \
	cp $(word 2,$(1)) $@.dtb; \
	dd if=/dev/zero bs=1 count="$$pad" >> $@.dtb 2>/dev/null; \
	cp $@.kernel $@; \
	$(call Build/fit-its,$(word 1,$(1)) $@.dtb with-rootfs)
	$(call Build/fit-image,$(word 1,$(1)) $@.dtb with-rootfs)
	kernel_size="$$(stat -c%s $@.kernel)"; \
	rootfs_offset="$$(grep -oba hsqs $@ | \
		awk -F: -v limit="$$kernel_size" '$$1 >= limit {print $$1; exit}')"; \
	[ "$$(( $$rootfs_offset % 4096 ))" -eq 0 ] || { echo "SquashFS is misaligned in $@"; exit 1; }; \
	rm -f $@.dtb $@.kernel
endef

define Build/verify-wave7-firmware
	$(TOPDIR)/scripts/wave7/stage-firmware.sh verify-root "$(TARGET_DIR)"
endef

define Build/verify-wave7-bootargs
	$(TOPDIR)/scripts/wave7/verify-boot-mode-dtb.sh $(1) \
		$(KDIR)/image-ipq5332-acer-wave7$(if $(filter ram,$(1)),-initramfs).dtb \
		$(LINUX_DIR)/scripts/dtc/dtc
endef

define Device/acer_wave7
	DEVICE_VENDOR := Acer
	DEVICE_MODEL := Wave 7
	# Compile separate DTS variants: persistent NAND root and RAM-only boot.
	DEVICE_DTS := ipq5332-acer-wave7 ipq5332-acer-wave7-initramfs
	DEVICE_DTS_CONFIG := config@mi04.1-c2
	SOC := ipq5332
	SUPPORTED_DEVICES += acer,wave7
	DEVICE_PACKAGES := kmod-dsa-rtl8365mb kmod-ath12k ethtool phytool
	KERNEL := verify-wave7-firmware | kernel-bin | lzma | \
		verify-wave7-bootargs nand | fit lzma $$(KDIR)/image-ipq5332-acer-wave7.dtb
	KERNEL_INITRAMFS := verify-wave7-firmware | kernel-bin | lzma | \
		verify-wave7-bootargs ram | fit lzma $$(KDIR)/image-ipq5332-acer-wave7-initramfs.dtb with-initrd | pad-to 64k
	KERNEL_INITRAMFS_SUFFIX := .itb
endef
TARGET_DEVICES += acer_wave7

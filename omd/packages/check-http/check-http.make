CHECK_HTTP := check-http
CHECK_HTTP_DEPLOYED := check_httpv2
CHECK_HTTP_PACKAGE := $(REPO_PATH)/packages/$(CHECK_HTTP)
CHECK_HTTP_RELEASE := $(CHECK_HTTP_PACKAGE)/target/release/check_http

CHECK_HTTP_BUILD := $(BUILD_HELPER_DIR)/$(CHECK_HTTP)-build
CHECK_HTTP_INSTALL := $(BUILD_HELPER_DIR)/$(CHECK_HTTP)-install

.PHONY: $(CHECK_HTTP_BUILD)
$(CHECK_HTTP_BUILD): $(OPENSSL_INTERMEDIATE_INSTALL)
	RUST_BACKTRACE=full \
	OPENSSL_DIR="$(OPENSSL_INSTALL_DIR)" \
	OPENSSL_LIB_DIR="$(OPENSSL_INSTALL_DIR)/lib" \
	OPENSSL_INCLUDE_DIR="$(OPENSSL_INSTALL_DIR)/include" \
	$(CHECK_HTTP_PACKAGE)/run --build
	# set RPATH
	patchelf --set-rpath "\$$ORIGIN/../../../lib" $(CHECK_HTTP_RELEASE)
	$(TOUCH) $@

.PHONY: $(CHECK_HTTP_INSTALL)
$(CHECK_HTTP_INSTALL): $(CHECK_HTTP_BUILD)
	install -m 755 $(CHECK_HTTP_RELEASE) $(DESTDIR)$(OMD_ROOT)/lib/nagios/plugins/$(CHECK_HTTP_DEPLOYED)
	$(TOUCH) $@

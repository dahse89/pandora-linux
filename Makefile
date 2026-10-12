.DEFAULT_GOAL := iso
PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: check iso iso-docker clean

check:
	@python3 "$(PROJECT_ROOT)/iso.py" check

iso:
	@python3 "$(PROJECT_ROOT)/iso.py" build

iso-docker:
	@python3 "$(PROJECT_ROOT)/iso.py" build-docker

# Remove generated builds only; keep authenticated downloads in cache/.
clean:
	@rm -rf -- "$(PROJECT_ROOT)/build"
	@find "$(PROJECT_ROOT)/artifacts" -maxdepth 1 -type f -name 'pandora-linux-*.iso*' -delete 2>/dev/null || test ! -e "$(PROJECT_ROOT)/artifacts"

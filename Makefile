.PHONY: assets test skills prepare-agent function-x86 circt-x86 hierarchy-x86

assets:
	python3 tools/check_assets.py

test:
	pytest -q

skills:
	dscflow skills

prepare-agent:
	dscflow uhdm-systemc prepare --config configs/uhdm_agent.json --output-dir .work/runs/uhdm-agent/dsc_encoder

function-x86:
	./models/function_tlm/run_x86_verify.sh

circt-x86:
	dscflow circt run --config configs/staged_circt.json --output-root .work/runs/staged-circt

hierarchy-x86:
	@test -n "$(CORE_IR)" -a -n "$(TOP)" -a -n "$(DEPTH)" || \
	  (echo "用法: make hierarchy-x86 CORE_IR=... TOP=... DEPTH=... [UHDM_JSON=...]" >&2; exit 2)
	./scripts/run_circt_hierarchy_peeling.sh \
	  "$(CORE_IR)" "$(TOP)" "$(DEPTH)" \
	  ".work/runs/hierarchy/$(TOP)/depth-$(DEPTH)" "$(UHDM_JSON)"

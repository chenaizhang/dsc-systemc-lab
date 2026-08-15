#pragma once

#include "dsc_function_tlm.hpp"

namespace dsc_function_tlm {

// Pure software implementation backed by the VESA DSC 1.2b C reference
// model.  The adapter has no SystemC process or RTL hierarchy: a complete
// frame and its PPS enter encode(), and a compressed frame leaves it.
//
// `approved` is deliberately explicit.  It must only be set after the local
// adapter has passed byte-exact comparison with the independently built VESA
// command-line model for the vectors used by the project.
class VesaReferenceCodec final : public SoftwareDscCodec {
public:
    explicit VesaReferenceCodec(bool approved = false) : approved_(approved) {}

    const char* name() const override { return "VESA DSC C model 1.67 (2021-12-13)"; }
    bool is_bit_exact_golden() const override { return approved_; }
    CodecResult encode(const FrameRequest& request) override;

private:
    bool approved_;
};

} // namespace dsc_function_tlm

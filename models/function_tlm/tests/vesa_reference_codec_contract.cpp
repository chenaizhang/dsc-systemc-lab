#include "vesa_reference_codec.hpp"

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct RgbImage {
    int width = 0;
    int height = 0;
    std::vector<std::uint8_t> pixels;
};

struct TlmDriver : sc_core::sc_module {
    tlm_utils::simple_initiator_socket<TlmDriver, 32> apb{"apb"};
    tlm_utils::simple_initiator_socket<TlmDriver, 192> pixel{"pixel"};

    explicit TlmDriver(sc_core::sc_module_name name) : sc_core::sc_module(name) {}

    bool write32(std::uint16_t address, std::uint32_t value)
    {
        std::array<unsigned char, 4> bytes{
            static_cast<unsigned char>(value & 0xffU),
            static_cast<unsigned char>((value >> 8U) & 0xffU),
            static_cast<unsigned char>((value >> 16U) & 0xffU),
            static_cast<unsigned char>((value >> 24U) & 0xffU)};
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_address(address);
        payload.set_data_ptr(bytes.data());
        payload.set_data_length(bytes.size());
        payload.set_streaming_width(bytes.size());
        sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
        apb->b_transport(payload, delay);
        return payload.get_response_status() == tlm::TLM_OK_RESPONSE;
    }

    bool configure(const std::array<std::uint8_t, 128>& pps)
    {
        if (!write32(0x104, 0))
            return false;
        for (const auto byte : pps) {
            if (!write32(0x100, byte))
                return false;
        }
        return write32(0x108, 1)
            && write32(0x000, static_cast<std::uint32_t>(dsc_tlm::EncoderCommand::EncodeFrame));
    }

    bool send(const dsc_tlm::PixelBeat& beat)
    {
        std::array<unsigned char, dsc_tlm::pixel_data_bytes> bytes{};
        for (std::size_t index = 0; index < beat.components.size(); ++index) {
            bytes[index * 2] = static_cast<unsigned char>(beat.components[index] & 0xffU);
            bytes[index * 2 + 1] = static_cast<unsigned char>(beat.components[index] >> 8U);
        }
        dsc_tlm::PixelStreamExtension extension;
        extension.valid_pixels = beat.valid_pixels;
        extension.start_of_frame = beat.start_of_frame;
        extension.end_of_frame = beat.end_of_frame;
        extension.start_of_line = beat.start_of_line;
        extension.end_of_line = beat.end_of_line;
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_address(0);
        payload.set_data_ptr(bytes.data());
        payload.set_data_length(bytes.size());
        payload.set_streaming_width(bytes.size());
        payload.set_extension(&extension);
        sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
        pixel->b_transport(payload, delay);
        payload.clear_extension<dsc_tlm::PixelStreamExtension>();
        return payload.get_response_status() == tlm::TLM_OK_RESPONSE;
    }
};

struct TlmSink : sc_core::sc_module {
    tlm_utils::simple_target_socket<TlmSink, 192> target{"target"};
    std::vector<std::uint8_t> bytes;
    bool saw_placeholder = false;

    explicit TlmSink(sc_core::sc_module_name name) : sc_core::sc_module(name)
    {
        target.register_b_transport(this, &TlmSink::b_transport);
    }

    void b_transport(tlm::tlm_generic_payload& payload, sc_core::sc_time& delay)
    {
        const auto* extension = payload.get_extension<dsc_tlm::EncodedStreamExtension>();
        if (!payload.is_write() || payload.get_data_ptr() == nullptr || extension == nullptr
            || extension->valid_bytes > payload.get_data_length()) {
            payload.set_response_status(tlm::TLM_BURST_ERROR_RESPONSE);
            return;
        }
        bytes.insert(bytes.end(), payload.get_data_ptr(),
            payload.get_data_ptr() + extension->valid_bytes);
        saw_placeholder = saw_placeholder || extension->algorithm_placeholder;
        delay += sc_core::sc_time(1, sc_core::SC_NS);
        payload.set_response_status(tlm::TLM_OK_RESPONSE);
    }
};

std::string ppm_token(std::istream& input)
{
    std::string token;
    char character = 0;
    while (input.get(character)) {
        if (character == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
            continue;
        }
        if (!std::isspace(static_cast<unsigned char>(character))) {
            token.push_back(character);
            break;
        }
    }
    while (input.get(character)) {
        if (std::isspace(static_cast<unsigned char>(character)))
            break;
        token.push_back(character);
    }
    return token;
}

RgbImage read_ppm(const std::string& path)
{
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw std::runtime_error("cannot open PPM input");
    if (ppm_token(input) != "P6")
        throw std::runtime_error("only binary P6 PPM is supported by this contract test");
    RgbImage image;
    image.width = std::stoi(ppm_token(input));
    image.height = std::stoi(ppm_token(input));
    if (ppm_token(input) != "255" || image.width <= 0 || image.height <= 0)
        throw std::runtime_error("invalid 8-bit PPM header");
    image.pixels.resize(static_cast<std::size_t>(image.width * image.height * 3));
    input.read(reinterpret_cast<char*>(image.pixels.data()),
        static_cast<std::streamsize>(image.pixels.size()));
    if (input.gcount() != static_cast<std::streamsize>(image.pixels.size()))
        throw std::runtime_error("truncated PPM input");
    return image;
}

std::vector<std::uint8_t> read_binary(const std::string& path)
{
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw std::runtime_error("cannot open reference bitstream");
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

dsc_function_tlm::FrameRequest make_request(
    const RgbImage& image, const std::vector<std::uint8_t>& dsc_file)
{
    constexpr std::size_t header_bytes = 4;
    constexpr std::size_t pps_bytes = 128;
    if (dsc_file.size() <= header_bytes + pps_bytes
        || std::string(dsc_file.begin(), dsc_file.begin() + 4) != "DSCF")
        throw std::runtime_error("reference file is not a VESA DSC file");

    dsc_function_tlm::FrameRequest request;
    std::copy_n(dsc_file.begin() + static_cast<std::ptrdiff_t>(header_bytes), pps_bytes,
        request.pps.begin());
    request.pixels_per_cycle = 4;
    request.output_mode = 7;

    const auto pixel_count = static_cast<std::size_t>(image.width * image.height);
    for (std::size_t first_pixel = 0; first_pixel < pixel_count; first_pixel += 4) {
        dsc_tlm::PixelBeat beat;
        beat.valid_pixels = static_cast<std::uint8_t>(
            std::min<std::size_t>(4, pixel_count - first_pixel));
        beat.start_of_frame = first_pixel == 0;
        beat.end_of_frame = first_pixel + beat.valid_pixels == pixel_count;
        beat.start_of_line = first_pixel % static_cast<std::size_t>(image.width) == 0;
        beat.end_of_line = (first_pixel + beat.valid_pixels)
            % static_cast<std::size_t>(image.width) == 0;
        for (std::size_t pixel = 0; pixel < beat.valid_pixels; ++pixel) {
            const auto source = (first_pixel + pixel) * 3;
            const auto target = pixel * 3;
            const auto red = image.pixels[source];
            const auto green = image.pixels[source + 1];
            const auto blue = image.pixels[source + 2];
            beat.components[target] = static_cast<std::uint16_t>(blue) << 8U;
            beat.components[target + 1] = static_cast<std::uint16_t>(green) << 8U;
            beat.components[target + 2] = static_cast<std::uint16_t>(red) << 8U;
        }
        request.beats.push_back(beat);
    }
    return request;
}

} // namespace

int sc_main(int argc, char** argv)
{
    try {
        if (argc != 3) {
            std::cerr << "usage: vesa_reference_codec_contract INPUT.ppm REFERENCE.dsc\n";
            return 2;
        }
        const auto image = read_ppm(argv[1]);
        const auto dsc_file = read_binary(argv[2]);
        const auto request = make_request(image, dsc_file);

        dsc_function_tlm::VesaReferenceCodec codec(true);
        dsc_function_tlm::DscFunctionTlm model("dsc_function_model", &codec);
        TlmDriver driver("driver");
        TlmSink sink("sink");
        driver.apb.bind(model.apb);
        driver.pixel.bind(model.pixel_stream_in);
        model.bitstream_out.bind(sink.target);
        sc_core::sc_start(sc_core::SC_ZERO_TIME);

        const auto result = codec.encode(request);
        if (result.status != dsc_function_tlm::CodecStatus::Ok) {
            std::cerr << result.diagnostic << '\n';
            return 3;
        }
        constexpr std::size_t payload_offset = 4 + 128;
        const std::vector<std::uint8_t> expected(
            dsc_file.begin() + static_cast<std::ptrdiff_t>(payload_offset), dsc_file.end());
        if (result.bitstream != expected) {
            std::cerr << "bit-exact comparison failed: adapter=" << result.bitstream.size()
                      << " bytes, VESA CLI=" << expected.size() << " bytes\n";
            const auto common = std::min(result.bitstream.size(), expected.size());
            for (std::size_t index = 0; index < common; ++index) {
                if (result.bitstream[index] != expected[index]) {
                    std::cerr << "first mismatch at byte " << index << ": adapter="
                              << static_cast<unsigned>(result.bitstream[index]) << ", CLI="
                              << static_cast<unsigned>(expected[index]) << '\n';
                    break;
                }
            }
            return 4;
        }
        if (!driver.configure(request.pps)) {
            std::cerr << "failed to configure the TLM function model\n";
            return 6;
        }
        for (const auto& beat : request.beats) {
            if (!driver.send(beat)) {
                std::cerr << "TLM function model rejected an input beat: "
                          << model.last_diagnostic() << '\n';
                return 7;
            }
        }
        if (sink.saw_placeholder || sink.bytes != expected || model.encoded_frame_count() != 1) {
            std::cerr << "TLM wrapper output differs from the approved software function output\n";
            return 8;
        }
        std::cout << "PASS bytes=" << result.bitstream.size() << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 5;
    }
}

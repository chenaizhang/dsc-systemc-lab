#include <uhdm/Serializer.h>
#include <uhdm/uhdm.h>
#include <uhdm/vpi_user.h>

#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

std::string VpiString(vpiHandle handle, int property) {
  const char* value = vpi_get_str(property, handle);
  return value == nullptr ? std::string() : std::string(value);
}

std::string JsonEscape(const std::string& value) {
  std::string escaped;
  escaped.reserve(value.size());
  for (unsigned char character : value) {
    switch (character) {
      case '"':
        escaped += "\\\"";
        break;
      case '\\':
        escaped += "\\\\";
        break;
      case '\b':
        escaped += "\\b";
        break;
      case '\f':
        escaped += "\\f";
        break;
      case '\n':
        escaped += "\\n";
        break;
      case '\r':
        escaped += "\\r";
        break;
      case '\t':
        escaped += "\\t";
        break;
      default:
        if (character < 0x20) {
          static const char hex[] = "0123456789abcdef";
          escaped += "\\u00";
          escaped += hex[character >> 4];
          escaped += hex[character & 0x0f];
        } else {
          escaped += static_cast<char>(character);
        }
        break;
    }
  }
  return escaped;
}

void Indent(std::ostream& output, unsigned int level) {
  for (unsigned int index = 0; index < level; ++index) {
    output << "  ";
  }
}

void WriteString(std::ostream& output, const std::string& value) {
  output << '"' << JsonEscape(value) << '"';
}

struct ModuleNode {
  std::string instance_name;
  std::string definition_name;
  std::string full_name;
  std::vector<ModuleNode> children;
};

struct Invocation {
  std::string parent_instance_full_name;
  std::string child_instance_full_name;
  std::string parent_definition_name;
  std::string child_definition_name;
};

ModuleNode ReadModuleTree(vpiHandle module, std::vector<Invocation>& invocations,
                          const std::string& parent_instance,
                          const std::string& parent_definition) {
  ModuleNode node;
  node.instance_name = VpiString(module, vpiName);
  node.definition_name = VpiString(module, vpiDefName);
  node.full_name = VpiString(module, vpiFullName);

  if (!parent_instance.empty() || !parent_definition.empty()) {
    invocations.push_back({parent_instance, node.full_name, parent_definition,
                           node.definition_name});
  }

  vpiHandle iterator = vpi_iterate(vpiModule, module);
  if (iterator != nullptr) {
    while (vpiHandle child = vpi_scan(iterator)) {
      node.children.push_back(ReadModuleTree(
          child, invocations, node.full_name, node.definition_name));
    }
  }
  return node;
}

void WriteModuleTree(std::ostream& output, const ModuleNode& node,
                     unsigned int level) {
  Indent(output, level);
  output << "{\n";
  Indent(output, level + 1);
  output << "\"instance_name\": ";
  WriteString(output, node.instance_name);
  output << ",\n";
  Indent(output, level + 1);
  output << "\"definition_name\": ";
  WriteString(output, node.definition_name);
  output << ",\n";
  Indent(output, level + 1);
  output << "\"full_name\": ";
  WriteString(output, node.full_name);
  output << ",\n";
  Indent(output, level + 1);
  output << "\"children\": [";
  if (!node.children.empty()) {
    output << '\n';
    for (std::size_t index = 0; index < node.children.size(); ++index) {
      WriteModuleTree(output, node.children[index], level + 2);
      if (index + 1 != node.children.size()) {
        output << ',';
      }
      output << '\n';
    }
    Indent(output, level + 1);
  }
  output << "]\n";
  Indent(output, level);
  output << '}';
}

void WriteInvocation(std::ostream& output, const Invocation& invocation,
                     unsigned int level) {
  Indent(output, level);
  output << "{\n";
  Indent(output, level + 1);
  output << "\"parent_instance_full_name\": ";
  WriteString(output, invocation.parent_instance_full_name);
  output << ",\n";
  Indent(output, level + 1);
  output << "\"child_instance_full_name\": ";
  WriteString(output, invocation.child_instance_full_name);
  output << ",\n";
  Indent(output, level + 1);
  output << "\"parent_definition_name\": ";
  WriteString(output, invocation.parent_definition_name);
  output << ",\n";
  Indent(output, level + 1);
  output << "\"child_definition_name\": ";
  WriteString(output, invocation.child_definition_name);
  output << '\n';
  Indent(output, level);
  output << '}';
}

void WriteDesign(std::ostream& output, vpiHandle design, unsigned int level) {
  std::vector<std::string> definitions;
  std::vector<ModuleNode> top_modules;
  std::vector<Invocation> invocations;

  vpiHandle all_modules = vpi_iterate(UHDM::uhdmallModules, design);
  vpiHandle definition_iterator =
      all_modules;
  if (definition_iterator != nullptr) {
    while (vpiHandle module = vpi_scan(definition_iterator)) {
      definitions.push_back(VpiString(module, vpiDefName));
    }
  }

  vpiHandle top_modules_handle = vpi_iterate(UHDM::uhdmtopModules, design);
  vpiHandle top_iterator = top_modules_handle == nullptr
                               ? nullptr
                               : top_modules_handle;
  if (top_iterator != nullptr) {
    while (vpiHandle module = vpi_scan(top_iterator)) {
      top_modules.push_back(ReadModuleTree(module, invocations, "", ""));
    }
  }

  Indent(output, level);
  output << "{\n";
  Indent(output, level + 1);
  output << "\"module_definitions\": [";
  if (!definitions.empty()) {
    output << '\n';
    for (std::size_t index = 0; index < definitions.size(); ++index) {
      Indent(output, level + 2);
      WriteString(output, definitions[index]);
      if (index + 1 != definitions.size()) {
        output << ',';
      }
      output << '\n';
    }
    Indent(output, level + 1);
  }
  output << "],\n";
  Indent(output, level + 1);
  output << "\"top_modules\": [";
  if (!top_modules.empty()) {
    output << '\n';
    for (std::size_t index = 0; index < top_modules.size(); ++index) {
      WriteModuleTree(output, top_modules[index], level + 2);
      if (index + 1 != top_modules.size()) {
        output << ',';
      }
      output << '\n';
    }
    Indent(output, level + 1);
  }
  output << "],\n";
  Indent(output, level + 1);
  output << "\"invocations\": [";
  if (!invocations.empty()) {
    output << '\n';
    for (std::size_t index = 0; index < invocations.size(); ++index) {
      WriteInvocation(output, invocations[index], level + 2);
      if (index + 1 != invocations.size()) {
        output << ',';
      }
      output << '\n';
    }
    Indent(output, level + 1);
  }
  output << "]\n";
  Indent(output, level);
  output << '}';
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2 && argc != 3) {
    std::cerr << "usage: uhdm_module_hierarchy INPUT_UHDM [OUTPUT_JSON]\n";
    return 2;
  }

  const std::string input_path(argv[1]);
  UHDM::Serializer serializer;
  const std::vector<vpiHandle>& designs = serializer.Restore(input_path);

  std::ofstream file_output;
  std::ostream* output = &std::cout;
  if (argc == 3) {
    file_output.open(argv[2]);
    if (!file_output) {
      std::cerr << "error: cannot open output JSON: " << argv[2] << '\n';
      return 1;
    }
    output = &file_output;
  }

  *output << "{\n  \"source\": ";
  WriteString(*output, input_path);
  *output << ",\n  \"designs\": [";
  if (!designs.empty()) {
    *output << '\n';
    for (std::size_t index = 0; index < designs.size(); ++index) {
      WriteDesign(*output, designs[index], 2);
      if (index + 1 != designs.size()) {
        *output << ',';
      }
      *output << '\n';
    }
    *output << "  ";
  }
  *output << "]\n}\n";

  if (!*output) {
    std::cerr << "error: failed while writing JSON output\n";
    return 1;
  }
  return 0;
}

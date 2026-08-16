#include <uhdm/Serializer.h>
#include <uhdm/uhdm.h>
#include <uhdm/vpi_user.h>

#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_set>
#include <utility>
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
  struct Port {
    std::string name;
    std::string direction;
    int width = 0;
    bool connected = false;
    std::string connection_name;
    std::string connection_full_name;
    std::string source_file;
    int source_line = 0;
  };

  std::string instance_name;
  std::string definition_name;
  std::string full_name;
  std::vector<Port> ports;
  std::vector<ModuleNode> children;
};

struct Invocation {
  std::string parent_instance_full_name;
  std::string child_instance_full_name;
  std::string parent_definition_name;
  std::string child_definition_name;
};

std::string DirectionName(int direction) {
  switch (direction) {
    case vpiInput:
      return "input";
    case vpiOutput:
      return "output";
    case vpiInout:
      return "inout";
    default:
      return "unknown";
  }
}

std::vector<ModuleNode::Port> ReadPorts(vpiHandle module) {
  std::vector<ModuleNode::Port> ports;
  vpiHandle iterator = vpi_iterate(vpiPort, module);
  if (iterator == nullptr) {
    return ports;
  }
  while (vpiHandle port = vpi_scan(iterator)) {
    ModuleNode::Port item;
    item.name = VpiString(port, vpiName);
    item.direction = DirectionName(vpi_get(vpiDirection, port));
    item.width = vpi_get(vpiSize, port);
    item.source_file = VpiString(port, vpiFile);
    item.source_line = vpi_get(vpiLineNo, port);

    // For an elaborated instance, vpiHighConn is the expression in the
    // parent scope connected to this port.  Keep both the printable name and
    // hierarchical name because packed selects and constants often have no
    // vpiFullName.
    vpiHandle connection = vpi_handle(vpiHighConn, port);
    if (connection != nullptr) {
      item.connected = true;
      item.connection_name = VpiString(connection, vpiName);
      item.connection_full_name = VpiString(connection, vpiFullName);
      if (item.connection_name.empty()) {
        item.connection_name = VpiString(connection, vpiDecompile);
      }
    }
    ports.push_back(std::move(item));
  }
  return ports;
}

ModuleNode ReadModuleTree(vpiHandle module, std::vector<Invocation>& invocations,
                          const std::string& parent_instance,
                          const std::string& parent_definition,
                          std::unordered_set<std::string>& visited_modules);

std::string ModuleIdentity(vpiHandle module) {
  const std::string full_name = VpiString(module, vpiFullName);
  if (!full_name.empty()) {
    return full_name;
  }
  return VpiString(module, vpiDefName) + "::" + VpiString(module, vpiName);
}

void ReadModulesInScope(vpiHandle scope, std::vector<ModuleNode>& children,
                        std::vector<Invocation>& invocations,
                        const std::string& parent_instance,
                        const std::string& parent_definition,
                        std::unordered_set<std::string>& visited_modules) {
  vpiHandle module_iterator = vpi_iterate(vpiModule, scope);
  if (module_iterator != nullptr) {
    while (vpiHandle child = vpi_scan(module_iterator)) {
      const std::string identity = ModuleIdentity(child);
      if (visited_modules.insert(identity).second) {
        children.push_back(ReadModuleTree(child, invocations, parent_instance,
                                          parent_definition, visited_modules));
      }
    }
  }

  // Elaborated instances created by generate loops/conditionals are owned by
  // vpiGenScope nodes rather than directly by their containing vpiModule.
  // Walk both individual scopes and scope arrays so those instances are not
  // silently omitted from the exported hierarchy.
  vpiHandle generate_iterator = vpi_iterate(vpiGenScope, scope);
  if (generate_iterator != nullptr) {
    while (vpiHandle generate_scope = vpi_scan(generate_iterator)) {
      ReadModulesInScope(generate_scope, children, invocations,
                         parent_instance, parent_definition, visited_modules);
    }
  }

  vpiHandle generate_array_iterator = vpi_iterate(vpiGenScopeArray, scope);
  if (generate_array_iterator != nullptr) {
    while (vpiHandle generate_array = vpi_scan(generate_array_iterator)) {
      ReadModulesInScope(generate_array, children, invocations,
                         parent_instance, parent_definition, visited_modules);
    }
  }
}

ModuleNode ReadModuleTree(vpiHandle module, std::vector<Invocation>& invocations,
                          const std::string& parent_instance,
                          const std::string& parent_definition,
                          std::unordered_set<std::string>& visited_modules) {
  ModuleNode node;
  node.instance_name = VpiString(module, vpiName);
  node.definition_name = VpiString(module, vpiDefName);
  node.full_name = VpiString(module, vpiFullName);
  node.ports = ReadPorts(module);

  if (!parent_instance.empty() || !parent_definition.empty()) {
    invocations.push_back({parent_instance, node.full_name, parent_definition,
                           node.definition_name});
  }

  ReadModulesInScope(module, node.children, invocations, node.full_name,
                     node.definition_name, visited_modules);
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
  output << "\"ports\": [";
  if (!node.ports.empty()) {
    output << '\n';
    for (std::size_t index = 0; index < node.ports.size(); ++index) {
      const ModuleNode::Port& port = node.ports[index];
      Indent(output, level + 2);
      output << "{\n";
      Indent(output, level + 3);
      output << "\"name\": ";
      WriteString(output, port.name);
      output << ",\n";
      Indent(output, level + 3);
      output << "\"direction\": ";
      WriteString(output, port.direction);
      output << ",\n";
      Indent(output, level + 3);
      output << "\"width_bits\": " << port.width << ",\n";
      Indent(output, level + 3);
      output << "\"connected\": " << (port.connected ? "true" : "false")
             << ",\n";
      Indent(output, level + 3);
      output << "\"connection_name\": ";
      WriteString(output, port.connection_name);
      output << ",\n";
      Indent(output, level + 3);
      output << "\"connection_full_name\": ";
      WriteString(output, port.connection_full_name);
      output << ",\n";
      Indent(output, level + 3);
      output << "\"source_file\": ";
      WriteString(output, port.source_file);
      output << ",\n";
      Indent(output, level + 3);
      output << "\"source_line\": " << port.source_line << '\n';
      Indent(output, level + 2);
      output << '}';
      if (index + 1 != node.ports.size()) {
        output << ',';
      }
      output << '\n';
    }
    Indent(output, level + 1);
  }
  output << "],\n";
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
  std::unordered_set<std::string> visited_modules;

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
      visited_modules.insert(ModuleIdentity(module));
      top_modules.push_back(
          ReadModuleTree(module, invocations, "", "", visited_modules));
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

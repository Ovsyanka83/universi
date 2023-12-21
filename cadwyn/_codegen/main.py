import ast
import dataclasses
import importlib
import os
import shutil
from collections.abc import Callable, Collection, Generator
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import ast_comments

from cadwyn._codegen.asts import get_all_names_defined_at_toplevel_of_module, read_python_module
from cadwyn._codegen.common import CodegenContext, GlobalCodegenContext, PydanticModelWrapper, _EnumWrapper
from cadwyn._package_utils import IdentifierPythonPath, get_package_path_from_module, get_version_dir_path
from cadwyn._utils import get_index_of_latest_schema_dir_in_module_python_path
from cadwyn.structure.versions import Version

_AUTO_GENERATION_WARNING = "# THIS FILE WAS AUTO-GENERATED BY CADWYN. DO NOT EVER TRY TO EDIT IT BY HAND\n\n"


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class CodegenPlugin:
    # TODO: Validate that the call has the right args and that call arg type is the same as node type at runtime
    call: Callable[[Any, CodegenContext], ast.AST | ast.Module]
    node_type: type[ast.AST] | None = None


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class MigrationPlugin:
    call: Callable[[GlobalCodegenContext], None]


def generate_versioned_directories(
    template_package: ModuleType,
    versions: list[Version],
    schemas: dict[IdentifierPythonPath, PydanticModelWrapper],
    enums: dict[IdentifierPythonPath, _EnumWrapper],
    extra_context: dict[str, Any],
    codegen_plugins: Collection[CodegenPlugin],
    migration_plugins: Collection[MigrationPlugin],
):
    # TODO: An alternative structure for module python path: An object similar to pathlib.Path with .name, etc
    for version in versions:
        global_context = GlobalCodegenContext(
            current_version=version,
            versions=versions,
            schemas=schemas,
            enums=enums,
            extra=extra_context,
        )
        _generate_directory_for_version(template_package, codegen_plugins, version, global_context)
        for plugin in migration_plugins:
            plugin.call(global_context)


def _generate_directory_for_version(
    template_package: ModuleType,
    plugins: Collection[CodegenPlugin],
    version: Version,
    global_context: GlobalCodegenContext,
):
    # TODO: This call can be optimized
    template_dir = get_package_path_from_module(template_package)
    version_dir = get_version_dir_path(template_package, version.value)
    for (
        _relative_path_to_file,
        template_module,
        parallel_file,
    ) in generate_parallel_directory(
        template_package,
        version_dir,
    ):
        file_source = read_python_module(template_module)
        parsed_file = ast.parse(file_source)
        if template_module.__name__.endswith(".__init__"):
            module_python_path = template_module.__name__.removesuffix(".__init__")
        else:
            module_python_path = template_module.__name__
        all_names_defined_at_toplevel_of_file = get_all_names_defined_at_toplevel_of_module(
            parsed_file,
            module_python_path,
        )
        version_dir = template_dir.with_name(version_dir.name)
        index_of_latest_schema_dir_in_module_python_path = get_index_of_latest_schema_dir_in_module_python_path(
            template_module,
            version_dir,
        )
        context: CodegenContext = CodegenContext(
            current_version=global_context.current_version,
            versions=global_context.versions,
            schemas=global_context.schemas,
            enums=global_context.enums,
            extra=global_context.extra,
            index_of_latest_schema_dir_in_module_python_path=index_of_latest_schema_dir_in_module_python_path,
            module_python_path=module_python_path,
            all_names_defined_on_toplevel_of_file=all_names_defined_at_toplevel_of_file,
            template_module=template_module,
            module_path=parallel_file,
        )
        node_type = type(parsed_file)
        for plugin in plugins:
            if plugin.node_type is None or issubclass(node_type, plugin.node_type):
                parsed_file = cast(ast.Module, plugin.call(parsed_file, context))

        new_body = []

        for node in parsed_file.body:
            node_type = type(node)
            for plugin in plugins:
                if plugin.node_type is None or isinstance(node_type, plugin.node_type):
                    node = plugin.call(node, context)  # noqa: PLW2901
            new_body.append(node)

        parallel_file.write_text(
            _AUTO_GENERATION_WARNING + ast_comments.unparse(ast.Module(body=new_body, type_ignores=[])),
        )


def generate_parallel_directory(
    template_module: ModuleType,
    parallel_dir: Path,
) -> Generator[tuple[Path, ModuleType, Path], Any, None]:
    if template_module.__file__ is None:  # pragma: no cover
        raise ValueError(
            f"You passed a {template_module=} but it doesn't have a file "
            "so it is impossible to generate its counterpart.",
        )
    dir = get_package_path_from_module(template_module)
    parallel_dir.mkdir(exist_ok=True)
    # >>> [cadwyn, structure, schemas]
    template_module_python_path_parts = template_module.__name__.split(".")
    # >>> [home, foo, bar, cadwyn, structure, schemas]
    template_module_path_parts = Path(template_module.__file__).parent.parts
    # >>> [home, foo, bar] = [home, foo, bar, cadwyn, structure, schemas][:-3]
    root_module_path = Path(
        *template_module_path_parts[: -len(template_module_python_path_parts)],
    )
    for subroot, dirnames, filenames in os.walk(dir):
        original_subroot = Path(subroot)
        parallel_subroot = parallel_dir / original_subroot.relative_to(dir)
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for dirname in dirnames:
            (parallel_subroot / dirname).mkdir(exist_ok=True)
        for filename in filenames:
            original_file = (original_subroot / filename).absolute()
            parallel_file = (parallel_subroot / filename).absolute()

            if filename.endswith(".py"):
                original_module_path = ".".join(
                    original_file.relative_to(root_module_path).with_suffix("").parts,
                )
                original_module = importlib.import_module(original_module_path)
                yield original_subroot.relative_to(dir), original_module, parallel_file
            else:
                shutil.copyfile(original_file, parallel_file)

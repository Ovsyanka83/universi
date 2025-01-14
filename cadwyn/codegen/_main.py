import ast
import importlib
import os
import shutil
from collections.abc import Collection, Generator, Sequence
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any, overload

import ast_comments
from typing_extensions import deprecated

from cadwyn._asts import get_all_names_defined_at_toplevel_of_module, read_python_module
from cadwyn._package_utils import IdentifierPythonPath, get_package_path_from_module, get_version_dir_path
from cadwyn._utils import get_index_of_head_schema_dir_in_module_python_path
from cadwyn.codegen._common import (
    CodegenContext,
    CodegenPlugin,
    GlobalCodegenContext,
    MigrationPlugin,
    PydanticModelWrapper,
    _EnumWrapper,
    _ModuleWrapper,
    get_fields_and_validators_from_model,
)
from cadwyn.codegen._plugins.class_migrations import class_migration_plugin
from cadwyn.codegen._plugins.class_rebuilding import ClassRebuildingPlugin
from cadwyn.codegen._plugins.class_renaming import ClassRenamingPlugin
from cadwyn.codegen._plugins.import_auto_adding import ImportAutoAddingPlugin
from cadwyn.codegen._plugins.module_migrations import module_migration_plugin
from cadwyn.structure.versions import Version, VersionBundle

_AUTO_GENERATION_WARNING = "# THIS FILE WAS AUTO-GENERATED BY CADWYN. DO NOT EVER TRY TO EDIT IT BY HAND\n\n"


DEFAULT_CODEGEN_PLUGINS: tuple[CodegenPlugin, ...] = (
    ClassRebuildingPlugin(),
    ClassRenamingPlugin(),
    ImportAutoAddingPlugin(),
)
DEFAULT_CODEGEN_MIGRATION_PLUGINS: tuple[MigrationPlugin, ...] = (
    module_migration_plugin,
    class_migration_plugin,
)


@overload
def generate_code_for_versioned_packages(
    head_package: ModuleType,
    versions: VersionBundle,
    *,
    codegen_plugins: Sequence[CodegenPlugin] = DEFAULT_CODEGEN_PLUGINS,
    migration_plugins: Sequence[MigrationPlugin] = DEFAULT_CODEGEN_MIGRATION_PLUGINS,
    extra_context: dict[str, Any] | None = None,
): ...


@overload
@deprecated(
    "ignore_coverage_for_latest_aliases is deprecated. "
    "You do not need to pass it any longer and it is going to be deleted in the future."
)
def generate_code_for_versioned_packages(
    head_package: ModuleType,
    versions: VersionBundle,
    *,
    ignore_coverage_for_latest_aliases: bool | None = None,
    codegen_plugins: Sequence[CodegenPlugin] = DEFAULT_CODEGEN_PLUGINS,
    migration_plugins: Sequence[MigrationPlugin] = DEFAULT_CODEGEN_MIGRATION_PLUGINS,
    extra_context: dict[str, Any] | None = None,
): ...


def generate_code_for_versioned_packages(
    head_package: ModuleType,
    versions: VersionBundle,
    *,
    ignore_coverage_for_latest_aliases: bool | None = None,
    codegen_plugins: Sequence[CodegenPlugin] = DEFAULT_CODEGEN_PLUGINS,
    migration_plugins: Sequence[MigrationPlugin] = DEFAULT_CODEGEN_MIGRATION_PLUGINS,
    extra_context: dict[str, Any] | None = None,
):
    """
    Args:
        head_package: The head package from which we will generate the versioned packages
        versions: Version bundle to generate versions from the head package.
    """
    extra_context = extra_context or {}
    schemas = {}
    for k, v in deepcopy(versions.versioned_schemas).items():
        fields, validators = get_fields_and_validators_from_model(v)
        schemas[k] = PydanticModelWrapper(v, v.__name__, fields, validators)

    _generate_versioned_directories(
        head_package,
        versions=list(versions),
        schemas=schemas,
        enums={
            k: _EnumWrapper(v, {member.name: member.value for member in v})
            for k, v in deepcopy(versions.versioned_enums).items()
        },
        modules={k: _ModuleWrapper(module) for k, module in versions.versioned_modules.items()},
        version_bundle=versions,
        extra_context=extra_context | {"ignore_coverage_for_latest_aliases": ignore_coverage_for_latest_aliases},
        codegen_plugins=codegen_plugins,
        migration_plugins=migration_plugins,
    )
    # This should not affect real use cases at all but is rather useful for testing
    importlib.invalidate_caches()


def _generate_versioned_directories(
    template_package: ModuleType,
    versions: list[Version],
    schemas: dict[IdentifierPythonPath, PydanticModelWrapper],
    enums: dict[IdentifierPythonPath, _EnumWrapper],
    modules: dict[IdentifierPythonPath, _ModuleWrapper],
    version_bundle: VersionBundle,
    extra_context: dict[str, Any],
    codegen_plugins: Collection[CodegenPlugin],
    migration_plugins: Collection[MigrationPlugin],
):
    global_context = GlobalCodegenContext(
        current_version=version_bundle.head_version,
        versions=versions,
        schemas=schemas,
        enums=enums,
        modules=modules,
        extra=extra_context,
        version_bundle=version_bundle,
    )
    for plugin in migration_plugins:
        plugin(global_context)
    for version in versions:
        print(f"Generating code for version={version.value!s}")  # noqa: T201
        global_context = GlobalCodegenContext(
            current_version=version,
            versions=versions,
            schemas=schemas,
            enums=enums,
            modules=modules,
            extra=extra_context,
            version_bundle=version_bundle,
        )
        _generate_directory_for_version(template_package, codegen_plugins, version, global_context)
        for plugin in migration_plugins:
            plugin(global_context)


def _generate_directory_for_version(
    template_package: ModuleType,
    plugins: Collection[CodegenPlugin],
    version: Version,
    global_context: GlobalCodegenContext,
):
    template_dir = get_package_path_from_module(template_package)
    version_dir = get_version_dir_path(template_package, version.value)

    for (
        _relative_path_to_file,
        template_module,
        parallel_file,
    ) in _generate_parallel_directory(
        template_package,
        version_dir,
    ):
        file_source = read_python_module(template_module)
        parsed_file = ast_comments.parse(file_source)
        context = _build_context(global_context, template_dir, version_dir, template_module, parallel_file, parsed_file)

        parsed_file = _apply_module_level_plugins(plugins, parsed_file, context)
        new_module = _apply_per_node_plugins(plugins, parsed_file, context)
        parallel_file.write_text(_AUTO_GENERATION_WARNING + ast_comments.unparse(new_module))


def _apply_module_level_plugins(
    plugins: Collection[CodegenPlugin],
    parsed_file: ast_comments.Module,
    context: CodegenContext,
) -> ast_comments.Module:
    node_type = type(parsed_file)
    for plugin in plugins:
        if issubclass(node_type, plugin.node_type):
            parsed_file = plugin(parsed_file, context)
    return parsed_file


def _apply_per_node_plugins(
    plugins: Collection[CodegenPlugin],
    parsed_file: ast_comments.Module,
    context: CodegenContext,
) -> ast_comments.Module:
    new_body = []

    for node in parsed_file.body:
        node_type = type(node)
        for plugin in plugins:
            if issubclass(node_type, plugin.node_type):
                node = plugin(node, context)  # noqa: PLW2901
        new_body.append(node)

    return ast_comments.Module(body=new_body, type_ignores=[])


def _build_context(
    global_context: GlobalCodegenContext,
    template_dir: Path,
    version_dir: Path,
    template_module: ModuleType,
    parallel_file: Path,
    parsed_file: ast_comments.Module,
):
    if template_module.__name__.endswith(".__init__"):
        module_python_path = template_module.__name__.removesuffix(".__init__")
    else:
        module_python_path = template_module.__name__
    all_names_defined_at_toplevel_of_file = get_all_names_defined_at_toplevel_of_module(
        parsed_file,
        module_python_path,
    )
    index_of_head_package_dir_in_module_python_path = get_index_of_head_schema_dir_in_module_python_path(
        template_module,
        template_dir.with_name(version_dir.name),
    )
    return CodegenContext(
        current_version=global_context.current_version,
        versions=global_context.versions,
        schemas=global_context.schemas,
        enums=global_context.enums,
        modules=global_context.modules,
        extra=global_context.extra,
        index_of_head_package_dir_in_module_python_path=index_of_head_package_dir_in_module_python_path,
        module_python_path=module_python_path,
        all_names_defined_on_toplevel_of_file=all_names_defined_at_toplevel_of_file,
        template_module=template_module,
        module_path=parallel_file,
        version_bundle=global_context.version_bundle,
    )


def _generate_parallel_directory(
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

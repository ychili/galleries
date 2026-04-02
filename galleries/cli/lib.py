"""Library module for command-line interface"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import dataclasses
import itertools
import logging
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TextIO, TypeVar

from .. import PROG

if TYPE_CHECKING:
    from _typeshed import StrPath

PathSpecT = TypeVar("PathSpecT", bound="CollectionPathSpec")

DB_DIR_NAME = ".galleries"
DB_CONFIG_NAME = "db.conf"
DEFAULT_PATH_SPEC = {"GalleriesDir": DB_DIR_NAME, "ConfigName": DB_CONFIG_NAME}
DEFAULT_GLOBAL_CONFIG: dict[str, dict[str, Any]] = {
    "global": {"Verbose": False},
    "init": {},
}
DEFAULT_CONFIG_STATE: dict[str, dict[str, Any]] = {
    "db": {
        "CSVName": "db.csv",
        "TagFields": "Tags",
        "PathField": "Path",
        "CountField": "Count",
    },
    "refresh": {"BackupSuffix": ".bak", "ReverseSort": False},
    "count": {},
    "query": {
        "Format": "none",
        "AutoFormat": "rich",
        "FieldFormats": "tableformat.conf",
        "RichTable": "richtable.toml",
    },
    "related": {"SortMetric": "cosine", "Filter": "", "Limit": 20},
}

log = logging.getLogger(__name__)


class AppendStoreConstAction(argparse.Action):
    """Like "append" and "append_const" combined."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        items = getattr(namespace, self.dest, None)
        if items is None:
            items = []
        items.append((values, self.const))
        setattr(namespace, self.dest, items)


class FileType:
    """Reduced version of ``argparse.FileType``.

    Only checks for special argument
    "-" meaning stdin (for mode "r") or stdout (for mode "w").
    """

    def __init__(self, mode: Literal["r", "w"] = "r") -> None:
        self.mode = mode

    def __call__(self, string: str) -> Path | TextIO:
        if string == "-":
            if "r" in self.mode:
                return sys.stdin
            if "w" in self.mode:
                return sys.stdout
            msg = f"argument '-' with mode {self.mode}"
            raise ValueError(msg)
        return Path(string)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.mode!r})"


class GlobalConfig:
    def __init__(
        self,
        options_p: configparser.ConfigParser | None = None,
        collections_p: configparser.ConfigParser | None = None,
    ) -> None:
        if options_p is None:
            self.options = configparser.ConfigParser(interpolation=None)
        else:
            self.options = options_p
        if collections_p is None:
            self.collections = configparser.ConfigParser(
                defaults=DEFAULT_PATH_SPEC,
                interpolation=configparser.ExtendedInterpolation(),
            )
        else:
            self.collections = collections_p

    def get_collections(self) -> CollectionFinder:
        try:
            default_collection = self.options["global"]["Default"]
        except KeyError:
            default_collection = None
        else:
            if not self.collections.has_section(default_collection):
                log.warning(
                    "Default collection not found in collections: %s",
                    default_collection,
                )
                default_collection = None
        finder = CollectionFinder(
            default_settings=self.collections[self.collections.default_section],
            default_name=default_collection,
        )
        for section in self.collections.sections():
            if path_spec := self._spec_from_section(section):
                finder.add_collection(path_spec)
        return finder

    def _spec_from_section(self, section: str) -> CollectionPathSpec | None:
        try:
            root = self.collections[section]["Root"]
        except KeyError:
            log.warning(
                "Ignoring collection [%s]: Required key is missing: Root", section
            )
            return None
        except configparser.InterpolationError as err:
            log.warning("Ignoring collection [%s]: %s", section, err)
            return None
        try:
            collection_path = Path(root).expanduser()
        except RuntimeError as err:
            log.warning("Error with Root path: %s: %s", root, err)
            collection_path = Path(root)
        if not collection_path.is_absolute():
            log.warning(
                "Ignoring collection [%s]: Root is not an absolute path: %s",
                section,
                collection_path,
            )
            return None
        try:
            return collection_path_spec(
                collection_path=collection_path,
                subdir_name=self.collections[section]["GalleriesDir"],
                config_name=self.collections[section]["ConfigName"],
                name=section,
            )
        except configparser.InterpolationError as err:
            log.warning("Ignoring collection [%s]: %s", section, err)
            return None


class DBConfig:
    """Helper for parsing the DB configuration"""

    def __init__(
        self,
        paths: CollectionPathSpec,
        parser: configparser.ConfigParser | None = None,
    ) -> None:
        self.paths = paths
        if parser is None:
            self.parser = self.default_parser()
        else:
            self.parser = parser
        self.parser.read_dict(DEFAULT_CONFIG_STATE)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(paths={self.paths}, parser={self.parser})"

    @staticmethod
    def default_parser() -> configparser.ConfigParser:
        return configparser.ConfigParser(default_section="db", interpolation=None)

    def _convert_to_boolean(self, value: str) -> bool:
        if value.lower() not in self.parser.BOOLEAN_STATES:
            raise ValueError(f"Not a boolean: {value}")
        return self.parser.BOOLEAN_STATES[value.lower()]

    def get_boolean(self, section: str, option: str, default: bool) -> bool:
        if val := self.parser[section].get(option):
            return self._convert_to_boolean(val)
        return default

    def get_multi_booleans(self, section: str, option: str) -> list[bool]:
        if val := self.parser[section].get(option):
            return [self._convert_to_boolean(arg) for arg in split_semicolon_list(val)]
        return []

    def get_list(self, section: str, option: str) -> list[str]:
        """Parse semicolon-separated list value of *option* in *section*."""
        return split_semicolon_list(self.parser[section].get(option, ""))

    def get_path(self, section: str, option: str) -> Path:
        """Parse DB-relative path value of *option* in *section*.

        If *option* is not found, then the return value will be equal to
        ``paths.subdir``.
        """
        return self.paths.get_db_path(self.parser[section].get(option, ""))

    def get_multi_paths(self, section: str, option: str) -> list[Path]:
        if val := self.parser[section].get(option):
            return [self.paths.get_db_path(name) for name in split_semicolon_list(val)]
        return []

    def get_implicating_fields(self, tag_fields: list[str] | None = None) -> set[str]:
        if tag_fields is None:
            tag_fields = self.get_list("refresh", "TagFields")
        implicating_fields = set(tag_fields)
        if val := self.parser["refresh"].get("ImplicatingFields"):
            arguments = frozenset(split_semicolon_list(val))
            if not arguments.issubset(implicating_fields):
                log.warning(
                    "In %s: ImplicatingFields is not a subset of TagFields",
                    self.paths.config,
                )
            implicating_fields &= arguments
        return implicating_fields

    def sort_spec(self, section: str, default_field: str) -> list[tuple[str, bool]]:
        try:
            reverse = self.get_multi_booleans(section, "ReverseSort")
        except ValueError as err:
            log.warning(
                "Invalid configuration setting for ReverseSort (defaulting to False): %s",
                err,
            )
            reverse = [False]
        sort_fields = self.get_list(section, "SortField") or [default_field]
        specs = zip(
            sort_fields, itertools.chain(reverse, itertools.repeat(False)), strict=False
        )
        return list(specs)


@dataclasses.dataclass(frozen=True)
class CollectionPathSpec:
    """The set of paths describing a collection, optionally named"""

    name: str | None
    collection: Path
    subdir: Path
    config: Path

    def get_db_path(self, filename: StrPath) -> Path:
        return self.subdir / filename

    def with_root(self: PathSpecT, collection: StrPath) -> PathSpecT:
        """Return new path spec with the same names rooted in *collection*."""
        root = Path(collection)
        new_subdir = root / self.subdir.name
        new_config = new_subdir / self.config.name
        return dataclasses.replace(
            self, collection=root, subdir=new_subdir, config=new_config
        )

    # In acquire_db_config and get_db_config, don't try to handle and recover
    # from configparser errors. The parser will not be in a readable state.
    # Log the error and re-raise the exception.

    def acquire_db_config(self) -> DBConfig | None:
        """Check collection's validity, and read its configuration.

        If this path spec represents a valid collection, one with a working
        config file, read it, construct and return ``DBConfig``, else return
        ``None``.
        """
        if not self.config.is_file():
            log.error("No valid collection found at path: %s", self.config)
            return None
        config = DBConfig(paths=self)
        try:
            successful = config.parser.read(self.config, encoding="utf-8")
        except configparser.Error as err:
            self._log_bad_read(err)
            raise
        if not successful:
            self._log_bad_read(self.config)
            return None
        return config

    def get_db_config(self) -> DBConfig:
        config = DBConfig(paths=self)
        try:
            config.parser.read(self.config, encoding="utf-8")
        except configparser.Error as err:
            self._log_bad_read(err)
            raise
        return config

    @staticmethod
    def _log_bad_read(error: object) -> None:
        return log.error("Unable to read configuration from file: %s", error)


class CollectionFinder:
    """Maintain the data needed to create ``CollectionPathSpec``s."""

    def __init__(
        self,
        collections: Iterable[CollectionPathSpec] | None = None,
        default_name: str | None = None,
        default_settings: Mapping[str, Any] | None = None,
    ) -> None:
        self.default_name = default_name
        if default_settings is not None:
            self.default_settings = default_settings
        else:
            self.default_settings = DEFAULT_PATH_SPEC
        self._collection_names: dict[str, CollectionPathSpec] = {}
        self._collection_paths: dict[Path, CollectionPathSpec] = {}
        if collections is not None:
            for spec in collections:
                self.add_collection(spec)

    def add_collection(self, path_spec: CollectionPathSpec) -> None:
        if path_spec.name is not None:
            self._collection_names[path_spec.name] = path_spec
        self._collection_paths[path_spec.collection] = path_spec

    def _disambiguate_collection_name(self, name: str) -> CollectionPathSpec | None:
        if exact_match := self._collection_names.get(name):
            log.debug("arg matches name exactly: %s", exact_match)
            return exact_match
        name = name.casefold()
        prefix_matches = [
            coll for coll in self._collection_names if coll.casefold().startswith(name)
        ]
        if prefix_matches:
            prefix_match = self._collection_names[min(prefix_matches)]
            log.debug("arg matches name prefix: %s", prefix_match)
            return prefix_match
        return None

    def _lookup_collection_by_path(self, path: Path) -> CollectionPathSpec | None:
        """Look up *path*, first by hash, then by samefile equivalence."""
        if hash_lookup := self._collection_paths.get(path):
            return hash_lookup
        for configured_path, spec in self._collection_paths.items():
            try:
                same_file = path.samefile(configured_path)
            except OSError as err:
                same_file = False
                log.debug("path cannot be accessed: %s", err)
            if same_file:
                log.debug("arg is samefile as collection path: %s", spec)
                # Since an explicit collection path was passed, use that path
                # as the collection root.
                return spec.with_root(path)
        return None

    def find_collection(self, arg: str | None = None) -> CollectionPathSpec:
        """Return the path spec determined by *arg*."""
        if arg:
            return self._lookup_collection(arg)
        cwd = Path.cwd()
        if path_lookup := self._lookup_collection_by_path(cwd):
            log.debug("cwd matches collection path: %s", path_lookup)
            return path_lookup
        if self.default_name:
            with contextlib.suppress(KeyError):
                default_collection = self._collection_names[self.default_name]
                log.debug("using default collection: %s", default_collection)
                return default_collection
        default_collection = self.anonymous_collection(cwd)
        log.debug("using cwd: %s", default_collection)
        return default_collection

    def _lookup_collection(self, arg: str) -> CollectionPathSpec:
        if name_lookup := self._disambiguate_collection_name(arg):
            return name_lookup
        path = Path(arg)
        if path_lookup := self._lookup_collection_by_path(path):
            log.debug("arg matches collection path: %s", path_lookup)
            return path_lookup
        as_path = self.anonymous_collection(arg)
        log.debug("using path value of arg: %s", as_path)
        return as_path

    def anonymous_collection(self, collection_path: StrPath) -> CollectionPathSpec:
        """Return the default path spec rooted in *collection_path*."""
        return collection_path_spec(
            collection_path=collection_path,
            subdir_name=self.default_settings["GalleriesDir"],
            config_name=self.default_settings["ConfigName"],
        )

    def collections_added(self) -> set[CollectionPathSpec]:
        return set(self._collection_paths.values())


def set_logging_level(args: argparse.Namespace, global_config: GlobalConfig) -> None:
    try:
        config_setting = global_config.options["global"].getboolean("Verbose")
    except ValueError as err:
        log.warning("Invalid global configuration setting for Verbose: %s", err)
        config_setting = False
    verbosity = 1 if config_setting else 0
    if args.verbose is not None:
        verbosity = args.verbose
    root_logger = logging.getLogger()
    if args.quiet or verbosity == 0:
        root_logger.setLevel(logging.WARNING)
    elif verbosity == 1:
        root_logger.setLevel(logging.INFO)
    else:
        root_logger.setLevel(logging.DEBUG)


def get_global_config_dir() -> Path:
    if custom_path := os.getenv("GALLERIES_CONF"):
        return Path(custom_path).expanduser()
    if xdg_config_home := os.getenv("XDG_CONFIG_HOME"):
        base_dir = Path(xdg_config_home)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / PROG


def collection_path_spec(
    collection_path: StrPath,
    subdir_name: StrPath,
    config_name: StrPath,
    name: str | None = None,
) -> CollectionPathSpec:
    collection_path = Path(collection_path)
    subdir_path = collection_path / subdir_name
    config_path = subdir_path / config_name
    return CollectionPathSpec(
        name=name, collection=collection_path, subdir=subdir_path, config=config_path
    )


def read_global_configuration() -> GlobalConfig:
    config_dir_path = get_global_config_dir()
    parser = GlobalConfig()
    parser.options.read_dict(DEFAULT_GLOBAL_CONFIG)
    # Don't try to recover from configparser.Error. The parser will not be in
    # a readable state.
    # Log the error and re-raise.
    err_msg = "Unable to read %s configuration file: %s"
    try:
        parser.options.read(config_dir_path / "config", encoding="utf-8")
    except configparser.Error as err:
        log.error(err_msg, "global", err)
        raise
    try:
        parser.collections.read(config_dir_path / "collections", encoding="utf-8")
    except configparser.Error as err:
        log.error(err_msg, "collections", err)
        raise
    return parser


def environ_get(key: str) -> str | None:
    value = os.environ.get(key)
    if value is not None:
        log.debug("picked up an environment variable: %s='%s'", key, value)
    return value


def join_semicolon_list(items: Iterable[str]) -> str:
    return "; ".join(items)


def split_semicolon_list(value: str) -> list[str]:
    if not value:
        return []
    return [stripped for item in value.split(";") if (stripped := item.strip())]

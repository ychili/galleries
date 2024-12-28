"""Unit tests for cli module, using pytest"""

import configparser
import dataclasses
import operator
import pathlib
import re

import pytest

import galleries
import galleries.cli

_STD_CONFIGPARSER_ERRORS = [
    # text, exception expected
    ("[global]\n[global]\n", configparser.DuplicateSectionError),
    ("default = myabbrev\n", configparser.MissingSectionHeaderError),
    ("[global]\ndefault=Is\ndefault=Isn't\n", configparser.DuplicateOptionError),
]


def write_utf8(path, text):
    return path.write_text(text, encoding="utf-8")


@pytest.fixture
def write_to_collections(real_path):
    collections_path = real_path / "collections"

    def write(data):
        write_utf8(collections_path, data)

    return write


@pytest.fixture
def real_db(tmp_path):
    """Create and return an unconfigured collection inside ``tmp_path``."""
    collection_path = tmp_path / "test_collection"
    spec = galleries.cli.collection_path_spec(
        collection_path=collection_path,
        subdir_name=galleries.cli.DB_DIR_NAME,
        config_name=galleries.cli.DB_CONFIG_NAME,
    )
    spec.collection.mkdir()
    spec.subdir.mkdir()
    return spec


@pytest.mark.usefixtures("global_config_dir")
class TestGlobalConfig:
    func = staticmethod(galleries.cli.read_global_configuration)

    def test_default_settings(self):
        cfg = self.func()
        assert cfg.options["global"].getboolean("verbose") is False
        assert cfg.options["global"].get("default") is None
        assert cfg.options["init"].get("TemplateDir") is None
        assert not cfg.collections.sections()

    def test_custom_settings(self, real_path):
        config_path = real_path / "config"
        config_text = "[global]\nVerbose=true\n"  # Change Verbose to True
        write_utf8(config_path, config_text)
        cfg = self.func()
        assert cfg.options["global"].getboolean("verbose") is True
        assert cfg.options["global"].get("default") is None
        assert cfg.options["init"].get("TemplateDir") is None
        assert not cfg.collections.sections()

    @pytest.mark.parametrize(("config_text", "exc"), _STD_CONFIGPARSER_ERRORS)
    @pytest.mark.parametrize("filename", ["config", "collections"])
    def test_config_parsing_exceptions(self, real_path, filename, config_text, exc):
        config_path = real_path / filename
        write_utf8(config_path, config_text)
        pytest.raises(exc, self.func)

    def test_default_collection_not_in_collections(self, real_path, caplog):
        config_path = real_path / "config"
        config_text = "[global]\nDefault = Where?\n"
        write_utf8(config_path, config_text)
        cfg = galleries.cli.read_global_configuration()
        finder = cfg.get_collections()  # This emits a warning log
        assert any(
            "Where?" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert finder.default_name is None

    def test_valid_collections(self, write_to_collections, caplog):
        colle_text = "[1]\nRoot: /some/path\n[2]\nRoot: /an/other/path\n"
        write_to_collections(colle_text)
        finder = self.func().get_collections()
        assert not any(
            record for record in caplog.records if record.levelname == "WARNING"
        )
        assert len(finder.collections_added()) == 2
        assert finder.default_name is None
        for key, value in galleries.cli.DEFAULT_PATH_SPEC.items():
            assert finder.default_settings[key] == value

    def test_collection_missing_root(self, write_to_collections, caplog):
        colle_text = "[1]\nConfigName: custom.conf\n"
        write_to_collections(colle_text)
        finder = self.func().get_collections()
        assert any(
            "Required key is missing" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert len(finder.collections_added()) == 0

    def test_collection_root_not_absolute(self, write_to_collections, caplog):
        colle_text = "[1]\nRoot: some/relative/path\n"
        write_to_collections(colle_text)
        finder = self.func().get_collections()
        assert any(
            "Root is not an absolute path" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert len(finder.collections_added()) == 0

    def test_collection_settings(self, write_to_collections, caplog):
        colle_text = "[DEFAULT]\nGalleriesDir=.db\n[1]\nRoot=/imaginary\n"
        write_to_collections(colle_text)
        finder = self.func().get_collections()
        assert not any(
            record for record in caplog.records if record.levelname == "WARNING"
        )
        assert len(finder.collections_added()) == 1

    def test_interpolation_syntax_error(self, write_to_collections, caplog):
        # The problem here is the unescaped $
        colle_text = "[1]\nRoot=$HOME/some/folder\n"
        write_to_collections(colle_text)
        finder = self.func().get_collections()
        assert any(
            "$HOME/some/folder" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert len(finder.collections_added()) == 0

    @pytest.mark.parametrize(
        "colle_text",
        [
            "[1]\nRoot = ${Phony}/somefolder\n",
            "[1]\nRoot = /Users/Me/Pictures\nConfigName = ${Phony}somestring\n",
        ],
    )
    def test_interpolation_missing_option_error(
        self, write_to_collections, caplog, colle_text
    ):
        write_to_collections(colle_text)
        finder = self.func().get_collections()
        assert any(
            "Bad value substitution" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert len(finder.collections_added()) == 0

    def test_arbitrary_interpolation(self, write_to_collections, caplog):
        # Arbitrary K-V pairs can be put in the DEFAULT section safely
        colle_text = """
            [DEFAULT]
            home_dir: /home/user
            [1]
            root: ${home_dir}/rootfolder1
            [2]
            root: ${home_dir}/rootfolder2
        """
        write_to_collections(colle_text)
        finder = self.func().get_collections()
        assert not any(
            record for record in caplog.records if record.levelname == "WARNING"
        )
        path_specs = finder.collections_added()
        assert len(path_specs) == 2
        assert all(spec.collection.match("/home/user/*") for spec in path_specs)


@pytest.mark.usefixtures("global_config_dir")
class TestCollectionFinding:
    @staticmethod
    def func():
        return galleries.cli.read_global_configuration().get_collections()

    @pytest.fixture
    def changedir(self, tmp_path, monkeypatch):
        """Change directory to ``tmp_path``."""
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def _test_collection_path_spec_objecthood(self, spec):
        assert re.match(r"CollectionPathSpec\(.+?\)\Z", repr(spec))
        assert hash(spec)
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.name = "friendly_collection_name"

    @pytest.mark.parametrize("arg", [None, "any/arg", "./文字"])
    def test_no_configuration(self, changedir, arg):
        finder = self.func()
        assert not finder.collections_added()
        path = finder.find_collection(arg)
        self._test_collection_path_spec_objecthood(path)
        assert path.name is None
        root = pathlib.Path(arg or changedir)
        assert path.collection == root
        db_dir_name = root / galleries.cli.DB_DIR_NAME
        assert path.subdir == db_dir_name
        assert path.config == db_dir_name / galleries.cli.DB_CONFIG_NAME

    def test_valid_default(self, real_path, changedir):
        write_utf8(real_path.joinpath("config"), "[global]\nDefault=1\n")
        root = changedir / "root1"
        write_utf8(real_path.joinpath("collections"), f"[1]\nRoot={root}\n")

        finder = self.func()
        assert len(finder.collections_added()) == 1
        path = finder.find_collection(None)
        self._test_collection_path_spec_objecthood(path)
        assert path.name == "1"
        assert path.collection == root
        db_dir_name = root / galleries.cli.DB_DIR_NAME
        assert path.subdir == db_dir_name
        assert path.config == db_dir_name / galleries.cli.DB_CONFIG_NAME

    def test_valid_cwd(self, write_to_collections, changedir, monkeypatch):
        root = changedir / "root1"
        root.mkdir()
        monkeypatch.chdir(root)
        write_to_collections(f"[1]\nRoot={root}\n")

        finder = self.func()
        assert len(finder.collections_added()) == 1
        path = finder.find_collection(None)
        self._test_collection_path_spec_objecthood(path)
        assert path.name == "1"
        assert path.collection == root
        db_dir_name = root / galleries.cli.DB_DIR_NAME
        assert path.subdir == db_dir_name
        assert path.config == db_dir_name / galleries.cli.DB_CONFIG_NAME

    # find_collection resolves the path, so it should be able to look up by
    # full path (str) or by basename (operator.attrgetter("name")).
    @pytest.mark.parametrize("arg_func", [str, operator.attrgetter("name")])
    def test_valid_collection_path(self, write_to_collections, changedir, arg_func):
        root = changedir / "root1"
        write_to_collections(f"[1]\nRoot={root}\n")
        finder = self.func()
        assert len(finder.collections_added()) == 1
        path = finder.find_collection(arg_func(root))
        assert path.name == "1"
        assert path.collection == root
        db_dir_name = root / galleries.cli.DB_DIR_NAME
        assert path.subdir == db_dir_name
        assert path.config == db_dir_name / galleries.cli.DB_CONFIG_NAME

    COLLECTIONS_TXT = "\n".join(
        f"[{name}]\n\tRoot=/any/abs/path/{path}]\n"
        for name, path in [("one", "1"), ("onetwo", "2"), ("three", "3"), ("四", "4")]
    )

    @pytest.mark.parametrize(
        ("arg", "name_expected"),
        [("one", "one"), ("o", "one"), ("ThReE", "three"), ("四", "四")],
    )
    def test_valid_collection_name(self, write_to_collections, arg, name_expected):
        write_to_collections(self.COLLECTIONS_TXT)
        finder = self.func()
        assert len(finder.collections_added()) == 4
        path = finder.find_collection(arg)
        assert path.name == name_expected
        assert path.collection.match("/any/abs/path/*")
        assert path.subdir.name == galleries.cli.DB_DIR_NAME
        assert path.config.name == galleries.cli.DB_CONFIG_NAME

    @pytest.mark.parametrize("arg", ["five", "六", "A", "/"])
    def test_invalid_collection_name(self, write_to_collections, arg):
        write_to_collections(self.COLLECTIONS_TXT)
        finder = self.func()
        assert len(finder.collections_added()) == 4
        path = finder.find_collection(arg)
        assert path.name is None
        assert path.collection == pathlib.Path(arg)

    @pytest.mark.parametrize(
        ("cname", "dirname", "cfgname"),
        [("1", ".", "g.conf"), ("2", ".db", "g.conf"), ("3", ".", ".myconfig")],
    )
    def test_path_settings(self, write_to_collections, cname, dirname, cfgname):
        colle_text = """
            [DEFAULT]
            GalleriesDir = .
            ConfigName = g.conf
            [1]
            Root = /data/g/1
            [2]
            Root = /data/g/2
            GalleriesDir = .db
            [3]
            Root = /data/g/3
            ConfigName = .myconfig
        """
        write_to_collections(colle_text)
        finder = self.func()
        assert len(finder.collections_added()) == 3
        path = finder.find_collection(cname)
        assert path.name == cname
        root = pathlib.Path(f"/data/g/{cname}")
        assert path.collection == root
        assert path.subdir == root / dirname
        assert path.config == root / dirname / cfgname


@pytest.mark.usefixtures("global_config_dir")
class TestDBConfig:
    def test_minimal_example(self, tmp_path, caplog):
        spec = galleries.cli.collection_path_spec(
            tmp_path,
            subdir_name=galleries.cli.DB_DIR_NAME,
            config_name=galleries.cli.DB_CONFIG_NAME,
        )
        cfg = spec.get_db_config()
        assert cfg.paths == spec
        assert not caplog.text
        assert spec.acquire_db_config() is None  # Error log emitted
        assert str(spec.config) in caplog.text

    def test_empty_config(self, tmp_path, caplog):
        spec = galleries.cli.collection_path_spec(
            tmp_path,
            subdir_name=galleries.cli.DB_DIR_NAME,
            config_name=galleries.cli.DB_CONFIG_NAME,
        )
        spec.subdir.mkdir()
        spec.config.touch()
        _ = spec.get_db_config()
        assert not caplog.text
        assert spec.acquire_db_config() is not None
        assert not caplog.text

    @pytest.mark.parametrize("caseless", [str, str.lower])
    def test_default_values(self, tmp_path, caseless):
        spec = galleries.cli.collection_path_spec(
            tmp_path,
            subdir_name=galleries.cli.DB_DIR_NAME,
            config_name=galleries.cli.DB_CONFIG_NAME,
        )
        cfg = spec.get_db_config()
        for section in galleries.cli.DEFAULT_CONFIG_STATE.keys():
            # These keys are inherited by all sections,
            # so their values should not vary by section.
            assert cfg.get_path(section, caseless("CSVName")) == spec.subdir / "db.csv"
            assert cfg.get_list(section, caseless("TagFields")) == ["Tags"]
            assert cfg.parser[section][caseless("PathField")] == "Path"
            assert cfg.parser[section][caseless("CountField")] == "Count"
        assert cfg.parser["refresh"][caseless("BackupSuffix")] == ".bak"
        assert not cfg.parser["refresh"].getboolean(caseless("ReverseSort"))
        assert cfg.parser["query"][caseless("Format")] == "none"
        assert (
            cfg.get_path("query", caseless("FieldFormats"))
            == spec.subdir / "tableformat.conf"
        )
        assert cfg.parser["related"][caseless("SortMetric")] == "cosine"
        assert cfg.parser["related"][caseless("Filter")] == ""
        assert cfg.parser["related"].getint(caseless("Limit")) == 20

    @pytest.mark.parametrize(("config_text", "exc"), _STD_CONFIGPARSER_ERRORS)
    @pytest.mark.parametrize("getter", ["get_db_config", "acquire_db_config"])
    def test_config_parsing_exceptions(self, real_db, caplog, getter, config_text, exc):
        write_utf8(real_db.config, config_text)
        with pytest.raises(exc):
            _ = getattr(real_db, getter)()
        assert "Unable to read configuration from file" in caplog.text

    def test_get_list(self, real_db):
        write_utf8(real_db.config, "[db]\n[refresh]\n")
        config = real_db.get_db_config()
        assert not config.get_list(
            "refresh", "TagActions"
        ), "A key without a default value produces an empty list"
        assert not config.get_list(
            "refresh", "???"
        ), "An unknown key produces an empty list"

    def test_get_path(self, real_db):
        write_utf8(real_db.config, "[db]\n[refresh]\n")
        config = real_db.get_db_config()
        assert config.get_path("refresh", "???") == real_db.subdir

    @pytest.mark.parametrize("caseless", [str, str.lower])
    def test_get_multi_paths(self, real_db, caseless):
        write_utf8(
            real_db.config, "[refresh]\nTagActions =\n\t1.toml\n\t2.toml; 3.toml\n"
        )
        config = real_db.get_db_config()
        assert config.get_multi_paths("refresh", caseless("TagActions")) == [
            real_db.subdir / filename for filename in ["1.toml\n2.toml", "3.toml"]
        ]
        assert not config.get_multi_paths("refresh", caseless("Other Key"))

    def test_get_implicating_fields(self, real_db, caplog):
        write_utf8(real_db.config, "[db]\nTagFields: Field A; Field B; Field C\n")
        config = real_db.get_db_config()
        fields = config.get_implicating_fields()
        assert not caplog.text
        assert fields == {"Field A", "Field B", "Field C"}

        config.parser["refresh"]["ImplicatingFields"] = "Field C"
        fields = config.get_implicating_fields()
        assert not caplog.text
        assert fields == {"Field C"}

        config.parser["refresh"]["ImplicatingFields"] = "Field D"
        fields = config.get_implicating_fields()  # This emits a warning log
        assert str(real_db.config) in caplog.text
        assert any(
            "not a subset" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert fields == set()


_ENV_VARS = ["GALLERIES_CONF", "XDG_CONFIG_HOME"]


@pytest.mark.parametrize(
    ("env_key", "env_val", "name_expected"),
    [
        ("GALLERIES_CONF", "~/.config/test_dir", "test_dir"),
        ("XDG_CONFIG_HOME", "/mnt/c/Users/Brian/.config", galleries.PROG),
        (None, None, galleries.PROG),
    ],
)
def test_get_global_config_dir(monkeypatch, env_key, env_val, name_expected):
    for var in _ENV_VARS:
        monkeypatch.setenv(var, "")
    if env_key:
        monkeypatch.setenv(env_key, env_val)
    result = galleries.cli.get_global_config_dir()
    assert result.name == name_expected


def test_split_semicolon_list():
    func = galleries.cli.split_semicolon_list
    assert not func("")
    assert func("1") == ["1"]
    assert func("1;") == ["1"]
    assert func("\n1\n2\n3") == ["1\n2\n3"]
    assert func("1;2;3") == ["1", "2", "3"]
    assert func("1;\n2;\n3") == ["1", "2", "3"]

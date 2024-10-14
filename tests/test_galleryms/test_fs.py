"""Tests for functions of galleryms needing filesystem, using pytest"""

import itertools

import pytest

import galleries.galleryms


@pytest.fixture
def make_folder(tmp_path):
    def _make_folder(
        n_regular_files=0, n_hidden_files=0, n_directories=0, folder_name="testgallery"
    ):
        folder = tmp_path / folder_name
        folder.mkdir()
        regular_files = [f"{num}" for num in range(1, n_regular_files + 1)]
        hidden_files = [f".{num}" for num in range(1, n_hidden_files + 1)]
        for name in regular_files + hidden_files:
            folder.joinpath(name).touch()
        for num in range(1, n_directories + 1):
            folder.joinpath(f"directory_{num}").mkdir()
        return tmp_path

    return _make_folder


class TestGallery:
    _FOLDER_NAME = "testgallery"

    @pytest.fixture
    def gallery(self):
        return galleries.galleryms.Gallery(Path=self._FOLDER_NAME)

    def test_get_folder(self, gallery, make_folder):
        path = make_folder(folder_name=self._FOLDER_NAME)
        folder = gallery.get_folder("Path", cwd=path)
        assert folder.name == self._FOLDER_NAME

    def test_check_folder(self, gallery, make_folder):
        path = make_folder(folder_name=self._FOLDER_NAME)
        folder = gallery.check_folder("Path", cwd=path)
        assert folder.name == self._FOLDER_NAME

    def test_check_nonexistent_folder(self, gallery, tmp_path):
        with pytest.raises(FileNotFoundError) as raises_ctx:
            gallery.check_folder("Path", cwd=tmp_path)
        assert tmp_path / self._FOLDER_NAME in raises_ctx.value.args

    def test_check_non_folder(self, gallery, tmp_path):
        tmp_path.joinpath(self._FOLDER_NAME).touch()
        with pytest.raises(NotADirectoryError) as raises_ctx:
            gallery.check_folder("Path", cwd=tmp_path)
        assert tmp_path / self._FOLDER_NAME in raises_ctx.value.args

    @pytest.mark.parametrize(
        "n_regular_files, n_hidden_files, n_directories",
        itertools.product((0, 9), repeat=3),
    )
    def test_update_count(
        self, gallery, make_folder, n_regular_files, n_hidden_files, n_directories
    ):
        path = make_folder(
            n_regular_files,
            n_hidden_files,
            n_directories,
            folder_name=self._FOLDER_NAME,
        )
        folder = gallery.get_folder("Path", cwd=path)
        gallery.update_count("Count", folder)
        assert gallery["Count"] == n_regular_files

    def test_idempotent_update_count(self, gallery, make_folder):
        path = make_folder(100, folder_name=self._FOLDER_NAME)
        folder = gallery.get_folder("Path", cwd=path)
        gallery.update_count("Count", folder)
        result = gallery["Count"]
        gallery.update_count("Count", folder)
        repeat = gallery["Count"]
        assert repeat == result, (repeat, result)

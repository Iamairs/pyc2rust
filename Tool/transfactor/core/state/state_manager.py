import asyncio
import copy
import hashlib
import json
import os
import uuid
import warnings
from contextlib import contextmanager
from enum import Enum
from typing import Callable, List, Literal, Optional
from collections import defaultdict
from threading import Lock

from pydantic import BaseModel

from sqlalchemy import select, update, insert
from sqlalchemy.orm import selectinload, joinedload

from core.db.models.translation import ModuleTranslationEntity, ProjectTranslation, ProjectTranslationStatus, \
    TranslationTaskEntity
from core.db.session import SessionManager
from core.db.models.project import FileContentEntity, FileEntity, ProjectEntity
from core.graph.dep_graph import DGNode
from core.schema.translation import ModuleTranslation, ModuleTranslationStatus, TranslationTask, TranslationTaskSource, \
    TranslationTaskStatus, TranslationTaskTarget, TranslationUnitNode
from core.utils.file_utils import add_line_numbers
from core.utils.vfs import VirtualFileSystem
from core.version.vcs import VCS


class ProjectFile(BaseModel):
    type: Literal["file"]
    path: str
    content: Optional[str] = None
    summary: Optional[str] = None


class Project:
    DEFAULT_IGNORES = [".git", ".vcs", ".gitignore", "target", "Cargo.lock"]

    def __init__(
            self,
            id: str,
            name: str,
            path: str,
            description: Optional[str] = None,
            file_summaries: Optional[dict[str, str]] = None,
            **kwargs
    ):
        self.id = id
        self.name = name
        self.path = path
        self.description = description
        self.file_summaries = file_summaries or {}
        self.details = kwargs

    def list_files(
        self,
        show_content: bool = False,
        show_summary: bool = False,
        show_line_numbers: bool = False,
        ignore_func: Callable[[str], bool] = None,
        relpath: Optional[str] = None
    ) -> List[ProjectFile]:
        """列出目录下的全部文件。

        Args:
            show_content: (bool) 是否显示文件内容。
            show_summary: (bool) 是否显示文件摘要。
            show_line_numbers: (bool) 是否显示行号。
            ignore_func: (Optional[Callable]) 忽略的文件或目录的函数。
            relpath: (Optional[str]) 相对路径。

        Returns:
            list[str]: 目录下的文件列表。
        """
        path = self.path
        file_list = []
        for root, dirs, files in os.walk(path):
            for ignore_file in Project.DEFAULT_IGNORES:
                if ignore_file in dirs:
                    dirs.remove(ignore_file)
            # 如果 relpath 存在，且 root 不在 relpath 下，则跳过
            if relpath:
                if not root.startswith(relpath):
                    continue
            # 若 relpath 存在，那么此时 root 是 relpath 或 relpath 的子目录
            for file in files:
                if os.path.basename(file) in Project.DEFAULT_IGNORES:
                    continue
                abs_filepath = os.path.join(root, file)
                if relpath:
                    filepath = os.path.relpath(os.path.join(root, file), relpath)
                else:
                    filepath = os.path.relpath(os.path.join(root, file), self.path)
                # NOTE: filepath 是相对路径
                if ignore_func and ignore_func(filepath):
                    continue
                current_file = ProjectFile(
                    type="file",
                    path=filepath
                )
                if show_content:
                    with open(abs_filepath, "r", encoding="utf-8") as f:
                        file_content = f.read()
                    if show_line_numbers:
                        current_file.content = add_line_numbers(file_content)
                    else:
                        current_file.content = file_content
                if show_summary:
                    # 这里必须是相对于项目根目录的路径
                    # 基于 abs_filepath 计算相对于项目根目录的路径，获取文件摘要
                    current_file.summary = self.file_summaries.get(os.path.relpath(abs_filepath, self.path), "")
                file_list.append(current_file)
        return file_list

    def pretty_structure(self, ignore_func: Callable[[str], bool] = None) -> str:
        """返回项目的结构。
        """

        def inner_list_files(dirpath: str):
            file_list = []
            for entry in os.listdir(dirpath):
                if os.path.basename(entry) in Project.DEFAULT_IGNORES:
                    continue
                path = os.path.join(dirpath, entry)
                filepath = os.path.relpath(os.path.join(dirpath, entry), self.path)
                if ignore_func and ignore_func(filepath):
                    continue
                current_file = {
                    "path": filepath,
                    "children": []
                }
                if os.path.isdir(path):
                    current_file["type"] = "dir"
                    current_file["children"] = inner_list_files(path)  # 递归调用，增加缩进
                else:
                    current_file["type"] = "file"
                file_list.append(current_file)
            return file_list

        def inner_pretty_files(node: dict, indent: int = 0):
            nonlocal file_structure_str
            # 添加当前节点信息
            file_structure_str += " " * indent + f"[{node['type'].upper()}] {node['path']}\n"
            # 如果是目录，递归显示子节点
            if node["type"] == "dir":
                for child in node["children"]:
                    inner_pretty_files(child, indent + 2)

        file_structure = {
            "path": os.path.basename(self.path),
            "type": "dir",
            "children": inner_list_files(self.path)
        }
        file_structure_str = ""
        inner_pretty_files(file_structure)
        return file_structure_str

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "file_summaries": self.file_summaries,
            **self.details
        }

    @property
    def src_path(self):
        return os.path.join(self.path, "src")

    @property
    def test_path(self):
        return os.path.join(self.path, "test")


class TargetProject(Project):
    def __init__(
        self,
        id: str,
        name: str,
        path: str,
        description: Optional[str] = None,
        file_system: Optional[VirtualFileSystem] = None,
        **kwargs
    ):
        super().__init__(id, name, path, description, **kwargs)
        self.file_system = file_system
        self.vcs: VCS = VCS(self.path)

    @property
    def test_path(self):
        return os.path.join(self.path, "tests")

    # def list_files(
    #     self,
    #     show_content: bool = False,
    #     show_summary: bool = False,
    #     show_line_numbers: bool = False,
    #     ignore_func: Callable[[str], bool] = None,
    #     only_src: bool = False,
    #     relpath: Optional[str] = None
    # ) -> List[ProjectFile]:
    #     """列出目录下的全部文件。
    #
    #     Args:
    #         show_content: (bool) 是否显示文件内容。
    #         show_summary: (bool) 是否显示文件摘要。
    #         show_line_numbers: (bool) 是否显示行号。
    #         ignore_func: (Optional[Callable]) 忽略的文件或目录的函数。
    #         only_src: (bool) 是否只列出 src 目录下的文件。
    #         relpath: (Optional[str]) 相对路径。
    #
    #     Returns:
    #         list[str]: 目录下的文件列表。
    #     """
    #     path = self.src_path if only_src else self.path
    #     file_list = []
    #     if self.file_system:
    #         for filepath in self.file_system.list_files(path, recursive=True):
    #             # NOTE: 这里的 filepath 是相对于项目根目录的路径
    #             abs_filepath = os.path.join(self.path, filepath)
    #             if relpath:
    #                 filepath = os.path.relpath(abs_filepath, relpath)
    #             if set(Project.DEFAULT_IGNORES) & set(filepath.split(os.path.sep)):
    #                 continue
    #             if ignore_func and ignore_func(filepath):
    #                 continue
    #             current_file = ProjectFile(
    #                 type="file",
    #                 path=filepath
    #             )
    #             if show_content:
    #                 with self.file_system.open(abs_filepath, "r") as f:
    #                     file_content = f.read()
    #                 if show_line_numbers:
    #                     current_file.content = add_line_numbers(file_content)
    #                 else:
    #                     current_file.content = file_content
    #             if show_summary:
    #                 current_file.summary = self.file_summaries.get(os.path.relpath(abs_filepath, self.path), "")
    #             file_list.append(current_file)
    #
    #     else:
    #         return super().list_files(
    #             show_content=show_content,
    #             show_summary=show_summary,
    #             ignore_func=ignore_func,
    #             only_src=only_src,
    #             relpath=relpath
    #         )
    #     return file_list

    def pretty_structure(self, ignore_func: Callable[[str], bool] = None) -> str:
        """返回项目的结构。
        """

        def inner_list_files(dirpath: str):
            file_list = []
            for entry in os.listdir(dirpath):
                if os.path.basename(entry) in Project.DEFAULT_IGNORES:
                    continue
                path = os.path.join(dirpath, entry)
                filepath = os.path.relpath(os.path.join(dirpath, entry), self.path)
                if ignore_func and ignore_func(filepath):
                    continue
                current_file = {
                    "path": filepath,
                    "children": []
                }
                if os.path.isdir(path):
                    current_file["type"] = "dir"
                    current_file["children"] = inner_list_files(path)  # 递归调用，增加缩进
                else:
                    current_file["type"] = "file"
                file_list.append(current_file)
            return file_list

        def inner_pretty_files(node: dict, indent: int = 0):
            nonlocal file_structure_str
            # 添加当前节点信息
            file_structure_str += " " * indent + f"[{node['type'].upper()}] {node['path']}\n"
            # 如果是目录，递归显示子节点
            if node["type"] == "dir":
                for child in node["children"]:
                    inner_pretty_files(child, indent + 2)

        file_structure = {
            "path": os.path.basename(self.path),
            "type": "dir",
            "children": inner_list_files(self.path)
        }
        file_structure_str = ""
        inner_pretty_files(file_structure)
        return file_structure_str

    def to_dict(self):
        return {
            **super().to_dict(),
        }


# class Translator(BaseModel):
#     module_translations: dict[str, ModuleTranslation] = {}
#     module_infos: dict[str, dict] = defaultdict(dict)
#     """模块名 -> 模块转译"""
#
#     def add_module_translation(self, module_name: str, module_translation_tasks: list[TranslationTask],
#                                status: Literal["init", "done", "pending"] = "init", info: dict = None):
#         related_c_files = set(
#             node.filepath
#             for task in module_translation_tasks
#             for node in task.source.nodes
#         )
#         self.module_translations[module_name] = ModuleTranslation(
#             module_name=module_name,
#             module_description="",
#             translation_tasks=module_translation_tasks,
#             related_c_files=list(related_c_files),
#             status=status
#         )
#         self.module_infos[module_name] = info or {}
#
#
#     def add_module_rust_files(self, module_name: str, rust_files: list[str]):
#         for rust_file in rust_files:
#             if rust_file not in self.module_translations[module_name].related_rust_files:
#                 self.module_translations[module_name].related_rust_files.append(rust_file)
#
#     def add_module_test_files(self, module_name: str, test_files: list[str]):
#         for test_file in test_files:
#             if test_file not in self.module_translations[module_name].related_test_files:
#                 self.module_translations[module_name].related_test_files.append(test_file)
#
#     def add_module_bench_files(self, module_name: str, bench_files: list[str]):
#         for bench_file in bench_files:
#             if bench_file not in self.module_translations[module_name].related_bench_files:
#                 self.module_translations[module_name].related_bench_files.append(bench_file)
#
#     @property
#     def modules(self):
#         return list(self.module_translations.keys())
#
#     @property
#     def ready_modules(self):
#         """获取准备好的模块"""
#         return [
#             module
#             for module, module_translation in self.module_translations.items()
#             if module_translation.status != ModuleTranslationStatus.DONE
#         ]

class FileLockManager:
    """文件锁管理器，用于管理文件的读写锁，防止并发读写冲突。"""
    def __init__(self):
        self.file_locks: dict[str, Lock] = {}

    @contextmanager
    def file_lock(self, filepath: str):
        """文件锁上下文管理器。用于在 with 语句中使用文件锁。"""
        # 确保每个文件只有一个锁
        if filepath not in self.file_locks:
            lock = Lock()
            self.file_locks[filepath] = lock
        else:
            lock = self.file_locks[filepath]
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def is_lock(self, filepath: str):
        # 判断文件是否被锁定
        if filepath not in self.file_locks:
            return False
        else:
            lock = self.file_locks[filepath]
            return lock.locked()

    def acquire_file_lock(self, filepath: str):
        if filepath not in self.file_locks:
            lock = Lock()
            self.file_locks[filepath] = lock
        else:
            lock = self.file_locks[filepath]
        lock.acquire()

    def release_file_lock(self, filepath: str):
        if filepath not in self.file_locks:
            raise ValueError(f"File lock for {filepath} not found")
        lock = self.file_locks[filepath]
        lock.release()


class State:

    def __init__(self):
        self.project_translation_id: Optional[str] = None
        self.source_project: Optional[Project] = None
        self.target_project: Optional[TargetProject] = None

        self.module_translations: list[ModuleTranslation] = []

    @property
    def ready_module_translations(self):
        """获取准备好的模块"""
        return [
            (index, module_translation)
            for index, module_translation in enumerate(self.module_translations)
            if module_translation.status not in [ModuleTranslationStatus.DONE, ModuleTranslationStatus.FAILED]
        ]

    def to_dict(self):
        return {
            "project_translation_id": self.project_translation_id,
            "source_project": self.source_project.to_dict() if self.source_project else None,
            "target_project": self.target_project.to_dict() if self.target_project else None,
            "module_translations": [module_translation.model_dump() for module_translation in self.module_translations]
        }

    def load_from_json(self, json_str: str, file_system: Optional[VirtualFileSystem] = None):
        state = json.loads(json_str)
        if "project_translation_id" in state and state["project_translation_id"]:
            self.project_translation_id = state["project_translation_id"]
        if "source_project" in state and state["source_project"]:
            self.source_project = Project(**state["source_project"])
        if "target_project" in state and state["target_project"]:
            self.target_project = TargetProject(**state["target_project"], file_system=file_system)
        if "module_translations" in state and state["module_translations"]:
            self.module_translations = [
                ModuleTranslation(**module_translation)
                for module_translation in state["module_translations"]
            ]


def optimize_translation_units(nodes: list[tuple[int, DGNode]]):
    """优化转译单元。"""

    def can_merge(current_nodes_line_count: int, node_line_count: int, target: int = 20):
        """判断节点是否可以合并。

        Args:
            current_nodes_line_count: 当前节点组总行数
            node_line_count: 待合并节点行数
            target: 合并目标行数，默认 20
        """
        return current_nodes_line_count + node_line_count <= target

    def find_best_combination(remaining_nodes: list[tuple[int, DGNode]], start_idx: int,
                              nodes_group_line_count: int = 0, nodes_group: Optional[list[DGNode]] = None):
        """寻找最佳组合。

        Args:
            remaining_nodes: 剩余节点
            start_idx: 起始索引
            nodes_group_line_count: 当前组行数
            nodes_group: 当前组
        """
        best_result = None  # 存储最优结果
        best_result_size = float('inf')  # 存储最少的组数

        # 初始化当前组（第一次调用）
        if nodes_group is None:
            nodes_group = []
        if start_idx >= len(remaining_nodes):
            return [nodes_group]
        # 尝试将当前节点加入当前组
        if can_merge(nodes_group_line_count, remaining_nodes[start_idx][0]):
            new_nodes_group = nodes_group + [remaining_nodes[start_idx][1]]
            # 递归调用，尝试将下一个节点加入当前组
            new_nodes_group_line_count = nodes_group_line_count + remaining_nodes[start_idx][0]
            result1 = find_best_combination(remaining_nodes, start_idx + 1, new_nodes_group_line_count, new_nodes_group)
            if result1 and len(result1) < best_result_size:
                best_result = result1
                best_result_size = len(result1)

        # 尝试不将当前节点加入当前组
        new_nodes_group = [remaining_nodes[start_idx][1]]
        new_nodes_group_line_count = remaining_nodes[start_idx][0]
        result2 = [nodes_group] + find_best_combination(remaining_nodes, start_idx + 1, new_nodes_group_line_count,
                                                        new_nodes_group)
        if len(result2) < best_result_size:
            best_result = result2
            best_result_size = len(result2)

        return best_result

    best_combination = find_best_combination(nodes, 0)
    return best_combination


class StateManager:

    def __init__(self, filepath: str, session_manager: SessionManager, file_system: Optional[VirtualFileSystem] = None):
        self.bound_filepath = filepath
        self.state = State()
        self.session_manager = session_manager
        self.file_system = file_system
        self.load_from_db = False

        self._lock = Lock()

        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                if content:
                    self.state.load_from_json(content, self.file_system)
            if self.load_from_db and self.state.project_translation_id:
                asyncio.run(self.load_by_project_translation_id(self.state.project_translation_id))

        # self.target_vcs: Optional[VCS] = None
        # # 转换器
        # self.translator: Translator = Translator()
        # # 文件锁管理器
        # self.file_lock_manager = FileLockManager()

    async def list_projects_by_dirpath(self, project_dir: str) -> List[ProjectEntity]:
        """ 列出指定目录下的所有项目。 """
        async with self.session_manager as session:
            results = await session.execute(
                select(ProjectEntity).where(ProjectEntity.dirpath == project_dir).order_by(
                    ProjectEntity.create_time.desc()))
            project_entities = results.scalars().all()
        return project_entities

    async def create_source_project(self, project_dir: str) -> ProjectEntity:
        """ 创建源项目，用于存储 C/C++ 项目。 """
        project_entity = ProjectEntity(
            name=os.path.basename(project_dir),
            description="",
            dirpath=project_dir
        )
        # async with self.session_manager as session:
        #     session.add(project_entity)
        #     await session.commit()

        self.state.source_project = Project(
            id=project_entity.id,
            name=project_entity.name,
            path=project_entity.dirpath,
            description=project_entity.description
        )
        self.sync_to_disk()
        return project_entity

    async def create_target_project(self, name: str, dirpath: str, description: str):
        """ 创建目标项目，用于存储转译后的 Rust 项目。 """
        new_project = ProjectEntity(
            name=name,
            dirpath=dirpath,
            description=description,
        )
        # async with self.session_manager as session:
        #     session.add(new_project)
        #     await session.commit()
        os.makedirs(dirpath, exist_ok=True)
        self.state.target_project = TargetProject(
            id=new_project.id,
            name=new_project.name,
            path=new_project.dirpath,
            description=new_project.description,
            file_system=self.file_system
        )
        # async with self.session_manager as session:
        #     project_translation = ProjectTranslation(
        #         source_project_id=self.state.source_project.id,
        #         source_lang="c",
        #         target_project_id=self.state.target_project.id,
        #         target_lang="rust",
        #         status=ProjectTranslationStatus.CREATED
        #     )
        #     session.add(project_translation)
        #     await session.commit()
        #     self.state.project_translation_id = project_translation.id
        self.sync_to_disk()
        self.state.target_project.vcs.init()
        if self.file_system:
            self.file_system.load(
                self.state.target_project.path,
            )

    async def load_source_project_by_id(self, project_id: str):
        """加载源项目及其文件摘要，如果 state 中已经存在对应字段，则不覆盖。"""
        async with self.session_manager as session:
            results = await session.execute(select(ProjectEntity).where(ProjectEntity.id == project_id))
            project_entity = results.scalars().first()
        if not self.state.source_project.name:
            self.state.source_project.name = project_entity.name
        if not self.state.source_project.path:
            self.state.source_project.path = project_entity.dirpath
        if not self.state.source_project.description:
            self.state.source_project.description = project_entity.description
        # 加载文件摘要
        async with self.session_manager as session:
            results = await session.execute(
                select(FileEntity)
                .where(FileEntity.project_id == project_id)
                # TODO: 目前是数据库中只存储最新版本的数据，不同版本数据是通过 VCS 管理的，后续需要改进
                .options(selectinload(FileEntity.content))  # 预加载文件内容
            )
            file_entities = results.scalars().all()
            for file in file_entities:
                if file.path not in self.state.source_project.file_summaries:
                    self.state.source_project.file_summaries[file.path] = file.content.summary
        self.sync_to_disk()

    async def load_target_project_by_id(self, project_id: str):
        """加载目标项目及其文件摘要，如果 state 中已经存在对应字段，则不覆盖。"""
        async with self.session_manager as session:
            results = await session.execute(select(ProjectEntity).where(ProjectEntity.id == project_id))
            project_entity = results.scalars().first()
        if not self.state.target_project.name:
            self.state.target_project.name = project_entity.name
        if not self.state.target_project.path:
            self.state.target_project.path = project_entity.dirpath
        if not self.state.target_project.description:
            self.state.target_project.description = project_entity.description
        # 加载文件摘要
        async with self.session_manager as session:
            results = await session.execute(
                select(FileEntity)
                .where(FileEntity.project_id == project_id)
                # TODO: 目前是数据库中只存储最新版本的数据，不同版本数据是通过 VCS 管理的，后续需要改进
                .options(selectinload(FileEntity.content))  # 预加载文件内容
            )
            # 获取所有文件实体
            file_entities = results.scalars().all()
            # 将文件摘要加载到 state 中
            for file in file_entities:
                if file.path not in self.state.target_project.file_summaries:
                    self.state.target_project.file_summaries[file.path] = file.content.summary
        self.sync_to_disk()

    async def load_module_translations_by_project_id(self, project_id: str):
        """加载模块转译及其任务。"""
        async with self.session_manager as session:
            results = await session.execute(
                select(ModuleTranslationEntity)
                .where(ModuleTranslationEntity.project_id == project_id)
                .options(joinedload(ModuleTranslationEntity.translation_tasks))
            )
            module_translation_entities = results.scalars().all()

        # 将数据库中的实体转换为 state 中的模块转译
        self.state.module_translations = [
            ModuleTranslation(
                id=module_translation_entity.id,
                translation_tasks=[
                    TranslationTask(
                        id=task.id,
                        source=TranslationTaskSource(**task.source),
                        target=TranslationTaskTarget(**task.target) if task.target else None,
                        prerequisites=task.prerequisites,
                        status=task.status
                    )
                    for task in module_translation_entity.translation_tasks
                ],
                related_files=module_translation_entity.related_files,
                status=module_translation_entity.status
            )
            for module_translation_entity in module_translation_entities
        ]
        self.sync_to_disk()

    async def load_by_project_translation_id(self, project_translation_id: str):
        """通过项目转译 ID 加载状态，包括源项目、目标项目及其文件摘要，模块转译及其任务。"""
        async with self.session_manager as session:
            results = await session.execute(
                select(ProjectTranslation).where(ProjectEntity.id == project_translation_id)
            )
            project_translation = results.scalars().first()
            if project_translation:
                await asyncio.gather(
                    self.load_source_project_by_id(project_translation.source_project_id),
                    self.load_target_project_by_id(project_translation.target_project_id),
                    self.load_module_translations_by_project_id(project_translation.source_project_id)
                )

    async def _save_file(self, project_id: str, filepath: str, content: str, summary: str = "") -> FileEntity:
        """ 保存文件及其摘要。"""
        file_entity = FileEntity(
            project_id=project_id,
            path=filepath,
            content=FileContentEntity(
                content=content,
                summary=summary
            )
        )
        # async with self.session_manager as session:
        #     session.add(file_entity)
        #     await session.commit()
        return file_entity

    async def save_source_project_file(self, filepath: str, content: str, summary: str = "") -> FileEntity:
        """ 保存源项目文件及其摘要。"""
        if not self.state.source_project:
            raise ValueError("source project not loaded")
        file_entity = await self._save_file(self.state.source_project.id, filepath, content, summary)
        self.state.source_project.file_summaries[filepath] = summary
        self.sync_to_disk()
        return file_entity

    async def update_source_project_description(self, description: str):
        self.state.source_project.description = description
        # async with self.session_manager as session:
        #     await session.execute(
        #         update(ProjectEntity)
        #         .where(ProjectEntity.id == self.state.source_project.id)
        #         .values(description=description)
        #     )
        #     await session.commit()
        self.sync_to_disk()

    async def create_module_translation(
            self,
            translation_units_list: list[list[list[DGNode]]],
            related_files: list[str]
    ):
        """创建模块转译，将多个转译单元列表转换为多个转译任务，并构建依赖关系。
        Args:
            translation_units_list: 转译单元列表，每个转译单元是一个节点列表，多个转译单元可以并行转译
            related_files: 相关文件列表
        """
        translation_tasks = []
        translation_task_entities = []
        # node_id -> task_id
        node_task_lookup_map = {}
        # 记录每个任务的所有节点的依赖节点
        prerequisites_nodes = defaultdict(list)
        # 遍历所有转译的转译单元组
        is_first = True
        all_nodes = []
        for translation_units in translation_units_list:
            # 将所有没有依赖的节点构建成一个任务，即第一个可并行转译的转译单元
            if is_first:
                is_first = False
                all_dep_nodes = [
                    node
                    for translation_unit in translation_units
                    for node in translation_unit
                ]
                translation_task = TranslationTask(
                    source=TranslationTaskSource(
                        name="init",
                        nodes=[
                            TranslationUnitNode(
                                filepath=os.path.relpath(node.location, self.state.source_project.path),
                                id=node.id,
                                name=node.name,
                                type=node.type,
                                text=node.text,
                            )
                            for node in all_dep_nodes
                        ],
                        description=""
                    ),
                    target=None,
                    status=TranslationTaskStatus.CREATED,
                    prerequisites=[]
                )
                prerequisites_nodes[translation_task.id] = [
                    edge.dst.id
                    for node in all_dep_nodes
                    for edge in node.edges
                    if edge.dst.id not in [n.id for n in all_dep_nodes]
                ]
                translation_tasks.append(translation_task)
                for node in all_dep_nodes:
                    node_task_lookup_map[node.id] = translation_task.id
            else:
                # 遍历所有可并行转译的转译单元，合并代码长度不超过 20 行的同类型的转译单元
                to_merge_nodes = defaultdict(list)
                new_translation_units = []
                for translation_unit in translation_units:
                    line_count = sum([len(node.text.split("\n")) for node in translation_unit])
                    if len(translation_unit) == 1 and line_count <= 20:
                        to_merge_nodes[translation_unit[0].type].append((line_count, translation_unit[0]))
                    else:
                        new_translation_units.append(translation_unit)
                for nodes in to_merge_nodes.values():
                    translation_units = optimize_translation_units(nodes)
                    new_translation_units.extend(translation_units)
                # 遍历所有转译单元
                # TODO: 新的转译单元中顺序可能发生变化，这里需要进行排序
                for translation_unit in new_translation_units:
                    translation_unit_node_ids = [node.id for node in translation_unit]
                    all_nodes.extend([
                        node
                        for node in translation_unit
                    ])
                    translation_task = TranslationTask(
                        source=TranslationTaskSource(
                            name="_".join(set([node.name for node in translation_unit]))[:50],
                            nodes=[
                                TranslationUnitNode(
                                    filepath=os.path.relpath(node.location, self.state.source_project.path),
                                    id=node.id,
                                    name=node.name,
                                    type=node.type,
                                    text=node.text,
                                )
                                for node in translation_unit
                            ],
                            description=""
                        ),
                        target=None,
                        status=TranslationTaskStatus.CREATED,
                        prerequisites=[]
                    )
                    prerequisites_nodes[translation_task.id] = list(set(
                        edge.dst.id
                        for node in translation_unit
                        for edge in node.edges
                        if edge.dst.id not in translation_unit_node_ids
                    ))
                    translation_tasks.append(translation_task)
                    for node in translation_unit:
                        node_task_lookup_map[node.id] = translation_task.id
        # 完善依赖关系
        for translation_task in translation_tasks:
            translation_task.prerequisites = list(set([
                node_task_lookup_map[node_id]
                for node_id in prerequisites_nodes[translation_task.id]
            ]))
            translation_task_entities.append(
                TranslationTaskEntity(**translation_task.model_dump())
            )

        # 保存模块转译
        module_translation = ModuleTranslation(
            translation_tasks=translation_tasks,
            related_files=[os.path.relpath(file, self.state.source_project.path) for file in related_files],
            status=ModuleTranslationStatus.CREATED
        )
        module_translation_entity = ModuleTranslationEntity(
            project_id=self.state.source_project.id,
            translation_tasks=translation_task_entities,
            related_files=module_translation.related_files,
            status=module_translation.status
        )
        # async with self.session_manager as session:
        #     session.add(module_translation_entity)
        #     await session.commit()
        self.state.module_translations.append(module_translation)
        self.sync_to_disk()

    async def update_module_translation_info(
        self,
        module_translation_id: str,
        name: str,
        description: str,
    ):
        """
            更新模块转译的信息，将 name 和 description 更新到数据库中。
        """
        module_translation_path = os.path.join(self.state.target_project.path, name)
        module_translation = self.get_module_translation_by_id(module_translation_id)
        if module_translation:
            module_translation.name = name
            module_translation.description = description
            module_translation.path = module_translation_path

            # async with self.session_manager as session:
            #     await session.execute(
            #         update(ModuleTranslationEntity)
            #         .where(ModuleTranslationEntity.id == module_translation_id)
            #         .values(name=name, description=description, path=module_translation_path)
            #     )
            #     await session.commit()

            self.sync_to_disk()

    async def update_module_translation_status(self, module_translation_id: str, status: ModuleTranslationStatus):
        module_translation = self.get_module_translation_by_id(module_translation_id)
        if module_translation:
            module_translation.status = status
            # async with self.session_manager as session:
            #     await session.execute(
            #         update(ModuleTranslationEntity)
            #         .where(ModuleTranslationEntity.id == module_translation_id)
            #         .values(status=status)
            #     )
            #     await session.commit()
            self.sync_to_disk()
        if status == ModuleTranslationStatus.DONE or status == ModuleTranslationStatus.FAILED:
            # 备份这个 state 文件
            back_filepath = os.path.join(
                os.path.dirname(self.bound_filepath),
                module_translation.name + "_state.json"
            )
            with open(back_filepath, "w", encoding="utf-8") as f:
                back_state = copy.deepcopy(self.state)
                back_state.module_translations = [module_translation]
                f.write(json.dumps(back_state.to_dict(), ensure_ascii=False, indent=4, cls=self.EnumEncoder))


    async def update_translation_task_status(
        self,
        module_translation_id: str,
        translation_task_id: str,
        status: TranslationTaskStatus
    ):
        module_translation = self.get_module_translation_by_id(module_translation_id)
        if module_translation:
            translation_task = module_translation.get_translation_task_by_id(translation_task_id)
            if translation_task:
                translation_task.status = status
                # 潜在 BUG，并发导致重复进入 session_manager
                # async with self.session_manager as session:
                #     await session.execute(
                #         update(TranslationTaskEntity)
                #         .where(TranslationTaskEntity.id == translation_task_id)
                #         .values(status=status)
                #     )
                self.sync_to_disk()

    def get_module_translation_by_id(self, module_translation_id: str):
        for module_translation in self.state.module_translations:
            if module_translation.id == module_translation_id:
                return module_translation
        return None

    async def add_module_translation_related_rust_files(self, module_translation_id: str, related_rust_files: list[str]):
        module_translation = self.get_module_translation_by_id(module_translation_id)
        if module_translation:
            for rust_file in related_rust_files:
                if rust_file not in module_translation.related_rust_files:
                    module_translation.related_rust_files.append(rust_file)
            # async with self.session_manager as session:
            #     await session.execute(
            #         update(ModuleTranslationEntity)
            #         .where(ModuleTranslationEntity.id == module_translation_id)
            #         .values(related_rust_files=module_translation.related_rust_files)
            #     )
            #     await session.commit()
            self.sync_to_disk()

    async def set_translation_task_target(self, module_translation_id: str, translation_task_id: str, target: TranslationTaskTarget):
        module_translation = self.get_module_translation_by_id(module_translation_id)
        if module_translation:
            translation_task = module_translation.get_translation_task_by_id(translation_task_id)
            if translation_task:
                translation_task.target = target
                # async with self.session_manager as session:
                #     await session.execute(
                #         update(TranslationTaskEntity)
                #         .where(TranslationTaskEntity.id == translation_task_id)
                #         .values(target=target.model_dump())
                #     )
                #     await session.commit()
                self.sync_to_disk()

    class EnumEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Enum):
                return obj.value
            return super().default(obj)

    def sync_to_disk(self):
        """将当前状态同步到磁盘文件。"""
        if os.path.dirname(self.bound_filepath) != "":
            os.makedirs(os.path.dirname(self.bound_filepath), exist_ok=True)
        with self._lock:
            with open(self.bound_filepath, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.state.to_dict(), ensure_ascii=False, indent=4, cls=self.EnumEncoder))

    # def update(self):
    #     """更新状态并写入文件。"""
    #     if self.bound_filepath:
    #         with self.file_lock_manager.file_lock(self.bound_filepath):
    #             self.dump(self.bound_filepath)
    #     else:
    #         warnings.warn("State file not bound, state not saved.")
    #
    # def mark_module_translation_as(self, module_name: str, status: ModuleTranslationStatus):
    #     if module_name not in self.translator.module_translations:
    #         raise ValueError(f"Module {module_name} not found")
    #     self.translator.module_translations[module_name].status = status
    #     self.update()
    #
    # def mark_translation_task_as(self, module_name: str, task_id: str,
    #                              status: Literal["init", "running", "completion", "done", "failed"]):
    #     if module_name not in self.translator.module_translations:
    #         raise ValueError(f"Module {module_name} not found")
    #     module_translation = self.translator.module_translations[module_name]
    #     translation_task = module_translation.get_translation_task_by_task_id(task_id)
    #     if not translation_task:
    #         raise ValueError(f"Translation task {task_id} not found in module {module_name}")
    #     translation_task.status = status
    #     self.update()
    #
    # # def set_benchmark_module(self, module: str, benchmark_file: str):
    # #     self.module_benchmarks[module] = benchmark_file
    # #     if self.bound_filepath:
    # #         self.dump(self.bound_filepath)
    #
    # def add_module_rust_files(self, module_name, related_rust_files: list[str]):
    #     self.translator.add_module_rust_files(module_name, related_rust_files)
    #     self.update()
    #
    # def add_module_test_files(self, module_name, related_test_files: list[str]):
    #     self.translator.add_module_test_files(module_name, related_test_files)
    #     self.update()
    #
    # def add_module_bench_files(self, module_name, related_bench_files: list[str]):
    #     self.translator.add_module_bench_files(module_name, related_bench_files)
    #     self.update()
    #
    # def add_module_translation(self, module_name: str, module_translation_tasks: list[TranslationTask], **kwargs):
    #     self.translator.add_module_translation(module_name, module_translation_tasks, **kwargs)
    #     self.update()
    #
    # def bind_filepath(self, filepath: str):
    #     self.bound_filepath = filepath

    # def create_rust_project(self, project_name: str, project_dir: str, crate_type: str, project_description: str):
    #     """
    #     创建项目
    #     """
    #     self.target_project = RustProject(
    #         name=project_name,
    #         path=project_dir,
    #         description=project_description,
    #         crate_type=crate_type
    #     )
    #     self.target_vcs = VCS(project_dir)
    #     self.target_vcs.init()
    #     self.target_vcs.add([
    #         os.path.join(project_dir, file.path)
    #         for file in self.target_project.list_files()
    #     ])
    #     self.target_vcs.commit("Initial commit")
    #     if self.bound_filepath:
    #         self.dump(self.bound_filepath)
    #     return self.target_project

    # def dump(self, filepath: str):
    #     """保存状态到文件。"""
    #     if os.path.dirname(filepath) != "":
    #         os.makedirs(os.path.dirname(filepath), exist_ok=True)
    #     with open(filepath, "w", encoding="utf-8") as f:
    #         f.write(json.dumps({
    #             "source_project": self.source_project.to_dict() if self.source_project else None,
    #             "target_project": self.target_project.to_dict() if self.target_project else None,
    #             "translator": json.loads(self.translator.model_dump_json()),
    #         }, ensure_ascii=False, indent=4))
    #
    # def load(self, filepath: str):
    #     """从文件加载状态。"""
    #     with open(filepath, "r", encoding="utf-8") as f:
    #         content = f.read()
    #         if not content:
    #             return
    #         state = json.loads(content)
    #         self.source_project = Project(**state["source_project"]) if "source_project" in state and state[
    #             "source_project"] else None
    #         self.target_project = Project(**state["target_project"]) if "target_project" in state and state[
    #             "target_project"] else None
    #         self.translator = Translator.model_validate(state["translator"]) if "translator" in state and state[
    #             "translator"] else Translator()
    #         if self.target_project:
    #             self.target_vcs = VCS(self.target_project.path)

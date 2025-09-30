import unittest
import uuid

from sqlalchemy import delete, select

from core.db.models.base import BaseTable
from core.db.models.translation import ProjectTranslation
from core.db.session import SessionManager
from core.db.models.project import ProjectEntity, FileEntity, FileContentEntity


class TestSessionManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_manager = SessionManager(
            url="sqlite+aiosqlite:///:memory:"
        )

    async def asyncSetUp(self):
        self.engine = self.session_manager.engine
        async with self.engine.begin() as conn:
            await conn.run_sync(BaseTable.metadata.create_all)

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(BaseTable.metadata.drop_all)
        await self.engine.dispose()

    async def test_crud_project(self):
        async with self.session_manager as session:
            # Create
            new_project = ProjectEntity(
                name="Test Project",
                description="This is a test project",
                dirpath="/path/to/test/project"
            )
            session.add(new_project)
            await session.commit()

            # Read
            result = await session.execute(
                select(ProjectEntity).filter_by(id=new_project.id)
            )
            project_from_db = result.scalar()
            self.assertIsNotNone(project_from_db)
            self.assertEqual(project_from_db.name, "Test Project")

            # Update
            project_from_db.name = "New Project"
            await session.commit()
            result = await session.execute(
                select(ProjectEntity).filter_by(id=new_project.id)
            )
            project_from_db = result.scalar()
            self.assertIsNotNone(project_from_db)
            self.assertEqual(project_from_db.name, "New Project")

            # Delete
            await session.execute(
                delete(ProjectEntity).filter_by(id=new_project.id)
            )
            await session.commit()
            result = await session.execute(
                select(ProjectEntity).filter_by(id=new_project.id)
            )
            project_from_db = result.scalar()
            self.assertIsNone(project_from_db)

    async def test_crud_project_with_files(self):
        async with self.session_manager as session:
            # Create
            new_project = ProjectEntity(
                id=str(uuid.uuid4()),
                name="Test Project",
                description="This is a test project",
                dirpath="/path/to/test/project"
            )
            session.add(new_project)
            for i in range(5):
                new_project.files.append(
                    FileEntity(
                        path=f"/path/to/test/project/file_{i}.txt",
                        meta={
                            "size": 1024
                        },
                        content=FileContentEntity(
                            content=f"File {i} content"
                        )
                    )
                )
            await session.commit()

            # Read
            result = await session.execute(
                select(ProjectEntity).filter_by(id=new_project.id)
            )
            project_from_db = result.scalar()
            self.assertIsNotNone(project_from_db)
            self.assertEqual(len(project_from_db.files), 5)
            self.assertEqual(project_from_db.files[0].content.content, "File 0 content")

            # Update
            project_from_db.files[0].content.content = "New content"
            await session.commit()
            result = await session.execute(
                select(FileContentEntity).filter_by(file_id=project_from_db.files[0].id)
            )
            file_content_from_db = result.scalar()
            self.assertIsNotNone(file_content_from_db)
            self.assertEqual(file_content_from_db.content, "New content")

            # Delete
            await session.execute(
                delete(ProjectEntity).filter_by(id=new_project.id)
            )
            await session.commit()
            result = await session.execute(
                select(ProjectEntity).filter_by(id=new_project.id)
            )
            project_from_db = result.scalar()
            self.assertIsNone(project_from_db)
            result = await session.execute(
                select(FileEntity).filter_by(project_id=new_project.id)
            )
            files_from_db = result.scalars().all()
            self.assertEqual(len(files_from_db), 0)
            result = await session.execute(
                select(FileContentEntity).filter(FileContentEntity.file_id.in_([file.id for file in files_from_db]))
            )
            file_contents_from_db = result.scalars().all()
            self.assertEqual(len(file_contents_from_db), 0)

    async def test_crud_translation(self):
        async with self.session_manager as session:
            # Create
            source_project = ProjectEntity(
                name="Source Project",
                description="This is a source project",
                dirpath="/path/to/source/project"
            )
            target_project = ProjectEntity(
                name="Target Project",
                description="This is a target project",
                dirpath="/path/to/target/project"
            )
            session.add_all([source_project, target_project])
            await session.commit()

            project_translation = ProjectTranslation(
                source_project_id=source_project.id,
                source_lang="c",
                target_project_id=target_project.id,
                target_lang="rust"
            )
            session.add(project_translation)
            await session.commit()

            # Read
            result = await session.execute(
                select(ProjectTranslation).filter_by(id=project_translation.id)
            )
            translation_from_db = result.scalar()
            self.assertIsNotNone(translation_from_db)
            self.assertEqual(translation_from_db.source_project.name, "Source Project")
            self.assertEqual(translation_from_db.target_project.name, "Target Project")

            # Update
            translation_from_db.source_lang = "cpp"
            await session.commit()
            result = await session.execute(
                select(ProjectTranslation).filter_by(id=project_translation.id)
            )
            translation_from_db = result.scalar()
            self.assertIsNotNone(translation_from_db)
            self.assertEqual(translation_from_db.source_lang, "cpp")

            # Delete
            await session.execute(
                delete(ProjectTranslation).filter_by(id=project_translation.id)
            )
            await session.commit()
            result = await session.execute(
                select(ProjectTranslation).filter_by(id=project_translation.id)
            )
            translation_from_db = result.scalar()
            self.assertIsNone(translation_from_db)


if __name__ == "__main__":
    unittest.main()
